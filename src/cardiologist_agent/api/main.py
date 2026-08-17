from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from cardiologist_agent import __version__
from cardiologist_agent.audit.sink import AuditSink
from cardiologist_agent.config.settings import get_settings
from cardiologist_agent.domain.response import HealthResponse, ReadyResponse, ReviewRequest
from cardiologist_agent.providers.llm import build_llm_provider
from cardiologist_agent.providers.openfda import build_openfda_client
from cardiologist_agent.repositories.factory import (
    build_medication_order_repository,
    build_patient_repository,
    build_policy_retriever,
)
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


def create_app() -> FastAPI:
    settings = get_settings()
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
        return HealthResponse(status="ok", app_env=settings.app_env, version=__version__)

    @app.get("/ready", response_model=ReadyResponse)
    async def ready() -> ReadyResponse:
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
