import json
from pathlib import Path

patients = json.loads(Path("data/patients/runtime/patients.json").read_text())
manifest = json.loads(Path("data/patients/evaluation/case_manifest.json").read_text())
by_id = {p["patient_id"]: p for p in patients}
tags = {m["patient_id"]: m["scenario_tags"] for m in manifest}

no_meds = []
stale_k = []
few_labs = []
for p in patients:
    pid = p["patient_id"]
    active = [m for m in p.get("medications", []) if m.get("medication_status", "").lower() == "active"]
    if not active:
        no_meds.append(pid)
    labs = p.get("lab_results", [])
    if len(labs) < 3:
        few_labs.append(pid)
    k_dates = [l["test_date"] for l in labs if "potassium" in l.get("test_name", "").lower()]
    if k_dates:
        latest = max(k_dates)
        if latest < "2026-04-01":
            stale_k.append(pid)

print("Total patients:", len(patients))
print("No active meds:", len(no_meds), no_meds[:15])
print("Few labs (<3):", len(few_labs), few_labs[:15])
print("Stale potassium (<2026-04-01):", len(stale_k), stale_k[:15])

for pid in [
    "P1001", "P1020", "P1050", "P1056", "P1063", "P1069", "P1074",
    "P1079", "P1083", "P1087", "P1091", "P1095", "P1098", "P1100",
]:
    p = by_id[pid]
    active = [m["drug_name"] for m in p.get("medications", []) if m.get("medication_status", "").lower() == "active"]
    print(
        pid,
        "tags=", tags[pid],
        "meds=", active[:4],
        "labs=", len(p.get("lab_results", [])),
        "cardio=", len(p.get("cardiology_tests", [])),
        "allergies=", len(p.get("allergies", [])),
        "status=", p.get("status"),
    )
