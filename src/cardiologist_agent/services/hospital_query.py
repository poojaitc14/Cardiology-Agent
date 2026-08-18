from __future__ import annotations

import re
from pathlib import Path

import yaml

from cardiologist_agent.config.settings import Settings, get_settings
from cardiologist_agent.domain.response import Citation
from cardiologist_agent.repositories.policy import PolicyRetriever


def _load_staff_directory(settings: Settings) -> dict:
    path = settings.resolve(Path("config/staff_directory.yaml"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _match_staff(question: str, staff_directory: dict) -> list[dict]:
    normalized = question.lower()
    matches: list[dict] = []
    for member in staff_directory.get("staff", []):
        score = 0
        for handle in member.get("handles", []):
            if handle.lower() in normalized:
                score += 2
        for token in (member.get("name", ""), member.get("title", "")):
            for word in token.lower().split():
                if len(word) > 3 and word in normalized:
                    score += 1
        if score:
            matches.append({**member, "_score": score})
    for keyword, staff_id in (staff_directory.get("condition_routing") or {}).items():
        if keyword.lower() in normalized:
            for member in staff_directory.get("staff", []):
                if member.get("id") == staff_id:
                    matches.append({**member, "_score": 3})
    matches.sort(key=lambda item: item.get("_score", 0), reverse=True)
    deduped: list[dict] = []
    seen: set[str] = set()
    for member in matches:
        staff_id = member.get("id")
        if staff_id in seen:
            continue
        seen.add(staff_id)
        deduped.append(member)
    return deduped[:3]


def _clean_policy_excerpt(text: str) -> str:
    cleaned = re.sub(
        r"Northbridge Cardiology Practice \| Fictional training corpus Page \d+\s*",
        "",
        " ".join(text.split()),
    )
    if "Document control and RAG metadata" in cleaned:
        return "Refer to the full policy document for complete guidance."
    for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
        sentence = sentence.strip()
        if len(sentence) < 30:
            continue
        if any(token in sentence for token in ("Field Value", "Canonical title", "Document ID")):
            continue
        return sentence
    trimmed = cleaned[:220].rstrip()
    return trimmed + ("…" if len(cleaned) > 220 else "")


async def answer_hospital_question(
    question: str,
    policy_retriever: PolicyRetriever,
    settings: Settings | None = None,
) -> tuple[str, list[Citation]]:
    settings = settings or get_settings()
    retrieval = await policy_retriever.retrieve(question)
    citations: list[Citation] = []
    chunks = retrieval.chunks[:3]

    for chunk in chunks:
        citations.append(
            Citation(
                source_type="policy",
                document_id=chunk.document_id,
                version=chunk.version,
                section=chunk.canonical_title or chunk.section_path,
                page=chunk.page,
                chunk_id=chunk.chunk_id,
                retrieved_at=chunk.ingestion_timestamp,
            )
        )

    staff_matches = _match_staff(question, _load_staff_directory(settings))
    parts: list[str] = []

    if staff_matches:
        staff_lines = []
        for member in staff_matches:
            handles = ", ".join(member.get("handles", [])[:4])
            staff_lines.append(
                f"• {member['name']} ({member['title']}) — contact: {member['contact']}. "
                f"They handle: {handles}."
            )
            citations.append(
                Citation(
                    source_type="staff_directory",
                    document_id="NB-ADM-007",
                    section=member.get("id"),
                )
            )
        parts.append("Hospital staff who may be able to help:\n" + "\n".join(staff_lines))

    if chunks:
        policy_lines = []
        for chunk in chunks:
            title = chunk.canonical_title or chunk.document_id
            summary = _clean_policy_excerpt(chunk.text)
            policy_lines.append(f"• {title}: {summary}")
        parts.append("Relevant hospital policy guidance:\n" + "\n".join(policy_lines))
    elif not staff_matches:
        return (
            "I could not find relevant hospital staff or policy information for that question.",
            citations,
        )

    if not retrieval.coverage_adequate and chunks:
        parts.append(
            "Note: policy coverage was limited for this question — please double-check with reception if unsure."
        )

    return ("\n\n".join(parts), citations)
