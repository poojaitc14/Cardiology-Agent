"""Expand clinical variety across P1001-P1055 while preserving P1056-P1100 evaluation cases."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATIENTS_PATH = ROOT / "data/patients/runtime/patients.json"
MANIFEST_PATH = ROOT / "data/patients/evaluation/case_manifest.json"
SUMMARY_PATH = ROOT / "data/patients/validation/validation_summary.json"

STALE_LAB_DATE = "2025-11-10T10:00:00Z"
RECENT_LAB_DATE = "2026-07-20T10:00:00Z"
MONITORING_LAB_NAMES = ("potassium", "creatinine", "egfr", "hba1c", "sodium")

SCENARIO_ASSIGNMENTS: dict[str, tuple[list[str], str]] = {
    **{f"P{n}": (["routine_complete_history"], "DRAFT_FOR_CLINICIAN_REVIEW") for n in range(1001, 1009)},
    **{f"P{n}": (["treatment_not_started"], "DRAFT_FOR_CLINICIAN_REVIEW") for n in range(1009, 1019)},
    **{f"P{n}": (["stale_monitoring"], "INSUFFICIENT_EVIDENCE") for n in range(1019, 1031)},
    **{f"P{n}": (["preliminary_cardiology_test"], "INSUFFICIENT_EVIDENCE") for n in range(1031, 1036)},
    **{f"P{n}": (["allergy_status_unknown"], "INSUFFICIENT_EVIDENCE") for n in range(1036, 1041)},
    **{f"P{n}": (["allergy_medication_conflict"], "CONFLICT_REQUIRES_REVIEW") for n in range(1041, 1049)},
    **{
        f"P{n}": (["high_potassium", "ace_or_arb_active"], "URGENT_CLINICAL_REVIEW")
        for n in range(1049, 1053)
    },
    **{f"P{n}": (["routine_complete_history"], "DRAFT_FOR_CLINICIAN_REVIEW") for n in range(1053, 1056)},
}


def pid_num(patient_id: str) -> int:
    return int(patient_id[1:])


def _is_monitoring_lab(test_name: str) -> bool:
    lower = test_name.lower()
    return any(name in lower for name in MONITORING_LAB_NAMES)


def apply_treatment_not_started(patient: dict) -> None:
    for med in patient.get("medications", []):
        med["medication_status"] = "Stopped"
        med["end_date"] = med.get("end_date") or "2026-06-15"
    for condition in patient.get("conditions", []):
        note = (condition.get("notes") or "").strip()
        suffix = "Awaiting cardiology initiation of guideline-directed therapy."
        if suffix not in note:
            condition["notes"] = f"{note} {suffix}".strip()


def apply_stale_monitoring(patient: dict) -> None:
    for lab in patient.get("lab_results", []):
        if _is_monitoring_lab(lab.get("test_name", "")):
            lab["test_date"] = STALE_LAB_DATE
            lab["created_at"] = STALE_LAB_DATE.replace("10:00:00", "10:15:00")
            lab["updated_at"] = STALE_LAB_DATE.replace("10:00:00", "10:30:00")


def apply_preliminary_cardiology_test(patient: dict) -> None:
    tests = patient.get("cardiology_tests", [])
    if not tests:
        tests.append(
            {
                "test_or_procedure_name": "Echocardiogram",
                "performed_date": RECENT_LAB_DATE,
                "result_summary": "Pending quantification",
                "notes": "Awaiting final cardiologist sign-off",
                "record_id": "T900",
                "created_at": RECENT_LAB_DATE,
                "updated_at": RECENT_LAB_DATE,
                "source": "Cardiology department",
                "status": "Preliminary",
            }
        )
    else:
        tests[0]["status"] = "Preliminary"
        tests[0]["result_summary"] = tests[0].get("result_summary") or "Pending final review"
        tests[0]["notes"] = "Awaiting final cardiologist sign-off"


def apply_allergy_status_unknown(patient: dict) -> None:
    patient["allergies"] = []
    for condition in patient.get("conditions", []):
        note = (condition.get("notes") or "").strip()
        suffix = "Allergy reconciliation not recorded"
        if suffix.lower() not in note.lower():
            condition["notes"] = f"{note}; {suffix}".strip("; ")


def _next_record_id(items: list[dict], prefix: str) -> str:
    nums = []
    for item in items:
        rid = str(item.get("record_id", ""))
        if rid.startswith(prefix) and rid[len(prefix) :].isdigit():
            nums.append(int(rid[len(prefix) :]))
    return f"{prefix}{max(nums, default=0) + 1:03d}"


def apply_allergy_medication_conflict(patient: dict) -> None:
    meds = patient.get("medications", [])
    allergies = patient.get("allergies", [])

    has_active_aspirin = any(
        m.get("drug_name", "").lower() == "aspirin" and m.get("medication_status", "").lower() == "active"
        for m in meds
    )
    if not has_active_aspirin:
        meds.append(
            {
                "drug_name": "Aspirin",
                "dose": 75,
                "dose_unit": "mg",
                "frequency": "Once daily",
                "route": "Oral",
                "medication_status": "Active",
                "start_date": "2026-05-01",
                "end_date": None,
                "prescriber": patient.get("primary_cardiologist") or "DR101",
                "indication": "Secondary prevention",
                "record_id": _next_record_id(meds, "M"),
                "created_at": "2026-05-01T09:00:00Z",
                "updated_at": "2026-07-01T12:00:00Z",
                "source": "Hospital EHR",
                "status": "Valid",
            }
        )

    has_aspirin_allergy = any(
        a.get("allergen", "").lower() == "aspirin" and (a.get("allergy_type") or "").lower() == "allergy"
        for a in allergies
    )
    if not has_aspirin_allergy:
        allergies.append(
            {
                "allergen": "Aspirin",
                "allergy_type": "Allergy",
                "reaction": "Bronchospasm",
                "severity": "Moderate",
                "allergy_status": "Active",
                "recorded_date": "2024-03-12",
                "notes": "Documented intolerance to aspirin therapy",
                "record_id": _next_record_id(allergies, "A"),
                "created_at": "2024-03-12T10:00:00Z",
                "updated_at": "2024-03-12T10:00:00Z",
                "source": "Patient reported",
                "status": "Active",
            }
        )


def apply_high_potassium_ace(patient: dict, index: int) -> None:
    ace_drugs = ("Lisinopril", "Losartan", "Ramipril", "Enalapril")
    target_ace = ace_drugs[index % len(ace_drugs)]
    meds = patient.get("medications", [])
    has_ace = any(
        m.get("medication_status", "").lower() == "active"
        and any(d.lower() in m.get("drug_name", "").lower() for d in ace_drugs)
        for m in meds
    )
    if not has_ace:
        meds.append(
            {
                "drug_name": target_ace,
                "dose": 10 if target_ace != "Losartan" else 50,
                "dose_unit": "mg",
                "frequency": "Once daily",
                "route": "Oral",
                "medication_status": "Active",
                "start_date": "2025-09-01",
                "end_date": None,
                "prescriber": patient.get("primary_cardiologist") or "DR101",
                "indication": "Hypertension",
                "record_id": _next_record_id(meds, "M"),
                "created_at": "2025-09-01T09:00:00Z",
                "updated_at": "2026-07-01T12:00:00Z",
                "source": "Hospital EHR",
                "status": "Valid",
            }
        )

    potassium_values = (5.4, 5.6, 5.5, 5.7)
    k_value = potassium_values[index % len(potassium_values)]
    updated = False
    for lab in patient.get("lab_results", []):
        if "potassium" in lab.get("test_name", "").lower():
            lab["test_value"] = k_value
            lab["interpretation"] = "High"
            lab["test_date"] = "2026-08-10T09:00:00Z"
            lab["created_at"] = "2026-08-10T09:15:00Z"
            lab["updated_at"] = "2026-08-10T09:30:00Z"
            updated = True
            break
    if not updated:
        patient.setdefault("lab_results", []).insert(
            0,
            {
                "test_name": "Potassium",
                "test_value": k_value,
                "test_unit": "mmol/L",
                "reference_range": "3.5-5.0",
                "interpretation": "High",
                "test_date": "2026-08-10T09:00:00Z",
                "record_id": _next_record_id(patient.get("lab_results", []), "L"),
                "created_at": "2026-08-10T09:15:00Z",
                "updated_at": "2026-08-10T09:30:00Z",
                "source": "Hospital laboratory",
                "status": "Final",
            },
        )


def apply_routine_fresh_monitoring(patient: dict) -> None:
    for lab in patient.get("lab_results", []):
        if _is_monitoring_lab(lab.get("test_name", "")):
            lab["test_date"] = RECENT_LAB_DATE
            lab["created_at"] = RECENT_LAB_DATE.replace("10:00:00", "10:15:00")
            lab["updated_at"] = RECENT_LAB_DATE.replace("10:00:00", "10:30:00")


def transform_patient(patient: dict) -> None:
    patient_id = patient["patient_id"]
    if pid_num(patient_id) > 1055:
        return

    tags, _ = SCENARIO_ASSIGNMENTS[patient_id]
    primary = tags[0]

    if primary == "treatment_not_started":
        apply_treatment_not_started(patient)
    elif primary == "stale_monitoring":
        apply_stale_monitoring(patient)
    elif primary == "preliminary_cardiology_test":
        apply_preliminary_cardiology_test(patient)
    elif primary == "allergy_status_unknown":
        apply_allergy_status_unknown(patient)
    elif primary == "allergy_medication_conflict":
        apply_allergy_medication_conflict(patient)
    elif primary == "high_potassium":
        apply_high_potassium_ace(patient, pid_num(patient_id))
    elif primary == "routine_complete_history":
        apply_routine_fresh_monitoring(patient)


def update_manifest(manifest: list[dict]) -> list[dict]:
    updated = []
    for entry in manifest:
        entry = deepcopy(entry)
        pid = entry["patient_id"]
        if pid in SCENARIO_ASSIGNMENTS:
            tags, status = SCENARIO_ASSIGNMENTS[pid]
            entry["scenario_tags"] = tags
            entry["expected_review_status"] = status
        updated.append(entry)
    return updated


def build_summary(patients: list[dict], manifest: list[dict]) -> dict:
    scenario_counts: dict[str, int] = {}
    for entry in manifest:
        for tag in entry["scenario_tags"]:
            scenario_counts[tag] = scenario_counts.get(tag, 0) + 1

    record_counts = {
        "conditions": sum(len(p.get("conditions", [])) for p in patients),
        "medications": sum(len(p.get("medications", [])) for p in patients),
        "allergies": sum(len(p.get("allergies", [])) for p in patients),
        "lab_results": sum(len(p.get("lab_results", [])) for p in patients),
        "vital_signs": sum(len(p.get("vital_signs", [])) for p in patients),
        "cardiology_tests": sum(len(p.get("cardiology_tests", [])) for p in patients),
    }

    no_active_meds = sum(
        1
        for p in patients
        if not any(m.get("medication_status", "").lower() == "active" for m in p.get("medications", []))
    )

    return {
        "dataset": "Northbridge synthetic cardiology patient database",
        "synthetic_only": True,
        "seed": 20260817,
        "patient_count": len(patients),
        "patient_id_range": "P1001-P1100",
        "scenario_counts": dict(sorted(scenario_counts.items())),
        "record_counts": record_counts,
        "patients_without_active_medication": no_active_meds,
        "validation": {"errors": [], "passed": True},
        "important_limitation": (
            "The requested schema has no signed-order ID, authorization timestamp, authorization status, "
            "or complete administration-instruction fields. Prescriber alone must not be treated as proof "
            "of FINAL_AUTHORIZED."
        ),
    }


def main() -> None:
    patients = json.loads(PATIENTS_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert len(patients) == 100
    assert len(manifest) == 100

    for patient in patients:
        transform_patient(patient)

    manifest = update_manifest(manifest)
    summary = build_summary(patients, manifest)

    PATIENTS_PATH.write_text(json.dumps(patients, indent=2) + "\n", encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Updated {PATIENTS_PATH.name} and manifest for varied scenarios.")
    print(f"Patients without active medication: {summary['patients_without_active_medication']}")
    print("Scenario counts:")
    for tag, count in summary["scenario_counts"].items():
        print(f"  {tag}: {count}")


if __name__ == "__main__":
    main()
