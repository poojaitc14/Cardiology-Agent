"""Deterministic generator for clearly labelled synthetic patient records."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

FIRST_NAMES = ("Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Avery", "Cameron")
LAST_NAMES = ("Reed", "Patel", "Morgan", "Taylor", "Bennett", "Hayes", "Quinn", "Shaw")
MEDICATIONS = (("Lisinopril", "10", "mg"), ("Atorvastatin", "20", "mg"), ("Metoprolol", "25", "mg"))
ALLERGENS = (("Penicillin", "Skin rash", "Moderate"), ("Aspirin", "Nausea", "Mild"), ("None known", "", ""))


def generate_patients(count: int = 100, seed: int = 20260814) -> list[dict[str, Any]]:
    """Generate complete DynamoDB items for a requested number of synthetic patients."""
    if count < 1:
        raise ValueError("count must be at least 1")
    rng = random.Random(seed)
    return [item for number in range(1, count + 1) for item in _patient_items(number, rng)]


def _patient_items(number: int, rng: random.Random) -> list[dict[str, Any]]:
    patient_id = f"P{1000 + number}"
    pk = f"PATIENT#{patient_id}"
    birth_date = date(1945, 1, 1) + timedelta(days=rng.randint(0, 21000))
    now = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    medication_name, dose, dose_unit = rng.choice(MEDICATIONS)
    allergen, reaction, severity = rng.choice(ALLERGENS)
    lab_date = f"2026-08-{rng.randint(1, 14):02d}T09:15:00Z"
    common = {"PK": pk, "patient_id": patient_id, "source": "Synthetic training dataset", "created_at": now, "updated_at": now}
    return [
        {**common, "SK": "PROFILE", "entity_type": "PATIENT_PROFILE", "first_name": rng.choice(FIRST_NAMES), "last_name": rng.choice(LAST_NAMES), "date_of_birth": birth_date.isoformat(), "gender": rng.choice(("Female", "Male", "Non-binary")), "smoking_status": rng.choice(("Never smoker", "Former smoker", "Current smoker")), "family_history_cardiovascular_disease": rng.choice((True, False)), "primary_cardiologist": f"DR{rng.randint(100, 199)}", "record_status": "Active"},
        {**common, "SK": "CONDITION#2020-04-10#C001", "entity_type": "CONDITION", "record_id": "C001", "condition_name": rng.choice(("Hypertension", "Coronary artery disease", "Atrial fibrillation")), "condition_category": "Cardiovascular", "condition_status": "Active", "severity": rng.choice(("Mild", "Moderate")), "diagnosis_date": "2020-04-10", "record_status": "Active"},
        {**common, "SK": "MEDICATION#2025-01-15#M001", "GSI1PK": f"{pk}#MEDICATION", "GSI1SK": "2025-01-15T09:00:00Z#M001", "GSI2PK": f"MEDICATION#{medication_name.upper()}", "GSI2SK": f"{pk}#2025-01-15#M001", "entity_type": "MEDICATION", "record_id": "M001", "drug_name": medication_name, "normalised_drug_name": medication_name.upper(), "dose": dose, "dose_unit": dose_unit, "frequency": "Once daily", "route": "Oral", "medication_status": "Active", "start_date": "2025-01-15", "end_date": None, "prescriber": "DR101", "indication": "Synthetic recorded indication", "record_status": "Active"},
        {**common, "SK": "ALLERGY#2024-06-20#A001", "GSI1PK": f"{pk}#ALLERGY", "GSI1SK": "2024-06-20T10:00:00Z#A001", "entity_type": "ALLERGY", "record_id": "A001", "allergen": allergen, "allergy_type": "Allergy", "reaction": reaction, "severity": severity, "allergy_status": "Active" if allergen != "None known" else "Not recorded", "recorded_date": "2024-06-20", "record_status": "Active"},
        {**common, "SK": f"LAB#{lab_date}#L001", "GSI1PK": f"{pk}#LAB", "GSI1SK": f"{lab_date}#L001", "entity_type": "LAB_RESULT", "record_id": "L001", "test_name": rng.choice(("Potassium", "LDL cholesterol", "Creatinine")), "test_value": str(round(rng.uniform(3.2, 180.0), 1)), "test_unit": "synthetic-unit", "reference_range": "See synthetic reference", "interpretation": rng.choice(("Within reference range", "High", "Low")), "test_date": lab_date, "record_status": "Final"},
        {**common, "SK": "VITAL#2026-08-13T09:30:00Z#V001", "GSI1PK": f"{pk}#VITAL", "GSI1SK": "2026-08-13T09:30:00Z#V001", "entity_type": "VITAL_SIGN", "record_id": "V001", "systolic_bp": rng.randint(110, 170), "diastolic_bp": rng.randint(65, 105), "heart_rate": rng.randint(55, 100), "oxygen_saturation": rng.randint(94, 100), "measured_at": "2026-08-13T09:30:00Z", "record_status": "Final"},
        {**common, "SK": "CARDIOLOGY_TEST#2026-07-20T14:00:00Z#T001", "GSI1PK": f"{pk}#CARDIOLOGY_TEST", "GSI1SK": "2026-07-20T14:00:00Z#T001", "entity_type": "CARDIOLOGY_TEST", "record_id": "T001", "test_or_procedure_name": "Echocardiogram", "performed_date": "2026-07-20T14:00:00Z", "result_summary": "Synthetic recorded result", "record_status": "Final"},
    ]
