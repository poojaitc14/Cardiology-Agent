"""Regenerate key RAG policy PDFs with named fictional staff contacts."""

from __future__ import annotations

from pathlib import Path

import yaml
from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[3]
STAFF_PATH = ROOT / "config/staff_directory.yaml"
POLICY_DIR = ROOT / "data/rag/runtime_policies"


def _header(pdf: FPDF, doc_id: str, title: str) -> None:
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Northbridge Cardiology Practice", ln=True)
    pdf.set_font("Helvetica", "B", 12)
    pdf.multi_cell(0, 7, title)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Document ID {doc_id} 1.0", ln=True)
    pdf.cell(0, 6, "Effective 2026-01-01  Review due 2027-01-01", ln=True)
    pdf.ln(4)


def _ascii(text: str) -> str:
    replacements = {
        "\u2014": "-",
        "\u2013": "-",
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u2022": "-",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _staff_block(pdf: FPDF, staff: list[dict]) -> None:
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Named contacts (fictional training directory)", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for member in staff:
        line = (
            f"{member['name']} - {member['title']}. "
            f"{member['contact']}. "
            f"Handles: {', '.join(member.get('handles', []))}."
        )
        pdf.multi_cell(0, 6, _ascii(line))
        pdf.ln(1)


def build_staff_directory(staff: list[dict]) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    _header(pdf, "NB-ADM-007", "Staff directory and contact routes")
    pdf.multi_cell(
        0,
        6,
        _ascii(
            "Use the named contacts below instead of generic 'clinician' referrals. "
            "All names are fictional and for training only."
        ),
    )
    pdf.ln(3)
    _staff_block(pdf, staff)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Routing guide", ln=True)
    pdf.set_font("Helvetica", "", 10)
    routes = [
        "Hypertension and general cardiology -> Dr Amelia Hartley (DR101)",
        "Heart failure and fluid management -> Dr Raj Patel (DR102)",
        "Palpitations, atrial fibrillation, anticoagulation -> Dr Sophie Chen (DR103)",
        "Mild conditions, lifestyle, screening -> Dr James Okonkwo (DR104)",
        "Blood tests and monitoring -> Sister Margaret Walsh (NURSE201)",
        "Appointments and referrals -> Mr Daniel Brooks (ADMIN301)",
        "Medicine conflicts and allergies -> Ms Elena Vasquez (PHARM401)",
        "Same-day urgent review -> Dr Fatima Al-Rashid (DUTY501)",
    ]
    for route in routes:
        pdf.cell(0, 6, _ascii(f"- {route}"), ln=True)
    out = POLICY_DIR / "07_staff_directory_and_contact_routes.pdf"
    pdf.output(str(out))
    print(f"Wrote {out.name}")


def build_booking_policy(staff: list[dict]) -> None:
    by_id = {s["id"]: s for s in staff}
    pdf = FPDF()
    pdf.add_page()
    _header(pdf, "NB-ADM-004", "Booking, referrals and appointment procedures")
    pdf.multi_cell(
        0,
        6,
        "Routine follow-ups should be booked through Mr Daniel Brooks at cardiology reception. "
        "Urgent same-day concerns must be directed to Dr Fatima Al-Rashid on the cardiology bleep.",
    )
    pdf.ln(3)
    pdf.multi_cell(
        0,
        6,
        f"Monitoring blood tests: contact {by_id['NURSE201']['name']} ({by_id['NURSE201']['contact']}).",
    )
    pdf.multi_cell(
        0,
        6,
        f"New patient heart failure referrals: {by_id['DR102']['name']} ({by_id['DR102']['contact']}).",
    )
    pdf.multi_cell(
        0,
        6,
        f"Arrhythmia clinic slots: {by_id['DR103']['name']} ({by_id['DR103']['contact']}).",
    )
    pdf.multi_cell(
        0,
        6,
        f"Mild hypertension annual reviews: {by_id['DR104']['name']} ({by_id['DR104']['contact']}).",
    )
    out = POLICY_DIR / "04_booking_referrals_and_appointment_procedures.pdf"
    pdf.output(str(out))
    print(f"Wrote {out.name}")


def build_escalation_policy(staff: list[dict]) -> None:
    duty = next(s for s in staff if s["id"] == "DUTY501")
    pdf = FPDF()
    pdf.add_page()
    _header(pdf, "NB-SAF-005", "Safety escalation and red flags")
    pdf.multi_cell(
        0,
        6,
        "For urgent potassium results with ACE inhibitors, phone Dr Fatima Al-Rashid immediately. "
        "For medication-allergy conflicts, involve Ms Elena Vasquez and the named lead cardiologist.",
    )
    pdf.ln(3)
    pdf.multi_cell(0, 6, f"Duty escalation contact: {duty['name']}, {duty['contact']}.")
    pdf.multi_cell(
        0,
        6,
        "Do not use the word 'clinician' alone in handover - always name the responsible doctor or nurse.",
    )
    out = POLICY_DIR / "05_safety_escalation_and_red_flags.pdf"
    pdf.output(str(out))
    print(f"Wrote {out.name}")


def main() -> None:
    data = yaml.safe_load(STAFF_PATH.read_text(encoding="utf-8"))
    staff = data["staff"]
    build_staff_directory(staff)
    build_booking_policy(staff)
    build_escalation_policy(staff)


if __name__ == "__main__":
    main()
