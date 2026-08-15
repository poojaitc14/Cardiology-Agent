"""Unit tests for the FastAPI backend."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas import Citation, QueryResponse


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_check_returns_200(self, client):
        """Test that health check returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_health_check_response_format(self, client):
        """Test health check response has required fields."""
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert "version" in data


class TestQueryRequestValidation:
    """Tests for query request validation."""

    def test_query_requires_patient_id(self, client):
        """Test that patient_id is required."""
        response = client.post("/query", json={"question": "What is the patient's status?"})
        assert response.status_code == 422

    def test_query_requires_question(self, client):
        """Test that question is required."""
        response = client.post("/query", json={"patient_id": "P1005"})
        assert response.status_code == 422

    def test_query_rejects_empty_patient_id(self, client):
        """Test that empty patient_id is rejected."""
        response = client.post(
            "/query", json={"patient_id": "", "question": "What is the status?"}
        )
        assert response.status_code == 422

    def test_query_rejects_empty_question(self, client):
        """Test that empty question is rejected."""
        response = client.post(
            "/query", json={"patient_id": "P1005", "question": ""}
        )
        assert response.status_code == 422

    def test_query_accepts_valid_input(self, client):
        """Test that valid input passes validation."""
        with patch("backend.main.agent") as mock_agent:
            mock_response = MagicMock()
            mock_response.content = "Test response"
            mock_response.citations = ()
            mock_response.tools_used = ()
            mock_response.errors = ()
            mock_agent.review.return_value = mock_response

            response = client.post(
                "/query",
                json={"patient_id": "P1005", "question": "Review patient status"},
            )
            assert response.status_code == 200

    def test_query_trims_whitespace(self, client):
        """Test that whitespace is trimmed from inputs."""
        with patch("backend.main.agent") as mock_agent:
            mock_response = MagicMock()
            mock_response.content = "Test response"
            mock_response.citations = ()
            mock_response.tools_used = ()
            mock_response.errors = ()
            mock_agent.review.return_value = mock_response

            response = client.post(
                "/query",
                json={"patient_id": "  P1005  ", "question": "  Review status  "},
            )
            assert response.status_code == 200


class TestQueryResponse:
    """Tests for query response format."""

    def test_query_response_format(self, client):
        """Test that query response has required fields."""
        with patch("backend.main.agent") as mock_agent:
            mock_response = MagicMock()
            mock_response.content = "Clinical decision support"
            mock_response.citations = (MagicMock(source="OpenFDA", detail="Warfarin"),)
            mock_response.tools_used = ("openfda_drug_tool",)
            mock_response.errors = ()
            mock_agent.review.return_value = mock_response

            response = client.post(
                "/query",
                json={"patient_id": "P1005", "question": "Drug information"},
            )
            data = response.json()
            assert "answer" in data
            assert "sources" in data
            assert "tools_used" in data
            assert "errors" in data
            assert "trace_id" in data
            assert len(data["trace_id"]) > 0

    def test_query_response_with_sources(self, client):
        """Test that citations are converted to sources."""
        with patch("backend.main.agent") as mock_agent:
            mock_citation = MagicMock()
            mock_citation.source = "OpenFDA"
            mock_citation.detail = "Warfarin label"
            mock_response = MagicMock()
            mock_response.content = "Drug info"
            mock_response.citations = (mock_citation,)
            mock_response.tools_used = ()
            mock_response.errors = ()
            mock_agent.review.return_value = mock_response

            response = client.post(
                "/query",
                json={"patient_id": "P1005", "question": "Drug info"},
            )
            data = response.json()
            assert len(data["sources"]) == 1
            assert data["sources"][0]["source"] == "OpenFDA"
            assert data["sources"][0]["detail"] == "Warfarin label"

    def test_query_response_with_errors(self, client):
        """Test that errors are included in response."""
        with patch("backend.main.agent") as mock_agent:
            mock_response = MagicMock()
            mock_response.content = "Partial response"
            mock_response.citations = ()
            mock_response.tools_used = ()
            mock_response.errors = ("Service timeout",)
            mock_agent.review.return_value = mock_response

            response = client.post(
                "/query",
                json={"patient_id": "P1005", "question": "Query"},
            )
            data = response.json()
            assert len(data["errors"]) == 1
            assert "timeout" in data["errors"][0].lower()


class TestPatientEndpoint:
    """Tests for the /patient/{patient_id} endpoint."""

    def test_patient_endpoint_requires_patient_id(self, client):
        """Test that patient_id is required."""
        response = client.get("/patient/")
        assert response.status_code == 404

    def test_patient_endpoint_rejects_empty_patient_id(self, client):
        """Test that empty patient_id is rejected."""
        response = client.get("/patient/")
        assert response.status_code == 404

    def test_patient_endpoint_returns_404_when_not_found(self, client):
        """Test that 404 is returned when patient not found."""
        with patch("backend.main.patient_repository") as mock_repo:
            mock_result = MagicMock()
            mock_result.found = False
            mock_result.records = []
            mock_repo.get_records.return_value = mock_result

            response = client.get("/patient/P9999")
            assert response.status_code == 404

    def test_patient_endpoint_returns_patient_data(self, client):
        """Test that patient data is returned."""
        with patch("backend.main.patient_repository") as mock_repo:
            mock_result = MagicMock()
            mock_result.found = True
            mock_result.records = [{"patient_id": "P1005", "first_name": "John"}]
            mock_result.source = "DynamoDB"
            mock_repo.get_records.return_value = mock_result

            response = client.get("/patient/P1005")
            assert response.status_code == 200
            data = response.json()
            assert data["patient_id"] == "P1005"
            assert data["source"] == "DynamoDB"
            assert "data" in data

    def test_patient_endpoint_response_format(self, client):
        """Test patient response has required fields."""
        with patch("backend.main.patient_repository") as mock_repo:
            mock_result = MagicMock()
            mock_result.found = True
            mock_result.records = [{"patient_id": "P1005"}]
            mock_result.source = "DynamoDB"
            mock_repo.get_records.return_value = mock_result

            response = client.get("/patient/P1005")
            data = response.json()
            assert "patient_id" in data
            assert "data" in data
            assert "source" in data


class TestErrorHandling:
    """Tests for error handling."""

    def test_query_returns_500_on_agent_error(self, client):
        """Test that 500 is returned on agent error."""
        with patch("backend.main.agent") as mock_agent:
            mock_agent.review.side_effect = RuntimeError("Agent failed")

            response = client.post(
                "/query",
                json={"patient_id": "P1005", "question": "Test query"},
            )
            assert response.status_code == 500

    def test_patient_returns_500_on_repository_error(self, client):
        """Test that 500 is returned on repository error."""
        with patch("backend.main.patient_repository") as mock_repo:
            mock_repo.get_records.side_effect = RuntimeError("DB error")

            response = client.get("/patient/P1005")
            assert response.status_code == 500

    def test_query_returns_503_when_agent_not_initialized(self, client):
        """Test that 503 is returned when agent is not initialized."""
        with patch("backend.main.agent", None):
            response = client.post(
                "/query",
                json={"patient_id": "P1005", "question": "Test"},
            )
            assert response.status_code == 503

    def test_patient_returns_503_when_repository_not_initialized(self, client):
        """Test that 503 is returned when repository is not initialized."""
        with patch("backend.main.patient_repository", None):
            response = client.get("/patient/P1005")
            assert response.status_code == 503
