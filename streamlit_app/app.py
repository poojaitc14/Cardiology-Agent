from __future__ import annotations

import html
import os

import requests
import streamlit as st

from cardiologist_agent.ui.narrative import format_secretary_letter

API_URL = (
    os.getenv("API_BASE_URL")
    or os.getenv("STREAMLIT_API_URL")
    or "http://127.0.0.1:8000"
)

st.set_page_config(
    page_title="Cardiology Review Assistant",
    page_icon="🫀",
    layout="centered",
)

st.markdown(
    """
    <style>
    .letter-box {
        background: #fafafa;
        border: 1px solid #e6e6e6;
        border-radius: 12px;
        padding: 1.75rem 2rem;
        line-height: 1.7;
        font-size: 1.05rem;
        color: #222;
        white-space: pre-wrap;
    }
    .app-caption {
        color: #666;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Cardiology Review Assistant")
st.markdown(
    '<p class="app-caption">Training environment only — fictional records, not for real patient care.</p>',
    unsafe_allow_html=True,
)

with st.form("review_form", clear_on_submit=False):
    patient_id = st.text_input("Patient record reference", value="P1001", help="Enter the patient ID to review.")
    clinician_id = st.text_input("Your clinician ID", value="DR101")
    question = st.text_area(
        "What would you like reviewed?",
        value=(
            "Please review the cardiovascular record, current medicines, recent results, "
            "and any safety concerns that need attention."
        ),
        height=100,
    )
    submit = st.form_submit_button("Prepare summary", type="primary", use_container_width=True)

if submit:
    if not patient_id.strip():
        st.error("Please enter a patient record reference.")
        st.stop()

    with st.spinner("Preparing your summary…"):
        try:
            resp = requests.post(
                f"{API_URL}/api/v1/reviews",
                json={
                    "patient_id": patient_id.strip(),
                    "clinician_id": clinician_id.strip(),
                    "clinical_question": question.strip(),
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            st.error(
                "The review service is temporarily unavailable. "
                "Please try again shortly or contact your system administrator."
            )
            st.stop()

    letter = format_secretary_letter(data, clinician_id=clinician_id.strip() or "Colleague")
    st.markdown("### Summary for your attention")
    st.markdown(
        f'<div class="letter-box">{html.escape(letter)}</div>',
        unsafe_allow_html=True,
    )
