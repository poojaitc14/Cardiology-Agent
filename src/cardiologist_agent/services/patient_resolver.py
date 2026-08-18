from __future__ import annotations

import re

from cardiologist_agent.domain.patient import Patient
from cardiologist_agent.repositories.patient import PatientRepository

_PATIENT_ID_PATTERN = re.compile(r"\bP(\d{3,5})\b", re.IGNORECASE)


async def resolve_patient_from_question(
    question: str,
    repo: PatientRepository,
) -> str | None:
    """Find a patient ID mentioned by code (P1001) or by name in free text."""
    id_match = _PATIENT_ID_PATTERN.search(question)
    if id_match:
        return f"P{id_match.group(1)}".upper()

    normalized = question.lower()
    ids = await repo.list_patient_ids()
    best_id: str | None = None
    best_len = 0

    for patient_id in ids:
        patient = await repo.get_patient(patient_id)
        if patient is None:
            continue
        matched = _match_patient_name(patient, normalized)
        if matched and len(matched) > best_len:
            best_id = patient.patient_id
            best_len = len(matched)

    return best_id


def _match_patient_name(patient: Patient, normalized_question: str) -> str | None:
    first = patient.first_name.lower()
    last = patient.last_name.lower()
    full = f"{first} {last}"
    if full in normalized_question:
        return full
    if last in normalized_question and len(last) > 3:
        return last
    record_label = f"record {patient.patient_id[1:]}".lower()
    if record_label in normalized_question:
        return record_label
    if patient.patient_id.lower() in normalized_question:
        return patient.patient_id.lower()
    return None
