"""Configuration for Streamlit frontend."""

from __future__ import annotations

import os

# API Configuration
API_BASE_URL = os.environ.get("FASTAPI_URL", "http://localhost:8000")
API_TIMEOUT = int(os.environ.get("API_TIMEOUT", "30"))

# Streamlit Configuration
STREAMLIT_CONFIG = {
    "page_title": "Cardiology Clinical Decision Support",
    "page_icon": "🏥",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
}

# UI Constants
PATIENT_ID_FORMAT = "P1005"  # Example format
PATIENT_ID_HELP = "Enter patient ID (e.g., P1005)"
QUESTION_PLACEHOLDER = "Enter your clinical question (e.g., 'Review patient medications and allergies')"

# Session state keys
SESSION_KEYS = {
    "patient_id": "patient_id",
    "patient_data": "patient_data",
    "query_history": "query_history",
    "current_response": "current_response",
    "loading": "loading",
    "error": "error",
}

# Display settings
MAX_QUESTION_LENGTH = 500
RESPONSE_TRUNCATE_LENGTH = 2000
SOURCE_TRUNCATE_LENGTH = 300

# Timeout messages
TIMEOUT_MESSAGE = "Request timed out. Please try again."
CONNECTION_ERROR_MESSAGE = "Unable to connect to the API. Please ensure the FastAPI server is running."
