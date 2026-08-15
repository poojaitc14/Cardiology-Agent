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


class TestCreatePatientEndpoint:
    """Tests for the POST /patients endpoint."""

    VALID_PAYLOAD = {
        "first_name": "Jordan",
        "last_name": "Reed",
        "date_of_birth": "1970-01-01",
        "gender": "Non-binary",
        "smoking_status": "Never smoker",
    }

    def test_create_patient_returns_503_when_repository_not_initialized(self, client):
        with patch("backend.main.patient_repository", None):
            response = client.post("/patients", json=self.VALID_PAYLOAD)
            assert response.status_code == 503

    def test_create_patient_generates_id_when_omitted(self, client):
        with patch("backend.main.patient_repository") as mock_repo:
            mock_repo.create_patient.side_effect = lambda profile: profile["patient_id"]
            response = client.post("/patients", json=self.VALID_PAYLOAD)
            assert response.status_code == 201
            data = response.json()
            assert data["patient_id"].startswith("P")
            assert "registered" in data["message"].lower()

    def test_create_patient_uses_explicit_id(self, client):
        with patch("backend.main.patient_repository") as mock_repo:
            mock_repo.create_patient.side_effect = lambda profile: profile["patient_id"]
            response = client.post("/patients", json={**self.VALID_PAYLOAD, "patient_id": "P200481"})
            assert response.status_code == 201
            assert response.json()["patient_id"] == "P200481"

    def test_create_patient_rejects_malformed_id(self, client):
        response = client.post("/patients", json={**self.VALID_PAYLOAD, "patient_id": "not-an-id"})
        assert response.status_code == 422

    def test_create_patient_rejects_invalid_date(self, client):
        response = client.post("/patients", json={**self.VALID_PAYLOAD, "date_of_birth": "not-a-date"})
        assert response.status_code == 422

    def test_create_patient_returns_409_on_duplicate(self, client):
        from backend.services.patient_repository import PatientAlreadyExistsError

        with patch("backend.main.patient_repository") as mock_repo:
            mock_repo.create_patient.side_effect = PatientAlreadyExistsError("Patient P200481 already exists.")
            response = client.post("/patients", json={**self.VALID_PAYLOAD, "patient_id": "P200481"})
            assert response.status_code == 409


class TestRAGDocumentEndpoints:
    """Tests for the /rag/documents endpoints."""

    def test_list_documents_returns_503_when_not_initialized(self, client):
        with patch("backend.main.rag_admin_service", None):
            response = client.get("/rag/documents")
            assert response.status_code == 503

    def test_list_documents_returns_documents(self, client):
        with patch("backend.main.rag_admin_service") as mock_admin:
            mock_admin.list_documents.return_value = [
                {"document_name": "Policy A", "version": "1.0", "effective_date": "2026-01-01", "source": "Src", "chunk_count": 3}
            ]
            response = client.get("/rag/documents")
            assert response.status_code == 200
            assert response.json()[0]["document_name"] == "Policy A"

    def test_upsert_document_returns_503_when_not_initialized(self, client):
        with patch("backend.main.rag_admin_service", None):
            response = client.post(
                "/rag/documents",
                json={"document_name": "Policy A", "version": "1.0", "effective_date": "2026-01-01", "source": "Src", "content": "## Scope\ntext"},
            )
            assert response.status_code == 503

    def test_upsert_document_success(self, client):
        with patch("backend.main.rag_admin_service") as mock_admin:
            mock_admin.upsert_document.return_value = (0, 2)
            response = client.post(
                "/rag/documents",
                json={"document_name": "Policy A", "version": "1.0", "effective_date": "2026-01-01", "source": "Src", "content": "## Scope\ntext"},
            )
            assert response.status_code == 201
            data = response.json()
            assert data["chunks_indexed"] == 2
            assert "Added" in data["message"]

    def test_upsert_document_rejects_empty_content(self, client):
        response = client.post(
            "/rag/documents",
            json={"document_name": "Policy A", "version": "1.0", "effective_date": "2026-01-01", "source": "Src", "content": ""},
        )
        assert response.status_code == 422

    def test_upsert_document_returns_400_on_validation_error(self, client):
        with patch("backend.main.rag_admin_service") as mock_admin:
            mock_admin.upsert_document.side_effect = ValueError("No content sections found.")
            response = client.post(
                "/rag/documents",
                json={"document_name": "Policy A", "version": "1.0", "effective_date": "2026-01-01", "source": "Src", "content": "plain text"},
            )
            assert response.status_code == 400

    def test_delete_document_returns_404_when_nothing_deleted(self, client):
        with patch("backend.main.rag_admin_service") as mock_admin:
            mock_admin.delete_document.return_value = 0
            response = client.delete("/rag/documents/Nonexistent")
            assert response.status_code == 404

    def test_delete_document_success(self, client):
        with patch("backend.main.rag_admin_service") as mock_admin:
            mock_admin.delete_document.return_value = 3
            response = client.delete("/rag/documents/Policy%20A")
            assert response.status_code == 200
            assert response.json()["chunks_deleted"] == 3
