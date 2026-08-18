from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cardiologist_agent.api.main import app, get_query_service, get_workflow
from cardiologist_agent.config.settings import get_settings, reset_settings


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


def test_list_patients(client: TestClient) -> None:
    resp = client.get("/api/v1/patients")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 130
    assert "P1001" in body["patient_ids"]
    assert body["suggested_next_id"].startswith("P")


def test_create_patient_and_review(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/patients",
        json={
            "patient_id": "P99001",
            "condition_name": "Mild hypertension",
            "on_medication": False,
            "run_review": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_id"] == "P99001"
    assert body["created"] is True
    assert body["review"] is not None
    assert body["review"]["patient_id"] == "P99001"
    assert body["review"]["review_status"] == "DRAFT_FOR_CLINICIAN_REVIEW"

    list_resp = client.get("/api/v1/patients")
    assert "P99001" in list_resp.json()["patient_ids"]

    settings = get_settings()
    saved = json.loads(settings.custom_patients_file.read_text(encoding="utf-8"))
    assert any(item["patient_id"] == "P99001" for item in saved)


def test_create_duplicate_patient(client: TestClient) -> None:
    payload = {
        "patient_id": "P99002",
        "condition_name": "Benign palpitations",
        "on_medication": False,
        "run_review": False,
    }
    first = client.post("/api/v1/patients", json=payload)
    assert first.status_code == 200
    second = client.post("/api/v1/patients", json=payload)
    assert second.status_code == 409
