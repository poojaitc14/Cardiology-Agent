"""Read-only patient data contracts used by the patient database tool."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PatientRecordScope(str, Enum):
    """Allowed categories for an exact-patient query."""

    PROFILE = "profile"
    CONDITIONS = "conditions"
    MEDICATIONS = "medications"
    ALLERGIES = "allergies"
    LABS = "labs"
    VITALS = "vitals"
    CARDIOLOGY_TESTS = "cardiology_tests"
    FULL_REVIEW = "full_review"


SCOPE_PREFIXES: dict[PatientRecordScope, str] = {
    PatientRecordScope.CONDITIONS: "CONDITION#",
    PatientRecordScope.MEDICATIONS: "MEDICATION#",
    PatientRecordScope.ALLERGIES: "ALLERGY#",
    PatientRecordScope.LABS: "LAB#",
    PatientRecordScope.VITALS: "VITAL#",
    PatientRecordScope.CARDIOLOGY_TESTS: "CARDIOLOGY_TEST#",
}


@dataclass(frozen=True)
class PatientDataResult:
    """A grounded result from the patient database, never an interpretation."""

    patient_id: str
    scope: PatientRecordScope
    records: list[dict[str, Any]]
    source: str
    found: bool

    @property
    def no_record_message(self) -> str | None:
        if not self.found:
            return "No corresponding information was found in the available patient record."
        return None
