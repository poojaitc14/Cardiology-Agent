from __future__ import annotations

import uuid
from datetime import datetime

from cardiologist_agent.citations.validator import (
    build_openfda_claim,
    build_policy_claims,
    validate_claims,
)
from cardiologist_agent.domain.enums import (
    AuthorizationStatus,
    ClaimType,
    RecommendationAction,
    ReviewStatus,
)
from cardiologist_agent.domain.patient import Patient
from cardiologist_agent.domain.response import (
    AuthorizationBlock,
    Citation,
    Claim,
    DependencyStatus,
    MedicationInstructionDraft,
    MedicationRecommendationResponse,
    PatientSnapshot,
    RequiredTest,
)
from cardiologist_agent.providers.openfda import OpenFDAResult
from cardiologist_agent.repositories.policy import RetrievalResult
from cardiologist_agent.safety.assessment import SafetyAssessment
from cardiologist_agent.safety.status import (
    compute_evidence_grade,
    safest_next_action,
    select_review_status,
)
from cardiologist_agent.ui.care_plan import _by_id, _load_staff, build_care_plan


def _allergy_summary(patient: Patient, assessment: SafetyAssessment) -> str:
    if assessment.allergy_reconciliation_unknown:
        return "Allergy reconciliation status unknown"
    if not patient.allergies:
        return "No allergy records documented (not verified NKDA)"
    return ", ".join(a.allergen for a in patient.allergies)


def _latest_vitals_summary(patient: Patient) -> str | None:
    if not patient.vital_signs:
        return None
    vital = sorted(
        patient.vital_signs,
        key=lambda v: v.measured_at or datetime.min,
        reverse=True,
    )[0]
    parts = []
    if vital.systolic_bp and vital.diastolic_bp:
        parts.append(f"BP {vital.systolic_bp}/{vital.diastolic_bp}")
    if vital.heart_rate is not None:
        parts.append(f"HR {vital.heart_rate}")
    if vital.oxygen_saturation is not None:
        parts.append(f"SpO2 {vital.oxygen_saturation}%")
    return "; ".join(parts) if parts else None


def _recent_medicines_summary(patient: Patient) -> str:
    active = [m for m in patient.medications if m.medication_status.lower() == "active"]
    if not active:
        return "No active heart medicines are listed on the record at the moment."
    count = len(active)
    word = "medicines" if count != 1 else "medicine"
    return f"The record shows {count} active heart {word} on file."


def _recent_labs_summary(patient: Patient) -> str:
    labs = sorted(
        [lab for lab in patient.lab_results if lab.test_date],
        key=lambda item: item.test_date or datetime.min,
        reverse=True,
    )
    if not labs:
        return "No recent blood test results are on file."
    latest = labs[0]
    names = ", ".join(dict.fromkeys(lab.test_name for lab in labs[:3]))
    when = latest.test_date.strftime("%d %B %Y") if latest.test_date else "recently"
    return f"Recent blood tests on file ({names}) date from {when}."


def _recent_care_summary(patient: Patient) -> str:
    tests = sorted(
        [test for test in patient.cardiology_tests if test.performed_date],
        key=lambda item: item.performed_date or datetime.min,
        reverse=True,
    )
    if not tests:
        return "No recent heart clinic tests or visits are recorded."
    latest = tests[0]
    when = latest.performed_date.strftime("%d %B %Y") if latest.performed_date else "recently"
    return (
        f"The most recent heart test on file is "
        f"{latest.test_or_procedure_name.lower()}, from {when}."
    )


def build_patient_snapshot(patient: Patient, assessment: SafetyAssessment) -> PatientSnapshot:
    active_meds = [
        f"{m.drug_name} {m.dose}{m.dose_unit or ''} ({m.medication_status})"
        for m in patient.medications
        if m.medication_status.lower() == "active"
    ]
    active_conditions = [
        c.condition_name
        for c in patient.conditions
        if (c.condition_status or "").lower() == "active"
    ]
    return PatientSnapshot(
        patient_id=patient.patient_id,
        name=f"{patient.first_name} {patient.last_name}",
        date_of_birth=patient.date_of_birth.isoformat(),
        gender=patient.gender,
        primary_cardiologist=patient.primary_cardiologist,
        record_status=patient.status,
        active_conditions=active_conditions,
        active_medications=active_meds,
        allergy_summary=_allergy_summary(patient, assessment),
        latest_vitals_summary=_latest_vitals_summary(patient),
        recent_medicines_summary=_recent_medicines_summary(patient),
        recent_labs_summary=_recent_labs_summary(patient),
        recent_care_summary=_recent_care_summary(patient),
    )


def build_medication_drafts(patient: Patient, authorized: bool) -> list[MedicationInstructionDraft]:
    drafts: list[MedicationInstructionDraft] = []
    for med in patient.medications:
        if med.medication_status.lower() != "active":
            continue
        drafts.append(
            MedicationInstructionDraft(
                medication_name=med.drug_name,
                strength=f"{med.dose}{med.dose_unit or ''}" if med.dose is not None else None,
                dose=str(med.dose) if med.dose is not None else None,
                dose_unit=med.dose_unit,
                route=med.route,
                frequency=med.frequency,
                start_date=med.start_date.isoformat() if med.start_date else None,
                source="medication_history",
                authorized=authorized,
            )
        )
    return drafts


def build_response(
    *,
    request_id: str,
    patient: Patient,
    clinical_question: str,
    assessment: SafetyAssessment,
    retrieval: RetrievalResult,
    openfda_results: list[OpenFDAResult],
    authorization_status: AuthorizationStatus,
    has_signed_orders: bool,
    dependencies: list[DependencyStatus],
    llm_payload: dict | None = None,
    llm_used: bool = False,
) -> MedicationRecommendationResponse:
    status = select_review_status(
        assessment,
        authorization_status,
        retrieval,
        has_signed_orders=has_signed_orders,
    )
    grade = compute_evidence_grade(
        status, assessment, retrieval, authorization_status, dependencies
    )

    staff_list, _ = _load_staff()
    staff = _by_id(staff_list)
    nurse = staff.get("NURSE201")
    nurse_name = nurse.name if nurse else "Sister Margaret Walsh"

    care = build_care_plan(
        patient=patient,
        assessment=assessment,
        status=status,
        retrieval=retrieval,
        clinical_question=clinical_question,
    )

    claims: list[Claim] = []
    for cond in patient.conditions[:5]:
        claims.append(
            Claim(
                claim_id=f"cond-{cond.record_id}",
                claim_type=ClaimType.PATIENT_FACT,
                text=f"Condition: {cond.condition_name} ({cond.condition_status})",
                citations=[
                    Citation(
                        source_type="patient_record",
                        patient_field=f"conditions.{cond.record_id}",
                    )
                ],
            )
        )
    claims.extend(build_policy_claims(retrieval.chunks if retrieval else []))
    for result in openfda_results:
        ext = build_openfda_claim(result)
        if ext:
            claims.append(ext)
    claims = validate_claims(claims)

    action = RecommendationAction.NO_RECOMMENDATION
    if status == ReviewStatus.DRAFT_FOR_CLINICIAN_REVIEW:
        action = RecommendationAction.NO_CHANGE
    elif status in {ReviewStatus.CONFLICT_REQUIRES_REVIEW, ReviewStatus.INSUFFICIENT_EVIDENCE}:
        action = RecommendationAction.NO_RECOMMENDATION

    rationale = (
        llm_payload.get("clinical_rationale")
        if llm_payload and llm_payload.get("clinical_rationale")
        else care.clinical_rationale
    )
    attention = list(assessment.flags)
    attention_items = [f"[{f.severity}] {f.message}" for f in attention]
    if care.attention_items:
        attention_items.extend(care.attention_items)
    if llm_payload and llm_payload.get("attention_items"):
        attention_items.extend(str(x) for x in llm_payload["attention_items"])

    required_tests: list[RequiredTest] = []
    for gap in assessment.stale:
        required_tests.append(
            RequiredTest(
                test=gap.field or gap.category,
                purpose="We need up-to-date blood results before any medicine changes.",
                target_date_or_window="Within 2 weeks",
                booking_owner=nurse_name,
                results_owner=patient.primary_cardiologist or "Dr Amelia Hartley",
                escalation=f"Contact {staff.get('DUTY501').name if staff.get('DUTY501') else 'duty cardiology'} if delayed.",
            )
        )

    limitations = [
        "Fictional training application — not for real patient care.",
        "Medication history is not proof of signed authorization.",
    ]
    if authorization_status == AuthorizationStatus.UNAVAILABLE:
        limitations.append(
            "No medication order repository configured; FINAL_AUTHORIZED is blocked."
        )

    return MedicationRecommendationResponse(
        request_id=request_id,
        patient_id=patient.patient_id,
        review_status=status,
        evidence_grade=grade,
        recommendation_action=action,
        clinical_rationale=str(rationale),
        authorization=AuthorizationBlock(
            authorization_status=authorization_status,
            message=(
                "Signed medication orders unavailable."
                if authorization_status == AuthorizationStatus.UNAVAILABLE
                else "Authorization verified."
            ),
        ),
        medication_instructions=build_medication_drafts(
            patient, authorized=status == ReviewStatus.FINAL_AUTHORIZED
        ),
        patient_snapshot=build_patient_snapshot(patient, assessment),
        attention_items=attention_items,
        warnings_and_red_flags=[
            f.message
            for f in assessment.flags
            if f.severity.value in {"URGENT", "EMERGENCY", "CRITICAL"}
        ],
        required_tests=required_tests,
        future_appointments=care.future_appointments,
        future_course_of_action=care.future_course_of_action,
        missing_or_stale_data=assessment.missing + assessment.stale,
        conflicts=assessment.conflicts,
        unavailable_dependencies=[d for d in dependencies if not d.available],
        claims=claims,
        limitations=limitations,
        safest_next_action=safest_next_action(status, assessment),
        llm_synthesis_used=llm_used,
    )


def new_request_id() -> str:
    return str(uuid.uuid4())
