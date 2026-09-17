"""LangChain-backed read path for the cardiology RAG tool.

Returns the same RetrievalResponse/RetrievalResult contract
rag.retrieval.cardiology_rag.CardiologyRAGService already returns, so this is
a drop-in replacement for it in the agent's tool wiring -- everything
downstream (citation building, the eval harness, the frontend) is unaffected.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from rag.models import DocumentMetadata, RetrievalResponse, RetrievalResult

LOGGER = logging.getLogger(__name__)


class LangChainVectorStore(Protocol):
    def similarity_search_with_score(self, query: str, k: int = 4, **kwargs: Any) -> list[tuple[Any, float]]: ...


class LangChainCardiologyRAGService:
    """Read-only: returns retrieved document data only, never follows it as instructions."""

    def __init__(self, vector_store: LangChainVectorStore) -> None:
        self._vector_store = vector_store

    @classmethod
    def from_environment(cls) -> "LangChainCardiologyRAGService":
        from rag.langchain_vectorstore import build_vector_store

        return cls(build_vector_store())

    def retrieve(self, query: str, limit: int = 5) -> RetrievalResponse:
        cleaned_query = query.strip()
        if not cleaned_query:
            return RetrievalResponse(cleaned_query, True, (), "A clinical-policy query is required.")
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20.")
        try:
            hits = self._vector_store.similarity_search_with_score(cleaned_query, k=limit)
        except Exception:
            LOGGER.exception("LangChain OpenSearch retrieval failed")
            return RetrievalResponse(cleaned_query, False, (), "Clinical document retrieval is temporarily unavailable.")
        results = tuple(self._to_result(doc, score) for doc, score in hits)
        if not results:
            return RetrievalResponse(cleaned_query, True, (), "Sufficient evidence was not found in the knowledge base.")
        return RetrievalResponse(cleaned_query, True, results)

    @staticmethod
    def _to_result(doc: Any, score: float) -> RetrievalResult:
        metadata = doc.metadata or {}
        document_name = metadata.get("document_name", "Unknown document")
        section = metadata.get("section", "Unknown section")
        return RetrievalResult(
            document_name,
            section,
            doc.page_content,
            DocumentMetadata(
                document_name,
                metadata.get("version", "Unknown"),
                section,
                metadata.get("effective_date", "Unknown"),
                metadata.get("source", "Unknown"),
            ),
            float(score),
        )
