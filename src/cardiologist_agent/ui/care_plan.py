from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from cardiologist_agent.config.settings import Settings, get_settings
from cardiologist_agent.domain.enums import ReviewStatus
from cardiologist_agent.domain.patient import Patient
from cardiologist_agent.domain.response import FutureAppointment
from cardiologist_agent.repositories.policy import RetrievalResult
from cardiologist_agent.safety.assessment import SafetyAssessment


@dataclass
class StaffMember:
    id: str
    name: str
    title: str
    contact: str
    handles: list[str] = field(default_factory=list)


@dataclass
class CarePlan:
    clinical_rationale: str
    future_course_of_action: list[str]
    future_appointments: list[FutureAppointment]
    attention_items: list[str] = field(default_factory=list)


def _load_staff(settings: Settings | None = None) -> tuple[list[StaffMember], dict[str, str]]:
    settings = settings or get_settings()
    path = settings.resolve(Path("config/staff_directory.yaml"))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    staff = [
        StaffMember(
            id=s["id"],
            name=s["name"],
            title=s["title"],
            contact=s["contact"],
            handles=list(s.get("handles", [])),
        )
        for s in data.get("staff", [])
    ]
    routing = dict(data.get("condition_routing", {}))
    return staff, routing


def _by_id(staff: list[StaffMember]) -> dict[str, StaffMember]:
    return {s.id: s for s in staff}


def _pick_lead_clinician(patient: Patient, routing: dict[str, str], staff: dict[str, StaffMember]) -> StaffMember:
    if patient.primary_cardiologist and patient.primary_cardiologist in staff:
        return staff[patient.primary_cardiologist]

    for condition in patient.conditions:
        name = condition.condition_name.lower()
        if "heart failure" in name:
            return staff.get(routing.get("heart failure", "DR102"), staff["DR102"])
        if "fibrillation" in name or "palpitation" in name or "arrhythm" in name:
            return staff.get(routing.get("atrial fibrillation", "DR103"), staff["DR103"])
        if "lipid" in name or "cholesterol" in name:
            return staff.get(routing.get("hyperlipidaemia", "DR104"), staff["DR104"])
        if "hypertension" in name or "blood pressure" in name:
            return staff.get(routing.get("hypertension", "DR101"), staff["DR101"])
        if "valve" in name or "murmur" in name or "regurgitation" in name:
            return staff.get(routing.get("valve", "DR101"), staff["DR101"])

    return staff.get(routing.get("default", "DR101"), staff["DR101"])


def _has_active_meds(patient: Patient) -> bool:
    return any(m.medication_status.lower() == "active" for m in patient.medications)


def _condition_summary(patient: Patient) -> str:
    active = [
        c.condition_name
        for c in patient.conditions
        if (c.condition_status or "").lower() == "active"
    ]
    if not active:
        return "general heart health"
    if len(active) == 1:
        return active[0].lower()
    return f"{active[0].lower()} and {active[1].lower()}"


def _steps_for_draft(
    patient: Patient,
    lead: StaffMember,
    nurse: StaffMember,
    admin: StaffMember,
    duty: StaffMember,
) -> list[str]:
    condition = _condition_summary(patient)
    on_meds = _has_active_meds(patient)
    steps: list[str] = []

    if on_meds:
        steps.append(
            f"Continue the current heart medicines as listed on the record until {lead.name} "
            f"has reviewed them at the next appointment."
        )
        steps.append(
            f"Ask {nurse.name} ({nurse.title}) to confirm the next routine blood tests are booked "
            f"within the usual monitoring window."
        )
        steps.append(
            f"Schedule a routine follow-up with {lead.name} in three to six months, or sooner if "
            f"symptoms change — {admin.name} can arrange this at {admin.contact}."
        )
    else:
        steps.append(
            f"{lead.name} should decide whether starting treatment for {condition} is appropriate "
            f"at the next available clinic appointment."
        )
        steps.append(
            f"{nurse.name} can talk the patient through lifestyle advice (salt, activity, smoking) "
            f"while waiting for the clinic review."
        )
        steps.append(
            f"{admin.name} should offer an appointment within four weeks with {lead.name} "
            f"({lead.contact})."
        )

    steps.append(
        "If the patient feels chest pain, severe breathlessness, or fainting, they should "
        f"call 999 or contact {duty.name} ({duty.contact}) immediately."
    )
    return steps


def staff_ref(staff_id: str, staff_map: dict[str, StaffMember] | None = None) -> str:
    if staff_map and staff_id in staff_map:
        s = staff_map[staff_id]
        return f"{s.name} ({s.title}, {s.contact})"
    return staff_id


def build_care_plan(
    *,
    patient: Patient,
    assessment: SafetyAssessment,
    status: ReviewStatus,
    retrieval: RetrievalResult | None = None,
    clinical_question: str = "",
    settings: Settings | None = None,
) -> CarePlan:
    staff_list, routing = _load_staff(settings)
    staff = _by_id(staff_list)
    lead = _pick_lead_clinician(patient, routing, staff)
    nurse = staff["NURSE201"]
    admin = staff["ADMIN301"]
    pharmacist = staff["PHARM401"]
    duty = staff["DUTY501"]
    condition = _condition_summary(patient)

    steps: list[str] = []
    appointments: list[FutureAppointment] = []
    attention: list[str] = []
    rationale = ""

    if status == ReviewStatus.EMERGENCY_ESCALATION:
        rationale = (
            f"The oxygen level or another vital sign suggests this patient may need emergency care. "
            f"This is not something to manage by letter or routine appointment."
        )
        steps = [
            f"Call 999 or take the patient to the emergency department immediately.",
            f"Also notify {duty.name} on {duty.contact} so cardiology is aware on arrival.",
            "Do not change or stop heart medicines unless emergency staff instruct you to.",
        ]
        attention.append("Emergency-level warning detected — act now, not later today.")

    elif status == ReviewStatus.URGENT_CLINICAL_REVIEW:
        rationale = (
            f"Something in the recent test results or observations needs attention today, "
            f"especially in the context of {condition}."
        )
        if any("POTASSIUM" in f.code for f in assessment.flags):
            steps.extend(
                [
                    f"Phone {duty.name} on {duty.contact} today about the potassium result "
                    f"while the patient is on blood-pressure or heart medicines.",
                    f"{nurse.name} should arrange a repeat blood test within 48 hours.",
                    f"Until {lead.name} advises otherwise, do not start or increase "
                    f"medicines that affect potassium.",
                ]
            )
        elif any("BRADYCARDIA" in f.code for f in assessment.flags):
            steps.extend(
                [
                    f"Ask {duty.name} to review the slow heart rate today while the patient "
                    f"is on rate-slowing medicines.",
                    f"{nurse.name} should repeat heart-rate and blood-pressure checks within 24 hours.",
                    "Do not change the dose of heart-rate medicines without cardiology advice.",
                ]
            )
        else:
            steps.extend(
                [
                    f"Contact {duty.name} on {duty.contact} for a same-day cardiology opinion.",
                    f"{nurse.name} should arrange any repeat tests that have been flagged.",
                    f"Book an urgent slot with {lead.name} within the next few days via {admin.name}.",
                ]
            )
        appointments.append(
            FutureAppointment(
                appointment_type="Urgent cardiology review",
                purpose="Review abnormal results and agree safe next steps",
                target_date_or_window="Within 3 working days",
                responsible_service=f"{lead.name}, {lead.contact}",
            )
        )

    elif status == ReviewStatus.CONFLICT_REQUIRES_REVIEW:
        rationale = (
            "The record contains conflicting information about medicines or allergies. "
            "It would not be safe to proceed without sorting this out first."
        )
        if any(c.code == "ALLERGY_MEDICATION_CONFLICT" for c in assessment.conflicts):
            steps.extend(
                [
                    f"{pharmacist.name} ({pharmacist.title}) should review the allergy list and "
                    f"identify a safe alternative medicine.",
                    f"{lead.name} must sign off any change before the patient receives a new prescription.",
                    "Do not give the conflicting medicine until this is resolved.",
                ]
            )
        elif any(c.code == "MEDICATION_STATUS_CONFLICT" for c in assessment.conflicts):
            steps.extend(
                [
                    f"{pharmacist.name} should reconcile whether the medicine is active or stopped.",
                    f"{lead.name} needs to confirm the correct list with the GP and pharmacy.",
                    "Hold any medicine changes until the record shows one clear status.",
                ]
            )
        else:
            steps.extend(
                [
                    f"{pharmacist.name} and {lead.name} should review the procedure plan together.",
                    f"{admin.name} may need to reschedule tests until medicines are clarified.",
                ]
            )
        appointments.append(
            FutureAppointment(
                appointment_type="Medication reconciliation",
                purpose="Resolve conflicting medicine or allergy entries",
                target_date_or_window="Within 1 week",
                responsible_service=f"{pharmacist.name} and {lead.name}",
            )
        )

    elif status == ReviewStatus.INSUFFICIENT_EVIDENCE:
        if assessment.allergy_reconciliation_unknown:
            rationale = (
                "We do not know whether the patient has allergies because this has not been "
                "checked and recorded properly."
            )
            steps.extend(
                [
                    f"{nurse.name} should complete an allergy check with the patient and update the record.",
                    f"{pharmacist.name} must review the updated list before any new prescription.",
                    f"Only after that should {lead.name} consider medicine changes.",
                ]
            )
        elif assessment.stale:
            rationale = (
                "Some important blood tests are too old to rely on for safe decisions about "
                f"heart medicines and {condition}."
            )
            stale_names = ", ".join(
                sorted({(g.field or g.category).replace("_", " ") for g in assessment.stale})
            )
            steps.extend(
                [
                    f"{nurse.name} should book fresh blood tests ({stale_names}) within two weeks.",
                    "Do not start, stop, or change heart medicines until the new results are back.",
                    f"Once results arrive, {lead.name} can review them and update the plan.",
                ]
            )
        else:
            rationale = (
                "A heart scan or test result is still preliminary, or other key information "
                "is missing from the record."
            )
            steps.extend(
                [
                    f"Chase the final report with the cardiology department and {admin.name}.",
                    f"{lead.name} should review the completed result before treatment decisions.",
                    f"{nurse.name} can support the patient while waiting for the final report.",
                ]
            )
        appointments.append(
            FutureAppointment(
                appointment_type="Review once results available",
                purpose="Complete monitoring or test reports before treatment changes",
                target_date_or_window="Within 2–3 weeks",
                responsible_service=f"{lead.name} via {admin.contact}",
            )
        )

    elif status == ReviewStatus.SYSTEM_UNAVAILABLE:
        rationale = "The patient record is inactive or could not be opened, so a proper review is not possible."
        steps = [
            f"Ask records staff to reactivate or locate the correct patient file.",
            f"Once active, repeat the review and notify {lead.name} if cardiology input is needed.",
        ]

    else:
        rationale = (
            f"Overall this looks like a stable picture for {condition}. "
            f"Nothing urgent jumped out, though signed prescriptions still need a doctor to approve."
        )
        steps = _steps_for_draft(patient, lead, nurse, admin, duty)
        if "mild" in condition or any(
            w in condition for w in ("palpitation", "hypertension", "lipid", "murmur", "ectopic")
        ):
            appointments.append(
                FutureAppointment(
                    appointment_type="Routine cardiology check-up",
                    purpose="Review symptoms, blood pressure, and whether treatment is needed",
                    target_date_or_window="Within 3–6 months",
                    responsible_service=f"{lead.name}, {lead.contact}",
                )
            )

    if retrieval and retrieval.chunks:
        policy_hint = next(
            (c.text[:120] for c in retrieval.chunks if "Northbridge" in c.text or "Dr " in c.text),
            None,
        )
        if policy_hint and status == ReviewStatus.DRAFT_FOR_CLINICIAN_REVIEW:
            attention.append("Practice policy supports the plan above.")

    return CarePlan(
        clinical_rationale=rationale,
        future_course_of_action=steps,
        future_appointments=appointments,
        attention_items=attention,
    )
