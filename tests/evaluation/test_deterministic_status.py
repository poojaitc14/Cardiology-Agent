import pytest

from cardiologist_agent.evaluation.manifest import CaseManifestDataset
from cardiologist_agent.providers.llm import build_llm_provider
from cardiologist_agent.providers.openfda import build_openfda_client
from cardiologist_agent.repositories.factory import (
    build_medication_order_repository,
    build_patient_repository,
    build_policy_retriever,
)
from cardiologist_agent.workflow.graph import ReviewWorkflow
from cardiologist_agent.workflow.response_builder import new_request_id


@pytest.mark.slow
@pytest.mark.asyncio
async def test_all_manifest_expected_statuses() -> None:
    workflow = ReviewWorkflow(
        patient_repo=build_patient_repository(),
        order_repo=build_medication_order_repository(),
        policy_retriever=build_policy_retriever(),
        openfda_client=build_openfda_client(),
        llm_provider=build_llm_provider(),
    )
    manifest = CaseManifestDataset()
    failures = []
    for case in manifest.cases:
        response = await workflow.run(
            request_id=new_request_id(),
            patient_id=case.patient_id,
            clinician_id="DR101",
            clinical_question="Review cardiovascular history and medications.",
        )
        if response.review_status != case.expected_review_status:
            failures.append(
                (case.patient_id, case.expected_review_status.value, response.review_status.value)
            )
    assert not failures, f"Failures: {failures[:10]}"
