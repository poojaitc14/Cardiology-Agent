from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import httpx

from cardiologist_agent.config.settings import Settings, get_settings


class OpenFDAResult:
    def __init__(
        self,
        drug_name: str,
        found: bool,
        label_excerpt: str | None = None,
        source_url: str | None = None,
        retrieved_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        self.drug_name = drug_name
        self.found = found
        self.label_excerpt = label_excerpt
        self.source_url = source_url
        self.retrieved_at = retrieved_at or datetime.now(UTC)
        self.error = error


class OpenFDAClient(ABC):
    @abstractmethod
    async def lookup_drug_label(self, drug_name: str) -> OpenFDAResult: ...


class FakeOpenFDAClient(OpenFDAClient):
    async def lookup_drug_label(self, drug_name: str) -> OpenFDAResult:
        return OpenFDAResult(
            drug_name=drug_name,
            found=False,
            error="openFDA unavailable in fake mode; no warning inferred from absence of result.",
        )


class LiveOpenFDAClient(OpenFDAClient):
    BASE_URL = "https://api.fda.gov/drug/label.json"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cache: dict[str, OpenFDAResult] = {}

    async def lookup_drug_label(self, drug_name: str) -> OpenFDAResult:
        key = drug_name.lower().strip()
        if key in self._cache:
            return self._cache[key]
        query = f'openfda.brand_name:"{drug_name}" OR openfda.generic_name:"{drug_name}"'
        params: dict[str, Any] = {"search": query, "limit": 1}
        if self.settings.openfda_api_key:
            params["api_key"] = self.settings.openfda_api_key
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    result = OpenFDAResult(
                        drug_name=drug_name,
                        found=False,
                        retrieved_at=datetime.now(UTC),
                        error="No openFDA label result returned.",
                    )
                else:
                    item = results[0]
                    excerpts = item.get("warnings") or item.get("indications_and_usage") or []
                    text = (
                        excerpts[0][:500]
                        if excerpts
                        else "Label retrieved without warnings excerpt."
                    )
                    result = OpenFDAResult(
                        drug_name=drug_name,
                        found=True,
                        label_excerpt=text,
                        source_url=self.BASE_URL,
                        retrieved_at=datetime.now(UTC),
                    )
        except Exception as exc:  # noqa: BLE001
            result = OpenFDAResult(
                drug_name=drug_name,
                found=False,
                retrieved_at=datetime.now(UTC),
                error=f"openFDA request failed: {exc}",
            )
        self._cache[key] = result
        return result


def build_openfda_client(settings: Settings | None = None) -> OpenFDAClient:
    settings = settings or get_settings()
    if settings.effective_openfda_provider() == "fake":
        return FakeOpenFDAClient()
    return LiveOpenFDAClient(settings)
