from __future__ import annotations

import requests
import streamlit as st

from ui_shared import (
    API_URL,
    inject_styles,
    render_hero,
    render_summary_letter,
)

st.set_page_config(
    page_title="Heart Care Summary",
    page_icon="💙",
    layout="centered",
    initial_sidebar_state="collapsed",
)

inject_styles()
render_hero(
    icon="💙",
    title="Heart Care Summary",
    subtitle=(
        "Ask anything in plain English — mention a patient by number (P1001) or name, "
        "or ask about medicines, hospital staff, and policies."
    ),
)

question = st.text_area(
    "What do you need to know?",
    value=(
        "For patient P1001, please check the heart record, medicines, recent test results, "
        "and tell me clearly what should happen next."
    ),
    height=120,
    help=(
        "Examples:\n"
        "• For P1001, what should happen next? (full care summary)\n"
        "• When did Training Record 105 last have a heart test? (patient record)\n"
        "• What are the side effects of warfarin? (drug label API)\n"
        "• Who handles heart failure cases? (hospital staff & policies)"
    ),
    label_visibility="visible",
)

st.page_link("pages/2_Add_New_Patient.py", label="Add a new patient to the database", icon="➕")

submit = st.button("Get my answer", type="primary", use_container_width=True)

if submit:
    question_text = question.strip()
    if not question_text:
        st.error("Please enter a question.")
        st.stop()

    with st.spinner("Finding the best answer for your question…"):
        try:
            resp = requests.post(
                f"{API_URL}/api/v1/queries",
                json={
                    "clinical_question": question_text,
                    "mode": "auto",
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.HTTPError:
            detail = ""
            try:
                detail = resp.json().get("detail", "")
            except Exception:  # noqa: BLE001
                pass
            st.error(detail or "Sorry — the service is not available right now.")
            st.stop()
        except requests.RequestException:
            st.error(
                "Sorry — the summary service is not available right now. "
                "Please try again in a few minutes."
            )
            st.stop()

    mode_labels = {
        "full_review": "Full care summary",
        "patient_db": "Patient record lookup",
        "medical_api": "Drug label lookup (openFDA)",
        "hospital_rag": "Hospital staff & policies",
    }
    mode = data.get("query_mode", "unknown")
    st.caption(f"Answer source: {mode_labels.get(mode, mode)}")

    render_summary_letter(data, clinician_id="Colleague")
