"""Partial RAGAS integration — full metrics require approved gold reference answers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RagasEvaluationSummary:
    available: bool
    message: str
    metrics_run: list[str]


def run_ragas_if_available() -> RagasEvaluationSummary:
    try:
        import ragas  # noqa: F401
    except ImportError:
        return RagasEvaluationSummary(
            available=False,
            message="ragas optional dependency not installed; skipped.",
            metrics_run=[],
        )
    return RagasEvaluationSummary(
        available=False,
        message=(
            "RAGAS installed but gold reference questions/answers/contexts are not in the repository. "
            "Deterministic manifest evaluation is used instead."
        ),
        metrics_run=[],
    )
