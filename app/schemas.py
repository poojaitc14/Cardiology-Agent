from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    patient_id: str = Field(pattern=r"^P[0-9]+$", examples=["P1005"])
    requesting_user_id: str = Field(min_length=3, examples=["clinician-demo"])
    question: str = Field(min_length=10, max_length=1_000)


class SourceRef(BaseModel):
    source_id: str
    source_type: Literal["patient_record", "hospital_policy", "medication_api"]
    observed_at: datetime | None = None
    document_version: str | None = None
    section: str | None = None


class ClinicalFact(BaseModel):
    fact: str
    source: SourceRef


class AttentionItem(BaseModel):
    observation: str
    basis: list[SourceRef]
    requires_clinician_verification: bool = True


class ReviewResponse(BaseModel):
    patient_id: str
    review_generated_at: datetime
    summary: str
    cardiovascular_history: list[ClinicalFact]
    current_medications: list[ClinicalFact]
    allergies: list[ClinicalFact]
    recent_laboratory_results: list[ClinicalFact]
    attention_items: list[AttentionItem]
    approved_knowledge: list[ClinicalFact]
    limitations: list[str]
    disclaimer: str = (
        "For clinician review only. This read-only system does not diagnose, "
        "prescribe, calculate doses, place orders, or replace clinical judgement."
    )


RecordType = Literal["CONDITION", "LAB", "MEDICATION", "ALLERGY", "VITALS", "CARDIOLOGY_PROCEDURE"]


class PatientProfileUpsert(BaseModel):
    """The one profile item stored for each patient in the DynamoDB single table."""

    patient_id: str = Field(pattern=r"^P[0-9]+$")
    admin_user_id: str = Field(min_length=3)
    smoking_status: str | None = None
    family_history_cardiovascular_disease: str | None = None
    primary_cardiologist: str | None = None
    source: str = "ADMIN_PORTAL"
    status: str = "ACTIVE"


class ClinicalRecordCreate(BaseModel):
    """A sparse item: common fields plus fields relevant to its record_type."""

    patient_id: str = Field(pattern=r"^P[0-9]+$")
    admin_user_id: str = Field(min_length=3)
    record_type: RecordType
    source: str = "ADMIN_PORTAL"
    status: str = "ACTIVE"
    # Medical conditions/history
    condition_name: str | None = None
    condition_category: str | None = None
    diagnosis_date: str | None = None
    condition_status: str | None = None
    severity: str | None = None
    # Laboratory results
    test_name: str | None = None
    test_value: str | None = None
    test_unit: str | None = None
    reference_range: str | None = None
    interpretation: Literal["normal", "high", "low", "critical"] | None = None
    test_date: str | None = None
    # Medications
    medication_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    prescriber: str | None = None
    indication: str | None = None
    medication_status: str | None = None
    # Allergies
    allergy_name: str | None = None
    allergy_type: Literal["allergy", "intolerance"] | None = None
    recorded_date: str | None = None
    # Vital signs
    systolic_bp: int | None = Field(default=None, ge=0)
    diastolic_bp: int | None = Field(default=None, ge=0)
    heart_rate: int | None = Field(default=None, ge=0)
    weight: float | None = Field(default=None, ge=0)
    oxygen_saturation: float | None = Field(default=None, ge=0, le=100)
    measured_at: str | None = None
    # Cardiology tests/procedures
    test_or_procedure_name: str | None = None
    performed_date: str | None = None
    result_summary: str | None = None
    notes: str | None = None
