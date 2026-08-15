"""Instrumented version of the CardialogistAgent with Langfuse tracing."""

from __future__ import annotations

import logging
from typing import Any, Callable

from backend.agent.cardiology_agent import (
    AGENT_PROMPT,
    KNOWN_DRUGS,
    PATIENT_ID,
    TOOL_SCHEMAS,
    AgentResponse,
    Citation,
    CardiologistAgent as BaseCardiologistAgent,
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

        patient_id = (patient_id or "").strip().upper() or self._patient_id(question)
        drug_name = self._drug_name(question)
        use_rag = self._should_use_rag(question)
        
        tools, citations, facts, errors = [], [], [], []

        # Trace patient database tool call
        if patient_id:
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
                        facts.append(
                            f"Patient record evidence for {patient_id}: "
                            f"{self._summarize_records(result.records)}"
                        )
                        citations.append(Citation(result.source, f"Patient {patient_id}"))
                    else:
                        facts.append(
                            result.no_record_message
                            or "No corresponding information was found in the available patient record."
                        )
            except Exception as e:
                error_msg = f"Patient record information is temporarily unavailable: {str(e)}"
                errors.append("Patient record information is temporarily unavailable.")
                trace_tool_result(span, error=error_msg)
                logger.error(error_msg)

        # Trace OpenFDA tool call
        if drug_name:
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
                        facts.append(
                            f"OpenFDA label evidence was retrieved for {drug_name}: "
                            f"generic name(s) {generic_names}."
                        )
                        citations.append(Citation("OpenFDA", drug_name))
                    else:
                        facts.append(result.user_message)
            except Exception as e:
                error_msg = f"Drug-label information is temporarily unavailable: {str(e)}"
                errors.append("Drug-label information is temporarily unavailable.")
                trace_tool_result(span, error=error_msg)
                logger.error(error_msg)

        # Trace RAG tool call
        if use_rag:
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
                        facts.append(
                            result.user_message
                            or "Sufficient evidence was not found in the knowledge base."
                        )
            except Exception as e:
                error_msg = f"Clinical document retrieval is temporarily unavailable: {str(e)}"
                errors.append("Clinical document retrieval is temporarily unavailable.")
                trace_tool_result(span, error=error_msg)
                logger.error(error_msg)

        if not tools:
            facts.append(
                "Please provide a patient ID for patient-specific information, "
                "a drug name, or a clinical-policy question."
            )
            content = (
                "Decision support only; a qualified healthcare professional must review this information. "
                + " ".join(facts)
            )
        elif self._llm_tool is not None:
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
                content = (
                    "Decision support only; a qualified healthcare professional must review this information.\n\n"
                    + generated
                )
            except Exception as e:
                error_msg = f"Clinical answer generation is temporarily unavailable: {str(e)}"
                errors.append("Clinical answer generation is temporarily unavailable; showing retrieved evidence only.")
                trace_tool_result(span, error=error_msg)
                logger.error(error_msg)
                content = (
                    "Decision support only; a qualified healthcare professional must review this information. "
                    + " ".join(facts)
                )
        else:
            content = (
                "Decision support only; a qualified healthcare professional must review this information. "
                + " ".join(facts)
            )
        return AgentResponse(content, tuple(citations), tuple(tools), tuple(errors))

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
        match = KNOWN_DRUGS.search(question)
        return match.group(1).capitalize() if match else None
