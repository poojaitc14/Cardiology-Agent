from __future__ import annotations

import re
from datetime import date, datetime

from cardiologist_agent.config.settings import Settings, get_settings
from cardiologist_agent.domain.patient import (
    CardiologyTest,
    Condition,
    LabResult,
    MedicationHistoryRecord,
    Patient,
    VitalSign,
)

CONDITION_CHOICES = [
    "Mild hypertension",
    "Borderline high cholesterol",
    "Benign palpitations",
    "Innocent heart murmur",
    "Mild mitral regurgitation",
    "Family history of heart disease",
]

MEDICATION_CHOICES = [
    "Amlodipine",
    "Atorvastatin",
    "Lisinopril",
    "Bisoprolol",
]


def suggest_next_patient_id(existing_ids: list[str]) -> str:
    numbers = []
    for pid in existing_ids:
        match = re.fullmatch(r"P(\d+)", pid.upper())
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers, default=1000) + 1
    return f"P{next_num}"


def build_patient_from_intake(
    *,
    patient_id: str,
    condition_name: str,
    on_medication: bool,
    medication_name: str | None,
    primary_cardiologist: str,
    settings: Settings | None = None,
) -> Patient:
    settings = settings or get_settings()
    ref = settings.reference_date
    now = datetime.combine(ref, datetime.min.time())

    suffix = patient_id[1:]
    conditions = [
        Condition(
            record_id="C001",
            condition_name=condition_name,
            condition_category="Cardiovascular",
            diagnosis_date=date(ref.year - 2, 6, 1),
            condition_status="Active",
            severity="Mild",
            notes="Added through the training intake form.",
            created_at=now,
            updated_at=now,
            source="Training intake",
            status="Active",
        )
    ]

    medications: list[MedicationHistoryRecord] = []
    if on_medication and medication_name:
        medications.append(
            MedicationHistoryRecord(
                record_id="M001",
                drug_name=medication_name,
                dose=5 if medication_name == "Amlodipine" else 20 if medication_name == "Atorvastatin" else 10,
                dose_unit="mg",
                frequency="Once daily",
                route="Oral",
                medication_status="Active",
                start_date=date(ref.year - 1, 3, 1),
                end_date=None,
                prescriber=primary_cardiologist,
                indication=condition_name,
                created_at=now,
                updated_at=now,
                source="Training intake",
                status="Valid",
            )
        )

    lab_date = datetime(ref.year, ref.month, max(1, ref.day - 14), 10, 0, 0)
    lab_results = [
        LabResult(
            record_id="L001",
            test_name="Potassium",
            test_value=4.2,
            test_unit="mmol/L",
            reference_range="3.5-5.0",
            interpretation="Normal",
            test_date=lab_date,
            created_at=lab_date,
            updated_at=lab_date,
            source="Hospital laboratory",
            status="Final",
        ),
        LabResult(
            record_id="L002",
            test_name="Creatinine",
            test_value=82,
            test_unit="umol/L",
            reference_range="45-105",
            interpretation="Normal",
            test_date=lab_date,
            created_at=lab_date,
            updated_at=lab_date,
            source="Hospital laboratory",
            status="Final",
        ),
    ]

    vital_signs = [
        VitalSign(
            record_id="V001",
            systolic_bp=128,
            diastolic_bp=78,
            heart_rate=72,
            weight=75.0,
            weight_unit="kg",
            oxygen_saturation=97,
            measured_at=lab_date,
            created_at=lab_date,
            updated_at=lab_date,
            source="Cardiology clinic",
            status="Final",
        )
    ]

    cardiology_tests = [
        CardiologyTest(
            record_id="T001",
            test_or_procedure_name="12-lead ECG",
            performed_date=lab_date,
            result_summary="Normal sinus rhythm",
            notes="No urgent abnormality",
            created_at=lab_date,
            updated_at=lab_date,
            source="Cardiology department",
            status="Final",
        )
    ]

    birth_year = ref.year - (45 + (int(suffix) % 20))
    return Patient(
        patient_id=patient_id.upper(),
        first_name="Training",
        last_name=f"Record {suffix}",
        date_of_birth=date(birth_year, 1, 15),
        gender=["Female", "Male", "Non-binary"][int(suffix) % 3],
        smoking_status="Never smoked",
        family_history_cardiovascular_disease=condition_name == "Family history of heart disease",
        primary_cardiologist=primary_cardiologist,
        conditions=conditions,
        medications=medications,
        allergies=[],
        lab_results=lab_results,
        vital_signs=vital_signs,
        cardiology_tests=cardiology_tests,
        created_at=now,
        updated_at=now,
        source="Training intake",
        status="Active",
    )
