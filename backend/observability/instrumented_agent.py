"""Instrumented version of the CardialogistAgent with Langfuse tracing."""

from __future__ import annotations

import logging
from typing import Any, Callable

from backend.agent.cardiology_agent import (
    AGENT_PROMPT,
    PATIENT_ID,
    TOOL_SCHEMAS,
    AgentResponse,
    Citation,
    CardiologistAgent as BaseCardiologistAgent,
    extract_drug_name,
)
from backend.observability.tracing import (
    TracingSpan,
    trace_tool_call,
    trace_tool_result,
)
from backend.services.openfda import OpenFDAResult
from rag.models import RetrievalResponse

logger = logging.getLogger(__name__)


class InstrumentedCardiologistAgent(BaseCardiologistAgent):
    """Cardiologist agent with Langfuse tracing instrumentation."""

    def review(self, question: str, patient_id: str | None = None) -> AgentResponse:
        """Route one clinical-review request with tracing.

        Args:
            question: Clinical question
            patient_id: Patient ID supplied out-of-band by the caller (e.g. the API
                request field). Takes priority over any ID mentioned in the question
                text; falls back to extracting one from the question when omitted.

        Returns:
            AgentResponse with citations, tools used, and errors
        """
        if not question.strip():
            return AgentResponse("A question is required for clinical decision support.", (), (), ())

        steps: list[str] = ["Parsed the question for a patient ID, known drug names, and guideline/policy keywords."]
        patient_id = (patient_id or "").strip().upper() or self._patient_id(question)
        drug_name = self._drug_name(question)
        use_rag = self._should_use_rag(question)

        tools, citations, facts, errors = [], [], [], []

        # Trace patient database tool call
        if patient_id:
            steps.append(f"Patient ID {patient_id} identified -- querying the patient database.")
            tools.append("patient_database_tool")
            span = trace_tool_call(
                "patient_database_tool",
                {"patient_id": patient_id, "scope": "profile"},
            )
            try:
                with span:
                    result = self._patient_database_tool(
                        patient_id, self._patient_scope(question)
                    )
                    trace_tool_result(span, result)
                    
                    if result.found:
                        steps.append(f"Retrieved {len(result.records)} record(s) for {patient_id} from the patient database.")
                        facts.append(
                            f"Patient record evidence for {patient_id}: "
                            f"{self._summarize_records(result.records)}"
                        )
                        citations.append(Citation(result.source, f"Patient {patient_id}"))
                    else:
                        steps.append(f"No records were found for {patient_id} in the patient database.")
                        facts.append(
                            result.no_record_message
                            or "No corresponding information was found in the available patient record."
                        )
            except Exception as e:
                error_msg = f"Patient record information is temporarily unavailable: {str(e)}"
                steps.append("The patient database tool raised an error; continuing without it.")
                errors.append("Patient record information is temporarily unavailable.")
                trace_tool_result(span, error=error_msg)
                logger.error(error_msg)
        else:
            steps.append("No patient ID was supplied or found in the question.")

        # Trace OpenFDA tool call
        if drug_name:
            steps.append(f"Drug name '{drug_name}' detected -- querying the OpenFDA drug-label tool.")
            tools.append("openfda_drug_tool")
            span = trace_tool_call(
                "openfda_drug_tool",
                {"drug_name": drug_name},
            )
            try:
                with span:
                    result = self._openfda_drug_tool(drug_name)
                    trace_tool_result(span, result)
                    
                    if result.found and result.label:
                        generic_names = ", ".join(result.label.generic_names) or "not listed"
                        steps.append(f"OpenFDA label evidence retrieved for {drug_name}.")
                        facts.append(
                            f"OpenFDA label evidence was retrieved for {drug_name}: "
                            f"generic name(s) {generic_names}."
                        )
                        citations.append(Citation("OpenFDA", drug_name))
                    else:
                        steps.append(f"No OpenFDA label was found for {drug_name}.")
                        facts.append(result.user_message)
            except Exception as e:
                error_msg = f"Drug-label information is temporarily unavailable: {str(e)}"
                steps.append("The OpenFDA tool raised an error; continuing without it.")
                errors.append("Drug-label information is temporarily unavailable.")
                trace_tool_result(span, error=error_msg)
                logger.error(error_msg)

        # Trace RAG tool call
        if use_rag:
            steps.append("Guideline/policy keywords detected -- searching the cardiology knowledge base.")
            tools.append("cardiology_rag_tool")
            span = trace_tool_call(
                "cardiology_rag_tool",
                {"query": question[:100], "limit": 5},
            )
            try:
                with span:
                    result = self._cardiology_rag_tool(question, 5)
                    trace_tool_result(span, result)
                    
                    if result.results:
                        steps.append(f"Retrieved {len(result.results)} guideline passage(s) from the knowledge base.")
                        for item in result.results:
                            facts.append(
                                f"Retrieved policy evidence: {item.document}, "
                                f"section {item.section}."
                            )
                            citations.append(
                                Citation(
                                    item.metadata.source,
                                    f"{item.document} {item.metadata.version}, {item.section}",
                                )
                            )
                    else:
                        steps.append("No matching guideline passages were found in the knowledge base.")
                        facts.append(
                            result.user_message
                            or "Sufficient evidence was not found in the knowledge base."
                        )
            except Exception as e:
                error_msg = f"Clinical document retrieval is temporarily unavailable: {str(e)}"
                steps.append("The cardiology guideline search raised an error; continuing without it.")
                errors.append("Clinical document retrieval is temporarily unavailable.")
                trace_tool_result(span, error=error_msg)
                logger.error(error_msg)

        if not tools:
            steps.append("No tool matched this question; asking the clinician for more specific input.")
            facts.append(
                "Please provide a patient ID for patient-specific information, "
                "a drug name, or a clinical-policy question."
            )
            content = (
                "Decision support only; a qualified healthcare professional must review this information. "
                + " ".join(facts)
            )
        elif self._llm_tool is not None:
            steps.append("Synthesizing a grounded answer from the retrieved evidence with the clinical language model.")
            span = TracingSpan(
                "llm_generation",
                span_type="generation",
                metadata={"question_length": len(question)},
            )
            try:
                with span:
                    patient_summary = next(
                        (fact for fact in facts if fact.startswith("Patient record evidence")),
                        "No specific patient record was retrieved for this question.",
                    )
                    generated = self._llm_tool(patient_summary, question, facts)
                    # self._llm_tool only returns the generated text, not a
                    # response object with token usage, so cost/tokens aren't
                    # available here the way they are for LangGraphCardiologistAgent
                    # (backend/agent/graph.py) -- this legacy path is unused by
                    # backend/main.py and kept only as a rollback.
                    span.set_output(generated)
                steps.append("Answer synthesis complete.")
                content = (
                    "Decision support only; a qualified healthcare professional must review this information.\n\n"
                    + generated
                )
            except Exception as e:
                error_msg = f"Clinical answer generation is temporarily unavailable: {str(e)}"
                steps.append("Language-model synthesis failed; falling back to the retrieved evidence directly.")
                errors.append("Clinical answer generation is temporarily unavailable; showing retrieved evidence only.")
                trace_tool_result(span, error=error_msg)
                logger.error(error_msg)
                content = (
                    "Decision support only; a qualified healthcare professional must review this information. "
                    + " ".join(facts)
                )
        else:
            steps.append("No language model is configured; returning the retrieved evidence directly.")
            content = (
                "Decision support only; a qualified healthcare professional must review this information. "
                + " ".join(facts)
            )
        return AgentResponse(content, tuple(citations), tuple(tools), tuple(errors), tuple(steps))

    def _should_use_rag(self, question: str) -> bool:
        """Check if RAG should be used."""
        import re
        return bool(
            re.search(
                r"\b(policy|guideline|protocol|hospital)\b",
                question,
                re.IGNORECASE,
            )
        )

    def _patient_id(self, question: str) -> str | None:
        """Extract patient ID from question."""
        match = PATIENT_ID.search(question)
        return match.group(1).upper() if match else None

    def _drug_name(self, question: str) -> str | None:
        """Extract drug name from question."""
        return extract_drug_name(question)
