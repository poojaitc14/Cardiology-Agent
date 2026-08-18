from __future__ import annotations

import re
from datetime import datetime

from cardiologist_agent.domain.patient import Patient
from cardiologist_agent.domain.response import Citation


def _format_date(value: datetime | None) -> str:
    if value is None:
        return "date not recorded"
    return value.strftime("%d %B %Y")


def _latest_cardiology_test(patient: Patient) -> tuple[str | None, datetime | None]:
    tests = [
        (t.test_or_procedure_name, t.performed_date)
        for t in patient.cardiology_tests
        if t.performed_date is not None
    ]
    if not tests:
        named = [(t.test_or_procedure_name, None) for t in patient.cardiology_tests]
        if named:
            return named[0][0], None
        return None, None
    tests.sort(key=lambda item: item[1] or datetime.min, reverse=True)
    return tests[0]


def _latest_lab(patient: Patient, test_hint: str | None = None) -> tuple[str | None, datetime | None, str | None]:
    labs = patient.lab_results
    if test_hint:
        hint = test_hint.lower()
        labs = [lab for lab in labs if hint in lab.test_name.lower()]
    dated = [(lab.test_name, lab.test_date, lab.interpretation) for lab in labs if lab.test_date]
    if not dated:
        if labs:
            lab = labs[0]
            return lab.test_name, lab.test_date, lab.interpretation
        return None, None, None
    dated.sort(key=lambda item: item[1] or datetime.min, reverse=True)
    return dated[0]


def _active_medications(patient: Patient) -> list[str]:
    meds = []
    for med in patient.medications:
        if med.medication_status.lower() == "active":
            dose = f"{med.dose}{med.dose_unit or ''}".strip()
            parts = [med.drug_name]
            if dose:
                parts.append(dose)
            if med.frequency:
                parts.append(med.frequency.lower())
            meds.append(" ".join(parts))
    return meds


def _active_conditions(patient: Patient) -> list[str]:
    return [
        c.condition_name
        for c in patient.conditions
        if (c.condition_status or c.status or "").lower() in {"active", "valid", ""}
    ]


def _latest_vitals(patient: Patient) -> str | None:
    vitals = [v for v in patient.vital_signs if v.measured_at]
    if not vitals:
        return None
    vital = sorted(vitals, key=lambda item: item.measured_at or datetime.min, reverse=True)[0]
    parts = []
    if vital.systolic_bp and vital.diastolic_bp:
        parts.append(f"blood pressure {vital.systolic_bp}/{vital.diastolic_bp}")
    if vital.heart_rate:
        parts.append(f"heart rate {vital.heart_rate} beats per minute")
    if vital.oxygen_saturation:
        parts.append(f"oxygen level {vital.oxygen_saturation}%")
    if not parts:
        return None
    return f"The most recent vitals ({_format_date(vital.measured_at)}) show " + ", ".join(parts) + "."


def answer_patient_question(patient: Patient, question: str) -> tuple[str, list[Citation]]:
    normalized = question.lower()
    citations: list[Citation] = []

    if re.search(r"\b(test|ecg|echo|scan|procedure)\b", normalized):
        name, when = _latest_cardiology_test(patient)
        if name and when:
            citations.append(Citation(source_type="patient_record", patient_field="cardiology_tests"))
            return (
                f"The most recent heart test on file is {name}, done on {_format_date(when)}.",
                citations,
            )
        if name:
            citations.append(Citation(source_type="patient_record", patient_field="cardiology_tests"))
            return (
                f"There is a {name} on file, but no date was recorded for it.",
                citations,
            )
        citations.append(Citation(source_type="patient_record", patient_field="cardiology_tests"))
        return ("There are no heart tests recorded for this patient.", citations)

    if re.search(r"\b(lab|blood|potassium|creatinine|sodium|egfr|hba1c)\b", normalized):
        hint = None
        for token in ("potassium", "creatinine", "sodium", "egfr", "hba1c"):
            if token in normalized:
                hint = token
                break
        name, when, interpretation = _latest_lab(patient, hint)
        if name and when:
            citations.append(Citation(source_type="patient_record", patient_field="lab_results"))
            extra = f" The result was marked as {interpretation.lower()}." if interpretation else ""
            return (
                f"The latest {name} result on file is from {_format_date(when)}.{extra}",
                citations,
            )
        citations.append(Citation(source_type="patient_record", patient_field="lab_results"))
        return ("There are no blood test results recorded for this patient.", citations)

    if re.search(r"\b(medic|tablet|drug|prescri)\b", normalized):
        meds = _active_medications(patient)
        citations.append(Citation(source_type="patient_record", patient_field="medications"))
        if meds:
            joined = "; ".join(meds)
            return (f"The patient is currently recorded as taking: {joined}.", citations)
        return ("There are no active heart medicines on this patient's record.", citations)

    if "allerg" in normalized:
        allergies = [
            a.allergen for a in patient.allergies if (a.allergy_status or "active").lower() != "inactive"
        ]
        citations.append(Citation(source_type="patient_record", patient_field="allergies"))
        if allergies:
            return (f"Recorded allergies: {', '.join(allergies)}.", citations)
        return ("No allergies are recorded for this patient.", citations)

    if re.search(r"\b(condition|diagnos)\b", normalized):
        conditions = _active_conditions(patient)
        citations.append(Citation(source_type="patient_record", patient_field="conditions"))
        if conditions:
            return (f"Active heart-related conditions on file: {', '.join(conditions)}.", citations)
        return ("No active conditions are recorded.", citations)

    if re.search(r"\b(vital|blood pressure|heart rate|oxygen)\b", normalized):
        vitals_text = _latest_vitals(patient)
        citations.append(Citation(source_type="patient_record", patient_field="vital_signs"))
        if vitals_text:
            return (vitals_text, citations)
        return ("No recent vital signs are recorded.", citations)

    test_name, test_when = _latest_cardiology_test(patient)
    meds = _active_medications(patient)
    conditions = _active_conditions(patient)
    parts = ["Here is what the patient record shows:"]
    if conditions:
        parts.append(f"Conditions: {', '.join(conditions)}.")
    if meds:
        parts.append(f"Active medicines: {'; '.join(meds)}.")
    if test_name and test_when:
        parts.append(f"Latest heart test: {test_name} on {_format_date(test_when)}.")
    elif test_name:
        parts.append(f"Latest heart test on file: {test_name} (date not recorded).")
    else:
        parts.append("No heart tests are on file.")
    citations.append(Citation(source_type="patient_record", patient_field="patient_snapshot"))
    return (" ".join(parts), citations)
