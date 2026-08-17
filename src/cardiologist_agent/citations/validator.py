from __future__ import annotations

from datetime import UTC, datetime

from cardiologist_agent.domain.enums import ClaimType
from cardiologist_agent.domain.response import Citation, Claim
from cardiologist_agent.providers.openfda import OpenFDAResult
from cardiologist_agent.repositories.policy import PolicyChunk


def validate_policy_citation(claim_text: str, chunk: PolicyChunk) -> Citation | None:
    needle = claim_text.lower().split()[0:5]
    hay = chunk.text.lower()
    if not needle:
        return None
    if needle[0] not in hay and not any(w in hay for w in needle if len(w) > 4):
        return None
    return Citation(
        source_type="policy",
        document_id=chunk.document_id,
        version=chunk.version,
        section=chunk.section_path,
        page=chunk.page,
        chunk_id=chunk.chunk_id,
        retrieved_at=datetime.now(UTC),
    )


def build_policy_claims(chunks: list[PolicyChunk]) -> list[Claim]:
    claims: list[Claim] = []
    for i, chunk in enumerate(chunks):
        snippet = chunk.text[:180].strip()
        claims.append(
            Claim(
                claim_id=f"policy-{i}",
                claim_type=ClaimType.POLICY_REQUIREMENT,
                text=snippet,
                citations=[
                    Citation(
                        source_type="policy",
                        document_id=chunk.document_id,
                        version=chunk.version,
                        section=chunk.section_path,
                        page=chunk.page,
                        chunk_id=chunk.chunk_id,
                        retrieved_at=datetime.now(UTC),
                    )
                ],
                supported=True,
            )
        )
    return claims


def build_openfda_claim(result: OpenFDAResult) -> Claim | None:
    if not result.found or not result.label_excerpt:
        return None
    return Claim(
        claim_id=f"openfda-{result.drug_name.lower()}",
        claim_type=ClaimType.EXTERNAL_EVIDENCE,
        text=result.label_excerpt[:300],
        citations=[
            Citation(
                source_type="openfda",
                document_id=result.drug_name,
                url=result.source_url,
                retrieved_at=result.retrieved_at,
            )
        ],
        supported=True,
    )


def validate_claims(claims: list[Claim]) -> list[Claim]:
    validated: list[Claim] = []
    for claim in claims:
        if claim.claim_type == ClaimType.MODEL_INTERPRETATION:
            validated.append(claim)
            continue
        if not claim.citations:
            claim.supported = False
        validated.append(claim)
    return validated
