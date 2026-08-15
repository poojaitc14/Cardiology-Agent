"""Request and response models for the FastAPI backend."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    """A single citation or evidence source."""

    source: str = Field(..., description="The source of the evidence")
    detail: str = Field(..., description="Specific detail or reference within the source")


class QueryRequest(BaseModel):
    """Request model for the /query endpoint."""

    patient_id: str = Field(..., min_length=1, description="Patient ID (e.g., P1005)")
    question: str = Field(..., min_length=1, description="Clinical question for the agent")

    @field_validator("patient_id")
    @classmethod
    def validate_patient_id(cls, v: str) -> str:
        """Validate patient ID format."""
        if not v.strip():
            raise ValueError("patient_id cannot be empty")
        return v.strip()

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        """Validate question is not empty."""
        if not v.strip():
            raise ValueError("question cannot be empty")
        return v.strip()


class QueryResponse(BaseModel):
    """Response model for the /query endpoint."""

    answer: str = Field(..., description="The agent's decision-support response")
    sources: list[Citation] = Field(
        default_factory=list, description="Evidence citations"
    )
    tools_used: list[str] = Field(
        default_factory=list, description="Tools invoked by the agent"
    )
    errors: list[str] = Field(
        default_factory=list, description="Non-fatal errors encountered"
    )
    trace_id: str = Field(..., description="Unique trace ID for observability")


class PatientResponse(BaseModel):
    """Response model for the /patient/{patient_id} endpoint."""

    patient_id: str = Field(..., description="The requested patient ID")
    data: dict[str, Any] = Field(..., description="Patient profile data")
    source: str = Field(..., description="Source of the data")


class HealthResponse(BaseModel):
    """Response model for the /health endpoint."""

    status: str = Field(..., description="Service status")
    version: str = Field(default="1.0.0", description="API version")
