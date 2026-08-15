"""Reusable UI components for Streamlit frontend."""

from __future__ import annotations

import streamlit as st
from typing import Any

from .config import RESPONSE_TRUNCATE_LENGTH, SOURCE_TRUNCATE_LENGTH


def display_patient_overview(patient_data: dict[str, Any]) -> None:
    """Display patient overview information.
    
    Args:
        patient_data: Patient profile data from API
    """
    with st.container():
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                "Patient ID",
                patient_data.get("patient_id", "N/A"),
            )
        
        with col2:
            first_name = patient_data.get("first_name", "")
            last_name = patient_data.get("last_name", "")
            name = f"{first_name} {last_name}".strip() or "N/A"
            st.metric("Name", name)
        
        with col3:
            dob = patient_data.get("date_of_birth", "N/A")
            st.metric("DOB", dob)
        
        # Secondary row
        col1, col2, col3 = st.columns(3)
        
        with col1:
            gender = patient_data.get("gender", "N/A")
            st.metric("Gender", gender)
        
        with col2:
            smoking = patient_data.get("smoking_status", "N/A")
            st.metric("Smoking Status", smoking)
        
        with col3:
            family_hx = patient_data.get("family_history_cardiovascular_disease")
            family_hx_text = "Yes" if family_hx else "No" if family_hx is False else "N/A"
            st.metric("Cardiac Family Hx", family_hx_text)


def display_agent_response(response: dict[str, Any]) -> None:
    """Display agent response with all components.
    
    Args:
        response: Query response from API
    """
    with st.container():
        # Answer section
        st.subheader("📋 Clinical Decision Support")
        answer = response.get("answer", "No answer provided")
        
        # Truncate if too long but show indicator
        if len(answer) > RESPONSE_TRUNCATE_LENGTH:
            with st.expander(f"Answer ({len(answer)} characters)"):
                st.write(answer)
        else:
            st.write(answer)
        
        # Add visual separator
        st.divider()
        
        # Create columns for metadata
        col1, col2 = st.columns(2)
        
        # Tools used
        with col1:
            st.subheader("🛠️ Tools Used")
            tools_used = response.get("tools_used", [])
            if tools_used:
                for i, tool in enumerate(tools_used, 1):
                    tool_name = tool.replace("_", " ").title()
                    st.write(f"{i}. {tool_name}")
            else:
                st.info("No tools were used for this query")
        
        # Errors
        with col2:
            errors = response.get("errors", [])
            if errors:
                st.subheader("⚠️ Errors")
                for error in errors:
                    st.warning(error)
            else:
                st.success("✓ No errors encountered")
        
        # Sources/Citations
        st.subheader("📚 Sources & Citations")
        sources = response.get("sources", [])
        
        if sources:
            for i, source in enumerate(sources, 1):
                with st.expander(
                    f"Source {i}: {source.get('source', 'Unknown')} "
                    f"- {source.get('detail', '')[:50]}..."
                ):
                    col1, col2 = st.columns([1, 2])
                    
                    with col1:
                        st.write("**Source:** " + source.get("source", "N/A"))
                    
                    with col2:
                        detail = source.get("detail", "N/A")
                        if len(detail) > SOURCE_TRUNCATE_LENGTH:
                            st.write("**Detail:** " + detail[:SOURCE_TRUNCATE_LENGTH] + "...")
                        else:
                            st.write("**Detail:** " + detail)
        else:
            st.info("No sources available for this query")
        
        # Trace ID for observability
        trace_id = response.get("trace_id")
        if trace_id:
            st.divider()
            with st.expander("🔍 Trace Information"):
                st.code(trace_id)
                st.caption("Use this trace ID to view detailed logs in Langfuse observability dashboard")


def display_error_message(error: str, error_type: str = "error") -> None:
    """Display an error message.
    
    Args:
        error: Error message to display
        error_type: Type of message ("error", "warning", "info")
    """
    if error_type == "error":
        st.error(error)
    elif error_type == "warning":
        st.warning(error)
    else:
        st.info(error)


def display_loading_state(message: str = "Processing query...") -> None:
    """Display a loading state.
    
    Args:
        message: Message to display during loading
    """
    with st.spinner(message):
        st.empty()


def display_query_history(queries: list[dict[str, Any]]) -> None:
    """Display query history in sidebar.
    
    Args:
        queries: List of previous queries
    """
    if queries:
        st.sidebar.divider()
        st.sidebar.subheader("📜 Query History")
        
        for i, query in enumerate(reversed(queries[-10:]), 1):  # Show last 10
            question = query.get("question", "")
            truncated = question[:40] + "..." if len(question) > 40 else question
            
            with st.sidebar.expander(f"{i}. {truncated}"):
                st.write("**Question:**")
                st.write(query.get("question", ""))
                
                st.write("**Answer:**")
                answer = query.get("answer", "")
                truncated_answer = answer[:200] + "..." if len(answer) > 200 else answer
                st.write(truncated_answer)


def display_api_status(is_healthy: bool) -> None:
    """Display API health status.
    
    Args:
        is_healthy: Whether API is healthy
    """
    if is_healthy:
        st.sidebar.success("✓ API Connected")
    else:
        st.sidebar.error("✗ API Disconnected")


def format_tool_name(tool_name: str) -> str:
    """Format tool name for display.
    
    Args:
        tool_name: Tool name from API
        
    Returns:
        Formatted tool name
    """
    tool_map = {
        "patient_database_tool": "📁 Patient Database",
        "openfda_drug_tool": "💊 OpenFDA Drug",
        "cardiology_rag_tool": "📖 Cardiology Documents",
    }
    return tool_map.get(tool_name, tool_name.replace("_", " ").title())
