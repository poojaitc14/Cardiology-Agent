from cardiologist_agent.services.question_router import (
    classify_question,
    is_default_summary_question,
)


def test_default_question_routes_to_full_review() -> None:
    question = (
        "Please check the heart record, medicines, recent test results, "
        "and tell me clearly what should happen next."
    )
    assert is_default_summary_question(question)
    assert classify_question(question) == "full_review"


def test_patient_test_question_routes_to_patient_db() -> None:
    assert (
        classify_question("When did P1001 last have a heart test, if at all?", has_patient_context=True)
        == "patient_db"
    )


def test_medical_question_routes_to_medical_api() -> None:
    assert classify_question("What are the side effects of warfarin?") == "medical_api"


def test_hospital_question_routes_to_hospital_rag() -> None:
    assert classify_question("Who handles heart failure cases at the hospital?") == "hospital_rag"
