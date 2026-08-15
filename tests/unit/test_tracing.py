"""Tests for Langfuse observability and tracing."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.observability.langfuse_config import LangfuseConfig, get_config
from backend.observability.tracing import (
    TracingSpan,
    clear_trace_context,
    get_trace_id,
    set_trace_id,
    trace_agent_invocation,
    trace_tool_call,
    trace_tool_result,
)


class TestLangfuseConfig:
    """Tests for Langfuse configuration."""

    def test_config_disabled_when_no_keys(self):
        """Test that config is disabled when keys are missing."""
        with patch.dict("os.environ", {"LANGFUSE_ENABLED": "true"}, clear=True):
            config = LangfuseConfig()
            assert config.enabled is False

    def test_config_enabled_with_keys(self):
        """Test that config is enabled with valid keys."""
        with patch.dict(
            "os.environ",
            {
                "LANGFUSE_ENABLED": "true",
                "LANGFUSE_PUBLIC_KEY": "pk_test",
                "LANGFUSE_SECRET_KEY": "sk_test",
            },
        ):
            config = LangfuseConfig()
            assert config.enabled is True
            assert config.public_key == "pk_test"
            assert config.secret_key == "sk_test"

    def test_config_uses_custom_host(self):
        """Test that custom host is used."""
        with patch.dict(
            "os.environ",
            {
                "LANGFUSE_PUBLIC_KEY": "pk_test",
                "LANGFUSE_SECRET_KEY": "sk_test",
                "LANGFUSE_HOST": "https://custom.example.com",
            },
        ):
            config = LangfuseConfig()
            assert config.host == "https://custom.example.com"

    def test_config_defaults_to_cloud_host(self):
        """Test that default host is cloud.langfuse.com."""
        with patch.dict(
            "os.environ",
            {
                "LANGFUSE_PUBLIC_KEY": "pk_test",
                "LANGFUSE_SECRET_KEY": "sk_test",
            },
            clear=True,
        ):
            config = LangfuseConfig()
            assert config.host == "https://cloud.langfuse.com"


class TestTracingContext:
    """Tests for trace context management."""

    def test_trace_id_generation(self):
        """Test that trace IDs are generated."""
        clear_trace_context()
        trace_id = get_trace_id()
        assert trace_id is not None
        assert len(trace_id) > 0
        # Should return same ID on subsequent calls
        assert get_trace_id() == trace_id

    def test_set_trace_id(self):
        """Test setting trace ID."""
        clear_trace_context()
        test_id = str(uuid.uuid4())
        set_trace_id(test_id)
        assert get_trace_id() == test_id

    def test_clear_trace_context(self):
        """Test clearing trace context."""
        set_trace_id("test_id")
        assert get_trace_id() == "test_id"
        clear_trace_context()
        # Should generate new ID after clear
        new_id = get_trace_id()
        assert new_id != "test_id"


class TestTracingSpan:
    """Tests for TracingSpan context manager."""

    def test_span_creation(self):
        """Test span creation and context management."""
        span = TracingSpan("test_span", "span", {"key": "value"})
        assert span.name == "test_span"
        assert span.start_time is None
        assert span.end_time is None

    def test_span_timing(self):
        """Test that span captures timing."""
        with TracingSpan("test_span") as span:
            assert span.start_time is not None
        assert span.end_time is not None
        assert span.end_time >= span.start_time

    def test_span_exception_handling(self):
        """Test that span handles exceptions gracefully."""
        try:
            with TracingSpan("test_span") as span:
                raise ValueError("Test error")
        except ValueError:
            pass
        # Should not raise even with inner exception
        assert span.end_time is not None

    def test_span_metadata_update(self):
        """Test updating span metadata."""
        with TracingSpan("test_span") as span:
            span.update_metadata("key", "value")
            # Should not raise


class TestToolTracing:
    """Tests for tool call tracing."""

    def test_trace_tool_call(self):
        """Test tool call span creation."""
        span = trace_tool_call("test_tool", {"param": "value"})
        assert span.name == "tool_test_tool"
        assert "tool" in span.metadata
        assert span.metadata["tool"] == "test_tool"

    def test_trace_tool_call_filters_sensitive_data(self):
        """Test that sensitive data is filtered from tool input."""
        span = trace_tool_call(
            "test_tool",
            {"patient_id": "P1005", "password": "secret", "key": "secret_key"},
        )
        # Metadata should have tool_input without sensitive keys
        if "tool_input" in span.metadata:
            tool_input = span.metadata["tool_input"]
            assert "patient_id" in tool_input
            assert "password" not in tool_input
            assert "key" not in tool_input

    def test_trace_tool_result(self):
        """Test recording tool result."""
        span = TracingSpan("test_tool")
        with span:
            result = MagicMock()
            result.found = True
            trace_tool_result(span, result=result)
        # Should not raise


class TestAgentTracing:
    """Tests for agent invocation tracing."""

    @pytest.mark.asyncio
    async def test_trace_agent_invocation(self):
        """Test agent invocation tracing."""
        async with trace_agent_invocation("test question") as context:
            assert "span" in context
            span = context["span"]
            assert span.name == "agent_review"


class TestEndToEndTracing:
    """End-to-end tracing scenarios."""

    def test_full_tool_call_flow(self):
        """Test full flow of tracing a tool call."""
        clear_trace_context()
        
        # Start trace
        trace_id = get_trace_id()
        assert trace_id is not None
        
        # Call tool with tracing
        span = trace_tool_call(
            "patient_database_tool",
            {"patient_id": "P1005"},
        )
        
        with span:
            # Simulate tool execution
            result = MagicMock()
            result.found = True
            result.records = [{"patient_id": "P1005"}]
            trace_tool_result(span, result=result)
        
        # Verify span was executed
        assert span.start_time is not None
        assert span.end_time is not None
        assert span.end_time >= span.start_time

    def test_no_errors_without_langfuse_package(self):
        """Test that tracing works gracefully without langfuse package."""
        with patch("backend.observability.tracing.get_langfuse_client", return_value=None):
            clear_trace_context()
            trace_id = get_trace_id()
            assert trace_id is not None
            
            with TracingSpan("test_span") as span:
                assert span.langfuse_span is None
            
            assert span.start_time is not None
            assert span.end_time is not None
