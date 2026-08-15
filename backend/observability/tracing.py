"""Langfuse tracing utilities and context managers."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

from backend.observability.langfuse_config import get_langfuse_client

logger = logging.getLogger(__name__)

# Thread-local storage for current trace context
_trace_context: dict[str, Any] = {}


def get_trace_id() -> str:
    """Get the current trace ID or generate a new one."""
    if "trace_id" not in _trace_context:
        _trace_context["trace_id"] = str(uuid.uuid4())
    return _trace_context["trace_id"]


def set_trace_id(trace_id: str) -> None:
    """Set the current trace ID."""
    _trace_context["trace_id"] = trace_id


def clear_trace_context() -> None:
    """Clear the current trace context."""
    _trace_context.clear()


class TracingSpan:
    """Context manager for tracing a span."""

    def __init__(
        self,
        name: str,
        span_type: str = "span",
        metadata: dict[str, Any] | None = None,
    ):
        """Initialize a tracing span.
        
        Args:
            name: Name of the span
            span_type: Type of span (span, generation, event)
            metadata: Additional metadata to capture
        """
        self.name = name
        self.span_type = span_type
        self.metadata = metadata or {}
        self.start_time = None
        self.end_time = None
        self.langfuse_span = None
        self.client = get_langfuse_client()

    def __enter__(self):
        """Enter the span context."""
        self.start_time = time.time()
        
        if self.client is None:
            return self
        
        try:
            trace_id = get_trace_id()
            
            if self.span_type == "generation":
                self.langfuse_span = self.client.generation(
                    name=self.name,
                    trace_id=trace_id,
                    metadata=self.metadata,
                )
            else:
                self.langfuse_span = self.client.span(
                    name=self.name,
                    trace_id=trace_id,
                    metadata=self.metadata,
                )
        except Exception as e:
            logger.debug(f"Failed to create Langfuse span: {e}")
        
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the span context."""
        self.end_time = time.time()
        latency_ms = (self.end_time - self.start_time) * 1000
        
        if self.langfuse_span is None:
            return False
        
        try:
            # Record latency
            if hasattr(self.langfuse_span, "end"):
                self.langfuse_span.end(
                    metadata={"latency_ms": latency_ms},
                )
            
            # Record error if occurred
            if exc_type is not None:
                error_msg = f"{exc_type.__name__}: {exc_val}"
                if hasattr(self.langfuse_span, "end"):
                    self.langfuse_span.end(
                        metadata={"error": error_msg, "latency_ms": latency_ms},
                    )
                logger.debug(f"Span '{self.name}' failed: {error_msg}")
            else:
                logger.debug(
                    f"Span '{self.name}' completed in {latency_ms:.2f}ms"
                )
        except Exception as e:
            logger.debug(f"Failed to end Langfuse span: {e}")
        
        return False

    def update_metadata(self, key: str, value: Any) -> None:
        """Update metadata for the span."""
        if self.langfuse_span is None:
            return
        
        try:
            if hasattr(self.langfuse_span, "update"):
                self.langfuse_span.update(
                    metadata={**self.metadata, key: value}
                )
        except Exception as e:
            logger.debug(f"Failed to update Langfuse span metadata: {e}")


@asynccontextmanager
async def trace_query(
    patient_id: str,
    question: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """Trace a query request.
    
    Args:
        patient_id: Patient ID from the query
        question: Clinical question
        
    Yields:
        Dictionary with trace context
    """
    trace_id = str(uuid.uuid4())
    set_trace_id(trace_id)
    
    client = get_langfuse_client()
    langfuse_trace = None
    
    if client is not None:
        try:
            langfuse_trace = client.trace(
                name="clinical_query",
                trace_id=trace_id,
                metadata={
                    "patient_id": patient_id,
                    "question_length": len(question),
                },
                input={"patient_id": patient_id, "question": question[:100]},
            )
        except Exception as e:
            logger.debug(f"Failed to create Langfuse trace: {e}")
    
    start_time = time.time()
    
    try:
        yield {"trace_id": trace_id, "langfuse_trace": langfuse_trace}
    finally:
        end_time = time.time()
        latency_ms = (end_time - start_time) * 1000
        
        if langfuse_trace is not None:
            try:
                langfuse_trace.end(
                    metadata={"total_latency_ms": latency_ms}
                )
            except Exception as e:
                logger.debug(f"Failed to end Langfuse trace: {e}")
        
        logger.debug(f"Query trace '{trace_id}' completed in {latency_ms:.2f}ms")


@asynccontextmanager
async def trace_agent_invocation(
    question: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """Trace an agent invocation.
    
    Args:
        question: Clinical question
        
    Yields:
        Dictionary with tracing context
    """
    with TracingSpan(
        name="agent_review",
        span_type="span",
        metadata={"question_length": len(question)},
    ) as span:
        yield {"span": span}


def trace_tool_call(
    tool_name: str,
    tool_input: dict[str, Any] | None = None,
) -> TracingSpan:
    """Create a span for a tool call.
    
    Args:
        tool_name: Name of the tool being called
        tool_input: Input parameters to the tool
        
    Returns:
        TracingSpan context manager
    """
    metadata = {"tool": tool_name}
    if tool_input:
        # Don't log sensitive data
        safe_input = {}
        for key, value in tool_input.items():
            if key.lower() not in ["password", "secret", "token", "key"]:
                safe_input[key] = value
        metadata["tool_input"] = safe_input
    
    return TracingSpan(
        name=f"tool_{tool_name}",
        span_type="span",
        metadata=metadata,
    )


def trace_tool_result(
    span: TracingSpan,
    result: Any | None = None,
    error: str | None = None,
) -> None:
    """Record the result of a tool call.
    
    Args:
        span: The tracing span
        result: Result from the tool
        error: Error message if tool failed
    """
    if span.langfuse_span is None:
        return
    
    try:
        metadata = {}
        
        if error:
            metadata["error"] = error
        elif result:
            # Capture safe result metadata
            if hasattr(result, "__dict__"):
                for key, value in result.__dict__.items():
                    if key.lower() not in ["password", "secret", "token", "key"]:
                        if isinstance(value, (str, int, float, bool, type(None))):
                            metadata[f"result_{key}"] = value
        
        if metadata and hasattr(span.langfuse_span, "end"):
            span.langfuse_span.end(metadata=metadata)
    except Exception as e:
        logger.debug(f"Failed to record tool result: {e}")
