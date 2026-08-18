import pytest

from cardiologist_agent.config.settings import get_settings
from cardiologist_agent.domain.enums import AuthorizationStatus, ReviewStatus
from cardiologist_agent.repositories.patient import LocalJsonPatientRepository
from cardiologist_agent.retrieval.ingest import ingest_runtime_policies, load_inventory
from cardiologist_agent.retrieval.local_index import LocalPolicyRetriever
from cardiologist_agent.safety.assessment import assess_patient
from cardiologist_agent.safety.status import select_review_status


@pytest.fixture
def patient_repo() -> LocalJsonPatientRepository:
    settings = get_settings()
    return LocalJsonPatientRepository(settings.patients_file)


@pytest.mark.asyncio
async def test_patient_count(patient_repo: LocalJsonPatientRepository) -> None:
    ids = await patient_repo.list_patient_ids()
    assert len(ids) == 130


def test_no_evaluation_pdfs_in_runtime_ingest() -> None:
    settings = get_settings()
    inventory = load_inventory(settings)
    runtime_paths = {
        d["source_path"]
        for d in inventory
        if d.get("runtime_retrieval_allowed") and d.get("corpus_eligibility") == "runtime"
    }
    for path in runtime_paths:
        assert "evaluation-only" not in path
    chunks = ingest_runtime_policies(settings)
    assert chunks
    assert all(c.corpus_eligibility == "runtime" for c in chunks)


@pytest.mark.asyncio
async def test_local_retriever_excludes_evaluation() -> None:
    retriever = LocalPolicyRetriever()
    result = await retriever.retrieve("worked synthetic patient review cases evaluation")
    assert not any(c.document_id == "NB-TRN-701" for c in result.chunks)


@pytest.mark.asyncio
async def test_assessment_emergency(patient_repo: LocalJsonPatientRepository) -> None:
    patient = await patient_repo.get_patient("P1091")
    assert patient is not None
    assessment = assess_patient(patient)
    status = select_review_status(assessment, AuthorizationStatus.UNAVAILABLE)
    assert status == ReviewStatus.EMERGENCY_ESCALATION


@pytest.mark.asyncio
async def test_final_authorized_blocked(patient_repo: LocalJsonPatientRepository) -> None:
    patient = await patient_repo.get_patient("P1001")
    assert patient is not None
    assessment = assess_patient(patient)
    status = select_review_status(
        assessment, AuthorizationStatus.UNAVAILABLE, has_signed_orders=False
    )
    assert status != ReviewStatus.FINAL_AUTHORIZED
