from app import tools


def test_dynamodb_context_maps_supported_timeline_records(monkeypatch) -> None:
    monkeypatch.setattr(
        tools,
        "get_patient_timeline",
        lambda _patient_id: [
            {
                "record_id": "condition-1",
                "record_type": "CONDITION",
                "updated_at": "2026-08-01T09:00:00Z",
                "condition_name": "Hypertension",
                "condition_status": "Active",
            },
            {
                "record_id": "medication-1",
                "record_type": "MEDICATION",
                "updated_at": "2026-08-02T09:00:00Z",
                "medication_name": "Example medicine",
                "medication_status": "Active",
            },
            {
                "record_id": "allergy-1",
                "record_type": "ALLERGY",
                "updated_at": "2026-08-03T09:00:00Z",
                "allergy_name": "Example allergen",
            },
            {
                "record_id": "lab-1",
                "record_type": "LAB",
                "updated_at": "2026-08-04T09:00:00Z",
                "test_name": "Example test",
                "test_value": "1.0",
            },
        ],
    )

    context = tools._dynamodb_context("P1005")

    assert len(context["history"]) == 1
    assert len(context["medications"]) == 1
    assert context["medications"][0]["medication_name"] == "Example medicine"
    assert len(context["allergies"]) == 1
    assert len(context["labs"]) == 1


def test_dynamodb_context_does_not_treat_profile_as_clinical_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        tools,
        "get_patient_timeline",
        lambda _patient_id: [
            {
                "record_id": "PROFILE#P1005",
                "record_type": "PROFILE",
                "updated_at": "2026-08-01T09:00:00Z",
            }
        ],
    )

    context = tools._dynamodb_context("P1005")

    assert context["history"] == []
    assert context["medications"] == []
    assert context["allergies"] == []
    assert context["labs"] == []
