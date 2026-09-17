"""Request and response models for the FastAPI backend."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.services.patient_repository import PATIENT_ID_PATTERN


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


class ToolStatusEntry(BaseModel):
    """The outcome of one tool invocation for this query."""

    tool: str = Field(..., description="Tool name, e.g. 'openfda_drug_tool'")
    status: str = Field(..., description="'ok' | 'no_data' | 'error'")
    detail: str = Field(..., description="Human-readable explanation of the outcome")


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
    steps: list[str] = Field(
        default_factory=list, description="The agent's tool-routing trace, in order, for display before the final answer"
    )
    tool_status: list[ToolStatusEntry] = Field(
        default_factory=list, description="Per-tool outcome (ok/no_data/error) for every tool invoked during this query"
    )


class PatientCreateRequest(BaseModel):
    """Request model for registering a brand-new patient."""

    patient_id: str | None = Field(
        None, description="Optional; a unique ID (e.g. P200481) is generated if omitted"
    )
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    date_of_birth: str = Field(..., description="YYYY-MM-DD")
    gender: str = Field(..., min_length=1)
    smoking_status: str = Field(..., min_length=1)
    family_history_cardiovascular_disease: bool = False
    primary_cardiologist: str | None = None

    @field_validator("patient_id")
    @classmethod
    def validate_patient_id(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip().upper()
        if not PATIENT_ID_PATTERN.fullmatch(v):
            raise ValueError("patient_id must use the format P followed by 4 to 12 digits.")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: str) -> str:
        try:
            date.fromisoformat(v.strip())
        except ValueError:
            raise ValueError("date_of_birth must be in YYYY-MM-DD format.")
        return v.strip()

    @field_validator("first_name", "last_name", "gender", "smoking_status")
    @classmethod
    def strip_required_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("This field cannot be empty.")
        return v


class PatientCreateResponse(BaseModel):
    """Response model for the patient-registration endpoint."""

    patient_id: str = Field(..., description="The newly registered patient's ID")
    message: str = Field(..., description="Human-readable confirmation")


class RAGDocumentInfo(BaseModel):
    """One row of the RAG document inventory."""

    document_name: str
    version: str
    effective_date: str
    source: str
    chunk_count: int


class RAGDocumentUpsertRequest(BaseModel):
    """Request model for adding or replacing a RAG document."""

    document_name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    effective_date: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    content: str = Field(
        ..., min_length=1, description="Markdown content; use '## Section Name' headings to structure it"
    )

    @field_validator("document_name", "version", "effective_date", "source", "content")
    @classmethod
    def strip_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("This field cannot be empty.")
        return v


class RAGDocumentUpsertResponse(BaseModel):
    """Response model for the RAG document add/replace endpoint."""

    document_name: str
    chunks_replaced: int
    chunks_indexed: int
    message: str


class RAGDocumentDeleteResponse(BaseModel):
    """Response model for the RAG document delete endpoint."""

    document_name: str
    chunks_deleted: int


class PatientResponse(BaseModel):
    """Response model for the /patient/{patient_id} endpoint."""

    patient_id: str = Field(..., description="The requested patient ID")
    data: dict[str, Any] = Field(..., description="Patient profile data")
    source: str = Field(..., description="Source of the data")


class HealthResponse(BaseModel):
    """Response model for the /health endpoint."""

    status: str = Field(..., description="Service status")
    version: str = Field(default="1.0.0", description="API version")
