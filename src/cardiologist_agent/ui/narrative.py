from __future__ import annotations

from typing import Any

STATUS_PHRASES = {
    "DRAFT_FOR_CLINICIAN_REVIEW": (
        "Everything looks broadly stable from what we can see in the record. "
        "A heart doctor still needs to sign off any medicine changes."
    ),
    "INSUFFICIENT_EVIDENCE": (
        "We do not yet have enough up-to-date information to give confident advice. "
        "Some tests or checks need to happen first."
    ),
    "CONFLICT_REQUIRES_REVIEW": (
        "Something in the record does not add up — usually about medicines or allergies. "
        "This needs sorting out before anyone changes treatment."
    ),
    "URGENT_CLINICAL_REVIEW": (
        "Something needs attention today. Please do not wait for a routine appointment."
    ),
    "EMERGENCY_ESCALATION": (
        "This may be an emergency. Immediate medical help is needed."
    ),
    "SYSTEM_UNAVAILABLE": (
        "We could not open this patient’s record, so a full review was not possible."
    ),
    "FINAL_AUTHORIZED": (
        "A signed treatment plan is on file and ready to share with the care team."
    ),
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


def _plain_attention(data: dict[str, Any]) -> list[str]:
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
            items.append(_simplify_medical_text(text))
    return items


def _simplify_medical_text(text: str) -> str:
    replacements = {
        "Potassium": "potassium (salt level in the blood)",
        "ACE/ARB": "blood-pressure tablets that can affect potassium",
        "SpO2": "oxygen level",
        "mmol/L": "",
        "bpm": "beats per minute",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    return " ".join(result.split())


def _snapshot(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("patient_snapshot") or {}


def _medication_paragraph(data: dict[str, Any]) -> str:
    auth = data.get("authorization") or {}
    auth_status = auth.get("authorization_status", "UNAVAILABLE")
    instructions = data.get("medication_instructions") or []
    action = data.get("recommendation_action", "NO_RECOMMENDATION")
    snapshot = _snapshot(data)
    recent = (snapshot.get("recent_medicines_summary") or "").strip()

    if action == "NO_CHANGE":
        action_text = "Nothing suggests an immediate change to heart medicines."
    elif action == "NO_RECOMMENDATION":
        action_text = "We cannot safely recommend a medicine change right now."
    else:
        action_text = "A medicine change might be worth discussing once a doctor has reviewed the file."

    parts = [action_text]
    if recent:
        parts.append(recent)

    if auth_status == "UNAVAILABLE" or not any(i.get("authorized") for i in instructions):
        active_count = sum(1 for i in instructions if i.get("medication_name"))
        if active_count:
            parts.append(
                "There are medicines on the record, but none have a signed prescription attached "
                "in this system. Please wait for a doctor to confirm what the patient should "
                "actually take."
            )
        elif not recent:
            parts.append("The patient is not on active heart treatment in the record at the moment.")
        return _join_sentences(parts)

    return _join_sentences(parts)


def _tests_paragraph(data: dict[str, Any]) -> str:
    tests = data.get("required_tests") or []
    snapshot = _snapshot(data)
    recent = (snapshot.get("recent_labs_summary") or "").strip()
    parts: list[str] = []

    if recent:
        parts.append(recent)

    if not tests:
        parts.append("No extra blood tests need booking right now on the basis of this review.")
        return _join_sentences(parts)

    booking_parts: list[str] = []
    for test in tests:
        name = test.get("test") or "Blood test"
        purpose = test.get("purpose") or "Routine monitoring"
        timing = test.get("target_date_or_window")
        owner = test.get("booking_owner")
        sentence = purpose.rstrip(".")
        if name.lower() not in sentence.lower():
            sentence = f"A {name.lower()} test is needed. {sentence}"
        if timing:
            sentence += f" Please arrange this {timing.lower()}."
        if owner:
            sentence += f" {owner} can help book it."
        sentence += "."
        booking_parts.append(sentence)
    parts.append("Tests to arrange: " + _format_list_as_prose(booking_parts, empty=""))
    return _join_sentences(parts)


def _appointments_paragraph(data: dict[str, Any]) -> str:
    appointments = data.get("future_appointments") or []
    snapshot = _snapshot(data)
    recent = (snapshot.get("recent_care_summary") or "").strip()
    parts: list[str] = []

    if recent:
        parts.append(recent)

    if not appointments:
        parts.append(
            "No new appointments need scheduling from this review. "
            "Any existing clinic dates can stay as they are."
        )
        return _join_sentences(parts)

    booking_parts: list[str] = []
    for appt in appointments:
        appt_type = appt.get("appointment_type") or "Appointment"
        purpose = appt.get("purpose") or "Heart check-up"
        timing = appt.get("target_date_or_window")
        service = appt.get("responsible_service")
        sentence = f"Book a {appt_type.lower()} for {purpose.lower().rstrip('.')}"
        if timing:
            sentence += f", ideally {timing.lower()}"
        if service:
            sentence += f". Contact: {service}"
        sentence += "."
        booking_parts.append(sentence)
    parts.append("Appointments: " + _format_list_as_prose(booking_parts, empty=""))
    return _join_sentences(parts)


def _gaps_paragraph(data: dict[str, Any]) -> str | None:
    gaps = data.get("missing_or_stale_data") or []
    if not gaps:
        return None
    parts = []
    for g in gaps:
        desc = g.get("description")
        if desc:
            parts.append(_simplify_medical_text(desc))
    if not parts:
        return None
    return "Information that needs updating: " + _format_list_as_prose(parts, empty="")


def _conflicts_paragraph(data: dict[str, Any]) -> str | None:
    conflicts = data.get("conflicts") or []
    if not conflicts:
        return None
    parts: list[str] = []
    for item in conflicts:
        desc = item.get("description")
        if desc:
            parts.append(_simplify_medical_text(desc))
    if not parts:
        return None
    return "Please resolve the following before changing medicines: " + _format_list_as_prose(parts, empty="")


def _next_steps_paragraph(data: dict[str, Any]) -> str:
    future = [str(x).strip() for x in (data.get("future_course_of_action") or []) if str(x).strip()]
    safest = (data.get("safest_next_action") or "").strip()

    if future:
        bullets = "\n".join(f"• {item}" for item in future)
        return f"Here is what I recommend happens next:\n{bullets}"
    if safest:
        return f"What to do next:\n• {safest}"
    return (
        "Please read through the summary above and follow your usual ward or clinic process "
        "for heart patients."
    )


def format_secretary_letter(data: dict[str, Any], *, clinician_id: str) -> str:
    """Plain-English letter for non-clinical hospital staff. No patient identifiers."""
    status = data.get("review_status", "UNKNOWN")
    rationale = (data.get("clinical_rationale") or "").strip()
    attention = _plain_attention(data)
    paragraphs: list[str] = []

    salutation = f"Hello,"
    opening = _join_sentences(
        [
            "Thank you — I have looked through the heart record, hospital policies, and supporting notes.",
            STATUS_PHRASES.get(status, "The review is complete."),
        ]
    )
    paragraphs.extend([salutation, opening])

    if rationale:
        paragraphs.append(rationale)

    if attention:
        paragraphs.append(
            "Please pay special attention to the following: "
            + _format_list_as_prose(attention, empty="Nothing urgent was flagged.")
        )

    paragraphs.append(_medication_paragraph(data))

    conflict_text = _conflicts_paragraph(data)
    if conflict_text:
        paragraphs.append(conflict_text)

    gap_text = _gaps_paragraph(data)
    if gap_text:
        paragraphs.append(gap_text)

    paragraphs.append(_tests_paragraph(data))
    paragraphs.append(_appointments_paragraph(data))
    paragraphs.append(_next_steps_paragraph(data))

    limitations = [str(x).strip() for x in (data.get("limitations") or []) if str(x).strip()]
    if limitations:
        paragraphs.append(
            "Please remember: this is a training system with made-up patients — "
            "not for real medical decisions."
        )

    closing = (
        "With best wishes,\n"
        "Cardiology Office\n"
        "Northbridge Hospital (training system only)"
    )
    paragraphs.append(closing)

    return "\n\n".join(paragraphs)


QUERY_MODE_INTROS = {
    "patient_db": (
        "I looked this up directly in the patient record — "
        "no policy search or drug label service was used."
    ),
    "medical_api": (
        "This answer comes from the openFDA drug label service — "
        "not from the hospital record or policy library."
    ),
    "hospital_rag": (
        "This answer comes from the hospital staff directory and policy guidance — "
        "not from the patient's medical record."
    ),
}


def format_query_response(data: dict[str, Any], *, clinician_id: str) -> str:
    """Plain-English answer for routed factual, medical, or hospital questions."""
    mode = data.get("query_mode", "unknown")
    review = data.get("review")
    if mode == "full_review" and review:
        return format_secretary_letter(review, clinician_id=clinician_id)

    answer = (data.get("answer") or "").strip()
    intro = QUERY_MODE_INTROS.get(mode, "Here is what I found:")
    paragraphs = [
        "Hello,",
        intro,
        answer or "I couldn't find an answer for that question.",
        (
            "Please remember: this is a training system with made-up patients — "
            "not for real medical decisions."
        ),
        (
            "With best wishes,\n"
            "Cardiology Office\n"
            "Northbridge Hospital (training system only)"
        ),
    ]
    return "\n\n".join(paragraphs)
