"""FastAPI backend for the Cardiology Clinical Decision Support Agent."""

from __future__ import annotations

import logging
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from langchain_openai import AzureChatOpenAI

from backend.agent.graph import LangGraphCardiologistAgent
from backend.models.patient import PatientRecordScope
from backend.observability.tracing import (
    clear_trace_context,
    get_trace_id,
    trace_agent_invocation,
    trace_query,
)
from backend.schemas import (
    Citation,
    HealthResponse,
    PatientCreateRequest,
    PatientCreateResponse,
    PatientResponse,
    QueryRequest,
    QueryResponse,
    RAGDocumentDeleteResponse,
    RAGDocumentInfo,
    RAGDocumentUpsertRequest,
    RAGDocumentUpsertResponse,
    ToolStatusEntry,
)
from backend.services.azure_openai import AzureOpenAIConfig
from backend.services.openfda import OpenFDAService
from backend.services.patient_repository import PatientAlreadyExistsError, PatientRepository
from rag.ingestion.admin import RAGDocumentAdminService
from rag.retrieval.langchain_cardiology_rag import LangChainCardiologyRAGService

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Global service instances
patient_repository: PatientRepository | None = None
openfda_service: OpenFDAService | None = None
cardiology_rag_service: LangChainCardiologyRAGService | None = None
rag_admin_service: RAGDocumentAdminService | None = None
agent: LangGraphCardiologistAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup and clean up on shutdown."""
    global patient_repository, openfda_service, cardiology_rag_service, rag_admin_service, agent

    logger.info("Starting Cardiology Decision Support Agent API")

    try:
        # Initialize services
        patient_repository = PatientRepository.from_environment()
        logger.info("PatientRepository initialized")

        openfda_service = OpenFDAService()
        logger.info("OpenFDAService initialized")

        # RAG service initialization is optional (may fail gracefully). Backed by
        # LangChain's OpenSearchVectorSearch + Azure text-embedding-3-small.
        try:
            cardiology_rag_service = LangChainCardiologyRAGService.from_environment()
            logger.info("LangChainCardiologyRAGService initialized")
        except Exception as e:
            logger.warning(f"LangChainCardiologyRAGService initialization failed: {e}")
            cardiology_rag_service = None

        # RAG document admin (write path for the "Manage Guidelines" UI) is optional
        try:
            rag_admin_service = RAGDocumentAdminService.from_environment()
            logger.info("RAGDocumentAdminService initialized")
        except Exception as e:
            logger.warning(f"RAGDocumentAdminService initialization failed: {e}")
            rag_admin_service = None

        # LLM-backed answer generation is optional (may fail gracefully)
        chat_model = None
        try:
            llm_config = AzureOpenAIConfig()
            if llm_config.is_configured():
                chat_model = AzureChatOpenAI(
                    azure_endpoint=llm_config.endpoint,
                    api_key=llm_config.api_key,
                    api_version=llm_config.api_version,
                    azure_deployment=llm_config.deployment_name,
                    temperature=0.5,
                    timeout=30.0,
                    max_retries=1,
                )
                logger.info("Azure OpenAI chat model initialized for answer generation")
            else:
                logger.info("Azure OpenAI is not configured; agent will summarize retrieved evidence only")
        except Exception as e:
            logger.warning(f"Azure OpenAI chat model initialization failed: {e}")
            chat_model = None

        # Initialize the LangGraph-orchestrated agent with all three tools
        agent = LangGraphCardiologistAgent(
            patient_database_tool=patient_repository.get_records,
            openfda_drug_tool=openfda_service.search_drug_label,
            cardiology_rag_tool=cardiology_rag_service.retrieve
            if cardiology_rag_service
            else _dummy_rag_tool,
            chat_model=chat_model,
        )
        logger.info("LangGraphCardiologistAgent initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise

    yield

    logger.info("Shutting down Cardiology Decision Support Agent API")


def _dummy_rag_tool(query: str, limit: int = 5):
    """Dummy RAG tool when service is unavailable."""
    from rag.models import RetrievalResponse

    return RetrievalResponse(
        query=query,
        results=(),
        user_message="Cardiology document retrieval is temporarily unavailable.",
        available=False,
    )


# Initialize FastAPI app
app = FastAPI(
    title="Cardiology Clinical Decision Support Agent",
    description="API for clinical decision support using patient data, drug information, and cardiology guidelines",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def value_error_handler(request, exc: ValueError):
    """Handle validation errors."""
    logger.warning(f"Validation error: {exc}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected error: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred"},
    )


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    logger.debug("Health check requested")
    return HealthResponse(status="healthy")


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """
    Submit a clinical question about a patient.

    Args:
        request: QueryRequest with patient_id and question

    Returns:
        QueryResponse with answer, sources, tools used, errors, and trace_id

    Raises:
        HTTPException: On invalid input or service errors
    """
    if agent is None:
        logger.error("Agent not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent service is not available",
        )

    logger.info(f"Query received for patient {request.patient_id}: {request.question[:50]}...")

    async with trace_query(request.patient_id, request.question) as trace_context:
        trace_id = trace_context["trace_id"]
        logger.debug(f"Trace ID: {trace_id}")

        try:
            async with trace_agent_invocation(request.question) as agent_context:
                # Call agent with the question and the explicitly supplied patient ID
                agent_response = agent.review(request.question, patient_id=request.patient_id)

                logger.info(
                    f"Agent review completed. Tools used: {agent_response.tools_used}, "
                    f"Errors: {len(agent_response.errors)}"
                )

            # Convert citations to response format
            sources = [
                Citation(source=citation.source, detail=citation.detail)
                for citation in agent_response.citations
            ]

            # steps/tool_status are newer fields; tolerate older/mocked AgentResponse objects that lack them
            raw_steps = getattr(agent_response, "steps", ())
            steps = list(raw_steps) if isinstance(raw_steps, (list, tuple)) else []

            raw_tool_status = getattr(agent_response, "tool_status", ())
            tool_status = (
                [ToolStatusEntry(tool=ts.tool, status=ts.status, detail=ts.detail) for ts in raw_tool_status]
                if isinstance(raw_tool_status, (list, tuple))
                else []
            )

            response = QueryResponse(
                answer=agent_response.content,
                sources=sources,
                tools_used=list(agent_response.tools_used),
                errors=list(agent_response.errors),
                trace_id=trace_id,
                steps=steps,
                tool_status=tool_status,
            )

            logger.debug(f"Query response prepared with trace ID: {trace_id}")
            return response

        except Exception as e:
            logger.error(f"Error processing query: {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process query",
            )
        finally:
            clear_trace_context()


@app.get("/patient/{patient_id}", response_model=PatientResponse)
async def get_patient(patient_id: str) -> PatientResponse:
    """
    Retrieve a patient's clinical profile.

    Args:
        patient_id: Patient ID (e.g., P1005)

    Returns:
        PatientResponse with patient profile data

    Raises:
        HTTPException: If patient not found or service unavailable
    """
    if patient_repository is None:
        logger.error("PatientRepository not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Patient repository is not available",
        )

    patient_id = patient_id.strip()
    if not patient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="patient_id cannot be empty",
        )

    logger.info(f"Patient profile requested for {patient_id}")

    try:
        result = patient_repository.get_records(patient_id, PatientRecordScope.PROFILE)

        if not result.found or not result.records:
            logger.warning(f"Patient {patient_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient {patient_id} not found",
            )

        # Extract patient data from the first record
        patient_data = result.records[0] if result.records else {}

        logger.info(f"Patient {patient_id} profile retrieved successfully")

        return PatientResponse(
            patient_id=patient_id,
            data=patient_data,
            source=result.source,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving patient {patient_id}: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve patient information",
        )


def _generate_patient_id() -> str:
    """Generate a candidate patient ID outside the seeded P1001-P1100 range."""
    return f"P{random.randint(200000, 999999)}"


@app.post("/patients", response_model=PatientCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(request: PatientCreateRequest) -> PatientCreateResponse:
    """
    Register a brand-new patient and write their profile to DynamoDB.

    Args:
        request: PatientCreateRequest with the new patient's profile fields

    Returns:
        PatientCreateResponse with the (possibly auto-generated) patient ID

    Raises:
        HTTPException: On invalid input, an ID collision, or a service error
    """
    if patient_repository is None:
        logger.error("PatientRepository not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Patient repository is not available",
        )

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    profile = {
        "first_name": request.first_name,
        "last_name": request.last_name,
        "date_of_birth": request.date_of_birth,
        "gender": request.gender,
        "smoking_status": request.smoking_status,
        "family_history_cardiovascular_disease": request.family_history_cardiovascular_disease,
        "primary_cardiologist": request.primary_cardiologist or "Unassigned",
        "record_status": "Active",
        "source": "Registered via clinician UI",
        "created_at": now,
        "updated_at": now,
    }

    try:
        if request.patient_id:
            profile["patient_id"] = request.patient_id
            patient_id = patient_repository.create_patient(profile)
        else:
            patient_id = None
            for _ in range(5):
                candidate = _generate_patient_id()
                try:
                    profile["patient_id"] = candidate
                    patient_id = patient_repository.create_patient(profile)
                    break
                except PatientAlreadyExistsError:
                    continue
            if patient_id is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Could not generate a unique patient ID; please try again",
                )
    except PatientAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering patient: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register patient",
        )

    logger.info(f"Patient {patient_id} registered successfully")
    return PatientCreateResponse(patient_id=patient_id, message=f"Patient {patient_id} registered successfully.")


@app.get("/rag/documents", response_model=list[RAGDocumentInfo])
async def list_rag_documents() -> list[RAGDocumentInfo]:
    """List every document currently indexed in the cardiology guideline knowledge base."""
    if rag_admin_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG document management is not available",
        )
    try:
        documents = rag_admin_service.list_documents()
    except Exception as e:
        logger.error(f"Error listing RAG documents: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list RAG documents",
        )
    return [RAGDocumentInfo(**document) for document in documents]


@app.post("/rag/documents", response_model=RAGDocumentUpsertResponse, status_code=status.HTTP_201_CREATED)
async def upsert_rag_document(request: RAGDocumentUpsertRequest) -> RAGDocumentUpsertResponse:
    """
    Add a new guideline document, or replace an existing one with the same document_name.

    Content is split into sections on '## Section Name' markdown headings, chunked,
    embedded, and indexed the same way the original 15 synthetic documents were.
    """
    if rag_admin_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG document management is not available",
        )
    try:
        replaced, indexed = rag_admin_service.upsert_document(
            document_name=request.document_name,
            version=request.version,
            effective_date=request.effective_date,
            source=request.source,
            content_markdown=request.content,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error indexing RAG document '{request.document_name}': {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to index RAG document",
        )

    action = "Replaced" if replaced else "Added"
    logger.info(f"{action} RAG document '{request.document_name}' ({indexed} chunk(s) indexed)")
    return RAGDocumentUpsertResponse(
        document_name=request.document_name,
        chunks_replaced=replaced,
        chunks_indexed=indexed,
        message=f"{action} '{request.document_name}' -- {indexed} chunk(s) indexed.",
    )


@app.delete("/rag/documents/{document_name}", response_model=RAGDocumentDeleteResponse)
async def delete_rag_document(document_name: str) -> RAGDocumentDeleteResponse:
    """Delete every indexed chunk belonging to `document_name`."""
    if rag_admin_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG document management is not available",
        )
    try:
        deleted = rag_admin_service.delete_document(document_name)
    except Exception as e:
        logger.error(f"Error deleting RAG document '{document_name}': {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete RAG document",
        )
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No chunks found for document '{document_name}'",
        )
    return RAGDocumentDeleteResponse(document_name=document_name, chunks_deleted=deleted)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
