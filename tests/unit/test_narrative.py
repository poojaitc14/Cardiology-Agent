from cardiologist_agent.ui.narrative import format_secretary_letter


def test_secretary_letter_excludes_patient_snapshot_fields() -> None:
    data = {
        "review_status": "DRAFT_FOR_CLINICIAN_REVIEW",
        "evidence_grade": "MODERATE",
        "recommendation_action": "NO_CHANGE",
        "clinical_rationale": "Review completed without urgent concerns.",
        "authorization": {"authorization_status": "UNAVAILABLE", "message": "No signed orders on file."},
        "patient_snapshot": {
            "patient_id": "P1001",
            "name": "Darius Evans",
            "date_of_birth": "1979-01-11",
            "gender": "Male",
        },
        "medication_instructions": [
            {"medication_name": "Atorvastatin", "dose": "40", "dose_unit": "mg", "authorized": False}
        ],
        "required_tests": [],
        "future_appointments": [],
        "safest_next_action": "Review draft with clinician.",
        "limitations": ["Fictional training application."],
    }
    letter = format_secretary_letter(data, clinician_id="DR101")
    assert "Darius" not in letter
    assert "1979-01-11" not in letter
    assert "DR101" in letter
    assert "No additional blood tests" in letter
    assert "No follow-up appointments" in letter
    assert "Atorvastatin" not in letter


def test_secretary_letter_includes_urgency_and_tests() -> None:
    data = {
        "review_status": "URGENT_CLINICAL_REVIEW",
        "evidence_grade": "LOW",
        "recommendation_action": "NO_RECOMMENDATION",
        "clinical_rationale": "Recent abnormal result flagged.",
        "authorization": {"authorization_status": "UNAVAILABLE", "message": "No signed orders."},
        "warnings_and_red_flags": ["Potassium elevated with ACE inhibitor active."],
        "required_tests": [
            {
                "test": "Potassium",
                "purpose": "Repeat monitoring",
                "target_date_or_window": "Within 48 hours",
                "booking_owner": "Cardiology clinic",
            }
        ],
        "future_appointments": [],
        "safest_next_action": "Contact duty cardiologist today.",
        "limitations": [],
    }
    letter = format_secretary_letter(data, clinician_id="DR102")
    assert "Urgent clinical review" in letter
    assert "Potassium" in letter
    assert "No follow-up appointments" in letter
