"""Main Streamlit frontend application."""

from __future__ import annotations

import logging
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
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure Streamlit
st.set_page_config(**STREAMLIT_CONFIG)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .subtitle {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .query-container {
        background-color: #f0f2f6;
        padding: 2rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    .response-container {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
        margin: 1rem 0;
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
        except:
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


def main():
    """Main application entry point."""
    # Initialize session state
    initialize_session_state()
    
    # Header
    st.markdown(
        '<div class="main-header">🏥 Cardiology Clinical Decision Support</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="subtitle">AI-powered clinical decision support for cardiologists</div>',
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
            value=st.session_state.get(SESSION_KEYS["patient_id"], ""),
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
        
        # Main content
        if not patient_id:
            st.info("👈 **Please enter a patient ID in the sidebar to get started**")
            st.divider()
            
            with st.container():
                st.subheader("ℹ️ How to use this application")
                st.write("""
                1. **Enter Patient ID** - Use the patient selector on the left sidebar
                2. **Enter Your Question** - Ask clinical questions about the patient
                3. **Review Results** - See agent responses, sources, and tools used
                4. **View Trace ID** - Access observability data for detailed logs
                
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
        
        # Process query
        if submit_button:
            if not question.strip():
                st.error("Please enter a question")
            else:
                response = submit_query(client, patient_id, question)
                
                if response:
                    st.session_state[SESSION_KEYS["current_response"]] = response
        
        # Display response
        if st.session_state.get(SESSION_KEYS["current_response"]):
            st.divider()
            response = st.session_state[SESSION_KEYS["current_response"]]
            display_agent_response(response)
    
    finally:
        client.close()


if __name__ == "__main__":
    main()
