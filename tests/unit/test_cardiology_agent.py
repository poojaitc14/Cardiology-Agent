from __future__ import annotations

from backend.agent.cardiology_agent import CardiologistAgent, TOOL_SCHEMAS
from backend.models.patient import PatientDataResult, PatientRecordScope
from backend.services.openfda import DrugLabel, OpenFDAResult
from rag.models import DocumentMetadata, RetrievalResponse, RetrievalResult


def agent(calls):
    def patient(patient_id, scope):
        calls.append(("patient", patient_id)); return PatientDataResult(patient_id, scope, [{"patient_id": patient_id}], f"DynamoDB / Patient {patient_id}", True)
    def drug(name):
        calls.append(("drug", name)); return OpenFDAResult(name, True, True, DrugLabel((name,), (), (), (), (), (), (), (), ()), "OpenFDA", "ok")
    def rag(query, limit):
        calls.append(("rag", query)); metadata = DocumentMetadata("Anticoagulation / Antiplatelet Therapy Protocol", "1.0", "Scope", "2026", "Synthetic")
        return RetrievalResponse(query, True, (RetrievalResult(metadata.document_name, "Scope", "content", metadata, 0.9),))
    return CardiologistAgent(patient, drug, rag)


def test_tool_schemas_are_exactly_the_three_approved_tools():
    assert {tool["name"] for tool in TOOL_SCHEMAS} == {"patient_database_tool", "openfda_drug_tool", "cardiology_rag_tool"}


def test_routes_patient_medication_question_to_database():
    calls = []; response = agent(calls).review("What medications does P1005 take?")
    assert calls == [("patient", "P1005")] and response.tools_used == ("patient_database_tool",)


def test_routes_warfarin_to_openfda():
    calls = []; response = agent(calls).review("What is Warfarin?")
    assert calls == [("drug", "Warfarin")] and response.citations[0].source == "OpenFDA"


def test_routes_combined_question_to_all_three_tools():
    calls = []; response = agent(calls).review("Review P1005's Warfarin therapy against our hospital policy.")
    assert [call[0] for call in calls] == ["patient", "drug", "rag"]
    assert len(response.citations) == 3


def test_explicit_patient_id_is_used_even_when_absent_from_the_question():
    calls = []; response = agent(calls).review("What medications is this patient taking?", patient_id="P1005")
    assert calls == [("patient", "P1005")] and response.tools_used == ("patient_database_tool",)


def test_explicit_patient_id_takes_priority_over_one_mentioned_in_the_question():
    calls = []; response = agent(calls).review("Compare P1005 against P1099's history.", patient_id="P1099")
    assert calls == [("patient", "P1099")]


def test_llm_tool_generates_the_final_answer_when_configured():
    calls = []
    def llm(patient_info, question, retrieved_docs):
        calls.append((patient_info, question, retrieved_docs)); return "Synthesized clinical answer."
    a = CardiologistAgent(
        lambda pid, scope: PatientDataResult(pid, scope, [{"patient_id": pid}], f"DynamoDB / Patient {pid}", True),
        lambda name: OpenFDAResult(name, True, True, DrugLabel((name,), (), (), (), (), (), (), (), ()), "OpenFDA", "ok"),
        lambda query, limit: RetrievalResponse(query, True, ()),
        llm_tool=llm,
    )
    response = a.review("What medications does P1005 take?")
    assert "Synthesized clinical answer." in response.content
    assert len(calls) == 1 and calls[0][1] == "What medications does P1005 take?"


def test_llm_tool_failure_falls_back_to_retrieved_facts():
    def failing_llm(patient_info, question, retrieved_docs):
        raise RuntimeError("upstream unavailable")
    a = CardiologistAgent(
        lambda pid, scope: PatientDataResult(pid, scope, [{"patient_id": pid}], f"DynamoDB / Patient {pid}", True),
        lambda name: OpenFDAResult(name, True, True, DrugLabel((name,), (), (), (), (), (), (), (), ()), "OpenFDA", "ok"),
        lambda query, limit: RetrievalResponse(query, True, ()),
        llm_tool=failing_llm,
    )
    response = a.review("What medications does P1005 take?")
    assert "Patient record evidence" in response.content
    assert any("generation is temporarily unavailable" in error for error in response.errors)


def test_summarize_records_surfaces_real_medication_fields():
    summary = CardiologistAgent._summarize_records([
        {"entity_type": "MEDICATION", "drug_name": "Lisinopril", "dose": "10", "dose_unit": "mg",
         "frequency": "Once daily", "medication_status": "Active"},
    ])
    assert "Lisinopril" in summary and "10mg" in summary


def test_summarize_records_covers_every_entity_type():
    records = [
        {"entity_type": "PATIENT_PROFILE", "gender": "Female", "date_of_birth": "1970-01-14", "smoking_status": "Never smoker"},
        {"entity_type": "ALLERGY", "allergen": "Penicillin", "reaction": "Skin rash", "severity": "Moderate"},
        {"entity_type": "LAB_RESULT", "test_name": "Potassium", "test_value": "5.2", "interpretation": "High"},
        {"entity_type": "VITAL_SIGN", "systolic_bp": 142, "diastolic_bp": 91, "heart_rate": 78, "oxygen_saturation": 97},
        {"entity_type": "CARDIOLOGY_TEST", "test_or_procedure_name": "Echocardiogram", "result_summary": "Normal"},
        {"entity_type": "CONDITION", "condition_name": "Hypertension", "severity": "Moderate"},
    ]
    summary = CardiologistAgent._summarize_records(records)
    for expected in ["Female", "1970-01-14", "Penicillin", "Potassium", "5.2", "142", "Echocardiogram", "Hypertension"]:
        assert expected in summary


def test_summarize_records_profile_includes_patient_name():
    summary = CardiologistAgent._summarize_records([
        {"entity_type": "PATIENT_PROFILE", "first_name": "Morgan", "last_name": "Patel", "gender": "Non-binary"},
    ])
    assert "Morgan Patel" in summary


def test_summarize_records_empty_list():
    assert CardiologistAgent._summarize_records([]) == "no records"


def test_summarize_records_unknown_entity_type_does_not_crash():
    summary = CardiologistAgent._summarize_records([{"entity_type": "SOMETHING_NEW"}])
    assert "SOMETHING_NEW" in summary


def test_patient_fact_conveys_real_field_values_to_llm_not_just_a_count():
    """Regression test for the grounding bug: facts must carry real record content."""
    calls = []
    def llm(patient_info, question, retrieved_docs):
        calls.append((patient_info, retrieved_docs)); return "ok"
    a = CardiologistAgent(
        lambda pid, scope: PatientDataResult(
            pid, scope,
            [{"entity_type": "MEDICATION", "drug_name": "Lisinopril", "dose": "10", "dose_unit": "mg", "medication_status": "Active"}],
            f"DynamoDB / Patient {pid}", True,
        ),
        lambda name: OpenFDAResult(name, True, True, DrugLabel((name,), (), (), (), (), (), (), (), ()), "OpenFDA", "ok"),
        lambda query, limit: RetrievalResponse(query, True, ()),
        llm_tool=llm,
    )
    a.review("What medications does P1003 take?")
    patient_info, retrieved_docs = calls[0]
    assert "Lisinopril" in patient_info
    assert any("Lisinopril" in fact for fact in retrieved_docs)


def test_no_llm_call_when_no_tools_matched():
    calls = []
    def llm(patient_info, question, retrieved_docs):
        calls.append(1); return "should not be called"
    a = CardiologistAgent(
        lambda pid, scope: PatientDataResult(pid, scope, [], f"DynamoDB / Patient {pid}", True),
        lambda name: OpenFDAResult(name, True, True, DrugLabel((name,), (), (), (), (), (), (), (), ()), "OpenFDA", "ok"),
        lambda query, limit: RetrievalResponse(query, True, ()),
        llm_tool=llm,
    )
    response = a.review("Hello there")
    assert not calls
    assert "Please provide a patient ID" in response.content
