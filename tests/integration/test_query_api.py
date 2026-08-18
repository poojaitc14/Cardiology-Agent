from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cardiologist_agent.api.main import app, get_query_service, get_workflow
from cardiologist_agent.config.settings import reset_settings


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    custom_file = tmp_path / "custom_patients.json"
    custom_file.write_text("[]\n", encoding="utf-8")
    monkeypatch.setenv("CUSTOM_PATIENTS_JSON_PATH", str(custom_file))
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("OPENFDA_PROVIDER", "fake")
    reset_settings()
    get_workflow.cache_clear()
    get_query_service.cache_clear()
    yield TestClient(app)
    get_query_service.cache_clear()
    get_workflow.cache_clear()
    reset_settings()


def test_query_patient_db(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/queries",
        json={
            "clinical_question": "When did P1001 last have a heart test?",
            "mode": "auto",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["query_mode"] == "patient_db"
    assert body["answer"]
    assert body["review"] is None


def test_query_medical_api(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/queries",
        json={
            "clinical_question": "What are the side effects of warfarin?",
            "mode": "auto",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["query_mode"] == "medical_api"
    assert "warfarin" in body["answer"].lower()


def test_query_hospital_rag(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/queries",
        json={
            "clinical_question": "Who handles heart failure cases?",
            "mode": "auto",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["query_mode"] == "hospital_rag"
    assert "Dr Raj Patel" in body["answer"] or "heart failure" in body["answer"].lower()


def test_query_full_review(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/queries",
        json={
            "clinical_question": (
                "For P1001, please check the heart record, medicines, recent test results, "
                "and tell me clearly what should happen next."
            ),
            "mode": "auto",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["query_mode"] == "full_review"
    assert body["review"] is not None
    assert body["review"]["patient_id"] == "P1001"
