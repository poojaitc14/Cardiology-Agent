"""Read-only patient, RAG, and medication-information tool interfaces."""

import os
from datetime import UTC, datetime

from langfuse import observe

from app.database import get_patient_timeline
from app.medication_api import lookup_openfda_label
from app.opensearch_rag import search_approved_documents


def _record(source_id: str, fact: str, observed_at: str) -> dict:
    return {
        "fact": fact,
        "source": {
            "source_id": source_id,
            "source_type": "patient_record",
            "observed_at": observed_at,
        },
    }


@observe(name="patient_database_tool", as_type="tool", capture_input=False, capture_output=False)
def get_patient_clinical_context(patient_id: str, requesting_user_id: str) -> dict:
    """Return a minimum-necessary context from synthetic data or DynamoDB."""
    # Demo authorization only. Production must validate an SSO care relationship.
    if not requesting_user_id.startswith("clinician-"):
        raise PermissionError("The requester is not authorized for this patient review.")
    if os.getenv("PATIENT_DATA_MODE", "synthetic").lower() == "dynamodb":
        return _dynamodb_context(patient_id)
    if patient_id != "P1005":
        return {"history": [], "medications": [], "allergies": [], "labs": [], "limitations": ["No synthetic patient record found."]}

    return {
        "history": [
            _record("HISTORY#P1005#001", "Recorded history: hypertension.", "2026-07-01T09:00:00Z"),
            _record("HISTORY#P1005#002", "Recorded history: coronary heart disease.", "2026-07-01T09:00:00Z"),
        ],
        "medications": [
            _record("MEDICATION#P1005#001", "Active medication record: example antihypertensive; dose requires source-record verification.", "2026-08-01T09:00:00Z"),
        ],
        "allergies": [
            _record("ALLERGY#P1005#001", "Recorded allergy: example substance; recorded reaction: verify in source record.", "2026-01-10T09:00:00Z"),
        ],
        "labs": [
            _record("LAB#P1005#001", "Recent laboratory result: synthetic example; value and units must be verified in source record.", "2026-08-10T09:00:00Z"),
        ],
        "limitations": ["Synthetic development data only; not for clinical use."],
    }


def _source(item: dict) -> dict:
    return {
        "source_id": item["record_id"],
        "source_type": "patient_record",
        "observed_at": item.get("updated_at") or item.get("created_at"),
    }


def _fact(item: dict, text: str, **extra: str) -> dict:
    return {"fact": text, "source": _source(item), **extra}


def _dynamodb_context(patient_id: str) -> dict:
    try:
        items = get_patient_timeline(patient_id)
    except RuntimeError:
        return {"history": [], "medications": [], "allergies": [], "labs": [], "limitations": ["DynamoDB patient data is unavailable; no patient facts were retrieved."]}
    if not items:
        return {"history": [], "medications": [], "allergies": [], "labs": [], "limitations": ["No patient timeline items were found in DynamoDB."]}

    history, medications, allergies, labs = [], [], [], []
    for item in items:
        record_type = item.get("record_type")
        if record_type == "CONDITION":
            history.append(_fact(item, "Recorded condition: {name}; category: {category}; status: {status}; severity: {severity}.".format(
                name=item.get("condition_name", "not recorded"), category=item.get("condition_category", "not recorded"),
                status=item.get("condition_status", "not recorded"), severity=item.get("severity", "not recorded"))))
        elif record_type == "MEDICATION":
            medications.append(_fact(item, "Recorded medication: {name}; status: {status}; indication: {indication}; prescriber: {prescriber}.".format(
                name=item.get("medication_name", "not recorded"), status=item.get("medication_status", "not recorded"),
                indication=item.get("indication", "not recorded"), prescriber=item.get("prescriber", "not recorded")),
                medication_name=item.get("medication_name", "")))
        elif record_type == "ALLERGY":
            allergies.append(_fact(item, "Recorded {kind}: {name}.".format(
                kind=item.get("allergy_type", "allergy/intolerance"), name=item.get("allergy_name", "not recorded"))))
        elif record_type == "LAB":
            labs.append(_fact(item, "Recorded laboratory result: {name} = {value} {unit}; interpretation: {interpretation}.".format(
                name=item.get("test_name", "not recorded"), value=item.get("test_value", "not recorded"),
                unit=item.get("test_unit", ""), interpretation=item.get("interpretation", "not recorded"))))

    return {
        "history": history,
        "medications": medications,
        "allergies": allergies,
        "labs": labs,
        "limitations": ["DynamoDB development data; clinician must verify source records."],
    }


@observe(name="rag_knowledge_tool", as_type="tool", capture_input=False, capture_output=False)
def search_approved_clinical_knowledge(query: str) -> list[dict]:
    """Retrieve only approved, citation-linked policy and guideline content."""
    try:
        return search_approved_documents(query)
    except RuntimeError:
        # The caller reports absent knowledge rather than fabricating policy content.
        return []


@observe(name="medication_information_tool", as_type="tool", capture_input=False, capture_output=False)
def get_medication_information(medications: list[dict]) -> list[dict]:
    """Look up compact OpenFDA label metadata for up to five active medicines."""
    results: list[dict] = []
    for medication in medications[:5]:
        medicine_name = medication.get("medication_name")
        if not medicine_name:
            continue
        result = lookup_openfda_label(medicine_name)
        if result["status"] == "disabled":
            continue
        if result["status"] == "not_found":
            results.append({"fact": f"OpenFDA: no drug-label result found for recorded medicine '{medicine_name}'.", "source": {"source_id": "openFDA:not-found", "source_type": "medication_api", "observed_at": datetime.now(UTC).isoformat()}})
            continue
        if result["status"] == "unavailable":
            results.append({"fact": f"OpenFDA lookup is unavailable for recorded medicine '{medicine_name}'.", "source": {"source_id": "openFDA:unavailable", "source_type": "medication_api", "observed_at": datetime.now(UTC).isoformat()}})
            continue
        flags = []
        if result["has_boxed_warning"]:
            flags.append("boxed-warning")
        if result["has_contraindications"]:
            flags.append("contraindications")
        if result["has_drug_interactions"]:
            flags.append("drug-interactions")
        label_name = result["brand_name"] or result["generic_name"]
        summary = f"OpenFDA label match: {label_name}; label effective date: {result['effective_time'] or 'not provided'}"
        if flags:
            summary += "; label sections present: " + ", ".join(flags) + ". Review the official label."
        results.append({"fact": summary, "source": {"source_id": result["source_id"], "source_type": "medication_api", "observed_at": result["retrieved_at"], "document_version": result["effective_time"]}})
    return results
