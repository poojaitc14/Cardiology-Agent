from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pypdf import PdfReader

from cardiologist_agent.config.settings import Settings, get_settings
from cardiologist_agent.repositories.policy import PolicyChunk


def load_inventory(settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    data = yaml.safe_load(settings.inventory_file.read_text(encoding="utf-8"))
    return data.get("documents", [])


def _extract_pdf_text(path: Path) -> list[tuple[int, str]]:
    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append((i, text))
    return pages


def _parse_header(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    doc_id = re.search(r"Document ID\s+(\S+)", text)
    version = re.search(r"Document ID\s+\S+\s+([\d.]+)", text)
    title_match = re.search(
        r"Northbridge Cardiology Practice\s*\n(.+?)\n",
        text,
        re.DOTALL,
    )
    if doc_id:
        meta["document_id"] = doc_id.group(1)
    if version:
        meta["version"] = version.group(1)
    if title_match:
        meta["canonical_title"] = title_match.group(1).strip().replace("\n", " ")
    eff = re.search(r"Effective\s+Review due\s*\n?\S+\s+[\d.]+\s+([\d-]+)", text)
    if eff:
        meta["effective_date"] = eff.group(1)
    return meta


def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + chunk_size)
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(0, end - overlap)
    return chunks


def ingest_runtime_policies(settings: Settings | None = None) -> list[PolicyChunk]:
    settings = settings or get_settings()
    inventory = load_inventory(settings)
    chunks: list[PolicyChunk] = []
    now = datetime.now(UTC)

    for doc in inventory:
        if not doc.get("runtime_retrieval_allowed"):
            continue
        if doc.get("corpus_eligibility") != "runtime":
            continue
        path = settings.resolve(Path(doc["source_path"]))
        pages = _extract_pdf_text(path)
        full_header = pages[0][1] if pages else ""
        header_meta = _parse_header(full_header)
        document_id = doc.get("document_id") or header_meta.get("document_id", path.stem)
        title = doc.get("canonical_title") or header_meta.get("canonical_title", path.stem)
        version = header_meta.get("version", "1.0")

        for page_num, page_text in pages:
            for idx, piece in enumerate(_chunk_text(page_text)):
                if len(piece.strip()) < 40:
                    continue
                content_hash = hashlib.sha256(piece.encode()).hexdigest()
                chunk_id = f"{document_id}-p{page_num}-c{idx}"
                chunks.append(
                    PolicyChunk(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        canonical_title=title,
                        version=version,
                        effective_date=header_meta.get("effective_date"),
                        review_date=None,
                        status="active",
                        owner=doc.get("owner"),
                        document_category=doc.get("category", "policy"),
                        corpus_eligibility=doc.get("corpus_eligibility", "runtime"),
                        synthetic=True,
                        section_path=None,
                        page=page_num,
                        source_path=str(doc["source_path"]),
                        content_hash=content_hash,
                        text=piece,
                        ingestion_timestamp=now,
                    )
                )
    return chunks


def save_index(chunks: list[PolicyChunk], index_path: Path) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [c.model_dump(mode="json") for c in chunks]
    index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_index(index_path: Path) -> list[PolicyChunk]:
    if not index_path.exists():
        return []
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    return [PolicyChunk.model_validate(item) for item in raw]
