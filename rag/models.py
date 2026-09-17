"""Typed contracts for approved-document retrieval."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentMetadata:
    document_name: str
    version: str
    section: str
    effective_date: str
    source: str


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    document_name: str
    section: str
    content: str
    metadata: DocumentMetadata


@dataclass(frozen=True)
class RetrievalResult:
    document: str
    section: str
    content: str
    metadata: DocumentMetadata
    similarity_score: float


@dataclass(frozen=True)
class RetrievalResponse:
    query: str
    available: bool
    results: tuple[RetrievalResult, ...]
    user_message: str | None = None
