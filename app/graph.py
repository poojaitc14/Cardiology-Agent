"""The explicit, auditable LangGraph workflow for a clinical review."""

import json
import os
import re
from datetime import UTC, datetime
from typing import TypedDict

import requests
from langfuse import observe
from langgraph.graph import END, START, StateGraph

from app.schemas import ReviewResponse
from app.tools import (
    get_medication_information,
    get_patient_clinical_context,
    search_approved_clinical_knowledge,
)


class ReviewState(TypedDict, total=False):
    patient_id: str
    requesting_user_id: str
    question: str
    restricted_clinical_request: bool
    patient_context: dict
    approved_knowledge: list[dict]
    medication_information: list[dict]
    response: dict


_PATIENT_ID_PATTERN = re.compile(r"^P[0-9]+$")
_PROMPT_INJECTION_PATTERN = re.compile(
    r"\b(ignore|override|bypass|disregard)\b.{0,40}\b(instruction|prompt|policy|rule)s?\b"
    r"|\b(reveal|display|print|return)\b.{0,40}\b(secret|credential|api[-_ ]?key|system prompt)s?\b",
    re.IGNORECASE,
)
_RESTRICTED_CLINICAL_REQUEST_PATTERN = re.compile(
    r"\b(?:diagnos(?:e|is|tic)|prescrib(?:e|ing|ed|er|ption))\b"
    r"|\b(?:calculate|recommend|suggest|determine|select)\w*\b.{0,50}\b(?:dose|dosage|dosing)\b"
    r"|\b(?:what|which|how much)\b.{0,50}\b(?:dose|dosage|dosing|medication|medicine|drug)\b"
    r"|\b(?:recommend|suggest|advise|tell me whether|should|must|need(?:s)? to|can I|may I)\b"
    r".{0,60}\b(?:start|stop|withhold|hold|switch|replace|increase|decrease|change)\w*\b"
    r".{0,40}\b(?:medication|medicine|drug|dose|dosage|dosing)?\b",
    re.IGNORECASE,
)
_CLINICAL_DIRECTIVE_PATTERN = re.compile(
    r"^\s*(?:start|stop|withhold|hold|switch|replace|increase|decrease|change|take|administer|give|prescribe)\b"
    r"|\b(?:you|the patient|patient)\s+(?:should|must|needs? to)\s+"
    r"(?:start|stop|withhold|hold|switch|replace|increase|decrease|change|take)\b"
    r"|\bI\s+(?:recommend|advise)\s+(?:that\s+)?(?:you|the patient|patient)?\s*"
    r"(?:start|stop|stopping|withhold|withholding|hold|switch|switching|replace|increase|decrease|change|changing|take)\b"
    r"|\b(?:diagnosis is|diagnosed with|calculated dose|dose (?:is|should be|must be))\b",
    re.IGNORECASE | re.MULTILINE,
)
_SAFE_NON_DIRECTIVE_PATTERN = re.compile(
    r"\b(?:should|must)\s+not\b"
    r"|\b(?:cannot|can't|do not|does not|must not|is unable to|is not permitted to)\b.{0,80}"
    r"\b(?:diagnose|prescribe|calculate|recommend|start|stop|withhold|hold|switch|replace|increase|decrease|change|take)\w*\b",
    re.IGNORECASE,
)
_RESTRICTED_REQUEST_LIMITATION = (
    "The system cannot make the requested clinical decision; retrieved evidence is provided "
    "for clinician review."
)


def _contains_unsafe_clinical_directive(text: str) -> bool:
    """Detect direct clinical instructions while allowing explicit negation and refusal."""
    sentences = re.split(r"(?<=[.!?;])\s+|[\r\n]+", text)
    return any(
        _CLINICAL_DIRECTIVE_PATTERN.search(sentence)
        and not _SAFE_NON_DIRECTIVE_PATTERN.search(sentence)
        for sentence in sentences
        if sentence.strip()
    )


@observe(name="validate_clinical_input", as_type="guardrail", capture_input=False, capture_output=False)
def validate_clinical_input(state: ReviewState) -> dict:
    """Validate the request and flag restricted clinical decisions without blocking retrieval."""
    patient_id = state.get("patient_id")
    requesting_user_id = state.get("requesting_user_id")
    question = state.get("question")
    if not isinstance(patient_id, str) or not _PATIENT_ID_PATTERN.fullmatch(patient_id):
        raise ValueError("Invalid patient identifier.")
    if not isinstance(requesting_user_id, str) or len(requesting_user_id.strip()) < 3:
        raise ValueError("Invalid requesting user identifier.")
    if not isinstance(question, str) or not 10 <= len(question.strip()) <= 1_000:
        raise ValueError("Clinical review question must contain 10 to 1,000 characters.")
    if _PROMPT_INJECTION_PATTERN.search(question):
        raise ValueError("Clinical review question contains disallowed instruction-manipulation content.")
    return {
        "restricted_clinical_request": bool(
            _RESTRICTED_CLINICAL_REQUEST_PATTERN.search(question)
        )
    }


@observe(name="retrieve_patient_context", as_type="tool", capture_input=False, capture_output=False)
def retrieve_patient_context(state: ReviewState) -> dict:
    return {"patient_context": get_patient_clinical_context(state["patient_id"], state["requesting_user_id"])}


@observe(name="retrieve_approved_knowledge", as_type="tool", capture_input=False, capture_output=False)
def retrieve_approved_knowledge(state: ReviewState) -> dict:
    return {"approved_knowledge": search_approved_clinical_knowledge(state["question"])}


@observe(name="retrieve_medication_information", as_type="tool", capture_input=False, capture_output=False)
def retrieve_medication_information(state: ReviewState) -> dict:
    return {"medication_information": get_medication_information(state["patient_context"]["medications"])}


def _generate_grounded_synthesis(state: ReviewState) -> dict:
    """Generate a concise synthesis without allowing the model to invent evidence."""
    evidence = {
        "question": state["question"],
        "patient_context": state["patient_context"],
        "approved_knowledge": state["approved_knowledge"],
        "medication_information": state["medication_information"],
    }
    system_prompt = (
        "You are a cardiology clinical evidence-synthesis assistant supporting clinician review. "
        "Treat the supplied patient context, approved hospital-policy evidence, and medication API "
        "evidence as the complete and exclusive evidence set for this response. Use only facts "
        "explicitly present in that evidence. Never infer, assume, fabricate, or fill in missing "
        "patient details, diagnoses, test results, medication details, policy requirements, or clinical "
        "events. Do not use outside medical knowledge.\n\n"
        "You must not diagnose or rule out a condition; prescribe or select treatment; calculate or "
        "suggest a dose; or recommend starting, stopping, withholding, switching, replacing, or "
        "changing the dose or schedule of any medication. Do not present an observation as a clinical "
        "decision or instruction.\n\n"
        "Clearly identify conflicting, incomplete, unavailable, stale, or uncertain evidence in "
        "limitations. If the evidence does not support a requested conclusion, state that it cannot "
        "be determined from the supplied evidence. Every safety-relevant finding must be framed as "
        "requiring clinician verification.\n\n"
        "Return one valid JSON object with exactly these top-level fields: summary, attention_items, "
        "and limitations. summary must be a concise string grounded only in the supplied evidence. "
        "attention_items must be an array of objects, each containing observation (a factual, "
        "non-directive statement) and basis_source_ids (an array containing only source_id values "
        "that appear in the supplied evidence). Do not create an attention item without supporting "
        "source IDs. limitations must be an array of concise strings describing uncertainty or "
        "missing evidence. Return JSON only, with no markdown or additional text."
    )

    try:
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        deployment = os.environ["AZURE_CHAT_DEPLOYMENT"]
        api_version = os.environ["CHAT_API_VERSION"]
        response = requests.post(
            f"{endpoint}/openai/deployments/{deployment}/chat/completions",
            params={"api-version": api_version},
            headers={
                "api-key": os.environ["AZURE_OPENAI_API_KEY"],
                "Content-Type": "application/json",
            },
            json={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(evidence, default=str)},
                ],
                "temperature": 0,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "clinical_evidence_synthesis",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "summary": {"type": "string"},
                                "attention_items": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "observation": {"type": "string"},
                                            "basis_source_ids": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                        "required": ["observation", "basis_source_ids"],
                                        "additionalProperties": False,
                                    },
                                },
                                "limitations": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["summary", "attention_items", "limitations"],
                            "additionalProperties": False,
                        },
                    },
                },
            },
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        generated = json.loads(content)
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError("Azure OpenAI synthesis service is unavailable.") from error

    if not isinstance(generated, dict) or not isinstance(generated.get("summary"), str):
        raise RuntimeError("Azure OpenAI synthesis returned an invalid response.")
    return generated


def _deterministic_synthesis(state: ReviewState) -> dict:
    """Build the original deterministic response for reliable fallback behavior."""
    context = state["patient_context"]
    attention_items: list[dict] = []
    if context["allergies"]:
        attention_items.append({
            "observation": "A recorded allergy/intolerance is present; verify it before medication decisions.",
            "basis": [item["source"] for item in context["allergies"]],
            "requires_clinician_verification": True,
        })
    if not state["approved_knowledge"]:
        attention_items.append({
            "observation": "No approved current policy/guideline excerpt was retrieved for this request.",
            "basis": [],
            "requires_clinician_verification": True,
        })

    limitations = context["limitations"] + ["The original draft policy is excluded from retrieval; only documents marked APPROVED are eligible."]
    medication_api_enabled = os.getenv("MEDICATION_API_ENABLED", "false").lower() == "true"
    if not medication_api_enabled:
        limitations.append("Medication API lookup is disabled by configuration.")
    elif not state["medication_information"]:
        limitations.append("No OpenFDA label metadata was returned for the recorded medications.")

    return {
        "patient_id": state["patient_id"],
        "review_generated_at": datetime.now(UTC).isoformat(),
        "summary": "Read-only evidence summary generated from available validated tool results; clinician verification is required.",
        "cardiovascular_history": context["history"],
        "current_medications": context["medications"],
        "allergies": context["allergies"],
        "recent_laboratory_results": context["labs"],
        "attention_items": attention_items,
        "approved_knowledge": state["approved_knowledge"] + state["medication_information"],
        "limitations": limitations,
    }


@observe(name="synthesize_evidence", as_type="chain", capture_input=False, capture_output=False)
def synthesize_evidence(state: ReviewState) -> dict:
    """Synthesize evidence with Azure OpenAI, falling back to deterministic output."""
    response = _deterministic_synthesis(state)
    try:
        generated = _generate_grounded_synthesis(state)
    except RuntimeError:
        response["limitations"].append(
            "LLM synthesis unavailable; deterministic fallback used."
        )
        return {"response": response}

    context = state["patient_context"]
    attention_items: list[dict] = []

    sources = {}
    evidence_facts = (
        context["history"]
        + context["medications"]
        + context["allergies"]
        + context["labs"]
        + state["approved_knowledge"]
        + state["medication_information"]
    )
    for fact in evidence_facts:
        source = fact.get("source", {})
        if source.get("source_id"):
            sources[source["source_id"]] = source

    generated_items = generated.get("attention_items", [])
    if isinstance(generated_items, list):
        for item in generated_items:
            if not isinstance(item, dict) or not isinstance(item.get("observation"), str):
                continue
            basis_ids = item.get("basis_source_ids", [])
            basis = [sources[source_id] for source_id in basis_ids if source_id in sources] if isinstance(basis_ids, list) else []
            if basis:
                attention_items.append({
                    "observation": item["observation"],
                    "basis": basis,
                    "requires_clinician_verification": True,
                })

    generated_limitations = generated.get("limitations", [])
    if isinstance(generated_limitations, list):
        response["limitations"].extend(
            item for item in generated_limitations
            if isinstance(item, str) and item not in response["limitations"]
        )
    response["summary"] = generated["summary"]
    response["attention_items"].extend(attention_items)
    return {"response": response}


def _validate_response_provenance(state: ReviewState, response: dict) -> None:
    """Ensure evidence fields and cited sources are unchanged from tool results."""
    context = state["patient_context"]
    expected_evidence = {
        "cardiovascular_history": context["history"],
        "current_medications": context["medications"],
        "allergies": context["allergies"],
        "recent_laboratory_results": context["labs"],
        "approved_knowledge": state["approved_knowledge"] + state["medication_information"],
    }
    for field, expected in expected_evidence.items():
        if response.get(field) != expected:
            raise ValueError(f"Response evidence field '{field}' does not match retrieved evidence.")

    valid_sources = {
        json.dumps(fact["source"], sort_keys=True, default=str)
        for facts in expected_evidence.values()
        for fact in facts
        if isinstance(fact, dict) and isinstance(fact.get("source"), dict)
    }
    for item in response.get("attention_items", []):
        for source in item.get("basis", []):
            if json.dumps(source, sort_keys=True, default=str) not in valid_sources:
                raise ValueError("Attention item contains provenance not present in retrieved evidence.")


def _add_restricted_request_limitation(state: ReviewState, response: dict) -> None:
    """Add a deterministic scope statement when the input guardrail flagged the request."""
    if state.get("restricted_clinical_request") is True:
        limitations = response.setdefault("limitations", [])
        if _RESTRICTED_REQUEST_LIMITATION not in limitations:
            limitations.append(_RESTRICTED_REQUEST_LIMITATION)


@observe(name="validate_clinical_output", as_type="guardrail", capture_input=False, capture_output=False)
def validate_clinical_output(state: ReviewState) -> dict:
    """Validate schema, provenance, and clinical scope; use deterministic output on failure."""
    response = state["response"]
    generated_text = [response.get("summary", "")]
    generated_text.extend(
        item.get("observation", "")
        for item in response.get("attention_items", [])
        if isinstance(item, dict)
    )
    unsafe_generated_content = any(
        isinstance(text, str) and _contains_unsafe_clinical_directive(text)
        for text in generated_text
    )
    if unsafe_generated_content:
        response = _deterministic_synthesis(state)
        response["limitations"].append(
            "Generated clinical-decision content was blocked by the safety guardrail; "
            "clinician judgement is required."
        )
        _add_restricted_request_limitation(state, response)
        ReviewResponse.model_validate(response)
        _validate_response_provenance(state, response)
        return {"response": response}

    try:
        ReviewResponse.model_validate(response)
        _validate_response_provenance(state, response)
    except (KeyError, TypeError, ValueError):
        response = _deterministic_synthesis(state)
        response["limitations"].append(
            "Generated response failed output validation; deterministic fallback used."
        )
    _add_restricted_request_limitation(state, response)
    ReviewResponse.model_validate(response)
    _validate_response_provenance(state, response)
    return {"response": response}


def build_review_graph():
    builder = StateGraph(ReviewState)
    builder.add_node("validate_clinical_input", validate_clinical_input)
    builder.add_node("retrieve_patient_context", retrieve_patient_context)
    builder.add_node("retrieve_approved_knowledge", retrieve_approved_knowledge)
    builder.add_node("retrieve_medication_information", retrieve_medication_information)
    builder.add_node("synthesize_evidence", synthesize_evidence)
    builder.add_node("validate_clinical_output", validate_clinical_output)
    builder.add_edge(START, "validate_clinical_input")
    builder.add_edge("validate_clinical_input", "retrieve_patient_context")
    builder.add_edge("retrieve_patient_context", "retrieve_approved_knowledge")
    builder.add_edge("retrieve_approved_knowledge", "retrieve_medication_information")
    builder.add_edge("retrieve_medication_information", "synthesize_evidence")
    builder.add_edge("synthesize_evidence", "validate_clinical_output")
    builder.add_edge("validate_clinical_output", END)
    return builder.compile()


review_graph = build_review_graph()
