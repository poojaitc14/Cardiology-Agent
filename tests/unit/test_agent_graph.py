from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.agent.graph import LangGraphCardiologistAgent
from backend.models.patient import PatientDataResult, PatientRecordScope
from backend.services.openfda import DrugLabel, OpenFDAResult
from rag.models import DocumentMetadata, RetrievalResponse, RetrievalResult


class FakeChatModel:
    def __init__(
        self,
        response_text: str | None = None,
        raises: Exception | None = None,
        deployment_name: str = "gpt-4.1-mini",
        usage_metadata: dict | None = None,
        resolved_model: str | None = None,
    ):
        self.response_text = response_text or "Synthesized clinical answer."
        self.raises = raises
        self.calls: list[list] = []
        self.deployment_name = deployment_name
        self.usage_metadata = usage_metadata
        self.resolved_model = resolved_model

    def invoke(self, messages):
        self.calls.append(messages)
        if self.raises:
            raise self.raises
        return SimpleNamespace(
            content=self.response_text,
            usage_metadata=self.usage_metadata,
            response_metadata={"model_name": self.resolved_model} if self.resolved_model else {},
        )


def agent(calls, chat_model=None):
    def patient(patient_id, scope):
        calls.append(("patient", patient_id))
        return PatientDataResult(patient_id, scope, [{"patient_id": patient_id, "entity_type": "PATIENT_PROFILE", "first_name": "Jordan", "last_name": "Reed"}], f"DynamoDB / Patient {patient_id}", True)

    def drug(name):
        calls.append(("drug", name))
        return OpenFDAResult(name, True, True, DrugLabel((name,), (), (), (), (), (), (), (), ()), "OpenFDA", "ok")

    def rag(query, limit):
        calls.append(("rag", query))
        metadata = DocumentMetadata("Anticoagulation / Antiplatelet Therapy Protocol", "1.0", "Scope", "2026", "Synthetic")
        return RetrievalResponse(query, True, (RetrievalResult(metadata.document_name, "Scope", "content", metadata, 0.9),))

    return LangGraphCardiologistAgent(patient, drug, rag, chat_model=chat_model)


def test_routes_patient_medication_question_to_database():
    calls = []
    response = agent(calls).review("What medications does P1005 take?")
    assert calls == [("patient", "P1005")]
    assert response.tools_used == ("patient_database_tool",)


def test_routes_drug_to_openfda():
    calls = []
    response = agent(calls).review("What is Warfarin?")
    assert calls == [("drug", "Warfarin")]
    assert response.citations[0].source == "OpenFDA"


def test_routes_combined_question_to_all_three_tools():
    calls = []
    response = agent(calls).review("Review P1005's Warfarin therapy against our hospital policy.")
    assert [call[0] for call in calls] == ["patient", "drug", "rag"]
    assert len(response.citations) == 3
    assert response.tools_used == ("patient_database_tool", "openfda_drug_tool", "cardiology_rag_tool")


def test_explicit_patient_id_is_used_even_when_absent_from_the_question():
    calls = []
    response = agent(calls).review("What medications is this patient taking?", patient_id="P1005")
    assert calls == [("patient", "P1005")]
    assert response.tools_used == ("patient_database_tool",)


def test_explicit_patient_id_takes_priority_over_one_mentioned_in_the_question():
    calls = []
    agent(calls).review("Compare P1005 against P1099's history.", patient_id="P1099")
    assert calls == [("patient", "P1099")]


def test_no_tools_matched_returns_prompt_message():
    response = agent([]).review("Hello there")
    assert "Please provide a patient ID" in response.content
    assert response.tools_used == ()


def test_llm_synthesis_used_when_chat_model_configured():
    chat_model = FakeChatModel(response_text="Grounded answer about the patient.")
    response = agent([], chat_model=chat_model).review("What medications does P1005 take?")
    assert "Grounded answer about the patient." in response.content
    assert len(chat_model.calls) == 1
    messages = chat_model.calls[0]
    assert messages[0].content.startswith("You are the Cardiology Clinical Decision Support Agent")
    assert "CLINICAL QUESTION" in messages[1].content


def test_llm_failure_falls_back_to_retrieved_facts():
    chat_model = FakeChatModel(raises=RuntimeError("upstream unavailable"))
    response = agent([], chat_model=chat_model).review("What medications does P1005 take?")
    assert "Patient record evidence" in response.content
    assert any("temporarily unavailable" in error for error in response.errors)


def test_no_chat_model_falls_back_to_retrieved_facts():
    response = agent([], chat_model=None).review("What medications does P1005 take?")
    assert "Patient record evidence" in response.content


def test_guardrail_blocks_unsafe_answer_and_falls_back_to_facts():
    chat_model = FakeChatModel(response_text="You should start the patient on 10mg lisinopril daily.")
    response = agent([], chat_model=chat_model).review("What medications does P1005 take?")
    assert "10mg lisinopril daily" not in response.content
    assert "Patient record evidence" in response.content
    assert any("guardrail" in error.lower() for error in response.errors)
    assert any("guardrail check failed" in step.lower() for step in response.steps)


def test_guardrail_passes_grounded_llm_answer_through():
    chat_model = FakeChatModel(response_text="The patient's profile lists Jordan Reed.")
    response = agent([], chat_model=chat_model).review("What is this patient's name?", patient_id="P1005")
    assert "Jordan Reed" in response.content
    assert not response.errors


def test_steps_trace_is_populated_in_order():
    response = agent([]).review("Review P1005's Warfarin therapy against our hospital policy.")
    assert response.steps[0].startswith("Parsed the question")
    assert any("Patient ID P1005 identified" in step for step in response.steps)
    assert any("Drug name 'Warfarin' detected" in step for step in response.steps)
    assert any("Guideline/policy keywords detected" in step for step in response.steps)


def test_empty_question_short_circuits():
    response = agent([]).review("   ")
    assert response.content == "A question is required for clinical decision support."
    assert response.tools_used == ()


class TestToolStatus:
    def test_ok_status_when_all_tools_succeed(self):
        response = agent([]).review("Review P1005's Warfarin therapy against our hospital policy.")
        by_tool = {ts.tool: ts for ts in response.tool_status}
        assert by_tool["patient_database_tool"].status == "ok"
        assert by_tool["openfda_drug_tool"].status == "ok"
        assert by_tool["cardiology_rag_tool"].status == "ok"

    def test_no_data_status_when_patient_not_found(self):
        def patient(patient_id, scope):
            return PatientDataResult(patient_id, scope, [], f"DynamoDB / Patient {patient_id}", False)

        agent_obj = LangGraphCardiologistAgent(
            patient, lambda name: OpenFDAResult(name, False, True, None, None, "not found"), lambda q, k: RetrievalResponse(q, True, ())
        )
        response = agent_obj.review("What medications does P9999 take?")
        status = next(ts for ts in response.tool_status if ts.tool == "patient_database_tool")
        assert status.status == "no_data"

    def test_error_status_when_patient_tool_raises(self):
        def patient(patient_id, scope):
            raise RuntimeError("DynamoDB unavailable")

        agent_obj = LangGraphCardiologistAgent(
            patient, lambda name: OpenFDAResult(name, False, True, None, None, "not found"), lambda q, k: RetrievalResponse(q, True, ())
        )
        response = agent_obj.review("What medications does P1005 take?")
        status = next(ts for ts in response.tool_status if ts.tool == "patient_database_tool")
        assert status.status == "error"

    def test_error_status_when_openfda_unavailable(self):
        def drug(name):
            return OpenFDAResult(name, False, False, None, None, "Drug-label information is temporarily unavailable from OpenFDA.")

        agent_obj = LangGraphCardiologistAgent(
            lambda pid, scope: PatientDataResult(pid, scope, [], f"DynamoDB / Patient {pid}", False),
            drug,
            lambda q, k: RetrievalResponse(q, True, ()),
        )
        response = agent_obj.review("What is Warfarin used for?")
        status = next(ts for ts in response.tool_status if ts.tool == "openfda_drug_tool")
        assert status.status == "error"
        assert "temporarily unavailable" in status.detail

    def test_no_data_status_when_openfda_finds_nothing(self):
        def drug(name):
            return OpenFDAResult(name, False, True, None, None, "No matching drug-label information was found in OpenFDA.")

        agent_obj = LangGraphCardiologistAgent(
            lambda pid, scope: PatientDataResult(pid, scope, [], f"DynamoDB / Patient {pid}", False),
            drug,
            lambda q, k: RetrievalResponse(q, True, ()),
        )
        response = agent_obj.review("What is Warfarin used for?")
        status = next(ts for ts in response.tool_status if ts.tool == "openfda_drug_tool")
        assert status.status == "no_data"

    def test_error_status_when_rag_unavailable(self):
        def rag(query, limit):
            return RetrievalResponse(query, False, (), "Clinical document retrieval is temporarily unavailable.")

        agent_obj = LangGraphCardiologistAgent(
            lambda pid, scope: PatientDataResult(pid, scope, [], f"DynamoDB / Patient {pid}", False),
            lambda name: OpenFDAResult(name, False, True, None, None, "not found"),
            rag,
        )
        response = agent_obj.review("What is our hospital policy on anticoagulation?")
        status = next(ts for ts in response.tool_status if ts.tool == "cardiology_rag_tool")
        assert status.status == "error"

    def test_no_tool_status_for_tools_never_invoked(self):
        response = agent([]).review("What medications does P1005 take?")
        tools_with_status = {ts.tool for ts in response.tool_status}
        assert tools_with_status == {"patient_database_tool"}


class TestLangfuseGenerationTracing:
    """Regression coverage for the gap where no LLM generation, cost, or
    token usage ever reached Langfuse: the active LangGraph agent's
    synthesize step now sends model/input/output/usage to a real
    'generation'-type observation."""

    def test_generation_span_receives_model_input_output_and_usage(self):
        fake_generation = MagicMock()
        fake_client = MagicMock()
        fake_client.generation.return_value = fake_generation

        chat_model = FakeChatModel(
            response_text="The patient's profile lists Jordan Reed.",
            usage_metadata={"input_tokens": 19, "output_tokens": 2, "total_tokens": 21},
            resolved_model="gpt-4.1-mini-2025-04-14",
        )

        with patch("backend.observability.tracing.get_langfuse_client", return_value=fake_client):
            agent([], chat_model=chat_model).review("What medications does P1005 take?")

        # created with the deployment name known before the call
        _, create_kwargs = fake_client.generation.call_args
        assert create_kwargs["model"] == "gpt-4.1-mini"
        assert create_kwargs["input"][1]["content"]  # the human message content was captured

        # ended with the real output, the resolved (dated) model, and token usage
        _, end_kwargs = fake_generation.end.call_args
        assert end_kwargs["output"] == "The patient's profile lists Jordan Reed."
        assert end_kwargs["model"] == "gpt-4.1-mini-2025-04-14"
        assert end_kwargs["usage"] == {"input": 19, "output": 2, "total": 21, "unit": "TOKENS"}

    def test_no_usage_sent_when_chat_model_does_not_report_it(self):
        """A fake/older chat model with no usage_metadata attribute at all
        must not crash synthesis -- usage is simply omitted."""
        fake_generation = MagicMock()
        fake_client = MagicMock()
        fake_client.generation.return_value = fake_generation
        chat_model = FakeChatModel(response_text="An answer.")

        with patch("backend.observability.tracing.get_langfuse_client", return_value=fake_client):
            response = agent([], chat_model=chat_model).review("What medications does P1005 take?")

        assert "An answer." in response.content
        _, end_kwargs = fake_generation.end.call_args
        assert "usage" not in end_kwargs
