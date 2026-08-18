import pytest

from cardiologist_agent.repositories.patient import LocalJsonPatientRepository
from cardiologist_agent.services.patient_resolver import resolve_patient_from_question


@pytest.fixture
def patient_repo() -> LocalJsonPatientRepository:
    from cardiologist_agent.config.settings import get_settings

    settings = get_settings()
    return LocalJsonPatientRepository(settings.patients_file)


@pytest.mark.asyncio
async def test_resolve_by_patient_code(patient_repo: LocalJsonPatientRepository) -> None:
    result = await resolve_patient_from_question(
        "For P1001, please check the heart record.",
        patient_repo,
    )
    assert result == "P1001"


@pytest.mark.asyncio
async def test_resolve_by_name(patient_repo: LocalJsonPatientRepository) -> None:
    patient = await patient_repo.get_patient("P1001")
    assert patient is not None
    result = await resolve_patient_from_question(
        f"When did {patient.last_name} last have a test?",
        patient_repo,
    )
    assert result == "P1001"
