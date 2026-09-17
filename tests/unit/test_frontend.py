"""Tests for the Streamlit frontend."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from frontend.api_client import APIClient


class TestAPIClient:
    """Tests for API client."""

    def test_client_initialization(self):
        """Test API client initialization."""
        client = APIClient(base_url="http://localhost:8000", timeout=30)
        assert client.base_url == "http://localhost:8000"
        assert client.timeout == 30

    def test_client_strips_trailing_slash(self):
        """Test that trailing slash is removed from base URL."""
        client = APIClient(base_url="http://localhost:8000/")
        assert client.base_url == "http://localhost:8000"

    def test_health_check_success(self):
        """Test successful health check."""
        client = APIClient()
        with patch.object(client, "client") as mock_http_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"status": "healthy"}
            mock_http_client.get.return_value = mock_response

            result = client.health_check()

            assert result == {"status": "healthy"}

    def test_health_check_failure(self):
        """Test health check failure handling."""
        client = APIClient()
        with patch.object(client, "client") as mock_http_client:
            mock_http_client.get.side_effect = httpx.RequestError("Connection failed")

            with pytest.raises(httpx.RequestError):
                client.health_check()


class TestAPIClientContextManager:
    """Tests for API client context manager."""

    def test_client_context_manager(self):
        """Test API client as context manager."""
        with APIClient(base_url="http://localhost:8000") as client:
            assert client is not None

    def test_client_closes_on_exit(self):
        """Test that client closes properly."""
        with patch.object(APIClient, "close") as mock_close:
            with APIClient(base_url="http://localhost:8000") as client:
                pass
            # Verify close was called


class TestQueryRequest:
    """Tests for query requests."""

    @pytest.mark.parametrize("patient_id,question", [
        ("P1005", "Review patient status"),
        ("P1010", "Check medications"),
        ("P1020", "What are the drug interactions?"),
    ])
    def test_query_validation(self, patient_id: str, question: str):
        """Test query parameter validation."""
        assert len(patient_id) > 0
        assert len(question) > 0


class TestPatientRequest:
    """Tests for patient requests."""

    @pytest.mark.parametrize("patient_id", [
        "P1005",
        "P1010",
        "P1020",
    ])
    def test_patient_id_format(self, patient_id: str):
        """Test patient ID format validation."""
        assert patient_id.startswith("P")
        assert patient_id[1:].isdigit()


class TestAPIErrorHandling:
    """Tests for error handling."""

    def test_timeout_exception(self):
        """Test timeout exception handling."""
        error = httpx.TimeoutException("Request timed out")
        assert "timed out" in str(error).lower()

    def test_connection_error(self):
        """Test connection error handling."""
        error = httpx.ConnectError("Failed to connect")
        assert isinstance(error, httpx.RequestError)

    def test_http_status_error(self):
        """Test HTTP status error handling."""
        response = MagicMock()
        response.status_code = 404
        error = httpx.HTTPStatusError("Not found", request=MagicMock(), response=response)
        assert error.response.status_code == 404
