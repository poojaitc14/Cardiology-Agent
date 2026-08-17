import pytest
from fastapi.testclient import TestClient

from cardiologist_agent.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ready(client: TestClient) -> None:
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["patients_file"] is True


def test_review_routine_patient(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/reviews",
        json={
            "patient_id": "P1001",
            "clinician_id": "DR101",
            "clinical_question": "Review medications and labs.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_status"] == "DRAFT_FOR_CLINICIAN_REVIEW"
    assert data["review_status"] != "FINAL_AUTHORIZED"


def test_review_inactive_patient(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/reviews",
        json={
            "patient_id": "P1100",
            "clinician_id": "DR101",
            "clinical_question": "Review patient.",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "SYSTEM_UNAVAILABLE"
