from __future__ import annotations

from database.synthetic_data import generate_patients


def test_default_generator_creates_100_isolated_synthetic_patients():
    records = generate_patients()
    patient_ids = {record["patient_id"] for record in records}
    assert len(patient_ids) == 100
    assert patient_ids == {f"P{number}" for number in range(1001, 1101)}
    assert all(record["source"] == "Synthetic training dataset" for record in records)


def test_each_patient_has_expected_record_types():
    records = [record for record in generate_patients() if record["patient_id"] == "P1001"]
    assert {record["entity_type"] for record in records} == {
        "PATIENT_PROFILE", "CONDITION", "MEDICATION", "ALLERGY", "LAB_RESULT", "VITAL_SIGN", "CARDIOLOGY_TEST"
    }
