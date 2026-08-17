from __future__ import annotations

from typing import Any, TypedDict

from cardiologist_agent.domain.patient import Patient
from cardiologist_agent.domain.response import DependencyStatus, MedicationRecommendationResponse
from cardiologist_agent.providers.openfda import OpenFDAResult
from cardiologist_agent.repositories.policy import RetrievalResult
from cardiologist_agent.safety.assessment import SafetyAssessment


class ReviewState(TypedDict, total=False):
    request_id: str
    patient_id: str
    clinician_id: str
    clinical_question: str
    patient: Patient | None
    assessment: SafetyAssessment | None
    retrieval: RetrievalResult | None
    openfda_results: list[OpenFDAResult]
    dependencies: list[DependencyStatus]
    authorization_status: str
    has_signed_orders: bool
    llm_payload: dict[str, Any] | None
    llm_used: bool
    response: MedicationRecommendationResponse | None
    error: str | None
