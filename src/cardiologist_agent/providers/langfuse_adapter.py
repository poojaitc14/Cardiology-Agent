"""Langfuse observability adapter — disabled unless ENABLE_LANGFUSE=true."""

from __future__ import annotations

from cardiologist_agent.config.settings import get_settings


class LangfuseAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.enabled = self.settings.enable_langfuse and bool(self.settings.langfuse_public_key)

    def trace_review(self, request_id: str, patient_id: str) -> None:
        if not self.enabled:
            return
        # Redacted trace hook — requires provisioned Langfuse project.
        raise NotImplementedError("Langfuse adapter not provisioned in local build.")
