from __future__ import annotations

import re
from typing import Literal

QueryMode = Literal["full_review", "patient_db", "medical_api", "hospital_rag"]

DEFAULT_SUMMARY_QUESTION = (
    "Please check the heart record, medicines, recent test results, "
    "and tell me clearly what should happen next."
)

_PATIENT_DB_PATTERNS = (
    r"\blast\b.*\b(test|lab|medic|appointment|visit)",
    r"\bwhen\b.*\b(test|lab|blood|ecg|echo|scan|result|medic|appointment)",
    r"\b(test|lab|blood|ecg|echo|scan|result).*\b(when|last|recent|latest)",
    r"\bwhat (medicine|medication|drug)",
    r"\bwhich (medicine|medication|drug)",
    r"\b(on|taking|takes)\b.*\b(medic|tablet|drug)",
    r"\ballerg",
    r"\bvital",
    r"\bblood pressure\b",
    r"\bheart rate\b",
    r"\bcondition",
    r"\bon file\b",
    r"\bin the record\b",
    r"\bpotassium\b",
    r"\bcreatinine\b",
    r"\bhad a test\b",
    r"\brecent test",
    r"\brecent (lab|blood)",
)

_MEDICAL_API_PATTERNS = (
    r"\bside effect",
    r"\binteraction",
    r"\bcontraindic",
    r"\bdos(e|ing)\b",
    r"\bsafe to take\b",
    r"\bwarning",
    r"\badverse",
    r"\bdrug label\b",
    r"\bopenfda\b",
    r"\bwhat (is|are)\b.*\b(risk|effect)",
    r"\btell me about\b.*\b(warfarin|statin|tablet|drug|medicine)",
)

_HOSPITAL_RAG_PATTERNS = (
    r"\bstaff\b",
    r"\bwho handles\b",
    r"\bwho should i\b",
    r"\bwho do i\b",
    r"\bwho is responsible\b",
    r"\bcontact\b",
    r"\bhow (do|can) i book\b",
    r"\bbooking\b",
    r"\breferral\b",
    r"\bnurse\b",
    r"\bpharmacist\b",
    r"\breception\b",
    r"\bcoordinator\b",
    r"\bbleep\b",
    r"\broute to\b",
    r"\bspeak to\b",
    r"\bext\.\b",
    r"\bhospital policy\b",
    r"\bclinic\b.*\b(contact|book)",
    r"\bcardiologist\b.*\b(handle|contact|see)",
)

_FULL_REVIEW_PATTERNS = (
    r"\bwhat should happen next\b",
    r"\bcheck the heart record\b",
    r"\bheart record\b.*\b(medic|test|result)",
    r"\bcare summary\b",
    r"\bwhat (should|needs to) happen\b",
    r"\breview (the )?patient\b",
    r"\bsummary of\b.*\b(care|treatment|next)",
)

_DRUG_NAMES = (
    "warfarin",
    "apixaban",
    "rivaroxaban",
    "amlodipine",
    "atorvastatin",
    "lisinopril",
    "bisoprolol",
    "ramipril",
    "losartan",
    "furosemide",
    "spironolactone",
    "digoxin",
    "metoprolol",
    "simvastatin",
    "clopidogrel",
    "aspirin",
)


def _score(question: str, patterns: tuple[str, ...]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, question))


def _normalize(question: str) -> str:
    return " ".join(question.lower().strip().split())


def is_default_summary_question(question: str) -> bool:
    return _normalize(question) == _normalize(DEFAULT_SUMMARY_QUESTION)


def classify_question(
    question: str,
    *,
    mode: Literal["auto", QueryMode] = "auto",
    has_patient_context: bool = False,
) -> QueryMode:
    if mode != "auto":
        return mode

    normalized = _normalize(question)
    patient_score = _score(normalized, _PATIENT_DB_PATTERNS)
    medical_score = _score(normalized, _MEDICAL_API_PATTERNS)
    hospital_score = _score(normalized, _HOSPITAL_RAG_PATTERNS)
    full_review_score = _score(normalized, _FULL_REVIEW_PATTERNS)

    if any(drug in normalized for drug in _DRUG_NAMES):
        medical_score += 2

    if is_default_summary_question(question):
        return "full_review"

    if medical_score >= 1 and medical_score >= hospital_score and medical_score >= patient_score:
        return "medical_api"

    if hospital_score >= 1 and hospital_score > patient_score:
        return "hospital_rag"

    if patient_score >= 1 and not full_review_score:
        return "patient_db"

    if full_review_score >= 1 or (has_patient_context and patient_score >= 1):
        return "full_review"

    if patient_score >= 1:
        return "patient_db"

    if has_patient_context:
        return "full_review"

    if medical_score >= 1:
        return "medical_api"

    if hospital_score >= 1:
        return "hospital_rag"

    return "full_review"


def extract_drug_names(question: str) -> list[str]:
    normalized = _normalize(question)
    found = [name.title() for name in _DRUG_NAMES if name in normalized]
    return list(dict.fromkeys(found))
