"""Approved-document RAG ingestion pipeline: extract, chunk, embed, index."""
from __future__ import annotations

from hashlib import sha256
import math
import re
from pathlib import Path
from typing import Any, Protocol

from rag.models import DocumentChunk, DocumentMetadata

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


class SearchIndex(Protocol):
    def index(self, *, index: str, body: dict[str, Any], refresh: bool = False) -> Any: ...


class HashEmbeddingProvider:
    """Deterministic development embedding; replace with an approved model in production."""
    def __init__(self, dimensions: int = 128) -> None:
        if dimensions < 8:
            raise ValueError("Embedding dimensions must be at least 8.")
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in TOKEN_PATTERN.findall(text.lower()):
            index = int.from_bytes(sha256(token.encode("utf-8")).digest()[:4], "big") % self.dimensions
            vector[index] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector] if magnitude else vector


def extract_markdown_text(text: str, document_name: str, version: str, effective_date: str, source: str) -> list[tuple[str, str, DocumentMetadata]]:
    """Extract markdown sections from raw text as data; never interpreted as instructions."""
    sections: list[tuple[str, str, DocumentMetadata]] = []
    section_name = "Overview"
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if lines:
                sections.append((section_name, "\n".join(lines).strip(), DocumentMetadata(document_name, version, section_name, effective_date, source)))
            section_name, lines = line[3:].strip(), []
        elif not line.startswith("# "):
            lines.append(line)
    if lines:
        sections.append((section_name, "\n".join(lines).strip(), DocumentMetadata(document_name, version, section_name, effective_date, source)))
    return [section for section in sections if section[1]]


def extract_markdown(path: Path, document_name: str, version: str, effective_date: str, source: str) -> list[tuple[str, str, DocumentMetadata]]:
    """Extract markdown sections from a file as data; the text is never interpreted as instructions."""
    return extract_markdown_text(path.read_text(encoding="utf-8"), document_name, version, effective_date, source)


def chunk_sections(sections: list[tuple[str, str, DocumentMetadata]], chunk_size: int = 180, overlap: int = 30) -> list[DocumentChunk]:
    """Create bounded, overlapping word chunks while retaining source metadata."""
    if chunk_size <= overlap or overlap < 0:
        raise ValueError("chunk_size must exceed a non-negative overlap.")
    chunks: list[DocumentChunk] = []
    for section, content, metadata in sections:
        words = content.split()
        for start in range(0, len(words), chunk_size - overlap):
            text = " ".join(words[start:start + chunk_size])
            if not text:
                continue
            chunk_id = sha256(f"{metadata.document_name}|{section}|{start}|{text}".encode()).hexdigest()
            chunks.append(DocumentChunk(chunk_id, metadata.document_name, section, text, metadata))
            if start + chunk_size >= len(words):
                break
    return chunks


def index_chunks(index: SearchIndex, index_name: str, chunks: list[DocumentChunk], embedder: HashEmbeddingProvider) -> int:
    """Index chunks and their embeddings into OpenSearch; this is not agent runtime work.

    Document IDs are never client-specified -- OpenSearch Serverless rejects a
    caller-supplied `id` on writes and always auto-assigns one. `chunk_id` is kept
    in the body itself so the deterministic content hash remains inspectable.
    """
    for chunk in chunks:
        index.index(index=index_name, refresh=False, body={
            "chunk_id": chunk.chunk_id,
            "document": chunk.document_name, "section": chunk.section, "content": chunk.content,
            "metadata": {"document_name": chunk.metadata.document_name, "version": chunk.metadata.version, "section": chunk.metadata.section, "effective_date": chunk.metadata.effective_date, "source": chunk.metadata.source},
            "embedding": embedder.embed(chunk.content),
        })
    return len(chunks)
