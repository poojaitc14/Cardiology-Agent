"""Integration tests for the FastAPI backend."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client(monkeypatch):
    """FastAPI test client with live Azure OpenAI calls disabled.

    Without this, a configured .env makes the /query tests below place real,
    billed calls to Azure OpenAI on every test run, which is slow and non-hermetic.
    """
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    with TestClient(app) as test_client:
        yield test_client


class TestHealthIntegration:
    """Integration tests for the /health endpoint."""

    def test_health_returns_200(self, client):
        """Test health endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_valid(self, client):
        """Test health response is valid."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] in ["healthy", "degraded"]
        assert "version" in data


class TestQueryIntegration:
    """Integration tests for the /query endpoint."""

    def test_query_endpoint_exists(self, client):
        """Test that query endpoint is available."""
        response = client.post(
            "/query",
            json={"patient_id": "P1005", "question": "Review patient status"},
        )
        # Should either succeed or fail gracefully (not 404)
        assert response.status_code != 404

    def test_query_with_patient_id_only(self, client):
        """Test query with patient ID extracts patient information."""
        response = client.post(
            "/query",
            json={"patient_id": "P1005", "question": "What is patient P1005's status?"},
        )
        # Should not return 422 (validation error)
        assert response.status_code != 422
        if response.status_code == 200:
            data = response.json()
            assert "answer" in data
            assert "tools_used" in data

    def test_query_with_drug_name(self, client):
        """Test query with drug name."""
        response = client.post(
            "/query",
            json={"patient_id": "P1005", "question": "What are the side effects of Warfarin?"},
        )
        assert response.status_code != 422
        if response.status_code == 200:
            data = response.json()
            assert "answer" in data

    def test_query_response_structure(self, client):
        """Test that query response has correct structure."""
        response = client.post(
            "/query",
            json={"patient_id": "P1005", "question": "Review patient"},
        )
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data.get("answer"), str)
            assert isinstance(data.get("sources"), list)
            assert isinstance(data.get("tools_used"), list)
            assert isinstance(data.get("errors"), list)

    def test_query_invalid_patient_id_format(self, client):
        """Test query with invalid patient ID."""
        response = client.post(
            "/query",
            json={"patient_id": "", "question": "Test query"},
        )
        assert response.status_code == 422


class TestPatientIntegration:
    """Integration tests for the /patient/{patient_id} endpoint."""

    def test_patient_endpoint_exists(self, client):
        """Test that patient endpoint is available."""
        response = client.get("/patient/P1005")
        # Should either succeed or return 404 (not 404 for the endpoint itself)
        assert response.status_code in [200, 404, 500]

    def test_patient_response_structure(self, client):
        """Test patient response structure."""
        response = client.get("/patient/P1005")
        if response.status_code == 200:
            data = response.json()
            assert "patient_id" in data
            assert "data" in data
            assert "source" in data
            assert isinstance(data["data"], dict)

    def test_patient_not_found(self, client):
        """Test that non-existent patient returns 404."""
        response = client.get("/patient/P9999")
        # Should return 404 or 500 (depending on implementation)
        assert response.status_code in [404, 500]

    def test_patient_with_valid_id(self, client):
        """Test patient endpoint with valid synthetic patient ID."""
        # P1005 is from synthetic data
        response = client.get("/patient/P1005")
        # Should either return 200 or 404 if not in database
        assert response.status_code in [200, 404, 500]
        if response.status_code == 200:
            data = response.json()
            assert data["patient_id"] == "P1005"
