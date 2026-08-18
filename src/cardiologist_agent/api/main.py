from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from cardiologist_agent import __version__
from cardiologist_agent.audit.sink import AuditSink
from cardiologist_agent.config.settings import get_settings
from cardiologist_agent.domain.response import (
    CreatePatientRequest,
    CreatePatientResponse,
    HealthResponse,
    PatientListResponse,
    QueryRequest,
    QueryResponse,
    ReadyResponse,
    ReviewRequest,
)
from cardiologist_agent.providers.llm import build_llm_provider
from cardiologist_agent.providers.openfda import build_openfda_client
from cardiologist_agent.repositories.factory import (
    build_medication_order_repository,
    build_patient_repository,
    build_policy_retriever,
)
from cardiologist_agent.repositories.patient import PatientAlreadyExistsError
from cardiologist_agent.services.patient_factory import (
    build_patient_from_intake,
    suggest_next_patient_id,
)
from cardiologist_agent.services.query_service import QueryService
from cardiologist_agent.workflow.graph import ReviewWorkflow
from cardiologist_agent.workflow.response_builder import new_request_id


@lru_cache
def get_workflow() -> ReviewWorkflow:
    settings = get_settings()
    return ReviewWorkflow(
        patient_repo=build_patient_repository(settings),
        order_repo=build_medication_order_repository(settings),
        policy_retriever=build_policy_retriever(settings),
        openfda_client=build_openfda_client(settings),
        llm_provider=build_llm_provider(settings),
    )


@lru_cache
def get_query_service() -> QueryService:
    settings = get_settings()
    return QueryService(
        patient_repo=build_patient_repository(settings),
        policy_retriever=build_policy_retriever(settings),
        openfda_client=build_openfda_client(settings),
        review_workflow=get_workflow(),
        settings=settings,
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Cardiologist Review Agent", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    audit = AuditSink()

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        settings = get_settings()
        return HealthResponse(status="ok", app_env=settings.app_env, version=__version__)

    @app.get("/ready", response_model=ReadyResponse)
    async def ready() -> ReadyResponse:
        settings = get_settings()
        runtime_pdf_dir = settings.resolve(settings.repo_root / "data/rag/runtime_policies")
        checks = {
            "patients_file": settings.patients_file.exists(),
            "corpus_inventory": settings.inventory_file.exists(),
            "runtime_policy_pdfs": runtime_pdf_dir.exists() and any(runtime_pdf_dir.glob("*.pdf")),
        }
        messages: list[str] = []
        if not checks["patients_file"]:
            messages.append("patients.json missing")
        ready_flag = all(checks.values())
        return ReadyResponse(ready=ready_flag, checks=checks, messages=messages)

    @app.get("/api/v1/patients", response_model=PatientListResponse)
    async def list_patients() -> PatientListResponse:
        settings = get_settings()
        repo = build_patient_repository(settings)
        ids = await repo.list_patient_ids()
        return PatientListResponse(
            patient_ids=ids,
            suggested_next_id=suggest_next_patient_id(ids),
            total=len(ids),
        )

    @app.post("/api/v1/patients", response_model=CreatePatientResponse)
    async def create_patient(request: CreatePatientRequest) -> CreatePatientResponse:
        settings = get_settings()
        repo = build_patient_repository(settings)
        ids = await repo.list_patient_ids()
        patient_id = (request.patient_id or suggest_next_patient_id(ids)).upper()
        patient = build_patient_from_intake(
            patient_id=patient_id,
            condition_name=request.condition_name,
            on_medication=request.on_medication,
            medication_name=request.medication_name,
            primary_cardiologist=request.primary_cardiologist,
            settings=settings,
        )
        try:
            await repo.create_patient(patient)
        except PatientAlreadyExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except NotImplementedError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc

        get_workflow.cache_clear()
        get_query_service.cache_clear()

        review = None
        if request.run_review:
            workflow = get_workflow()
            review = await workflow.run(
                request_id=new_request_id(),
                patient_id=patient.patient_id,
                clinician_id=request.clinician_id,
                clinical_question=request.clinical_question,
            )
            audit.review_completed(review)
        return CreatePatientResponse(patient_id=patient.patient_id, review=review)

    @app.post("/api/v1/reviews")
    async def create_review(request: ReviewRequest):
        workflow = get_workflow()
        request_id = request.request_id or new_request_id()
        try:
            response = await workflow.run(
                request_id=request_id,
                patient_id=request.patient_id,
                clinician_id=request.clinician_id,
                clinical_question=request.clinical_question,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        audit.review_completed(response)
        return response

    @app.post("/api/v1/queries", response_model=QueryResponse)
    async def run_query(request: QueryRequest) -> QueryResponse:
        service = get_query_service()
        try:
            response = await service.run(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if response.review is not None:
            audit.review_completed(response.review)
        return response

    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "cardiologist_agent.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
