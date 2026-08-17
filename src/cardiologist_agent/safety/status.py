from __future__ import annotations

from cardiologist_agent.domain.enums import (
    AuthorizationStatus,
    EvidenceGrade,
    ReviewStatus,
)
from cardiologist_agent.domain.response import DependencyStatus
from cardiologist_agent.repositories.policy import RetrievalResult
from cardiologist_agent.safety.assessment import SafetyAssessment

STATUS_PRIORITY: list[ReviewStatus] = [
    ReviewStatus.EMERGENCY_ESCALATION,
    ReviewStatus.SYSTEM_UNAVAILABLE,
    ReviewStatus.URGENT_CLINICAL_REVIEW,
    ReviewStatus.CONFLICT_REQUIRES_REVIEW,
    ReviewStatus.INSUFFICIENT_EVIDENCE,
    ReviewStatus.FINAL_AUTHORIZED,
    ReviewStatus.DRAFT_FOR_CLINICIAN_REVIEW,
]


def select_review_status(
    assessment: SafetyAssessment,
    authorization_status: AuthorizationStatus,
    retrieval: RetrievalResult | None = None,
    has_signed_orders: bool = False,
) -> ReviewStatus:
    if assessment.inactive_record:
        return ReviewStatus.SYSTEM_UNAVAILABLE
    if assessment.emergency:
        return ReviewStatus.EMERGENCY_ESCALATION
    if assessment.urgent:
        return ReviewStatus.URGENT_CLINICAL_REVIEW
    if assessment.conflict:
        return ReviewStatus.CONFLICT_REQUIRES_REVIEW
    if assessment.insufficient or assessment.allergy_reconciliation_unknown:
        return ReviewStatus.INSUFFICIENT_EVIDENCE
    if retrieval and retrieval.contamination_detected:
        return ReviewStatus.INSUFFICIENT_EVIDENCE

    if (
        has_signed_orders
        and authorization_status == AuthorizationStatus.SIGNED
        and not assessment.flags
        and not assessment.conflicts
    ):
        return ReviewStatus.FINAL_AUTHORIZED

    return ReviewStatus.DRAFT_FOR_CLINICIAN_REVIEW


def compute_evidence_grade(
    status: ReviewStatus,
    assessment: SafetyAssessment,
    retrieval: RetrievalResult | None,
    authorization_status: AuthorizationStatus,
    dependencies: list[DependencyStatus],
) -> EvidenceGrade:
    if status in {
        ReviewStatus.SYSTEM_UNAVAILABLE,
        ReviewStatus.EMERGENCY_ESCALATION,
    }:
        return EvidenceGrade.INSUFFICIENT
    if status == ReviewStatus.INSUFFICIENT_EVIDENCE:
        return EvidenceGrade.INSUFFICIENT
    if status == ReviewStatus.CONFLICT_REQUIRES_REVIEW:
        return EvidenceGrade.LOW
    if status == ReviewStatus.URGENT_CLINICAL_REVIEW:
        return EvidenceGrade.LOW
    if status == ReviewStatus.FINAL_AUTHORIZED:
        return EvidenceGrade.HIGH

    dep_failures = [d for d in dependencies if not d.available]
    if dep_failures:
        return EvidenceGrade.LOW
    if retrieval and not retrieval.coverage_adequate:
        return EvidenceGrade.LOW
    if authorization_status == AuthorizationStatus.UNAVAILABLE:
        return EvidenceGrade.MODERATE
    return EvidenceGrade.MODERATE


def safest_next_action(status: ReviewStatus, assessment: SafetyAssessment) -> str:
    if status == ReviewStatus.SYSTEM_UNAVAILABLE:
        return "Do not proceed with automated review. Reactivate or verify patient record with records administration."
    if status == ReviewStatus.EMERGENCY_ESCALATION:
        return "Initiate emergency escalation per practice policy. Arrange immediate clinical assessment."
    if status == ReviewStatus.URGENT_CLINICAL_REVIEW:
        return "Contact duty cardiology clinician today for urgent review of flagged results and medications."
    if status == ReviewStatus.CONFLICT_REQUIRES_REVIEW:
        return "Route to clinician for medication reconciliation and conflict resolution before any medication action."
    if status == ReviewStatus.INSUFFICIENT_EVIDENCE:
        if assessment.allergy_reconciliation_unknown:
            return "Complete allergy reconciliation before medication recommendations."
        if assessment.stale:
            return "Book required monitoring tests and withhold medication changes until fresh results are available."
        return "Gather missing or finalized data before issuing a medication recommendation."
    if status == ReviewStatus.FINAL_AUTHORIZED:
        return "Release authorized recommendation per signed order after final safety verification."
    return "Review draft summary and authorize or amend medication plan through standard clinician workflow."
