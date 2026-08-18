from cardiologist_agent.ui.narrative import format_secretary_letter


def test_secretary_letter_excludes_patient_snapshot_fields() -> None:
    data = {
        "review_status": "DRAFT_FOR_CLINICIAN_REVIEW",
        "evidence_grade": "MODERATE",
        "recommendation_action": "NO_CHANGE",
        "clinical_rationale": "Overall this looks stable.",
        "authorization": {"authorization_status": "UNAVAILABLE", "message": "No signed orders on file."},
        "patient_snapshot": {
            "patient_id": "P1001",
            "name": "Training Record 001",
            "date_of_birth": "1979-01-11",
            "gender": "Male",
            "record_status": "Active",
            "allergy_summary": "None documented",
            "recent_medicines_summary": "The record shows 1 active heart medicine on file.",
            "recent_labs_summary": "Recent blood tests on file (Potassium, Creatinine) date from 03 August 2026.",
            "recent_care_summary": "The most recent heart test on file is 12-lead ecg, from 03 August 2026.",
        },
        "medication_instructions": [
            {"medication_name": "Atorvastatin", "dose": "40", "dose_unit": "mg", "authorized": False}
        ],
        "required_tests": [],
        "future_appointments": [],
        "future_course_of_action": [
            "Continue the current heart medicines until Dr Amelia Hartley reviews them.",
        ],
        "safest_next_action": "Review draft with doctor.",
        "limitations": ["Fictional training application."],
    }
    letter = format_secretary_letter(data, clinician_id="Reception")
    assert "Darius" not in letter
    assert "1979-01-11" not in letter
    assert "Atorvastatin" not in letter
    assert "active heart medicine on file" in letter
    assert "Recent blood tests on file" in letter
    assert "most recent heart test on file" in letter
    assert "Dr Amelia Hartley" in letter
    assert "• Continue the current heart medicines" in letter


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
                "purpose": "We need up-to-date blood results",
                "target_date_or_window": "Within 48 hours",
                "booking_owner": "Sister Margaret Walsh",
            }
        ],
        "future_appointments": [],
        "future_course_of_action": [
            "Phone Dr Fatima Al-Rashid today about the potassium result.",
        ],
        "safest_next_action": "Contact duty doctor today.",
        "limitations": [],
    }
    letter = format_secretary_letter(data, clinician_id="Ward")
    assert "attention today" in letter
    assert "Dr Fatima Al-Rashid" in letter
    assert "No new appointments need scheduling" in letter
