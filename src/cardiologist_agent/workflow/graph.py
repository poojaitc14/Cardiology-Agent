from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, StateGraph

from cardiologist_agent.domain.enums import AuthorizationStatus
from cardiologist_agent.domain.response import DependencyStatus
from cardiologist_agent.providers.llm import LLMProvider
from cardiologist_agent.providers.openfda import OpenFDAClient
from cardiologist_agent.repositories.medication_order import MedicationOrderRepository
from cardiologist_agent.repositories.patient import PatientRepository
from cardiologist_agent.repositories.policy import PolicyRetriever
from cardiologist_agent.safety.assessment import SafetyAssessment, assess_patient
from cardiologist_agent.workflow.response_builder import build_response
from cardiologist_agent.workflow.state import ReviewState


class ReviewWorkflow:
    def __init__(
        self,
        patient_repo: PatientRepository,
        order_repo: MedicationOrderRepository,
        policy_retriever: PolicyRetriever,
        openfda_client: OpenFDAClient,
        llm_provider: LLMProvider,
    ) -> None:
        self.patient_repo = patient_repo
        self.order_repo = order_repo
        self.policy_retriever = policy_retriever
        self.openfda_client = openfda_client
        self.llm_provider = llm_provider
        self.graph = self._build_graph()

    def _build_graph(self):  # noqa: ANN202
        graph = StateGraph(ReviewState)
        graph.add_node("load_patient", self._load_patient)
        graph.add_node("assess_safety", self._assess_safety)
        graph.add_node("retrieve_evidence", self._retrieve_evidence)
        graph.add_node("openfda_lookup", self._openfda_lookup)
        graph.add_node("llm_synthesize", self._llm_synthesize)
        graph.add_node("assemble_response", self._assemble_response)

        graph.set_entry_point("load_patient")
        graph.add_edge("load_patient", "assess_safety")
        graph.add_edge("assess_safety", "retrieve_evidence")
        graph.add_edge("retrieve_evidence", "openfda_lookup")
        graph.add_edge("openfda_lookup", "llm_synthesize")
        graph.add_edge("llm_synthesize", "assemble_response")
        graph.add_edge("assemble_response", END)
        return graph.compile()

    async def _load_patient(self, state: ReviewState) -> dict[str, Any]:
        patient = await self.patient_repo.get_patient(state["patient_id"])
        if patient is None:
            return {"error": "Patient not found", "patient": None}
        auth_status = await self.order_repo.authorization_source_status()
        orders = await self.order_repo.get_active_orders(state["patient_id"])
        return {
            "patient": patient,
            "authorization_status": auth_status.value,
            "has_signed_orders": len(orders) > 0,
        }

    async def _assess_safety(self, state: ReviewState) -> dict[str, Any]:
        patient = state.get("patient")
        if patient is None:
            assessment = SafetyAssessment()
            assessment.inactive_record = True
            return {"assessment": assessment}
        return {"assessment": assess_patient(patient)}

    async def _retrieve_evidence(self, state: ReviewState) -> dict[str, Any]:
        query = state.get("clinical_question", "cardiology medication review safety")
        retrieval = await self.policy_retriever.retrieve(query)
        return {"retrieval": retrieval}

    async def _openfda_lookup(self, state: ReviewState) -> dict[str, Any]:
        patient = state.get("patient")
        deps = list(state.get("dependencies") or [])
        results = []
        if patient is None:
            return {"openfda_results": results, "dependencies": deps}
        active = [
            m.drug_name for m in patient.medications if m.medication_status.lower() == "active"
        ]
        for drug in active[:3]:
            result = await self.openfda_client.lookup_drug_label(drug)
            results.append(result)
        deps.append(
            DependencyStatus(
                name="openfda",
                available=not any(r.error for r in results),
                message=results[0].error if results and results[0].error else None,
            )
        )
        return {"openfda_results": results, "dependencies": deps}

    async def _llm_synthesize(self, state: ReviewState) -> dict[str, Any]:
        if state.get("error"):
            return {"llm_payload": None, "llm_used": False}
        system = (
            "You are a clinical documentation assistant for a fictional training system. "
            "Use only verified facts provided. Do not prescribe, authorize, invent doses, "
            "or infer signed orders. Return JSON with clinical_rationale, attention_items, "
            "future_course_of_action."
        )
        user = json.dumps(
            {
                "question": state.get("clinical_question"),
                "patient_id": state.get("patient_id"),
                "flags": [
                    {"code": f.code, "message": f.message}
                    for f in (state.get("assessment").flags if state.get("assessment") else [])
                ],
            }
        )
        try:
            raw = await self.llm_provider.synthesize(system, user)
            payload = (
                json.loads(raw) if raw.strip().startswith("{") else {"clinical_rationale": raw}
            )
            return {"llm_payload": payload, "llm_used": self.llm_provider.available}
        except Exception:  # noqa: BLE001
            return {"llm_payload": None, "llm_used": False}

    async def _assemble_response(self, state: ReviewState) -> dict[str, Any]:
        patient = state.get("patient")
        assessment = state.get("assessment")
        if patient is None or assessment is None:
            from cardiologist_agent.domain.enums import (
                EvidenceGrade,
                RecommendationAction,
                ReviewStatus,
            )
            from cardiologist_agent.domain.response import (
                AuthorizationBlock,
                MedicationRecommendationResponse,
                PatientSnapshot,
            )

            return {
                "response": MedicationRecommendationResponse(
                    request_id=state["request_id"],
                    patient_id=state["patient_id"],
                    review_status=ReviewStatus.SYSTEM_UNAVAILABLE,
                    evidence_grade=EvidenceGrade.INSUFFICIENT,
                    recommendation_action=RecommendationAction.NO_RECOMMENDATION,
                    clinical_rationale="Patient record unavailable.",
                    authorization=AuthorizationBlock(),
                    patient_snapshot=PatientSnapshot(
                        patient_id=state["patient_id"],
                        name="Unknown",
                        date_of_birth="",
                        record_status="Unknown",
                        allergy_summary="Unknown",
                    ),
                    safest_next_action="Verify patient identifier and record availability.",
                )
            }

        auth = AuthorizationStatus(
            state.get("authorization_status", AuthorizationStatus.UNAVAILABLE)
        )
        response = build_response(
            request_id=state["request_id"],
            patient=patient,
            clinical_question=state.get("clinical_question", ""),
            assessment=assessment,
            retrieval=state.get("retrieval"),
            openfda_results=state.get("openfda_results") or [],
            authorization_status=auth,
            has_signed_orders=bool(state.get("has_signed_orders")),
            dependencies=state.get("dependencies") or [],
            llm_payload=state.get("llm_payload"),
            llm_used=bool(state.get("llm_used")),
        )
        return {"response": response}

    async def run(
        self,
        *,
        request_id: str,
        patient_id: str,
        clinician_id: str,
        clinical_question: str,
    ):
        initial: ReviewState = {
            "request_id": request_id,
            "patient_id": patient_id,
            "clinician_id": clinician_id,
            "clinical_question": clinical_question,
            "dependencies": [],
        }
        final_state = await self.graph.ainvoke(initial)
        return final_state["response"]
