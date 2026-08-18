"""Add 30 fictional patients with mild, non-serious heart conditions (P1101–P1130)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATIENTS_PATH = ROOT / "data/patients/runtime/patients.json"
MANIFEST_PATH = ROOT / "data/patients/evaluation/case_manifest.json"
SUMMARY_PATH = ROOT / "data/patients/validation/validation_summary.json"

MILD_CONDITIONS = [
    ("Mild hypertension", "Blood pressure slightly above target at last check"),
    ("Borderline high cholesterol", "Lifestyle advice given; no urgent treatment needed"),
    ("Benign palpitations", "Occasional extra heartbeats; ECG otherwise normal"),
    ("Innocent heart murmur", "Soft murmur noted; no significant valve disease"),
    ("Mild mitral regurgitation", "Small leak on echo; watch and review annually"),
    ("Post-viral pericarditis (resolved)", "Previous inflammation settled; monitoring only"),
    ("Family history of heart disease", "Screening visit; no active disease identified"),
    ("Mild left ventricular hypertrophy", "Thickening related to blood pressure; moderate severity"),
    ("Occasional ectopic beats", "Extra beats on Holter; patient well"),
    ("Stable angina (mild)", "Chest tightness on exertion only; symptoms infrequent"),
]

FIRST_NAMES = [
    "Alice", "Ben", "Chloe", "David", "Emma", "Finn", "Grace", "Hassan",
    "Isla", "Jack", "Keira", "Liam", "Maya", "Noah", "Olivia", "Priya",
    "Quinn", "Rosa", "Sam", "Tara", "Uma", "Vik", "Wendy", "Xavier",
    "Yasmin", "Zoe", "Aaron", "Bella", "Callum", "Dina",
]

LAST_NAMES = [
    "Baker", "Clark", "Dean", "Foster", "Gray", "Hayes", "Ingram", "Jones",
    "King", "Lewis", "Moore", "Nelson", "Owen", "Price", "Quinn", "Reed",
    "Shaw", "Turner", "Underwood", "Vaughn", "Walker", "Young", "Brooks",
    "Carter", "Dixon", "Ellis", "Fraser", "Green", "Hughes", "Irving",
]

CARDIOLOGISTS = ["DR101", "DR102", "DR103", "DR104"]


def _template() -> dict:
    patients = json.loads(PATIENTS_PATH.read_text(encoding="utf-8"))
    return copy.deepcopy(patients[0])


def build_mild_patient(index: int) -> dict:
    pid = f"P{1101 + index}"
    cond_name, cond_note = MILD_CONDITIONS[index % len(MILD_CONDITIONS)]
    patient = _template()
    patient["patient_id"] = pid
    patient["first_name"] = FIRST_NAMES[index]
    patient["last_name"] = LAST_NAMES[index]
    patient["date_of_birth"] = f"{1965 + (index % 25):02d}-{(index % 12) + 1:02d}-{(index % 27) + 1:02d}"
    patient["gender"] = ["Female", "Male", "Non-binary"][index % 3]
    patient["smoking_status"] = ["Never smoked", "Former smoker", "Never smoked"][index % 3]
    patient["family_history_cardiovascular_disease"] = index % 4 == 0
    patient["primary_cardiologist"] = CARDIOLOGISTS[index % len(CARDIOLOGISTS)]
    patient["conditions"] = [
        {
            "condition_name": cond_name,
            "condition_category": "Cardiovascular",
            "diagnosis_date": "2023-06-15",
            "condition_status": "Active",
            "severity": "Mild",
            "notes": cond_note,
            "record_id": "C001",
            "created_at": "2023-06-15T10:00:00Z",
            "updated_at": "2026-07-01T12:00:00Z",
            "source": "Hospital EHR",
            "status": "Active",
        }
    ]

    if index % 3 == 0:
        patient["medications"] = []
    elif index % 3 == 1:
        patient["medications"] = [
            {
                "drug_name": "Amlodipine",
                "dose": 5,
                "dose_unit": "mg",
                "frequency": "Once daily",
                "route": "Oral",
                "medication_status": "Active",
                "start_date": "2025-01-10",
                "end_date": None,
                "prescriber": patient["primary_cardiologist"],
                "indication": cond_name,
                "record_id": "M001",
                "created_at": "2025-01-10T09:00:00Z",
                "updated_at": "2026-06-01T12:00:00Z",
                "source": "Hospital EHR",
                "status": "Valid",
            }
        ]
    else:
        patient["medications"] = [
            {
                "drug_name": "Atorvastatin",
                "dose": 20,
                "dose_unit": "mg",
                "frequency": "Once daily",
                "route": "Oral",
                "medication_status": "Active",
                "start_date": "2024-09-01",
                "end_date": None,
                "prescriber": patient["primary_cardiologist"],
                "indication": "Cholesterol management",
                "record_id": "M001",
                "created_at": "2024-09-01T09:00:00Z",
                "updated_at": "2026-06-01T12:00:00Z",
                "source": "Hospital EHR",
                "status": "Valid",
            }
        ]

    patient["allergies"] = []
    for lab in patient.get("lab_results", []):
        if any(
            t in lab.get("test_name", "").lower()
            for t in ("potassium", "creatinine", "egfr", "sodium", "cholesterol")
        ):
            lab["test_date"] = "2026-07-15T10:00:00Z"
            lab["interpretation"] = "Normal"
    for test in patient.get("cardiology_tests", []):
        test["status"] = "Final"
        test["result_summary"] = "No significant abnormality — mild findings only"
    patient["status"] = "Active"
    patient["updated_at"] = "2026-08-17T12:00:00Z"
    return patient


def main() -> None:
    patients = json.loads(PATIENTS_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    existing_ids = {p["patient_id"] for p in patients}
    new_patients = [build_mild_patient(i) for i in range(30)]
    for p in new_patients:
        if p["patient_id"] not in existing_ids:
            patients.append(p)

    patients.sort(key=lambda p: int(p["patient_id"][1:]))

    manifest_by_id = {m["patient_id"]: m for m in manifest}
    for p in new_patients:
        manifest_by_id[p["patient_id"]] = {
            "patient_id": p["patient_id"],
            "scenario_tags": ["mild_cardiac_condition"],
            "expected_review_status": "DRAFT_FOR_CLINICIAN_REVIEW",
            "notes": "Mild non-urgent cardiac condition for training demos.",
        }
    manifest = [manifest_by_id[f"P{n}"] for n in range(1001, 1101 + len(new_patients))]

    PATIENTS_PATH.write_text(json.dumps(patients, indent=2) + "\n", encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    summary["patient_count"] = len(patients)
    summary["patient_id_range"] = f"P1001-P{1000 + len(patients)}"
    summary["scenario_counts"]["mild_cardiac_condition"] = 30
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Added/updated 30 mild patients. Total patients: {len(patients)}")


if __name__ == "__main__":
    main()
