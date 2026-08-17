"""Run: streamlit run frontend/streamlit_app.py (synthetic/development use only)."""
import json
import os
from datetime import date, datetime
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
EVALUATION_RESULTS_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "evaluation_results.json"
)

def post(path: str, payload: dict):
    try:
        response = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=30)
        return response.ok, response.json()
    except requests.RequestException as error:
        return False, str(error)

def show_error(result):
    st.error(result.get("detail", result) if isinstance(result, dict) else result)

def show_evaluation_results():
    st.markdown("### Evaluation")
    if not EVALUATION_RESULTS_PATH.exists():
        st.info("Evaluation results are not available yet.")
        return
    try:
        results = json.loads(EVALUATION_RESULTS_PATH.read_text(encoding="utf-8"))
        aggregates = results["aggregate_metrics"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        st.info("Evaluation results are not available yet.")
        return

    metric_labels = (
        ("Context Precision", "context_precision"),
        ("Context Recall", "context_recall"),
        ("Faithfulness", "faithfulness"),
        ("Answer Relevancy", "answer_relevancy"),
        ("Policy Section Recall", "policy_section_recall"),
        ("Source Type Recall", "source_type_recall"),
        ("Citation Validity", "citation_validity"),
        ("Guardrail Compliance", "guardrail_compliance"),
        ("Prompt Injection Blocked", "prompt_injection_blocked"),
    )
    rows = []
    for label, key in metric_labels:
        value = aggregates.get(key)
        rows.append({
            "Metric": label,
            "Score": f"{value:.3f}" if isinstance(value, (int, float)) else "Not available",
        })
    st.table(rows)

st.set_page_config(page_title="CardioLens | Clinical Review", page_icon="♥", layout="wide")
style = Path(__file__).parent / "assets" / "styles.css"
st.markdown(f"<style>{style.read_text()}</style>", unsafe_allow_html=True)
st.markdown("<section class='hero'><div><p class='eyebrow'>CARDIOLOGY CLINICAL INTELLIGENCE</p><h1>Cardio<span>Lens</span></h1><p>Evidence-led clinical review, designed for clinician verification.</p></div><div class='status'>● DEVELOPMENT<br><small>Synthetic data only</small></div></section>", unsafe_allow_html=True)

review, admin, safety = st.tabs(["Clinical Review Agent", "Administration", "Data & Safety"])
with review:
    st.markdown("### Evidence-led patient review")
    a, b = st.columns([1, 2])
    patient_id = a.text_input("Patient ID", "P1005")
    clinician_id = a.text_input("Clinician ID", "clinician-demo")
    question = b.text_area("Clinical question", "Review cardiovascular history, current medication, recent labs, and approved policy. Highlight information requiring my attention.", height=115)
    if st.button("Generate clinical review", type="primary", use_container_width=True):
        with st.spinner("Retrieving validated evidence…"):
            ok, result = post("/v1/reviews", {"patient_id": patient_id, "requesting_user_id": clinician_id, "question": question})
        if not ok: show_error(result)
        else:
            st.success("Review generated. Verify all facts in the source clinical record.")
            st.markdown(f"#### Clinical summary\n{result['summary']}")
            sections = [("Cardiovascular history", "cardiovascular_history"), ("Current medications", "current_medications"), ("Allergies / intolerances", "allergies"), ("Recent laboratory results", "recent_laboratory_results"), ("Approved knowledge & medication data", "approved_knowledge")]
            for title, key in sections:
                with st.expander(title, expanded=key == "allergies"):
                    if result[key]:
                        for item in result[key]:
                            st.markdown(f"- {item['fact']}")
                            st.caption(f"Source: {item['source']['source_id']} · {item['source']['source_type']}")
                    else: st.info("No validated information available.")
            st.markdown("#### Items requiring review")
            for item in result["attention_items"]: st.warning(item["observation"])
            for item in result["limitations"]: st.caption(f"• {item}")
            st.caption(result["disclaimer"])

with admin:
    st.warning("Development interface only. Production requires hospital SSO, RBAC, audit logs, and approved identity workflows.")
    profile_tab, record_tab = st.tabs(["Patient profile", "Clinical record"])
    with profile_tab:
        with st.form("profile"):
            patient = st.text_input("Patient ID *", "P1005", key="profile_patient")
            x, y = st.columns(2)
            smoking = x.selectbox("Smoking status", ["", "Never", "Former", "Current", "Unknown"])
            cardiologist = y.text_input("Primary cardiologist")
            family = st.text_area("Family history of cardiovascular disease")
            submitted = st.form_submit_button("Save patient profile", type="primary")
        if submitted:
            ok, result = post("/v1/admin/patient-profiles", {"patient_id":patient,"admin_user_id":"admin-demo","smoking_status":smoking or None,"family_history_cardiovascular_disease":family or None,"primary_cardiologist":cardiologist or None})
            if ok:
                st.success("Profile saved.")
                st.caption(f"DynamoDB key: {result['PK']} / {result['SK']}")
            else:
                show_error(result)
    with record_tab:
        st.caption("Choose a category first. The form below will then change to show only the relevant fields.")
        # This selectbox is deliberately outside st.form: Streamlit forms do not
        # rerun when a field changes, which previously showed the wrong form.
        category = st.selectbox("Record category *", ["CONDITION", "LAB", "MEDICATION", "ALLERGY", "VITALS", "CARDIOLOGY_PROCEDURE"], key="record_category")
        with st.form(f"record_{category}"):
            patient = st.text_input("Patient ID *", "P1005", key=f"record_patient_{category}")
            source, status = st.columns(2)
            record_source = source.text_input("Source", "ADMIN_PORTAL", key=f"source_{category}")
            record_status = status.selectbox("Status", ["ACTIVE", "INACTIVE", "HISTORICAL"], key=f"status_{category}")
            payload = {}
            if category == "CONDITION":
                payload = {"condition_name":st.text_input("Condition name *"),"condition_category":st.text_input("Condition category"),"diagnosis_date":str(st.date_input("Diagnosis date",date.today())),"condition_status":st.selectbox("Condition status",["Active","Resolved","Historical"]),"severity":st.selectbox("Severity",["Mild","Moderate","Severe","Unknown"])}
            elif category == "LAB":
                x,y,z=st.columns(3); payload={"test_name":x.text_input("Test name *"),"test_value":y.text_input("Value *"),"test_unit":z.text_input("Unit"),"reference_range":st.text_input("Reference range"),"interpretation":st.selectbox("Interpretation",["normal","high","low","critical"]),"test_date":str(st.date_input("Test date",date.today()))}
            elif category == "MEDICATION":
                has_end_date = st.checkbox("Medication has an end date")
                payload={"medication_name":st.text_input("Medication name *"),"start_date":str(st.date_input("Start date",date.today())),"end_date":str(st.date_input("End date",date.today())) if has_end_date else None,"prescriber":st.text_input("Prescriber"),"indication":st.text_input("Indication"),"medication_status":st.selectbox("Medication status",["Active","Stopped","Held","Historical"])}
            elif category == "ALLERGY":
                payload={"allergy_name":st.text_input("Allergen / medicine *"),"allergy_type":st.selectbox("Type",["allergy","intolerance"]),"recorded_date":str(st.date_input("Recorded date",date.today()))}
            elif category == "VITALS":
                x,y,z=st.columns(3); payload={"systolic_bp":x.number_input("Systolic BP",0,300,120),"diastolic_bp":y.number_input("Diastolic BP",0,200,80),"heart_rate":z.number_input("Heart rate",0,250,70),"weight":st.number_input("Weight (kg)",0.0,500.0,70.0),"oxygen_saturation":st.number_input("Oxygen saturation (%)",0.0,100.0,98.0),"measured_at":datetime.now().astimezone().isoformat()}
            else:
                payload={"test_or_procedure_name":st.text_input("Test or procedure *",placeholder="ECG, echocardiogram, angiography…"),"performed_date":str(st.date_input("Performed date",date.today())),"result_summary":st.text_area("Result summary")}
            payload["notes"] = st.text_area("Notes")
            submitted=st.form_submit_button("Save clinical record",type="primary")
        if submitted:
            data={"patient_id":patient,"admin_user_id":"admin-demo","record_type":category,"source":record_source,"status":record_status,**payload}
            ok,result=post("/v1/admin/clinical-records",data)
            if ok:
                st.success("Clinical record saved.")
                st.caption(f"DynamoDB key: {result['PK']} / {result['SK']}")
                st.caption(f"Record ID: {result['record_id']}")
            else:
                show_error(result)

with safety:
    st.markdown("### One DynamoDB table, structured patient timeline")
    st.markdown("Each item uses `PK = PATIENT#{patient_id}` and either `SK = PROFILE` or a sortable clinical-record key. Every item has `record_id`, `created_at`, `updated_at`, `source`, and `status`; category-specific attributes remain sparse. This is one DynamoDB table without a fragile, mostly-empty wide row.")
    st.info("The agent is read-only. No draft RAG policy is retrieved, and medication API data is not yet configured.")
    show_evaluation_results()
