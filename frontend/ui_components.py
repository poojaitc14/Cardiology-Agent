"""Reusable UI components for Streamlit frontend."""

from __future__ import annotations

import time
from typing import Any

import streamlit as st

from .config import RESPONSE_TRUNCATE_LENGTH, SOURCE_TRUNCATE_LENGTH

# Fixed color per tool so the same tool always reads the same way across the app.
TOOL_META: dict[str, dict[str, str]] = {
    "patient_database_tool": {"emoji": "🩺", "label": "Patient Database", "color": "#3A86FF"},
    "openfda_drug_tool": {"emoji": "💊", "label": "OpenFDA Drug Label", "color": "#FB8500"},
    "cardiology_rag_tool": {"emoji": "📖", "label": "Guideline Search", "color": "#8338EC"},
}
DOCUMENT_CARD_PALETTE = ("#8338EC", "#3A86FF", "#FB8500", "#06D6A0", "#EF476F", "#FFB703")


def _tool_meta(tool_name: str) -> dict[str, str]:
    return TOOL_META.get(
        tool_name, {"emoji": "🔧", "label": tool_name.replace("_", " ").title(), "color": "#6C757D"}
    )


def render_tool_badge(tool_name: str) -> str:
    """Return an inline-HTML pill badge for one tool, colored consistently across the app."""
    meta = _tool_meta(tool_name)
    return (
        f'<span style="display:inline-flex;align-items:center;gap:6px;'
        f'background:{meta["color"]}1A;color:{meta["color"]};border:1px solid {meta["color"]}55;'
        f'padding:4px 12px;border-radius:999px;font-size:0.85rem;font-weight:600;'
        f'margin:2px 8px 2px 0;">{meta["emoji"]} {meta["label"]}</span>'
    )


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


def display_thinking_process(steps: list[str], animate: bool = True) -> None:
    """Display the agent's tool-routing trace before the final answer.

    Args:
        steps: Ordered, human-readable trace of what the agent did to answer
            the question (patient lookup, drug lookup, guideline search,
            answer synthesis, ...), as returned by the API.
        animate: Reveal steps one at a time with a short pause (used right
            after a fresh submission); when False, render the completed
            trace instantly (used on reruns triggered by unrelated widgets,
            so switching tabs doesn't replay the animation).
    """
    if not steps:
        return
    if animate:
        with st.status("🧠 Agent is thinking...", expanded=True) as status:
            for step in steps:
                st.write(f"• {step}")
                time.sleep(0.35)
            status.update(label="✅ Reasoning complete", state="complete", expanded=False)
    else:
        with st.status("✅ Reasoning complete", state="complete", expanded=False):
            for step in steps:
                st.write(f"• {step}")


def display_agent_response(response: dict[str, Any]) -> None:
    """Display agent response with all components.

    Args:
        response: Query response from API
    """
    with st.container():
        # Answer section
        st.markdown(
            '<div class="response-container">',
            unsafe_allow_html=True,
        )
        st.subheader("📋 Clinical Decision Support")
        answer = response.get("answer", "No answer provided")

        # Truncate if too long but show indicator
        if len(answer) > RESPONSE_TRUNCATE_LENGTH:
            with st.expander(f"Answer ({len(answer)} characters)"):
                st.write(answer)
        else:
            st.write(answer)
        st.markdown("</div>", unsafe_allow_html=True)

        # Add visual separator
        st.divider()

        # Create columns for metadata
        col1, col2 = st.columns(2)

        # Tools used
        with col1:
            st.subheader("🛠️ Tools Used")
            tools_used = response.get("tools_used", [])
            if tools_used:
                st.markdown(
                    "".join(render_tool_badge(tool) for tool in tools_used),
                    unsafe_allow_html=True,
                )
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


def display_rag_documents(documents: list[dict[str, Any]]) -> None:
    """Display the indexed guideline documents as colorful cards, two per row.

    Args:
        documents: List of RAGDocumentInfo dicts (document_name, version,
            effective_date, source, chunk_count) from GET /rag/documents
    """
    if not documents:
        st.info("No guideline documents are indexed yet. Add one below to get started.")
        return

    cols_per_row = 2
    rows = [documents[i : i + cols_per_row] for i in range(0, len(documents), cols_per_row)]
    for row in rows:
        cols = st.columns(cols_per_row)
        for col, doc in zip(cols, row):
            color = DOCUMENT_CARD_PALETTE[hash(doc["document_name"]) % len(DOCUMENT_CARD_PALETTE)]
            with col:
                st.markdown(
                    f"""
                    <div style="border:1px solid {color}55;border-left:5px solid {color};
                                border-radius:10px;padding:14px 18px;margin-bottom:14px;
                                background:{color}0D;">
                        <div style="font-weight:700;font-size:1.05rem;color:{color};">
                            📄 {doc.get('document_name', 'Unknown')}
                        </div>
                        <div style="font-size:0.85rem;opacity:0.85;margin-top:4px;">
                            Version {doc.get('version', 'Unknown')} · Effective {doc.get('effective_date', 'Unknown')}
                        </div>
                        <div style="font-size:0.8rem;opacity:0.7;margin-top:2px;">
                            {doc.get('chunk_count', 0)} indexed chunk(s) · Source: {doc.get('source', 'Unknown')}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


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
    meta = _tool_meta(tool_name)
    return f'{meta["emoji"]} {meta["label"]}'
