"""LangGraph-orchestrated cardiology agent.

Same deterministic, regex-based tool routing as CardiologistAgent (preserves
the eval-verified 97% grounded-answer baseline -- this is a re-platform of the
control flow, not a behavior change), restructured as an explicit graph of
nodes with a guardrail-gated synthesis step. Tool selection stays regex-driven
on purpose: an LLM choosing which of three tools to call would be more
flexible but less predictable and auditable for a clinical safety tool.

LangGraphCardiologistAgent.review() returns the same AgentResponse the rest of
the app already expects, so backend/main.py only changes how the agent object
is constructed, not how it's called.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from backend.agent.cardiology_agent import (
    PATIENT_ID,
    AgentResponse,
    Citation,
    CardiologistAgent,
    ToolStatus,
    extract_drug_name,
)
from backend.agent.guardrails import check_answer
from backend.agent.prompts import SYSTEM_PROMPT, build_human_message
from backend.models.patient import PatientDataResult, PatientRecordScope
from backend.observability.tracing import TracingSpan
from backend.services.openfda import OpenFDAResult
from rag.models import RetrievalResponse

logger = logging.getLogger(__name__)

RAG_TRIGGER = re.compile(r"\b(policy|guideline|protocol|hospital)\b", re.IGNORECASE)


class AgentState(TypedDict, total=False):
    question: str
    patient_id: str | None
    drug_name: str | None
    use_rag: bool
    tools: list[str]
    citations: list[Citation]
    facts: list[str]
    errors: list[str]
    steps: list[str]
    tool_status: list[ToolStatus]
    patient_summary: str
    draft_answer: str
    answer_source: str  # "llm" or "facts"
    guardrail_passed: bool
    answer: str


def _extract_patient_id(question: str) -> str | None:
    match = PATIENT_ID.search(question)
    return match.group(1).upper() if match else None


def _extract_drug_name(question: str) -> str | None:
    return extract_drug_name(question)


def build_graph(
    patient_database_tool: Callable[[str, PatientRecordScope], PatientDataResult],
    openfda_drug_tool: Callable[[str], OpenFDAResult],
    cardiology_rag_tool: Callable[[str, int], RetrievalResponse],
    chat_model: Any | None = None,
):
    """Build and compile the agent's StateGraph.

    Args:
        patient_database_tool, openfda_drug_tool, cardiology_rag_tool: the same
            three read-only tool callables CardiologistAgent takes.
        chat_model: a LangChain chat model (e.g. AzureChatOpenAI) used for
            answer synthesis, or None to always fall back to a deterministic
            summary of retrieved facts (mirrors CardiologistAgent's
            llm_tool=None behavior).
    """

    def parse_intent(state: AgentState) -> dict:
        question = state["question"]
        steps = list(state.get("steps", []))
        steps.append("Parsed the question for a patient ID, known drug names, and guideline/policy keywords.")
        patient_id = (state.get("patient_id") or "").strip().upper() or _extract_patient_id(question)
        drug_name = _extract_drug_name(question)
        use_rag = bool(RAG_TRIGGER.search(question))
        return {"patient_id": patient_id, "drug_name": drug_name, "use_rag": use_rag, "steps": steps}

    def patient_lookup(state: AgentState) -> dict:
        steps = list(state.get("steps", []))
        tools = list(state.get("tools", []))
        citations = list(state.get("citations", []))
        facts = list(state.get("facts", []))
        errors = list(state.get("errors", []))
        tool_status = list(state.get("tool_status", []))
        patient_id = state.get("patient_id")
        patient_summary = "No specific patient record was retrieved for this question."
        if patient_id:
            steps.append(f"Patient ID {patient_id} identified -- querying the patient database.")
            tools.append("patient_database_tool")
            try:
                scope = CardiologistAgent._patient_scope(state["question"])
                result = patient_database_tool(patient_id, scope)
                if result.found:
                    steps.append(f"Retrieved {len(result.records)} record(s) for {patient_id} from the patient database.")
                    summary = CardiologistAgent._summarize_records(result.records)
                    fact = f"Patient record evidence for {patient_id}: {summary}"
                    facts.append(fact)
                    patient_summary = fact
                    citations.append(Citation(result.source, f"Patient {patient_id}"))
                    tool_status.append(ToolStatus("patient_database_tool", "ok", f"Retrieved {len(result.records)} record(s) for {patient_id}."))
                else:
                    steps.append(f"No records were found for {patient_id} in the patient database.")
                    facts.append(result.no_record_message or "No corresponding information was found in the available patient record.")
                    tool_status.append(ToolStatus("patient_database_tool", "no_data", f"No records found for {patient_id}."))
            except Exception:
                steps.append("The patient database tool raised an error; continuing without it.")
                errors.append("Patient record information is temporarily unavailable.")
                tool_status.append(ToolStatus("patient_database_tool", "error", "Patient record information is temporarily unavailable."))
        else:
            steps.append("No patient ID was supplied or found in the question.")
        return {
            "steps": steps, "tools": tools, "citations": citations, "facts": facts,
            "errors": errors, "patient_summary": patient_summary, "tool_status": tool_status,
        }

    def drug_lookup(state: AgentState) -> dict:
        steps = list(state.get("steps", []))
        tools = list(state.get("tools", []))
        citations = list(state.get("citations", []))
        facts = list(state.get("facts", []))
        errors = list(state.get("errors", []))
        tool_status = list(state.get("tool_status", []))
        drug_name = state.get("drug_name")
        if drug_name:
            steps.append(f"Drug name '{drug_name}' detected -- querying the OpenFDA drug-label tool.")
            tools.append("openfda_drug_tool")
            try:
                result = openfda_drug_tool(drug_name)
                if result.found and result.label:
                    steps.append(f"OpenFDA label evidence retrieved for {drug_name}.")
                    generic_names = ", ".join(result.label.generic_names) or "not listed"
                    facts.append(f"OpenFDA label evidence was retrieved for {drug_name}: generic name(s) {generic_names}.")
                    citations.append(Citation("OpenFDA", drug_name))
                    tool_status.append(ToolStatus("openfda_drug_tool", "ok", f"Label evidence retrieved for {drug_name}."))
                elif result.available:
                    steps.append(f"No OpenFDA label was found for {drug_name}.")
                    facts.append(result.user_message)
                    tool_status.append(ToolStatus("openfda_drug_tool", "no_data", result.user_message))
                else:
                    steps.append(f"No OpenFDA label was found for {drug_name}.")
                    facts.append(result.user_message)
                    tool_status.append(ToolStatus("openfda_drug_tool", "error", result.user_message))
            except Exception:
                steps.append("The OpenFDA tool raised an error; continuing without it.")
                errors.append("Drug-label information is temporarily unavailable.")
                tool_status.append(ToolStatus("openfda_drug_tool", "error", "Drug-label information is temporarily unavailable."))
        return {"steps": steps, "tools": tools, "citations": citations, "facts": facts, "errors": errors, "tool_status": tool_status}

    def rag_lookup(state: AgentState) -> dict:
        steps = list(state.get("steps", []))
        tools = list(state.get("tools", []))
        citations = list(state.get("citations", []))
        facts = list(state.get("facts", []))
        errors = list(state.get("errors", []))
        tool_status = list(state.get("tool_status", []))
        if state.get("use_rag"):
            steps.append("Guideline/policy keywords detected -- searching the cardiology knowledge base.")
            tools.append("cardiology_rag_tool")
            try:
                result = cardiology_rag_tool(state["question"], 5)
                if result.results:
                    steps.append(f"Retrieved {len(result.results)} guideline passage(s) from the knowledge base.")
                    for item in result.results:
                        facts.append(f"Retrieved policy evidence: {item.document}, section {item.section}.")
                        citations.append(Citation(item.metadata.source, f"{item.document} {item.metadata.version}, {item.section}"))
                    tool_status.append(ToolStatus("cardiology_rag_tool", "ok", f"Retrieved {len(result.results)} guideline passage(s)."))
                elif result.available:
                    steps.append("No matching guideline passages were found in the knowledge base.")
                    message = result.user_message or "Sufficient evidence was not found in the knowledge base."
                    facts.append(message)
                    tool_status.append(ToolStatus("cardiology_rag_tool", "no_data", message))
                else:
                    steps.append("No matching guideline passages were found in the knowledge base.")
                    message = result.user_message or "Clinical document retrieval is temporarily unavailable."
                    facts.append(message)
                    tool_status.append(ToolStatus("cardiology_rag_tool", "error", message))
            except Exception:
                steps.append("The cardiology guideline search raised an error; continuing without it.")
                errors.append("Clinical document retrieval is temporarily unavailable.")
                tool_status.append(ToolStatus("cardiology_rag_tool", "error", "Clinical document retrieval is temporarily unavailable."))
        return {"steps": steps, "tools": tools, "citations": citations, "facts": facts, "errors": errors, "tool_status": tool_status}

    def synthesize(state: AgentState) -> dict:
        steps = list(state.get("steps", []))
        facts = list(state.get("facts", []))
        errors = list(state.get("errors", []))
        tools = state.get("tools", [])

        if not tools:
            steps.append("No tool matched this question; asking the clinician for more specific input.")
            facts.append("Please provide a patient ID for patient-specific information, a drug name, or a clinical-policy question.")
            return {"draft_answer": " ".join(facts), "answer_source": "facts", "steps": steps, "facts": facts, "errors": errors}

        if chat_model is not None:
            steps.append("Synthesizing a grounded answer from the retrieved evidence with the clinical language model.")
            try:
                patient_summary = state.get("patient_summary") or "No specific patient record was retrieved for this question."
                human_content = build_human_message(patient_summary, state["question"], facts)
                deployment_name = getattr(chat_model, "deployment_name", None) or getattr(chat_model, "model_name", None)
                with TracingSpan(
                    "llm_generation",
                    span_type="generation",
                    model=deployment_name,
                    input=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": human_content},
                    ],
                    metadata={"question_length": len(state["question"])},
                ) as generation_span:
                    response = chat_model.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=human_content)])
                    usage_metadata = getattr(response, "usage_metadata", None) or {}
                    usage = None
                    if usage_metadata:
                        usage = {
                            "input": usage_metadata.get("input_tokens"),
                            "output": usage_metadata.get("output_tokens"),
                            "total": usage_metadata.get("total_tokens"),
                            "unit": "TOKENS",
                        }
                    resolved_model = getattr(response, "response_metadata", {}).get("model_name")
                    generation_span.set_output(response.content, usage=usage, model=resolved_model)
                generated = response.content
                steps.append("Answer synthesis complete.")
                return {"draft_answer": generated, "answer_source": "llm", "steps": steps, "facts": facts, "errors": errors}
            except Exception as e:
                logger.error(f"Language-model synthesis failed: {type(e).__name__}: {e}")
                steps.append("Language-model synthesis failed; falling back to the retrieved evidence directly.")
                errors.append("Clinical answer generation is temporarily unavailable; showing retrieved evidence only.")
                return {"draft_answer": " ".join(facts), "answer_source": "facts", "steps": steps, "facts": facts, "errors": errors}

        steps.append("No language model is configured; returning the retrieved evidence directly.")
        return {"draft_answer": " ".join(facts), "answer_source": "facts", "steps": steps, "facts": facts, "errors": errors}

    def guardrail_check(state: AgentState) -> dict:
        steps = list(state.get("steps", []))
        errors = list(state.get("errors", []))
        if state.get("answer_source") != "llm":
            # Deterministic, fact-derived text needs no guardrail -- it can only
            # ever restate what's already in `facts`.
            return {"guardrail_passed": True, "steps": steps, "errors": errors}
        result = check_answer(state.get("draft_answer", ""), state.get("facts", []))
        if result.passed:
            steps.append("Guardrail check passed.")
        else:
            steps.append("Guardrail check failed; withholding the generated answer.")
            for reason in result.reasons:
                logger.warning(f"Guardrail violation: {reason}")
            errors.append("The generated answer was withheld by a safety guardrail; showing retrieved evidence only.")
        return {"guardrail_passed": result.passed, "steps": steps, "errors": errors}

    def fallback_to_evidence(state: AgentState) -> dict:
        facts = state.get("facts", [])
        return {"draft_answer": " ".join(facts), "answer_source": "facts"}

    def finalize(state: AgentState) -> dict:
        disclaimer = "Decision support only; a qualified healthcare professional must review this information."
        draft = state.get("draft_answer", "")
        separator = "\n\n" if state.get("answer_source") == "llm" else " "
        return {"answer": f"{disclaimer}{separator}{draft}"}

    graph = StateGraph(AgentState)
    graph.add_node("parse_intent", parse_intent)
    graph.add_node("patient_lookup", patient_lookup)
    graph.add_node("drug_lookup", drug_lookup)
    graph.add_node("rag_lookup", rag_lookup)
    graph.add_node("synthesize", synthesize)
    graph.add_node("guardrail_check", guardrail_check)
    graph.add_node("fallback_to_evidence", fallback_to_evidence)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("parse_intent")
    graph.add_edge("parse_intent", "patient_lookup")
    graph.add_edge("patient_lookup", "drug_lookup")
    graph.add_edge("drug_lookup", "rag_lookup")
    graph.add_edge("rag_lookup", "synthesize")
    graph.add_edge("synthesize", "guardrail_check")
    graph.add_conditional_edges(
        "guardrail_check",
        lambda state: "pass" if state.get("guardrail_passed", True) else "fail",
        {"pass": "finalize", "fail": "fallback_to_evidence"},
    )
    graph.add_edge("fallback_to_evidence", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


class LangGraphCardiologistAgent:
    """Drop-in replacement for CardiologistAgent: same review() signature and
    AgentResponse return type, backed by a compiled LangGraph StateGraph."""

    def __init__(
        self,
        patient_database_tool: Callable[[str, PatientRecordScope], PatientDataResult],
        openfda_drug_tool: Callable[[str], OpenFDAResult],
        cardiology_rag_tool: Callable[[str, int], RetrievalResponse],
        chat_model: Any | None = None,
    ) -> None:
        self._graph = build_graph(patient_database_tool, openfda_drug_tool, cardiology_rag_tool, chat_model)

    def review(self, question: str, patient_id: str | None = None) -> AgentResponse:
        if not question.strip():
            return AgentResponse("A question is required for clinical decision support.", (), (), ())
        final_state = self._graph.invoke({"question": question, "patient_id": patient_id})
        return AgentResponse(
            content=final_state.get("answer", ""),
            citations=tuple(final_state.get("citations", [])),
            tools_used=tuple(final_state.get("tools", [])),
            errors=tuple(final_state.get("errors", [])),
            steps=tuple(final_state.get("steps", [])),
            tool_status=tuple(final_state.get("tool_status", [])),
        )
