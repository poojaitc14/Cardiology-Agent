"""FastAPI backend for the Cardiology Clinical Decision Support Agent."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.agent.cardiology_agent import CardiologistAgent
from backend.models.patient import PatientRecordScope
from backend.observability.instrumented_agent import InstrumentedCardiologistAgent
from backend.observability.tracing import (
    clear_trace_context,
    get_trace_id,
    trace_agent_invocation,
    trace_query,
)
from backend.schemas import (
    Citation,
    HealthResponse,
    PatientResponse,
    QueryRequest,
    QueryResponse,
)
from backend.services.azure_openai import AzureOpenAIConfig, AzureOpenAILLM
from backend.services.openfda import OpenFDAService
from backend.services.patient_repository import PatientRepository
from rag.retrieval.cardiology_rag import CardiologyRAGService

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Global service instances
patient_repository: PatientRepository | None = None
openfda_service: OpenFDAService | None = None
cardiology_rag_service: CardiologyRAGService | None = None
agent: CardiologistAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup and clean up on shutdown."""
    global patient_repository, openfda_service, cardiology_rag_service, agent

    logger.info("Starting Cardiology Decision Support Agent API")

    try:
        # Initialize services
        patient_repository = PatientRepository.from_environment()
        logger.info("PatientRepository initialized")

        openfda_service = OpenFDAService()
        logger.info("OpenFDAService initialized")

        # RAG service initialization is optional (may fail gracefully)
        try:
            cardiology_rag_service = CardiologyRAGService.from_environment()
            logger.info("CardiologyRAGService initialized")
        except Exception as e:
            logger.warning(f"CardiologyRAGService initialization failed: {e}")
            cardiology_rag_service = None

        # LLM-backed answer generation is optional (may fail gracefully)
        llm_tool = None
        try:
            llm_config = AzureOpenAIConfig()
            if llm_config.is_configured():
                llm_tool = AzureOpenAILLM(llm_config).generate_clinical_response
                logger.info("Azure OpenAI LLM initialized for answer generation")
            else:
                logger.info("Azure OpenAI is not configured; agent will summarize retrieved evidence only")
        except Exception as e:
            logger.warning(f"Azure OpenAI LLM initialization failed: {e}")
            llm_tool = None

        # Initialize agent with all three tools
        agent = InstrumentedCardiologistAgent(
            patient_database_tool=patient_repository.get_records,
            openfda_drug_tool=openfda_service.search_drug_label,
            cardiology_rag_tool=cardiology_rag_service.retrieve
            if cardiology_rag_service
            else _dummy_rag_tool,
            llm_tool=llm_tool,
        )
        logger.info("InstrumentedCardiologistAgent initialized successfully")

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

            response = QueryResponse(
                answer=agent_response.content,
                sources=sources,
                tools_used=list(agent_response.tools_used),
                errors=list(agent_response.errors),
                trace_id=trace_id,
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
