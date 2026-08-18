
from cardiologist_agent.evaluation.manifest import CaseManifestDataset


def test_manifest_has_130_cases() -> None:
    manifest = CaseManifestDataset()
    assert len(manifest) == 130


def test_manifest_no_final_authorized_expected() -> None:
    manifest = CaseManifestDataset()
    assert all(c.expected_review_status.value != "FINAL_AUTHORIZED" for c in manifest.cases)
