"""Main Streamlit frontend application."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx
import streamlit as st

from frontend.api_client import APIClient
from frontend.config import (
    API_BASE_URL,
    API_TIMEOUT,
    PATIENT_ID_HELP,
    QUESTION_PLACEHOLDER,
    SESSION_KEYS,
    STREAMLIT_CONFIG,
)
from frontend.ui_components import (
    display_agent_response,
    display_api_status,
    display_error_message,
    display_patient_overview,
    display_query_history,
    display_rag_documents,
    display_thinking_process,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure Streamlit
st.set_page_config(**STREAMLIT_CONFIG)

SIDEBAR_PATIENT_WIDGET_KEY = "sidebar_patient_id_widget"

# Custom CSS -- a vibrant, cardiology-themed palette (magenta -> violet -> blue)
# used consistently for the hero banner, tabs, buttons, and cards.
st.markdown("""
<style>
    .hero-banner {
        background: linear-gradient(135deg, #FF4D6D 0%, #8338EC 55%, #3A86FF 100%);
        border-radius: 16px;
        padding: 1.75rem 2rem;
        margin-bottom: 1.5rem;
        color: #ffffff;
        box-shadow: 0 8px 24px rgba(131, 56, 236, 0.25);
    }
    .hero-banner h1 {
        margin: 0;
        font-size: 2.3rem;
    }
    .hero-banner p {
        margin: 0.35rem 0 0;
        opacity: 0.94;
        font-size: 1.05rem;
    }
    .query-container {
        background: linear-gradient(135deg, #EEF3FF 0%, #F3ECFF 100%);
        padding: 1.75rem;
        border-radius: 12px;
        margin: 1rem 0;
        border: 1px solid #E3D9FA;
    }
    .response-container {
        background: rgba(131, 56, 236, 0.04);
        padding: 1.5rem;
        border-radius: 12px;
        border-left: 5px solid #8338EC;
        margin: 0 0 1rem;
    }
    [data-testid="stTabs"] button[data-baseweb="tab"] {
        font-weight: 600;
        font-size: 1rem;
    }
    [data-testid="stTabs"] button[aria-selected="true"] {
        color: #8338EC;
    }
    div.stButton > button[kind="primary"],
    div.stFormSubmitButton > button[kind="primary"] {
        background: linear-gradient(135deg, #FF4D6D 0%, #8338EC 100%);
        border: none;
        font-weight: 700;
        color: #ffffff;
    }
    div.stButton > button[kind="primary"]:hover,
    div.stFormSubmitButton > button[kind="primary"]:hover {
        filter: brightness(1.08);
        color: #ffffff;
    }
    [data-testid="stMetric"] {
        background: rgba(131, 56, 236, 0.06);
        border: 1px solid rgba(131, 56, 236, 0.18);
        border-radius: 10px;
        padding: 0.6rem 0.8rem;
    }
</style>
""", unsafe_allow_html=True)


def initialize_session_state():
    """Initialize Streamlit session state."""
    for key in SESSION_KEYS.values():
        if key not in st.session_state:
            if key == SESSION_KEYS["query_history"]:
                st.session_state[key] = []
            elif key == SESSION_KEYS["loading"]:
                st.session_state[key] = False
            else:
                st.session_state[key] = None

    # Consume a pending "jump to this patient" request (set by patient
    # registration) *before* the sidebar widget below is instantiated --
    # Streamlit forbids setting a widget-bound session_state key afterwards.
    pending_patient_id = st.session_state.pop("_pending_patient_id", None)
    if pending_patient_id:
        st.session_state[SIDEBAR_PATIENT_WIDGET_KEY] = pending_patient_id


def check_api_health(client: APIClient) -> bool:
    """Check if API is healthy.

    Args:
        client: API client instance

    Returns:
        Whether API is healthy
    """
    try:
        response = client.health_check()
        return response.get("status") == "healthy"
    except (httpx.RequestError, httpx.HTTPStatusError):
        return False


def fetch_patient_data(client: APIClient, patient_id: str) -> dict[str, Any] | None:
    """Fetch patient data from API.

    Args:
        client: API client instance
        patient_id: Patient ID to fetch

    Returns:
        Patient data or None if error
    """
    try:
        response = client.get_patient(patient_id)
        return response.get("data", {})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            display_error_message(f"Patient {patient_id} not found", "warning")
        else:
            display_error_message(f"Error fetching patient: {e}", "error")
        return None
    except httpx.RequestError as e:
        display_error_message(f"Connection error: {e}", "error")
        return None


def submit_query(client: APIClient, patient_id: str, question: str) -> dict[str, Any] | None:
    """Submit query to API.

    Args:
        client: API client instance
        patient_id: Patient ID
        question: Clinical question

    Returns:
        Query response or None if error
    """
    try:
        st.session_state[SESSION_KEYS["loading"]] = True

        with st.spinner("Processing your query..."):
            response = client.query(patient_id, question)

        st.session_state[SESSION_KEYS["loading"]] = False

        # Store in history
        query_record = {
            "patient_id": patient_id,
            "question": question,
            "answer": response.get("answer", ""),
            "tools_used": response.get("tools_used", []),
            "trace_id": response.get("trace_id", ""),
        }
        st.session_state[SESSION_KEYS["query_history"]].append(query_record)

        return response

    except httpx.HTTPStatusError as e:
        st.session_state[SESSION_KEYS["loading"]] = False
        error_detail = f"HTTP {e.response.status_code}"
        try:
            error_data = e.response.json()
            error_detail = error_data.get("detail", error_detail)
        except Exception:
            pass
        display_error_message(f"Query failed: {error_detail}", "error")
        return None
    except httpx.TimeoutException:
        st.session_state[SESSION_KEYS["loading"]] = False
        display_error_message("Request timed out. Please try again.", "error")
        return None
    except httpx.RequestError as e:
        st.session_state[SESSION_KEYS["loading"]] = False
        display_error_message(f"Connection error: {str(e)}", "error")
        return None


def render_ask_question_tab(client: APIClient, patient_id: str | None) -> None:
    """Render the main query workflow: patient overview, question box, thinking trace, answer."""
    if not patient_id:
        st.info("👈 **Please enter a patient ID in the sidebar to get started**")
        st.divider()
        with st.container():
            st.subheader("ℹ️ How to use this application")
            st.write("""
            1. **Enter Patient ID** - Use the patient selector on the left sidebar, or register a new patient in the **🆕 Register Patient** tab
            2. **Enter Your Question** - Ask clinical questions about the patient
            3. **Watch the Agent Think** - See which tools it calls and what it finds, before the final answer
            4. **Review Results** - See the agent's answer, sources, and tools used

            **Example Questions:**
            - "Review patient P1005's cardiovascular history"
            - "What medications is patient P1005 currently taking?"
            - "Are there any drug interactions with Warfarin?"
            - "Show me the cardiology guidelines for hypertension management"
            """)
        return

    # Patient overview section
    st.subheader("📋 Patient Overview")
    if st.session_state.get(SESSION_KEYS["patient_data"]):
        display_patient_overview(st.session_state[SESSION_KEYS["patient_data"]])
    else:
        st.warning("Patient data not available")

    st.divider()

    # Query section
    st.subheader("❓ Clinical Question")
    with st.container():
        st.markdown('<div class="query-container">', unsafe_allow_html=True)
        col1, col2 = st.columns([4, 1])

        with col1:
            question = st.text_area(
                "Ask a clinical question about this patient",
                height=80,
                placeholder=QUESTION_PLACEHOLDER,
                label_visibility="collapsed",
            )

        with col2:
            st.write("")  # Spacing
            submit_button = st.button(
                "🔍 Submit",
                use_container_width=True,
                type="primary",
            )
        st.markdown("</div>", unsafe_allow_html=True)

    # Process query
    just_answered = False
    if submit_button:
        if not question.strip():
            st.error("Please enter a question")
        else:
            response = submit_query(client, patient_id, question)
            if response:
                st.session_state[SESSION_KEYS["current_response"]] = response
                just_answered = True

    # Display response (thinking trace, then the answer)
    if st.session_state.get(SESSION_KEYS["current_response"]):
        st.divider()
        response = st.session_state[SESSION_KEYS["current_response"]]
        display_thinking_process(response.get("steps", []), animate=just_answered)
        display_agent_response(response)


def render_register_patient_tab(client: APIClient) -> None:
    """Render the new-patient registration form, writing straight to DynamoDB."""
    st.subheader("🆕 Register a New Patient")
    st.caption("Creates a new patient profile directly in DynamoDB -- the only write path in this application.")

    with st.form("register_patient_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            first_name = st.text_input("First name*")
            dob = st.date_input(
                "Date of birth*", value=date(1970, 1, 1), min_value=date(1920, 1, 1), max_value=date.today()
            )
            gender = st.selectbox("Gender*", ["Female", "Male", "Non-binary"])
            patient_id_input = st.text_input(
                "Patient ID (optional)",
                placeholder="Leave blank to auto-generate",
                help="Format: P followed by 4-12 digits, e.g. P200481",
            )
        with col2:
            last_name = st.text_input("Last name*")
            smoking_status = st.selectbox("Smoking status*", ["Never smoker", "Former smoker", "Current smoker"])
            family_history = st.checkbox("Known family history of cardiovascular disease")
            primary_cardiologist = st.text_input("Primary cardiologist", placeholder="e.g. DR101 (optional)")

        submitted = st.form_submit_button("✅ Register Patient", type="primary", use_container_width=True)

    if not submitted:
        return

    if not first_name.strip() or not last_name.strip():
        st.error("First and last name are required.")
        return

    payload: dict[str, Any] = {
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "date_of_birth": dob.isoformat(),
        "gender": gender,
        "smoking_status": smoking_status,
        "family_history_cardiovascular_disease": family_history,
        "primary_cardiologist": primary_cardiologist.strip() or None,
    }
    if patient_id_input.strip():
        payload["patient_id"] = patient_id_input.strip().upper()

    try:
        with st.spinner("Registering patient..."):
            result = client.create_patient(payload)
        st.success(f"✅ {result['message']}")
        st.session_state["_pending_patient_id"] = result["patient_id"]
        st.info(f"Loaded **{result['patient_id']}** in the sidebar -- switch to **💬 Ask a Question** to review them.")
        st.rerun()
    except httpx.HTTPStatusError as e:
        detail: Any = e.response.status_code
        try:
            detail = e.response.json().get("detail", detail)
        except Exception:
            pass
        st.error(f"Registration failed: {detail}")
    except httpx.RequestError as e:
        st.error(f"Connection error: {e}")


def render_manage_guidelines_tab(client: APIClient) -> None:
    """Render the RAG document inventory plus add/update/delete controls."""
    st.subheader("📚 Manage Cardiology Guidelines")
    st.caption(
        "Documents are chunked, embedded, and indexed into the OpenSearch Serverless "
        "knowledge base the guideline-search tool retrieves from. New or updated documents "
        "can take up to about 15 seconds to become searchable (Serverless indexes "
        "near-real-time, not instantly) -- refresh this tab if one doesn't show up right away."
    )

    documents: list[dict[str, Any]] = []
    rag_available = True
    try:
        documents = client.list_rag_documents()
    except httpx.HTTPStatusError as e:
        rag_available = False
        if e.response.status_code == 503:
            st.warning("⚠️ RAG document management is not configured on the backend.")
        else:
            st.error(f"Failed to load documents: HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        rag_available = False
        st.error(f"Connection error: {e}")

    display_rag_documents(documents)

    if not rag_available:
        return

    st.divider()
    st.markdown("#### ➕ Add or Update a Document")
    st.caption("Adding a document with a name that already exists replaces all of its previously indexed content.")
    with st.form("rag_upsert_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            doc_name = st.text_input("Document name*", placeholder="e.g. Beta-Blocker Titration Protocol")
            doc_version = st.text_input("Version*", value="1.0")
        with col2:
            doc_effective_date = st.text_input("Effective date*", value=date.today().isoformat())
            doc_source = st.text_input("Source*", placeholder="e.g. Cardiology Department Policy")
        doc_content = st.text_area(
            "Content (Markdown)*",
            height=220,
            placeholder="## Scope\n...\n\n## Recommendation\n...",
            help="Use '## Section Name' headings to split the document into retrievable sections.",
        )
        upsert_submitted = st.form_submit_button("📤 Index Document", type="primary", use_container_width=True)

    if upsert_submitted:
        if not all(f.strip() for f in (doc_name, doc_version, doc_effective_date, doc_source, doc_content)):
            st.error("All fields are required.")
        else:
            try:
                with st.spinner("Chunking, embedding, and indexing..."):
                    result = client.upsert_rag_document(
                        {
                            "document_name": doc_name.strip(),
                            "version": doc_version.strip(),
                            "effective_date": doc_effective_date.strip(),
                            "source": doc_source.strip(),
                            "content": doc_content,
                        }
                    )
                st.success(f"✅ {result['message']}")
                st.rerun()
            except httpx.HTTPStatusError as e:
                detail: Any = e.response.status_code
                try:
                    detail = e.response.json().get("detail", detail)
                except Exception:
                    pass
                st.error(f"Indexing failed: {detail}")
            except httpx.RequestError as e:
                st.error(f"Connection error: {e}")

    if documents:
        st.divider()
        st.markdown("#### 🗑️ Delete a Document")
        doc_to_delete = st.selectbox("Choose a document to remove", [d["document_name"] for d in documents])
        if st.button("Delete Document"):
            try:
                result = client.delete_rag_document(doc_to_delete)
                st.success(f"Deleted {result['chunks_deleted']} chunk(s) for '{doc_to_delete}'.")
                st.rerun()
            except httpx.HTTPStatusError as e:
                st.error(f"Delete failed: HTTP {e.response.status_code}")
            except httpx.RequestError as e:
                st.error(f"Connection error: {e}")


def main():
    """Main application entry point."""
    # Initialize session state
    initialize_session_state()

    # Header
    st.markdown(
        """
        <div class="hero-banner">
            <h1>🫀 Cardiology Clinical Decision Support</h1>
            <p>AI-powered, tool-grounded decision support for cardiologists</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Initialize API client
    try:
        client = APIClient(base_url=API_BASE_URL, timeout=API_TIMEOUT)
        is_api_healthy = check_api_health(client)
        display_api_status(is_api_healthy)

        if not is_api_healthy:
            st.error(
                "⚠️ **API Not Available**\n\n"
                "The FastAPI backend is not responding. "
                "Please ensure it is running at " + API_BASE_URL
            )
            return
    except Exception as e:
        logger.error(f"Failed to initialize API client: {e}")
        st.error("Failed to initialize API client")
        return

    try:
        # Sidebar: Patient Selection
        st.sidebar.title("👤 Patient Selection")

        patient_id = st.sidebar.text_input(
            "Patient ID",
            key=SIDEBAR_PATIENT_WIDGET_KEY,
            help=PATIENT_ID_HELP,
            placeholder="P1005",
        )

        # Fetch patient data if ID provided
        if patient_id:
            if patient_id != st.session_state.get(SESSION_KEYS["patient_id"]):
                st.session_state[SESSION_KEYS["patient_id"]] = patient_id
                patient_data = fetch_patient_data(client, patient_id)
                if patient_data:
                    st.session_state[SESSION_KEYS["patient_data"]] = patient_data
                else:
                    st.session_state[SESSION_KEYS["patient_data"]] = None

            # Display patient overview
            if st.session_state.get(SESSION_KEYS["patient_data"]):
                st.sidebar.divider()
                st.sidebar.subheader("👤 Patient Overview")
                with st.sidebar.container():
                    patient_data = st.session_state[SESSION_KEYS["patient_data"]]
                    st.sidebar.metric("Name", f"{patient_data.get('first_name', '')} {patient_data.get('last_name', '')}".strip())
                    st.sidebar.metric("DOB", patient_data.get("date_of_birth", "N/A"))
                    st.sidebar.metric("Gender", patient_data.get("gender", "N/A"))

            # Display query history
            display_query_history(st.session_state[SESSION_KEYS["query_history"]])

        # Main content: tabbed workflow
        tab_ask, tab_register, tab_manage = st.tabs(
            ["💬 Ask a Question", "🆕 Register Patient", "📚 Manage Guidelines"]
        )

        with tab_ask:
            render_ask_question_tab(client, patient_id)

        with tab_register:
            render_register_patient_tab(client)

        with tab_manage:
            render_manage_guidelines_tab(client)

    finally:
        client.close()


if __name__ == "__main__":
    main()
