from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from cardiologist_agent.domain.enums import (
    AuthorizationStatus,
    ClaimType,
    EvidenceGrade,
    RecommendationAction,
    ReviewStatus,
    Severity,
)


class Citation(BaseModel):
    source_type: str
    document_id: str | None = None
    version: str | None = None
    section: str | None = None
    page: int | None = None
    chunk_id: str | None = None
    retrieved_at: datetime | None = None
    url: str | None = None
    patient_field: str | None = None
    order_id: str | None = None


class Claim(BaseModel):
    claim_id: str
    claim_type: ClaimType
    text: str
    citations: list[Citation] = Field(default_factory=list)
    supported: bool = True


class SafetyFlag(BaseModel):
    code: str
    severity: Severity
    message: str
    field: str | None = None


class ConflictItem(BaseModel):
    code: str
    description: str
    withheld: str | None = None
    owner: str | None = None
    urgency: Severity = Severity.WARNING


class DataGap(BaseModel):
    category: str
    description: str
    field: str | None = None


class MedicationInstructionDraft(BaseModel):
    medication_name: str | None = None
    formulation: str | None = None
    strength: str | None = None
    dose: str | None = None
    dose_unit: str | None = None
    route: str | None = None
    frequency: str | None = None
    timing: str | None = None
    food_instructions: str | None = None
    start_date: str | None = None
    duration_or_stop_date: str | None = None
    review_date: str | None = None
    missed_dose_instructions: str | None = None
    prohibited_self_adjustments: str | None = None
    hold_restart_instructions: str | None = None
    source: str = "medication_history"
    authorized: bool = False


class AuthorizationBlock(BaseModel):
    authorization_status: AuthorizationStatus = AuthorizationStatus.UNAVAILABLE
    authorizing_clinician: str | None = None
    order_id: str | None = None
    order_version: int | None = None
    authorization_timestamp: datetime | None = None
    effective_date: str | None = None
    review_or_expiry_date: str | None = None
    message: str = "No signed medication order source configured."


class RequiredTest(BaseModel):
    test: str
    purpose: str
    target_date_or_window: str | None = None
    prerequisites: str | None = None
    booking_owner: str | None = None
    results_owner: str | None = None
    escalation: str | None = None


class FutureAppointment(BaseModel):
    appointment_type: str
    purpose: str
    urgency: str | None = None
    target_date_or_window: str | None = None
    prerequisites: str | None = None
    responsible_service: str | None = None
    responsible_reviewer: str | None = None
    outcome_communication_route: str | None = None


class DependencyStatus(BaseModel):
    name: str
    available: bool
    message: str | None = None


class PatientSnapshot(BaseModel):
    patient_id: str
    name: str
    date_of_birth: str
    gender: str | None = None
    primary_cardiologist: str | None = None
    record_status: str
    active_conditions: list[str] = Field(default_factory=list)
    active_medications: list[str] = Field(default_factory=list)
    allergy_summary: str
    latest_vitals_summary: str | None = None
    recent_medicines_summary: str | None = None
    recent_labs_summary: str | None = None
    recent_care_summary: str | None = None


class MedicationRecommendationResponse(BaseModel):
    request_id: str
    patient_id: str
    review_status: ReviewStatus
    evidence_grade: EvidenceGrade
    recommendation_action: RecommendationAction
    clinical_rationale: str
    authorization: AuthorizationBlock
    medication_instructions: list[MedicationInstructionDraft] = Field(default_factory=list)
    patient_snapshot: PatientSnapshot
    attention_items: list[str] = Field(default_factory=list)
    warnings_and_red_flags: list[str] = Field(default_factory=list)
    required_tests: list[RequiredTest] = Field(default_factory=list)
    future_appointments: list[FutureAppointment] = Field(default_factory=list)
    future_course_of_action: list[str] = Field(default_factory=list)
    missing_or_stale_data: list[DataGap] = Field(default_factory=list)
    conflicts: list[ConflictItem] = Field(default_factory=list)
    unavailable_dependencies: list[DependencyStatus] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    safest_next_action: str
    llm_synthesis_used: bool = False


class ReviewRequest(BaseModel):
    patient_id: str
    clinical_question: str
    clinician_id: str = "DR101"
    request_id: str | None = None


class QueryRequest(BaseModel):
    patient_id: str | None = None
    clinical_question: str
    clinician_id: str = "Reception"
    mode: str = "auto"
    request_id: str | None = None


class QueryResponse(BaseModel):
    request_id: str
    query_mode: str
    patient_id: str | None = None
    answer: str
    sources: list[Citation] = Field(default_factory=list)
    review: MedicationRecommendationResponse | None = None


class CreatePatientRequest(BaseModel):
    patient_id: str | None = None
    condition_name: str
    on_medication: bool = False
    medication_name: str | None = None
    primary_cardiologist: str = "DR104"
    clinician_id: str = "Reception"
    clinical_question: str = (
        "Please check the heart record, medicines, recent test results, "
        "and tell me clearly what should happen next."
    )
    run_review: bool = True


class PatientListResponse(BaseModel):
    patient_ids: list[str]
    suggested_next_id: str
    total: int


class CreatePatientResponse(BaseModel):
    patient_id: str
    created: bool = True
    review: MedicationRecommendationResponse | None = None


class HealthResponse(BaseModel):
    status: str
    app_env: str
    version: str


class ReadyResponse(BaseModel):
    ready: bool
    checks: dict[str, bool]
    messages: list[str] = Field(default_factory=list)
