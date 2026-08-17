from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cardiologist_agent.config.settings import get_settings
from cardiologist_agent.domain.response import MedicationRecommendationResponse


class AuditSink:
    def __init__(self, log_path: Path | None = None) -> None:
        settings = get_settings()
        self.log_path = log_path or settings.audit_file

    def write(self, event_type: str, payload: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            **payload,
        }
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def review_completed(self, response: MedicationRecommendationResponse) -> None:
        self.write(
            "review_completed",
            {
                "request_id": response.request_id,
                "patient_id": response.patient_id,
                "review_status": response.review_status.value,
                "evidence_grade": response.evidence_grade.value,
            },
        )
