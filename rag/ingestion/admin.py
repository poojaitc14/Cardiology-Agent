"""Write-capable admin service for managing RAG documents (list, add, replace,
delete), backed by the same LangChain OpenSearch Serverless vector store used
for retrieval (see rag.langchain_vectorstore and
rag.retrieval.langchain_cardiology_rag).

Unlike the retrieval path (read-only, wired into the agent's tool set), this
service performs writes and is used exclusively by the interactive "Manage
Guidelines" UI/API path -- it must never be passed to the agent.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from opensearchpy.exceptions import NotFoundError

from rag.ingestion.pipeline import chunk_sections, extract_markdown_text
from rag.models import DocumentMetadata

LOGGER = logging.getLogger(__name__)

# OpenSearch's default dynamic mapping gives every string leaf both an
# analyzed "text" field and an unanalyzed "<field>.keyword" multi-field --
# exact-match term queries/aggregations against nested metadata must use the
# ".keyword" variant, not the bare field.
DOCUMENT_NAME_KEYWORD_FIELD = "metadata.document_name.keyword"


class LangChainAdminVectorStore(Protocol):
    """The subset of OpenSearchVectorSearch this service actually uses."""

    client: Any
    index_name: str

    def add_texts(self, texts: list[str], metadatas: list[dict] | None = None, **kwargs: Any) -> list[str]: ...

    def delete(self, ids: list[str] | None = None, refresh_indices: bool = True, **kwargs: Any) -> bool | None: ...


class RAGDocumentAdminService:
    """Adds, replaces, deletes, and lists documents in the cardiology RAG index."""

    def __init__(
        self,
        vector_store: LangChainAdminVectorStore,
        *,
        delete_max_attempts: int = 3,
        delete_retry_delay_seconds: float = 3.0,
    ) -> None:
        self._vector_store = vector_store
        self._delete_max_attempts = delete_max_attempts
        self._delete_retry_delay_seconds = delete_retry_delay_seconds

    @classmethod
    def from_environment(cls) -> "RAGDocumentAdminService":
        """Create a service using the same OpenSearch Serverless collection and Azure
        OpenAI embeddings as retrieval -- write access is granted by the collection's
        data-access policy, not by any separate credential."""
        from rag.langchain_vectorstore import build_vector_store

        return cls(build_vector_store())

    def recreate_index(self) -> bool:
        """Delete the index if it exists; the next write recreates it fresh with
        the LangChain-managed schema. Used for a clean cutover away from a
        differently-schemed index (e.g. one written by the old raw opensearch-py
        pipeline), never during normal operation. Returns True if an index was
        deleted."""
        client = self._vector_store.client
        index_name = self._vector_store.index_name
        if client.indices.exists(index=index_name):
            client.indices.delete(index=index_name)
            return True
        return False

    def list_documents(self) -> list[dict[str, Any]]:
        """Return one summary row per distinct document currently indexed."""
        response = self._vector_store.client.search(
            index=self._vector_store.index_name,
            body={"size": 0, "aggs": {"documents": {"terms": {"field": DOCUMENT_NAME_KEYWORD_FIELD, "size": 500}}}},
        )
        buckets = response.get("aggregations", {}).get("documents", {}).get("buckets", [])
        summaries: list[dict[str, Any]] = []
        for bucket in buckets:
            name = bucket.get("key")
            sample = self._vector_store.client.search(
                index=self._vector_store.index_name,
                body={"size": 1, "query": {"term": {DOCUMENT_NAME_KEYWORD_FIELD: name}}},
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
        """Replace all existing chunks for `document_name` with freshly chunked,
        Azure-embedded content, parsed from a markdown string. Returns
        `(chunks_replaced, chunks_indexed)`."""
        if not document_name.strip():
            raise ValueError("document_name is required.")
        if not content_markdown.strip():
            raise ValueError("content is required.")
        sections = extract_markdown_text(content_markdown, document_name, version, effective_date, source)
        if not sections:
            raise ValueError("No content sections found -- use '## Section Name' headings to structure the document.")
        return self.upsert_sections(document_name, sections)

    def upsert_sections(self, document_name: str, sections: list[tuple[str, str, DocumentMetadata]]) -> tuple[int, int]:
        """Replace all existing chunks for `document_name` with freshly chunked,
        Azure-embedded content, from already-sectioned (section, content, metadata)
        tuples. Used directly by re-ingestion scripts that already have structured
        content (e.g. the synthetic document fixtures), bypassing markdown parsing.
        Returns `(chunks_replaced, chunks_indexed)`.
        """
        replaced = self.delete_document(document_name)
        chunks = chunk_sections(sections)
        texts = [chunk.content for chunk in chunks]
        metadatas = [
            {
                "document_name": chunk.metadata.document_name,
                "section": chunk.section,
                "version": chunk.metadata.version,
                "effective_date": chunk.metadata.effective_date,
                "source": chunk.metadata.source,
                "chunk_id": chunk.chunk_id,
            }
            for chunk in chunks
        ]
        ids = self._vector_store.add_texts(texts, metadatas=metadatas)
        return replaced, len(ids)

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
            try:
                response = self._vector_store.client.search(
                    index=self._vector_store.index_name,
                    body={"size": 1000, "query": {"term": {DOCUMENT_NAME_KEYWORD_FIELD: document_name}}},
                )
            except NotFoundError:
                # The index doesn't exist yet at all (e.g. a brand-new knowledge
                # base, or right after recreate_index()) -- nothing to delete.
                break
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                break
            ids = [hit["_id"] for hit in hits if hit.get("_id")]
            if ids:
                try:
                    self._vector_store.delete(ids=ids, refresh_indices=False)
                    deleted += len(ids)
                except Exception:
                    LOGGER.exception("Failed to delete chunks for document %s", document_name)
            if attempt < max_attempts - 1:
                time.sleep(retry_delay_seconds)
        return deleted
