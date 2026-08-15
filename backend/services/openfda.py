"""Read-only OpenFDA drug-label information service."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any, Protocol

import httpx

LOGGER = logging.getLogger(__name__)
DEFAULT_BASE_URL = "https://api.fda.gov/drug/label.json"
DEFAULT_TIMEOUT_SECONDS = 10.0


class HttpResponse(Protocol):
    def raise_for_status(self) -> None: ...
    def json(self) -> Any: ...


class HttpClient(Protocol):
    def get(self, url: str, *, params: dict[str, str | int], timeout: float) -> HttpResponse: ...


@dataclass(frozen=True)
class DrugLabel:
    """Selected factual label fields; no clinical interpretation is performed."""
    generic_names: tuple[str, ...]
    brand_names: tuple[str, ...]
    manufacturer_names: tuple[str, ...]
    purposes: tuple[str, ...]
    indications_and_usage: tuple[str, ...]
    warnings: tuple[str, ...]
    contraindications: tuple[str, ...]
    adverse_reactions: tuple[str, ...]
    dosage_and_administration: tuple[str, ...]


@dataclass(frozen=True)
class OpenFDAResult:
    requested_drug_name: str
    found: bool
    available: bool
    label: DrugLabel | None
    source: str | None
    user_message: str


class OpenFDAService:
    """Retrieve and normalize one drug-label result from OpenFDA."""
    def __init__(self, client: HttpClient | None = None, base_url: str | None = None, timeout_seconds: float | None = None, api_key: str | None = None) -> None:
        self._client = client or httpx.Client()
        self._base_url = base_url or os.environ.get("OPENFDA_BASE_URL", DEFAULT_BASE_URL)
        self._timeout_seconds = timeout_seconds if timeout_seconds is not None else self._environment_timeout()
        self._api_key = api_key or os.environ.get("OPENFDA_API_KEY", "")

    def search_drug_label(self, drug_name: str) -> OpenFDAResult:
        name = drug_name.strip()
        if not name:
            return OpenFDAResult("", False, True, None, None, "A drug name is required to search the available drug-label information.")
        try:
            params = {"search": self._search_expression(name), "limit": 1}
            if self._api_key:
                params["api_key"] = self._api_key
            response = self._client.get(self._base_url, params=params, timeout=self._timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            LOGGER.warning("OpenFDA request timed out", extra={"drug_name": name})
            return self._unavailable_result(name)
        except httpx.HTTPError:
            LOGGER.warning("OpenFDA request failed", extra={"drug_name": name}, exc_info=True)
            return self._unavailable_result(name)
        except (TypeError, ValueError):
            LOGGER.warning("OpenFDA returned an unreadable response", extra={"drug_name": name})
            return self._unavailable_result(name)
        label = self._extract_label(payload)
        if label is None:
            return OpenFDAResult(name, False, True, None, None, "No matching drug-label information was found in OpenFDA.")
        return OpenFDAResult(name, True, True, label, "OpenFDA", "Drug-label information was retrieved from OpenFDA.")

    @staticmethod
    def _search_expression(drug_name: str) -> str:
        escaped_name = drug_name.replace('"', r'\"')
        return f'openfda.generic_name:"{escaped_name}" OR openfda.brand_name:"{escaped_name}"'

    @staticmethod
    def _extract_label(payload: Any) -> DrugLabel | None:
        if not isinstance(payload, dict):
            return None
        results = payload.get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            return None
        record = results[0]
        openfda = record.get("openfda")
        fields = openfda if isinstance(openfda, dict) else {}
        return DrugLabel(_strings(fields.get("generic_name")), _strings(fields.get("brand_name")), _strings(fields.get("manufacturer_name")), _strings(record.get("purpose")), _strings(record.get("indications_and_usage")), _strings(record.get("warnings")), _strings(record.get("contraindications")), _strings(record.get("adverse_reactions")), _strings(record.get("dosage_and_administration")))

    @staticmethod
    def _environment_timeout() -> float:
        value = os.environ.get("OPENFDA_TIMEOUT_SECONDS")
        try:
            timeout = float(value) if value is not None else DEFAULT_TIMEOUT_SECONDS
        except ValueError:
            LOGGER.warning("Invalid OPENFDA_TIMEOUT_SECONDS; using default")
            return DEFAULT_TIMEOUT_SECONDS
        return timeout if timeout > 0 else DEFAULT_TIMEOUT_SECONDS

    @staticmethod
    def _unavailable_result(drug_name: str) -> OpenFDAResult:
        return OpenFDAResult(drug_name, False, False, None, None, "Drug-label information is temporarily unavailable from OpenFDA.")


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())
