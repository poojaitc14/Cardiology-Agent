from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


class PolicyChunk(BaseModel):
    chunk_id: str
    document_id: str
    canonical_title: str
    version: str
    effective_date: str | None = None
    review_date: str | None = None
    status: str = "active"
    owner: str | None = None
    document_category: str
    corpus_eligibility: str
    synthetic: bool = True
    section_path: str | None = None
    page: int
    source_path: str
    content_hash: str
    text: str
    ingestion_timestamp: datetime


@dataclass
class RetrievalResult:
    chunks: list[PolicyChunk]
    query: str
    coverage_adequate: bool
    contamination_detected: bool = False


class PolicyRetriever:
    async def retrieve(self, query: str, top_k: int = 5) -> RetrievalResult:
        raise NotImplementedError
