"""Bounded OpenFDA drug-label adapter for development and evaluation."""

import os
import re
from datetime import UTC, datetime

import requests


def _first(value: object) -> str | None:
    return value[0] if isinstance(value, list) and value else None


def lookup_openfda_label(medicine_name: str) -> dict:
    """Return compact, source-linked label metadata; never dosing advice."""
    if os.getenv("MEDICATION_API_ENABLED", "false").lower() != "true":
        return {"status": "disabled"}

    safe_name = re.sub(r"[^A-Za-z0-9 -]", "", medicine_name).strip()
    if not safe_name:
        return {"status": "not_found"}
    params = {
        "search": f'openfda.generic_name:"{safe_name}" + openfda.brand_name:"{safe_name}"',
        "limit": 1,
    }
    api_key = os.getenv("MEDICATION_API_KEY")
    if api_key:
        params["api_key"] = api_key
    base_url = os.getenv("MEDICATION_API_BASE_URL", "https://api.fda.gov").rstrip("/")
    try:
        response = requests.get(f"{base_url}/drug/label.json", params=params, timeout=8)
        if response.status_code == 404:
            return {"status": "not_found"}
        response.raise_for_status()
        label = response.json()["results"][0]
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return {"status": "unavailable"}

    identifiers = label.get("openfda", {})
    spl_id = _first(identifiers.get("spl_id")) or "unidentified-label"
    return {
        "status": "found",
        "source_id": f"openFDA:drug-label:{spl_id}",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "effective_time": label.get("effective_time"),
        "generic_name": _first(identifiers.get("generic_name")) or safe_name,
        "brand_name": _first(identifiers.get("brand_name")),
        "has_boxed_warning": bool(label.get("boxed_warning")),
        "has_contraindications": bool(label.get("contraindications")),
        "has_drug_interactions": bool(label.get("drug_interactions")),
    }
