from __future__ import annotations

from cardiologist_agent.config.settings import Settings, get_settings
from cardiologist_agent.domain.response import QueryRequest, QueryResponse
from cardiologist_agent.providers.openfda import OpenFDAClient
from cardiologist_agent.repositories.patient import PatientRepository
from cardiologist_agent.repositories.policy import PolicyRetriever
from cardiologist_agent.services.hospital_query import answer_hospital_question
from cardiologist_agent.services.medical_query import answer_medical_question
from cardiologist_agent.services.patient_query import answer_patient_question
from cardiologist_agent.services.patient_resolver import resolve_patient_from_question
from cardiologist_agent.services.question_router import QueryMode, classify_question
from cardiologist_agent.workflow.graph import ReviewWorkflow
from cardiologist_agent.workflow.response_builder import new_request_id


class QueryService:
    def __init__(
        self,
        patient_repo: PatientRepository,
        policy_retriever: PolicyRetriever,
        openfda_client: OpenFDAClient,
        review_workflow: ReviewWorkflow,
        settings: Settings | None = None,
    ) -> None:
        self.patient_repo = patient_repo
        self.policy_retriever = policy_retriever
        self.openfda_client = openfda_client
        self.review_workflow = review_workflow
        self.settings = settings or get_settings()

    async def _resolve_patient_id(self, request: QueryRequest) -> str | None:
        if request.patient_id:
            return request.patient_id.upper()
        return await resolve_patient_from_question(request.clinical_question, self.patient_repo)

    async def run(self, request: QueryRequest) -> QueryResponse:
        request_id = request.request_id or new_request_id()
        patient_id = await self._resolve_patient_id(request)
        mode: QueryMode = classify_question(
            request.clinical_question,
            mode=request.mode,
            has_patient_context=patient_id is not None,
        )

        if mode == "medical_api":
            patient = await self.patient_repo.get_patient(patient_id) if patient_id else None
            answer, sources = await answer_medical_question(
                request.clinical_question,
                self.openfda_client,
                patient,
            )
            return QueryResponse(
                request_id=request_id,
                query_mode=mode,
                patient_id=patient_id,
                answer=answer,
                sources=sources,
            )

        if mode == "hospital_rag":
            answer, sources = await answer_hospital_question(
                request.clinical_question,
                self.policy_retriever,
                self.settings,
            )
            return QueryResponse(
                request_id=request_id,
                query_mode=mode,
                patient_id=patient_id,
                answer=answer,
                sources=sources,
            )

        if mode == "patient_db":
            if not patient_id:
                return QueryResponse(
                    request_id=request_id,
                    query_mode=mode,
                    patient_id=None,
                    answer=(
                        "Please mention which patient you mean — by reference number "
                        "(e.g. P1001) or by name — in your question."
                    ),
                    sources=[],
                )
            patient = await self.patient_repo.get_patient(patient_id)
            if patient is None:
                return QueryResponse(
                    request_id=request_id,
                    query_mode=mode,
                    patient_id=patient_id,
                    answer="That patient was not found in the records.",
                    sources=[],
                )
            answer, sources = answer_patient_question(patient, request.clinical_question)
            return QueryResponse(
                request_id=request_id,
                query_mode=mode,
                patient_id=patient_id,
                answer=answer,
                sources=sources,
            )

        if not patient_id:
            return QueryResponse(
                request_id=request_id,
                query_mode=mode,
                patient_id=None,
                answer=(
                    "Please mention which patient you mean — by reference number "
                    "(e.g. P1001) or by name — in your question."
                ),
                sources=[],
            )

        review = await self.review_workflow.run(
            request_id=request_id,
            patient_id=patient_id,
            clinician_id=request.clinician_id,
            clinical_question=request.clinical_question,
        )
        return QueryResponse(
            request_id=request_id,
            query_mode=mode,
            patient_id=patient_id,
            answer="",
            sources=[],
            review=review,
        )
