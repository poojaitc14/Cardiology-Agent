"""Output guardrails for the cardiology agent's LLM-synthesized answers.

Runs after synthesis, before an answer is returned. Deliberately lightweight and
dependency-free (no external guardrails framework) to match this codebase's
existing style of small, explicit, auditable safety checks -- see
backend/agent/cardiology_agent.py's regex-based tool routing for the same
philosophy applied to tool selection.

This is defense in depth alongside the SYSTEM_PROMPT's own instructions
(backend/agent/prompts.py), not a replacement for them: the prompt is the first
line of defense, this is the second, catching cases where the model didn't
follow its instructions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Phrasing that would cross from "decision support" into the prescriptive/
# diagnostic territory the agent is explicitly barred from (see the system
# prompt's CLINICAL SAFETY BOUNDARIES section).
UNSAFE_LANGUAGE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bI (?:diagnose|am diagnosing)\b", re.IGNORECASE),
    re.compile(r"\byou (?:should|must|need to) (?:take|start|stop|increase|decrease)\b.{0,40}(?:\bdose\b|\bdosage\b|mg\b|\bmilligrams\b)", re.IGNORECASE),
    re.compile(r"\b(?:start|stop|increase|decrease|discontinue)\s+(?:the\s+)?(?:patient'?s?\s+)?(?:medication|dose|dosage)\b", re.IGNORECASE),
    re.compile(r"\bthis is (?:definitely|certainly|clearly) a (?:diagnosis|case of)\b", re.IGNORECASE),
)

# Signals that a prompt-injection attempt embedded in retrieved content (a
# guideline document, a patient free-text field) leaked into the answer rather
# than being treated as inert data.
INJECTION_MARKERS: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard the above",
    "disregard previous instructions",
    "new instructions:",
    "system prompt:",
    "you are now",
)


@dataclass(frozen=True)
class GuardrailResult:
    """The outcome of running all guardrail checks against one generated answer."""

    passed: bool
    reasons: tuple[str, ...]


def check_answer(answer: str, evidence: list[str]) -> GuardrailResult:
    """Run every guardrail check against a generated answer. Fails closed: any
    one violation fails the whole result."""
    reasons: list[str] = [
        *_safety_language_violations(answer),
        *_injection_leak_violations(answer),
        *_fabrication_violations(answer, evidence),
    ]
    return GuardrailResult(passed=not reasons, reasons=tuple(reasons))


def _safety_language_violations(answer: str) -> list[str]:
    return [
        f"Detected prescriptive/diagnostic language matching: {pattern.pattern}"
        for pattern in UNSAFE_LANGUAGE_PATTERNS
        if pattern.search(answer)
    ]


def _injection_leak_violations(answer: str) -> list[str]:
    lowered = answer.lower()
    return [f"Answer echoes a known injection marker: '{marker}'" for marker in INJECTION_MARKERS if marker in lowered]


def _fabrication_violations(answer: str, evidence: list[str]) -> list[str]:
    """Heuristic only: flag a known drug name that appears in the answer but
    nowhere in the retrieved evidence. Covers this app's constrained drug
    vocabulary (see KNOWN_DRUGS in cardiology_agent.py) -- a coarse safety net,
    not a substitute for the grounding rules in the system prompt."""
    from backend.agent.cardiology_agent import KNOWN_DRUGS

    evidence_text = " ".join(evidence).lower()
    violations = []
    seen = set()
    for match in KNOWN_DRUGS.finditer(answer):
        drug = match.group(1).lower()
        if drug in seen:
            continue
        seen.add(drug)
        if drug not in evidence_text:
            violations.append(f"Answer mentions '{match.group(1)}' which does not appear in retrieved evidence")
    return violations
