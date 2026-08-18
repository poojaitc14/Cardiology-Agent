from __future__ import annotations

import html
import os

import requests
import streamlit as st

from cardiologist_agent.ui.narrative import format_query_response, format_secretary_letter

API_URL = (
    os.getenv("API_BASE_URL")
    or os.getenv("STREAMLIT_API_URL")
    or "http://127.0.0.1:8000"
)

PAGE_STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Source+Sans+3:wght@400;500;600&display=swap');

.stApp {
    background: linear-gradient(165deg, #f0f7fa 0%, #fdf8f3 45%, #eef4f8 100%);
}

[data-testid="stHeader"] { background: transparent; }

.hero {
    text-align: center;
    padding: 0.5rem 0 1.75rem 0;
}
.hero-icon {
    font-size: 2.4rem;
    line-height: 1;
    margin-bottom: 0.35rem;
}
.hero h1 {
    font-family: 'Fraunces', Georgia, serif;
    font-weight: 600;
    font-size: 2.15rem;
    color: #1a3a4a;
    margin: 0 0 0.4rem 0;
    letter-spacing: -0.02em;
}
.hero p {
    font-family: 'Source Sans 3', sans-serif;
    color: #5a6c76;
    font-size: 1.05rem;
    max-width: 34rem;
    margin: 0 auto;
    line-height: 1.55;
}
.badge {
    display: inline-block;
    margin-top: 0.85rem;
    padding: 0.3rem 0.85rem;
    border-radius: 999px;
    background: #fff;
    border: 1px solid #d6e4ea;
    color: #6b7f89;
    font-size: 0.82rem;
    font-family: 'Source Sans 3', sans-serif;
}

[data-testid="stForm"] {
    background: #ffffffcc;
    backdrop-filter: blur(8px);
    border: 1px solid #e2ecf1;
    border-radius: 18px;
    padding: 1.25rem 1.5rem 0.5rem 1.5rem;
    box-shadow: 0 8px 32px rgba(26, 58, 74, 0.06);
}

.stTextInput label, .stTextArea label, .stSelectbox label {
    font-family: 'Source Sans 3', sans-serif !important;
    font-weight: 600 !important;
    color: #2c4a58 !important;
}

div[data-testid="stFormSubmitButton"] button {
    font-family: 'Source Sans 3', sans-serif;
    font-weight: 600;
    border-radius: 12px;
    padding: 0.65rem 1rem;
    background: linear-gradient(135deg, #2a6f84 0%, #1f5566 100%);
    border: none;
    box-shadow: 0 4px 14px rgba(31, 85, 102, 0.25);
}
div[data-testid="stFormSubmitButton"] button:hover {
    background: linear-gradient(135deg, #327f96 0%, #256278 100%);
    border: none;
    color: white;
}

.letter-shell {
    margin-top: 1.5rem;
}
.letter-heading {
    font-family: 'Source Sans 3', sans-serif;
    font-weight: 600;
    font-size: 0.92rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #5a8294;
    margin-bottom: 0.75rem;
}
.letter-box {
    background: #fff;
    border: 1px solid #e6eef2;
    border-left: 4px solid #3a8fa8;
    border-radius: 16px;
    padding: 2rem 2.15rem;
    line-height: 1.85;
    font-size: 1.08rem;
    color: #24343c;
    white-space: pre-wrap;
    font-family: 'Fraunces', Georgia, serif;
    box-shadow: 0 12px 40px rgba(26, 58, 74, 0.07);
}

.match-hint {
    font-family: 'Source Sans 3', sans-serif;
    font-size: 0.88rem;
    color: #6b7f89;
    margin: -0.35rem 0 0.75rem 0;
}
</style>
"""


def inject_styles() -> None:
    st.markdown(PAGE_STYLES, unsafe_allow_html=True)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_patient_catalog() -> dict:
    resp = requests.get(f"{API_URL}/api/v1/patients", timeout=30)
    resp.raise_for_status()
    return resp.json()


def filter_patient_ids(all_ids: list[str], query: str) -> list[str]:
    needle = query.strip().upper()
    if not needle:
        return all_ids
    return [pid for pid in all_ids if needle in pid.upper()]


def patient_id_exists(patient_id: str, all_ids: list[str]) -> bool:
    needle = patient_id.strip().upper()
    return needle in {pid.upper() for pid in all_ids}


def normalize_patient_id(patient_id: str) -> str:
    return patient_id.strip().upper()


def render_hero(*, icon: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-icon">{icon}</div>
            <h1>{html.escape(title)}</h1>
            <p>{html.escape(subtitle)}</p>
            <span class="badge">Training only · fictional records</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_summary_letter(data: dict, *, clinician_id: str) -> None:
    if data.get("query_mode") and data.get("query_mode") != "full_review":
        letter = format_query_response(data, clinician_id=clinician_id or "Colleague")
    elif data.get("review"):
        letter = format_query_response(data, clinician_id=clinician_id or "Colleague")
    else:
        letter = format_secretary_letter(data, clinician_id=clinician_id or "Colleague")
    st.markdown('<div class="letter-shell">', unsafe_allow_html=True)
    st.markdown('<div class="letter-heading">Your summary</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="letter-box">{html.escape(letter)}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
