from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from cardiologist_agent.domain.enums import AuthorizationStatus, RecommendationAction


class Condition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str
    condition_name: str
    condition_category: str | None = None
    diagnosis_date: date | None = None
    condition_status: str | None = None
    severity: str | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: str | None = None
    status: str | None = None


class MedicationHistoryRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str
    drug_name: str
    dose: float | int | None = None
    dose_unit: str | None = None
    frequency: str | None = None
    route: str | None = None
    medication_status: str
    start_date: date | None = None
    end_date: date | None = None
    prescriber: str | None = None
    indication: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: str | None = None
    status: str | None = None


class Allergy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str
    allergen: str
    allergy_type: str | None = None
    reaction: str | None = None
    severity: str | None = None
    allergy_status: str | None = None
    recorded_date: date | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: str | None = None
    status: str | None = None


class LabResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str
    test_name: str
    test_value: float | int | None = None
    test_unit: str | None = None
    reference_range: str | None = None
    interpretation: str | None = None
    test_date: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: str | None = None
    status: str | None = None


class VitalSign(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str
    systolic_bp: int | None = None
    diastolic_bp: int | None = None
    heart_rate: int | None = None
    weight: float | None = None
    weight_unit: str | None = None
    oxygen_saturation: int | None = None
    measured_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: str | None = None
    status: str | None = None


class CardiologyTest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str
    test_or_procedure_name: str
    performed_date: datetime | None = None
    result_summary: str | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: str | None = None
    status: str | None = None


class Patient(BaseModel):
    model_config = ConfigDict(extra="ignore")

    patient_id: str
    first_name: str
    last_name: str
    date_of_birth: date
    gender: str | None = None
    smoking_status: str | None = None
    family_history_cardiovascular_disease: bool | None = None
    primary_cardiologist: str | None = None
    conditions: list[Condition] = Field(default_factory=list)
    medications: list[MedicationHistoryRecord] = Field(default_factory=list)
    allergies: list[Allergy] = Field(default_factory=list)
    lab_results: list[LabResult] = Field(default_factory=list)
    vital_signs: list[VitalSign] = Field(default_factory=list)
    cardiology_tests: list[CardiologyTest] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: str | None = None
    status: str = "Active"


class MedicationOrder(BaseModel):
    order_id: str
    order_version: int
    patient_id: str
    medication_record_id: str | None = None
    drug_name: str
    formulation: str
    strength: str
    dose: Decimal
    dose_unit: str
    route: str
    frequency: str
    timing: str | None = None
    food_or_formulation_instructions: str | None = None
    start_date: date
    duration_or_stop_date: date | None = None
    review_or_expiry_date: date
    missed_dose_instructions: str
    prohibited_self_adjustments: str | None = None
    temporary_hold_instructions: str | None = None
    restart_instructions: str | None = None
    authorization_status: AuthorizationStatus
    authorizing_clinician_id: str
    authorization_timestamp: datetime
    effective_date: date
    recommendation_action: RecommendationAction = RecommendationAction.CONTINUE
