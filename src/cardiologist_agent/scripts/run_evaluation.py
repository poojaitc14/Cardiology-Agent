from __future__ import annotations

import asyncio
from dataclasses import dataclass

from cardiologist_agent.config.settings import get_settings, reset_settings
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


@dataclass
class EvaluationResult:
    patient_id: str
    expected: str
    actual: str
    passed: bool


async def run_deterministic_evaluation() -> list[EvaluationResult]:
    settings = get_settings()
    workflow = ReviewWorkflow(
        patient_repo=build_patient_repository(settings),
        order_repo=build_medication_order_repository(settings),
        policy_retriever=build_policy_retriever(settings),
        openfda_client=build_openfda_client(settings),
        llm_provider=build_llm_provider(settings),
    )
    manifest = CaseManifestDataset()
    results: list[EvaluationResult] = []
    for case in manifest.cases:
        response = await workflow.run(
            request_id=new_request_id(),
            patient_id=case.patient_id,
            clinician_id="DR101",
            clinical_question="Review cardiovascular history, medications, labs, and safety flags.",
        )
        passed = response.review_status == case.expected_review_status
        results.append(
            EvaluationResult(
                patient_id=case.patient_id,
                expected=case.expected_review_status.value,
                actual=response.review_status.value,
                passed=passed,
            )
        )
    return results


def main() -> None:
    reset_settings()
    results = asyncio.run(run_deterministic_evaluation())
    passed = sum(1 for r in results if r.passed)
    print(f"Deterministic evaluation: {passed}/{len(results)} passed")
    failures = [r for r in results if not r.passed]
    for fail in failures[:20]:
        print(f"  FAIL {fail.patient_id}: expected {fail.expected}, got {fail.actual}")
    if len(failures) > 20:
        print(f"  ... and {len(failures) - 20} more failures")
    raise SystemExit(0 if not failures else 1)


if __name__ == "__main__":
    main()
