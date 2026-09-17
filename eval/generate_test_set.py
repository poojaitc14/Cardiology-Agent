"""Builds a 100-question evaluation set for the Cardiologist agent's /query endpoint.

Ground truth is derived directly from `database.synthetic_data.generate_patients()`
with the same (seed, count) used to seed the local DynamoDB table, so expected facts
are guaranteed correct for whatever patients are actually loaded -- no hand-typed
clinical data. Each case records what a *correct* response should do (which tools
fire, which citations should appear, which real facts should be conveyed) so the
evaluator can score actual agent behavior against it automatically.

Run: python -m eval.generate_test_set
"""
from __future__ import annotations

import json
from pathlib import Path

from database.synthetic_data import generate_patients

SEED = 20260814
PATIENT_IDS = [
    "P1003", "P1005", "P1012", "P1017", "P1021", "P1028", "P1033", "P1040",
    "P1045", "P1050", "P1058", "P1063", "P1070", "P1077", "P1089",
]

RAG_DOCUMENTS = [
    ("ESC Guidelines for Acute Coronary Syndromes", "guideline", "acute coronary syndromes"),
    ("ESC Guidelines for Chronic Coronary Syndromes", "guideline", "chronic coronary syndromes"),
    ("ESC Guidelines for Heart Failure", "guideline", "heart failure"),
    ("ESC Guidelines for Atrial Fibrillation", "guideline", "atrial fibrillation"),
    ("ESC Guidelines for Hypertension", "guideline", "hypertension"),
    ("ESC Guidelines for Dyslipidaemias", "guideline", "dyslipidaemias"),
    ("ESC Guidelines for Cardiomyopathies", "guideline", "cardiomyopathies"),
    ("ESC Guidelines for Ventricular Arrhythmias & Sudden Cardiac Death", "guideline", "ventricular arrhythmias and sudden cardiac death"),
    ("ESC Guidelines for Valvular Heart Disease", "guideline", "valvular heart disease"),
    ("ESC Guidelines for Pericardial Diseases", "guideline", "pericardial diseases"),
    ("ESC Guidelines for Pulmonary Hypertension", "guideline", "pulmonary hypertension"),
    ("ESC Guidelines for Endocarditis", "guideline", "endocarditis"),
    ("ESC Guidelines for Cardiovascular Disease Prevention", "guideline", "cardiovascular disease prevention"),
    ("Anticoagulation / Antiplatelet Therapy Protocol", "protocol", "anticoagulation and antiplatelet therapy"),
    ("Hospital Cardiology Medication & Monitoring Policy", "hospital policy", "cardiology medication and monitoring"),
]

KNOWN_DRUGS = ["Warfarin", "Atorvastatin", "Lisinopril", "Metoprolol"]


def ground_truth(patients: list[dict]) -> dict[str, dict]:
    by_pid: dict[str, dict[str, dict]] = {}
    for rec in patients:
        by_pid.setdefault(rec["patient_id"], {})[rec["SK"].split("#")[0]] = rec
    out = {}
    for pid in PATIENT_IDS:
        r = by_pid[pid]
        out[pid] = {
            "name": f"{r['PROFILE']['first_name']} {r['PROFILE']['last_name']}",
            "gender": r["PROFILE"]["gender"],
            "dob": r["PROFILE"]["date_of_birth"],
            "smoking": r["PROFILE"]["smoking_status"],
            "condition": r["CONDITION"]["condition_name"],
            "medication": r["MEDICATION"]["drug_name"],
            "allergen": r["ALLERGY"]["allergen"],
            "lab_test": r["LAB"]["test_name"],
            "systolic": str(r["VITAL"]["systolic_bp"]),
            "cardio_test": r["CARDIOLOGY_TEST"]["test_or_procedure_name"],
        }
    return out


def build_cases(gt: dict[str, dict]) -> list[dict]:
    cases: list[dict] = []
    cid = 0

    def add(category, patient_id, question, expected_tools, citation_substrings=None, fact_substrings=None, expect_error=False, notes=""):
        nonlocal cid
        cid += 1
        cases.append({
            "id": f"Q{cid:03d}",
            "category": category,
            "patient_id": patient_id,
            "question": question,
            "expected_tools": expected_tools,
            "expected_citation_substrings": citation_substrings or [],
            "expected_fact_substrings": fact_substrings or [],
            "expect_error": expect_error,
            "notes": notes,
        })

    # A. Patient demographic/profile (10) -- no scope keyword -> FULL_REVIEW
    demo_plan = [
        ("P1003", "What is patient P1003's date of birth?", gt["P1003"]["dob"]),
        ("P1005", "What is the gender recorded for patient P1005?", gt["P1005"]["gender"]),
        ("P1012", "What is patient P1012's smoking status?", gt["P1012"]["smoking"]),
        ("P1017", "What is patient P1017's date of birth?", gt["P1017"]["dob"]),
        ("P1021", "What is the gender recorded for patient P1021?", gt["P1021"]["gender"]),
        ("P1028", "What is patient P1028's smoking status?", gt["P1028"]["smoking"]),
        ("P1033", "What is patient P1033's date of birth?", gt["P1033"]["dob"]),
        ("P1040", "What is the gender recorded for patient P1040?", gt["P1040"]["gender"]),
        ("P1045", "What is this patient's full name?", gt["P1045"]["name"]),
        ("P1050", "What is patient P1050's smoking status?", gt["P1050"]["smoking"]),
    ]
    for pid, q, fact in demo_plan:
        add("A_demographic", pid, q, ["patient_database_tool"], [f"Patient {pid}"], [fact])

    # B. Medications (10) -- generic wording, must trigger MEDICATIONS scope only
    for pid in ["P1003", "P1005", "P1012", "P1017", "P1021", "P1028", "P1033", "P1040", "P1045", "P1050"]:
        add("B_medication", pid, "What medications is this patient currently taking?",
            ["patient_database_tool"], [f"Patient {pid}"], [gt[pid]["medication"]])

    # C. Allergies (10)
    for pid in ["P1058", "P1063", "P1070", "P1077", "P1089", "P1003", "P1005", "P1012", "P1017", "P1021"]:
        add("C_allergy", pid, "Does this patient have any known drug allergies?",
            ["patient_database_tool"], [f"Patient {pid}"], [gt[pid]["allergen"]])

    # D. Labs (8)
    for pid in ["P1003", "P1005", "P1012", "P1017", "P1021", "P1028", "P1033", "P1040"]:
        add("D_lab", pid, "What lab results are on file for this patient?",
            ["patient_database_tool"], [f"Patient {pid}"], [gt[pid]["lab_test"]])

    # E. Vitals (8)
    for pid in ["P1045", "P1050", "P1058", "P1063", "P1070", "P1077", "P1089", "P1003"]:
        add("E_vital", pid, "What are this patient's latest vital signs?",
            ["patient_database_tool"], [f"Patient {pid}"], [gt[pid]["systolic"]])

    # F. Cardiology tests (8)
    for pid in ["P1005", "P1012", "P1017", "P1021", "P1028", "P1033", "P1040", "P1045"]:
        add("F_cardiology_test", pid, "What cardiology tests or procedures has this patient had?",
            ["patient_database_tool"], [f"Patient {pid}"], [gt[pid]["cardio_test"]])

    # G. Full review / condition (6)
    for pid in ["P1050", "P1058", "P1063", "P1070", "P1077", "P1089"]:
        add("G_condition", pid, "Please review this patient's cardiovascular condition.",
            ["patient_database_tool"], [f"Patient {pid}"], [gt[pid]["condition"]])

    # H. Drug label lookups (10) -- patient_id is a required API field, so
    # patient_database_tool always fires alongside openfda_drug_tool.
    drug_plan = [
        ("P1003", "Warfarin"), ("P1005", "Warfarin"), ("P1012", "Warfarin"),
        ("P1017", "Atorvastatin"), ("P1021", "Atorvastatin"), ("P1028", "Atorvastatin"),
        ("P1033", "Lisinopril"), ("P1040", "Lisinopril"),
        ("P1045", "Metoprolol"), ("P1050", "Metoprolol"),
    ]
    for pid, drug in drug_plan:
        add("H_drug_label", pid, f"What are the side effects and warnings for {drug}?",
            ["patient_database_tool", "openfda_drug_tool"], ["OpenFDA"], [], notes=f"drug={drug}")

    # I. RAG / policy retrieval (15) -- one per synthetic document
    rag_patients = (PATIENT_IDS * 2)[:15]
    for (doc_name, trigger, topic), pid in zip(RAG_DOCUMENTS, rag_patients):
        question = f"What does the hospital {trigger} say about {topic}?"
        add("I_rag_policy", pid, question,
            ["patient_database_tool", "cardiology_rag_tool"], [doc_name], [], notes=f"document={doc_name}")

    # J. Combined patient + drug + policy (8)
    combo_plan = [
        ("P1003", "Warfarin", "anticoagulation protocol"),
        ("P1005", "Lisinopril", "hospital medication policy"),
        ("P1012", "Atorvastatin", "dyslipidaemia guideline"),
        ("P1017", "Atorvastatin", "chronic coronary syndromes guideline"),
        ("P1021", "Metoprolol", "atrial fibrillation guideline"),
        ("P1028", "Metoprolol", "heart failure guideline"),
        ("P1033", "Metoprolol", "hospital cardiology monitoring policy"),
        ("P1050", "Lisinopril", "hypertension guideline"),
    ]
    for pid, drug, topic in combo_plan:
        add("J_combined", pid, f"Review this patient's {drug} therapy against the {topic}.",
            ["patient_database_tool", "openfda_drug_tool", "cardiology_rag_tool"], ["OpenFDA"], [], notes=f"drug={drug}")

    # K. Edge cases (7) -- all reachable via the live API as-is
    add("K_edge", "P12", "Can you review this patient's overall status?",
        ["patient_database_tool"], [], [], expect_error=True,
        notes="malformed patient_id (fails P\\d{4,12} format) -> repository ValueError, must degrade gracefully, not crash")
    add("K_edge", "P9999", "Can you review this patient's overall status?",
        ["patient_database_tool"], [], ["No corresponding information"],
        notes="well-formed but nonexistent patient -> must say not found, not fabricate a record")
    add("K_edge", "p1005", "What is this patient's gender?",
        ["patient_database_tool"], ["Patient P1005"], [gt["P1005"]["gender"]],
        notes="lowercase patient_id must be normalized/uppercased and still resolve")
    add("K_edge", "  P1012  ", "What is this patient's smoking status?",
        ["patient_database_tool"], ["Patient P1012"], [gt["P1012"]["smoking"]],
        notes="whitespace-padded patient_id must still resolve")
    add("K_edge", "P1005", "Is aspirin safe to combine with this patient's other medications?",
        ["patient_database_tool"], [], [],
        notes="'aspirin' is NOT in the hardcoded known-drug list -> openfda_drug_tool must NOT fire (routing gap, not a crash)")
    add("K_edge", "P1005", "Any concerns about WARFARIN for this patient?",
        ["patient_database_tool", "openfda_drug_tool"], ["OpenFDA"], [],
        notes="drug matching must be case-insensitive")
    add("K_edge", "P1005", "Please check this patient's insurance policyholder status.",
        ["patient_database_tool"], [], [],
        notes="'policyholder' must NOT word-boundary-match the RAG trigger 'policy' -> cardiology_rag_tool must NOT fire")

    return cases


def main() -> None:
    patients = generate_patients(count=100, seed=SEED)
    gt = ground_truth(patients)
    cases = build_cases(gt)
    assert len(cases) == 100, f"expected 100 cases, built {len(cases)}"

    out_path = Path(__file__).parent / "qa_test_set.json"
    out_path.write_text(json.dumps({"seed": SEED, "count": len(cases), "cases": cases}, indent=2), encoding="utf-8")
    print(f"Wrote {len(cases)} test cases to {out_path}")


if __name__ == "__main__":
    main()
