from __future__ import annotations

from typing import Any

STATUS_PHRASES = {
    "DRAFT_FOR_CLINICIAN_REVIEW": (
        "A draft summary has been prepared for clinician review. "
        "It is not a final authorised medication plan."
    ),
    "INSUFFICIENT_EVIDENCE": (
        "There is not yet enough reliable information to make a safe recommendation. "
        "Further checks or updated records are needed first."
    ),
    "CONFLICT_REQUIRES_REVIEW": (
        "Conflicting information was found in the record. "
        "A clinician must review and resolve this before any medication action is taken."
    ),
    "URGENT_CLINICAL_REVIEW": (
        "Urgent clinical review is recommended today because of flagged safety concerns."
    ),
    "EMERGENCY_ESCALATION": (
        "Emergency escalation is advised. Immediate clinical assessment is required."
    ),
    "SYSTEM_UNAVAILABLE": (
        "The review could not be completed because the patient record is unavailable or inactive."
    ),
    "FINAL_AUTHORIZED": (
        "A fully authorised medication recommendation is available for release."
    ),
}

GRADE_PHRASES = {
    "HIGH": "The available evidence is strong and complete.",
    "MODERATE": "The available evidence is reasonably complete, though some items remain open.",
    "LOW": "The available evidence is limited; please treat recommendations with extra caution.",
    "INSUFFICIENT": "The evidence available is not sufficient to support a confident recommendation.",
}

ACTION_PHRASES = {
    "CONTINUE": "Continue current treatment as documented, subject to clinician approval.",
    "START": "Starting a new medicine may be appropriate once authorisation is confirmed.",
    "ADJUST": "A dose or regimen adjustment may be needed after clinician review.",
    "HOLD": "A temporary hold may be appropriate pending further review.",
    "STOP": "Stopping a medicine may be appropriate after clinician review.",
    "NO_CHANGE": "No change to medicines is suggested at this time.",
    "NO_RECOMMENDATION": "No medication recommendation can be made safely at this time.",
}


def _join_sentences(parts: list[str]) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def _format_list_as_prose(items: list[str], *, empty: str) -> str:
    if not items:
        return empty
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} Also, {items[1]}"
    body = "; ".join(items[:-1])
    return f"{body}; and {items[-1]}"


def _attention_items(data: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for raw in data.get("attention_items") or []:
        text = str(raw).strip()
        if text.startswith("["):
            closing = text.find("]")
            if closing != -1:
                text = text[closing + 1 :].strip()
        if text:
            items.append(text)
    for warning in data.get("warnings_and_red_flags") or []:
        text = str(warning).strip()
        if text and text not in items:
            items.append(text)
    return items


def _medication_paragraph(data: dict[str, Any]) -> str:
    auth = data.get("authorization") or {}
    auth_status = auth.get("authorization_status", "UNAVAILABLE")
    instructions = data.get("medication_instructions") or []
    action = data.get("recommendation_action", "NO_RECOMMENDATION")
    action_text = ACTION_PHRASES.get(action, "No medication action has been confirmed.")

    if auth_status == "UNAVAILABLE" or not any(i.get("authorized") for i in instructions):
        return _join_sentences(
            [
                action_text,
                "Medicines appear on the record, but no signed orders are available to confirm "
                "exact administration instructions. Please do not act on undocumented directions "
                "until a clinician has authorised them.",
            ]
        )

    lines = [action_text, "The following authorised instructions apply:"]
    for med in instructions:
        if not med.get("authorized"):
            continue
        detail = med.get("medication_name") or "Medication"
        if med.get("dose") and med.get("dose_unit"):
            detail += f" {med['dose']}{med['dose_unit']}"
        if med.get("route"):
            detail += f", {med['route']}"
        if med.get("frequency"):
            detail += f", {med['frequency']}"
        lines.append(detail + ".")
    return " ".join(lines)


def _tests_paragraph(data: dict[str, Any]) -> str:
    tests = data.get("required_tests") or []
    if not tests:
        return (
            "No additional blood tests or investigations need to be arranged on the basis of "
            "this review at present."
        )
    parts: list[str] = []
    for test in tests:
        name = test.get("test") or "Investigation"
        purpose = test.get("purpose") or "Clinical monitoring"
        timing = test.get("target_date_or_window")
        owner = test.get("booking_owner")
        sentence = f"{name} is recommended for {purpose.lower().rstrip('.')}"
        if timing:
            sentence += f", ideally {timing.lower()}"
        if owner:
            sentence += f", to be booked by {owner}"
        sentence += "."
        parts.append(sentence)
    intro = "The following tests or monitoring checks should be arranged:"
    return intro + " " + _format_list_as_prose(parts, empty="")


def _appointments_paragraph(data: dict[str, Any]) -> str:
    appointments = data.get("future_appointments") or []
    if not appointments:
        return (
            "No follow-up appointments need to be scheduled at this time. "
            "Routine clinic arrangements may continue as already planned."
        )
    parts: list[str] = []
    for appt in appointments:
        appt_type = appt.get("appointment_type") or "Appointment"
        purpose = appt.get("purpose") or "Clinical review"
        timing = appt.get("target_date_or_window")
        service = appt.get("responsible_service")
        sentence = f"A {appt_type.lower()} is suggested for {purpose.lower().rstrip('.')}"
        if timing:
            sentence += f", target window {timing.lower()}"
        if service:
            sentence += f", with {service}"
        sentence += "."
        parts.append(sentence)
    intro = "Please arrange the following appointments:"
    return intro + " " + _format_list_as_prose(parts, empty="")


def _gaps_paragraph(data: dict[str, Any]) -> str | None:
    gaps = (data.get("missing_or_stale_data") or []) + []
    if not gaps:
        return None
    parts = [g.get("description") for g in gaps if g.get("description")]
    if not parts:
        return None
    return (
        "Some information in the record is missing, outdated, or not yet finalised: "
        + _format_list_as_prose(parts, empty="")
    )


def _conflicts_paragraph(data: dict[str, Any]) -> str | None:
    conflicts = data.get("conflicts") or []
    if not conflicts:
        return None
    parts: list[str] = []
    for item in conflicts:
        desc = item.get("description")
        withheld = item.get("withheld")
        if desc and withheld:
            parts.append(f"{desc} Until this is resolved, {withheld.lower()} should be withheld.")
        elif desc:
            parts.append(desc)
    if not parts:
        return None
    return "The following conflicts require attention: " + _format_list_as_prose(parts, empty="")


def _dependencies_paragraph(data: dict[str, Any]) -> str | None:
    deps = [d for d in (data.get("unavailable_dependencies") or []) if not d.get("available")]
    if not deps:
        return None
    parts = []
    for dep in deps:
        name = dep.get("name") or "external source"
        message = dep.get("message") or "This source was unavailable."
        parts.append(f"{name}: {message}")
    return (
        "Please note that some supporting information could not be retrieved: "
        + _format_list_as_prose(parts, empty="")
    )


def format_secretary_letter(data: dict[str, Any], *, clinician_id: str) -> str:
    """Turn a review API payload into a single secretary-style letter without patient identifiers."""
    status = data.get("review_status", "UNKNOWN")
    grade = data.get("evidence_grade", "INSUFFICIENT")
    rationale = (data.get("clinical_rationale") or "").strip()
    safest = (data.get("safest_next_action") or "").strip()
    future = [str(x).strip() for x in (data.get("future_course_of_action") or []) if str(x).strip()]

    attention = _attention_items(data)
    paragraphs: list[str] = []

    salutation = f"Dear Colleague ({clinician_id}),"
    opening = _join_sentences(
        [
            "Thank you for your review request.",
            "I have completed a structured check of the record, practice policies, and "
            "available supporting sources.",
            STATUS_PHRASES.get(status, "The review has been completed."),
            GRADE_PHRASES.get(grade, ""),
        ]
    )
    paragraphs.extend([salutation, opening])

    if rationale:
        paragraphs.append(rationale)

    if attention:
        paragraphs.append(
            "Matters that need your attention: "
            + _format_list_as_prose(attention, empty="None were identified.")
        )

    paragraphs.append(_medication_paragraph(data))

    auth = data.get("authorization") or {}
    auth_message = (auth.get("message") or "").strip()
    if auth_message:
        paragraphs.append(f"Authorisation note: {auth_message}")

    conflict_text = _conflicts_paragraph(data)
    if conflict_text:
        paragraphs.append(conflict_text)

    gap_text = _gaps_paragraph(data)
    if gap_text:
        paragraphs.append(gap_text)

    paragraphs.append(_tests_paragraph(data))
    paragraphs.append(_appointments_paragraph(data))

    if future:
        paragraphs.append(
            "Recommended next steps in the clinic workflow: "
            + _format_list_as_prose(future, empty="")
        )
    elif safest:
        paragraphs.append(f"Recommended next step: {safest}")
    else:
        paragraphs.append(
            "Please review the summary above and proceed according to your usual clinical workflow."
        )

    dep_text = _dependencies_paragraph(data)
    if dep_text:
        paragraphs.append(dep_text)

    limitations = [str(x).strip() for x in (data.get("limitations") or []) if str(x).strip()]
    if limitations:
        paragraphs.append(
            "Important reminders: "
            + _format_list_as_prose(limitations, empty="This is a fictional training environment.")
        )

    closing = (
        "Kind regards,\n"
        "Cardiology Administration Support\n"
        "(Northbridge Training System — fictional synthetic data only; not for real patient care.)"
    )
    paragraphs.append(closing)

    return "\n\n".join(paragraphs)
