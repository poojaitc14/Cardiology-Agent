from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
import streamlit as st

from cardiologist_agent.services.patient_factory import CONDITION_CHOICES, MEDICATION_CHOICES
from ui_shared import (
    API_URL,
    fetch_patient_catalog,
    inject_styles,
    normalize_patient_id,
    patient_id_exists,
    render_hero,
    render_summary_letter,
)

st.set_page_config(
    page_title="Add New Patient",
    page_icon="➕",
    layout="centered",
    initial_sidebar_state="collapsed",
)

inject_styles()
render_hero(
    icon="➕",
    title="Add New Patient",
    subtitle=(
        "Create a training patient record and get an immediate plain-English "
        "heart care summary for ward or reception staff."
    ),
)

try:
    catalog = fetch_patient_catalog()
except requests.RequestException:
    st.error("Could not load patient list from the API. Please try again shortly.")
    st.stop()

all_patient_ids: list[str] = catalog.get("patient_ids", [])
suggested_id = catalog.get("suggested_next_id", "P1131")

patient_id = st.text_input(
    "Patient reference number",
    value=suggested_id,
    placeholder=f"e.g. {suggested_id}",
    help="Enter any custom ID. It must not already exist in the database.",
)
st.caption(f"Suggested next free ID: **{suggested_id}**")

condition_name = st.selectbox("Main heart-related concern", options=CONDITION_CHOICES)
on_medication = st.checkbox("Patient is already on heart medicine", value=False)
medication_name = None
if on_medication:
    medication_name = st.selectbox("Current medicine", options=MEDICATION_CHOICES)
primary_cardiologist = st.text_input("Cardiologist ID", value="DR104")
clinician_id = st.text_input("Your name or staff ID", value="Reception")
question = st.text_area(
    "What should the summary cover?",
    value=(
        "Please check the heart record, medicines, recent test results, "
        "and tell me clearly what should happen next."
    ),
    height=88,
)

submit = st.button(
    "Create patient & get summary",
    type="primary",
    use_container_width=True,
)

if submit:
    chosen_id = normalize_patient_id(patient_id) or suggested_id
    if patient_id_exists(chosen_id, all_patient_ids):
        st.error(
            f"Patient **{chosen_id}** already exists. "
            "Please choose a different patient ID."
        )
        st.stop()

    payload = {
        "patient_id": chosen_id,
        "condition_name": condition_name,
        "on_medication": on_medication,
        "medication_name": medication_name,
        "primary_cardiologist": primary_cardiologist.strip() or "DR104",
        "clinician_id": clinician_id.strip() or "Reception",
        "clinical_question": question.strip(),
        "run_review": True,
    }
    with st.spinner("Creating the record and preparing your summary…"):
        try:
            resp = requests.post(f"{API_URL}/api/v1/patients", json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
        except requests.HTTPError:
            detail = ""
            try:
                detail = resp.json().get("detail", "")
            except Exception:  # noqa: BLE001
                pass
            if resp.status_code == 409:
                st.error(f"That patient reference is already in use. {detail}".strip())
            else:
                st.error("Sorry — we could not create the patient right now. Please try again.")
            st.stop()
        except requests.RequestException:
            st.error("Sorry — the service is not available right now. Please try again shortly.")
            st.stop()

    fetch_patient_catalog.clear()
    st.success(f"Patient {data['patient_id']} has been added to the training records.")

    review = data.get("review")
    if review:
        render_summary_letter(
            {"query_mode": "full_review", "review": review},
            clinician_id=clinician_id.strip() or "Reception",
        )
    else:
        st.info("The patient was created but no summary was returned.")
