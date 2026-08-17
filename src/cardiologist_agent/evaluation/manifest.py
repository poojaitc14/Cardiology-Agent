from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cardiologist_agent.config.settings import get_settings
from cardiologist_agent.domain.enums import ReviewStatus


@dataclass
class CaseEntry:
    patient_id: str
    scenario_tags: list[str]
    expected_review_status: ReviewStatus
    notes: str | None = None


class CaseManifestDataset:
    def __init__(self, manifest_path: Path | None = None) -> None:
        settings = get_settings()
        path = manifest_path or settings.manifest_file
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.cases = [
            CaseEntry(
                patient_id=item["patient_id"],
                scenario_tags=item.get("scenario_tags", []),
                expected_review_status=ReviewStatus(item["expected_review_status"]),
                notes=item.get("notes"),
            )
            for item in raw
        ]

    def __len__(self) -> int:
        return len(self.cases)
