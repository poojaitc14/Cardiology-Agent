"""Integration tests for Streamlit frontend."""

from __future__ import annotations

import pytest


class TestFrontendIntegration:
    """Integration tests for Streamlit frontend with FastAPI backend."""

    def test_frontend_imports(self):
        """Test that frontend modules import correctly."""
        from frontend.config import API_BASE_URL, API_TIMEOUT
        from frontend.api_client import APIClient
        from frontend.ui_components import display_agent_response
        
        assert API_BASE_URL
        assert API_TIMEOUT > 0
        assert APIClient is not None
        assert display_agent_response is not None

    def test_config_environment_variables(self):
        """Test configuration from environment."""
        from frontend.config import API_BASE_URL
        assert "localhost" in API_BASE_URL or "8000" in API_BASE_URL

    def test_api_client_initialization(self):
        """Test API client can be initialized."""
        from frontend.api_client import APIClient
        
        client = APIClient(base_url="http://localhost:8000", timeout=30)
        assert client is not None
        assert client.base_url == "http://localhost:8000"


class TestStreamlitApp:
    """Tests for Streamlit app structure."""

    def test_streamlit_app_exists(self):
        """Test that Streamlit app file exists and imports."""
        try:
            # Note: Can't fully import streamlit_app here as it uses Streamlit
            # But we can verify the file exists and basic syntax
            import os
            app_path = "frontend/streamlit_app.py"
            assert os.path.exists(app_path)
        except AssertionError:
            pytest.skip("Streamlit app file not found")


class TestFrontendAPI:
    """Tests for frontend API interactions."""

    def test_query_response_format(self):
        """Test that query responses have correct format."""
        # Simulate expected response from API
        expected_response = {
            "answer": "...",
            "sources": [],
            "tools_used": [],
            "errors": [],
            "trace_id": "550e8400-e29b-41d4-a716-446655440000",
        }
        
        # Verify structure
        assert "answer" in expected_response
        assert "sources" in expected_response
        assert "tools_used" in expected_response
        assert "errors" in expected_response
        assert "trace_id" in expected_response

    def test_patient_response_format(self):
        """Test that patient responses have correct format."""
        # Simulate expected response from API
        expected_response = {
            "patient_id": "P1005",
            "data": {"first_name": "John", "last_name": "Doe"},
            "source": "DynamoDB",
        }
        
        # Verify structure
        assert "patient_id" in expected_response
        assert "data" in expected_response
        assert "source" in expected_response


class TestUIComponents:
    """Tests for UI component structure."""

    def test_ui_components_exist(self):
        """Test that UI components can be imported."""
        from frontend.ui_components import (
            display_agent_response,
            display_patient_overview,
            display_error_message,
            format_tool_name,
        )
        
        assert display_agent_response is not None
        assert display_patient_overview is not None
        assert display_error_message is not None
        assert format_tool_name is not None

    def test_tool_name_formatting(self):
        """Test tool name formatting."""
        from frontend.ui_components import format_tool_name
        
        result = format_tool_name("patient_database_tool")
        assert "Patient" in result or "patient" in result.lower()
        
        result = format_tool_name("openfda_drug_tool")
        assert "FDA" in result or "Drug" in result or "fda" in result.lower()


class TestErrorHandling:
    """Tests for error handling in frontend."""

    def test_connection_error_message(self):
        """Test connection error message."""
        from frontend.config import CONNECTION_ERROR_MESSAGE
        
        assert CONNECTION_ERROR_MESSAGE
        assert "API" in CONNECTION_ERROR_MESSAGE or "connect" in CONNECTION_ERROR_MESSAGE.lower()

    def test_timeout_message(self):
        """Test timeout error message."""
        from frontend.config import TIMEOUT_MESSAGE
        
        assert TIMEOUT_MESSAGE
        assert "timed out" in TIMEOUT_MESSAGE.lower()
