"""Write-capable admin service for managing RAG documents (list, add, replace, delete).

Unlike `CardiologyRAGService` (read-only, wired into the agent's tool set), this
service performs writes and is used exclusively by the interactive "Manage
Guidelines" UI/API path -- it must never be passed to the agent.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Protocol

from rag.ingestion.pipeline import HashEmbeddingProvider, chunk_sections, extract_markdown_text, index_chunks

LOGGER = logging.getLogger(__name__)


class OpenSearchAdminClient(Protocol):
    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]: ...

    def index(self, *, index: str, body: dict[str, Any], refresh: bool = False) -> dict[str, Any]: ...

    def delete(self, *, index: str, id: str) -> dict[str, Any]: ...


class RAGDocumentAdminService:
    """Adds, replaces, deletes, and lists documents in the cardiology RAG index."""

    def __init__(
        self,
        client: OpenSearchAdminClient,
        index_name: str,
        embedder: HashEmbeddingProvider | None = None,
        *,
        delete_max_attempts: int = 3,
        delete_retry_delay_seconds: float = 3.0,
    ) -> None:
        self._client, self._index_name = client, index_name
        self._embedder = embedder or HashEmbeddingProvider()
        self._delete_max_attempts = delete_max_attempts
        self._delete_retry_delay_seconds = delete_retry_delay_seconds

    @classmethod
    def from_environment(cls) -> "RAGDocumentAdminService":
        """Create a service using the same OpenSearch Serverless collection as retrieval.

        Uses the same SigV4-signed client construction as `CardiologyRAGService` --
        write access is granted by the collection's data-access policy, not by any
        separate credential.
        """
        host = os.environ.get("OPENSEARCH_HOST")
        index_name = os.environ.get("OPENSEARCH_INDEX")
        region = os.environ.get("AWS_REGION")
        if not host:
            raise ValueError("OPENSEARCH_HOST must be configured.")
        if not index_name:
            raise ValueError("OPENSEARCH_INDEX must be configured.")
        if not region:
            raise ValueError("AWS_REGION must be configured.")
        dimensions = int(os.environ.get("RAG_EMBEDDING_DIMENSIONS", "128"))
        from rag.opensearch_client import build_serverless_client

        client = build_serverless_client(host, region)
        return cls(client, index_name, HashEmbeddingProvider(dimensions))

    def list_documents(self) -> list[dict[str, Any]]:
        """Return one summary row per distinct document currently indexed."""
        response = self._client.search(
            index=self._index_name,
            body={"size": 0, "aggs": {"documents": {"terms": {"field": "document", "size": 500}}}},
        )
        buckets = response.get("aggregations", {}).get("documents", {}).get("buckets", [])
        summaries: list[dict[str, Any]] = []
        for bucket in buckets:
            name = bucket.get("key")
            sample = self._client.search(
                index=self._index_name,
                body={"size": 1, "query": {"term": {"document": name}}},
            )
            hits = sample.get("hits", {}).get("hits", [])
            metadata = hits[0]["_source"].get("metadata", {}) if hits else {}
            summaries.append(
                {
                    "document_name": name,
                    "version": metadata.get("version", "Unknown"),
                    "effective_date": metadata.get("effective_date", "Unknown"),
                    "source": metadata.get("source", "Unknown"),
                    "chunk_count": bucket.get("doc_count", 0),
                }
            )
        return summaries

    def upsert_document(
        self, *, document_name: str, version: str, effective_date: str, source: str, content_markdown: str
    ) -> tuple[int, int]:
        """Replace all existing chunks for `document_name` with freshly chunked/embedded content.

        Returns `(chunks_replaced, chunks_indexed)`.
        """
        if not document_name.strip():
            raise ValueError("document_name is required.")
        if not content_markdown.strip():
            raise ValueError("content is required.")
        replaced = self.delete_document(document_name)
        sections = extract_markdown_text(content_markdown, document_name, version, effective_date, source)
        if not sections:
            raise ValueError("No content sections found -- use '## Section Name' headings to structure the document.")
        chunks = chunk_sections(sections)
        indexed = index_chunks(self._client, self._index_name, chunks, self._embedder)
        return replaced, indexed

    def delete_document(self, document_name: str, *, max_attempts: int | None = None, retry_delay_seconds: float | None = None) -> int:
        """Delete every currently-indexed chunk for `document_name`. Returns the count deleted.

        OpenSearch Serverless indexes near-real-time rather than instantly, so a
        chunk written moments ago may not yet be visible to this method's search
        on the first attempt. Retries a few times with a short delay so a
        just-written straggler still gets caught rather than left orphaned.
        """
        max_attempts = self._delete_max_attempts if max_attempts is None else max_attempts
        retry_delay_seconds = self._delete_retry_delay_seconds if retry_delay_seconds is None else retry_delay_seconds
        deleted = 0
        for attempt in range(max_attempts):
            response = self._client.search(
                index=self._index_name,
                body={"size": 1000, "query": {"term": {"document": document_name}}},
            )
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                break
            for hit in hits:
                doc_id = hit.get("_id")
                if not doc_id:
                    continue
                try:
                    self._client.delete(index=self._index_name, id=doc_id)
                    deleted += 1
                except Exception:
                    LOGGER.exception("Failed to delete chunk %s for document %s", doc_id, document_name)
            if attempt < max_attempts - 1:
                time.sleep(retry_delay_seconds)
        return deleted
