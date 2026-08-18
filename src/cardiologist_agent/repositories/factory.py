from __future__ import annotations

from cardiologist_agent.config.settings import Settings, get_settings
from cardiologist_agent.repositories.medication_order import (
    MedicationOrderRepository,
    UnavailableMedicationOrderRepository,
)
from cardiologist_agent.repositories.patient import (
    DynamoDBPatientRepository,
    LocalJsonPatientRepository,
    PatientRepository,
)
from cardiologist_agent.repositories.policy import PolicyRetriever
from cardiologist_agent.retrieval.local_index import LocalPolicyRetriever
from cardiologist_agent.retrieval.opensearch import OpenSearchPolicyRetriever


def build_patient_repository(settings: Settings | None = None) -> PatientRepository:
    settings = settings or get_settings()
    if settings.enable_dynamodb and settings.patient_repository_provider == "dynamodb":
        return DynamoDBPatientRepository(
            table_name=settings.dynamodb_patients_table,
            region=settings.aws_region,
        )
    return LocalJsonPatientRepository(
        settings.patients_file,
        custom_path=settings.custom_patients_file,
    )


def build_medication_order_repository(
    settings: Settings | None = None,
) -> MedicationOrderRepository:
    settings = settings or get_settings()
    if settings.medication_order_provider == "unavailable":
        return UnavailableMedicationOrderRepository()
    return UnavailableMedicationOrderRepository()


def build_policy_retriever(settings: Settings | None = None) -> PolicyRetriever:
    settings = settings or get_settings()
    if settings.enable_opensearch and settings.policy_retriever_provider == "opensearch":
        return OpenSearchPolicyRetriever(settings)
    return LocalPolicyRetriever(settings)
