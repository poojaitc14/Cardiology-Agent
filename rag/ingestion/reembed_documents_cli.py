"""Operator-only command that migrates the cardiology RAG knowledge base from the
development HashEmbeddingProvider to real Azure OpenAI (text-embedding-3-small)
embeddings via LangChain, re-indexing all 15 synthetic documents.

Deletes and recreates the OpenSearch index from scratch rather than reusing the
old one -- the old index's documents use a different field schema (raw
opensearch-py's `document`/`content`/`embedding` top-level fields) than the new
LangChain-managed one (`metadata.document_name`/`text`/`vector_field`), so
reusing it would leave old- and new-schema documents mixed together with no
way for the new admin service's delete-by-document-name to find and remove the
old ones. This must never be invoked by the agent runtime.
"""
from __future__ import annotations

import os
import time

from opensearchpy.exceptions import NotFoundError
from opensearchpy.helpers.errors import BulkIndexError

from rag.ingestion.admin import RAGDocumentAdminService
from rag.ingestion.dummy_documents import load_dummy_sections
from rag.models import DocumentMetadata

# A brand-new index's k-NN field mapping is still settling for a moment right
# after creation -- OpenSearch Serverless can transiently fail one or two of
# the very first writes to it with "Exception occurred in Mapping update".
# Retrying (the index already exists by the second attempt, so there's no
# mapping race left) clears it; this is specific to this one-time full-rebuild
# script, not steady-state add/replace via RAGDocumentAdminService.
WARMUP_RETRY_ATTEMPTS = 3
WARMUP_RETRY_DELAY_SECONDS = 2.0


def _upsert_with_warmup_retry(admin_service: RAGDocumentAdminService, document_name: str, sections) -> tuple[int, int]:
    for attempt in range(WARMUP_RETRY_ATTEMPTS):
        try:
            return admin_service.upsert_sections(document_name, sections)
        except (BulkIndexError, NotFoundError):
            if attempt == WARMUP_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(WARMUP_RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable")


def main() -> None:
    index_name = os.environ.get("OPENSEARCH_INDEX")
    if not index_name:
        raise SystemExit("Set OPENSEARCH_INDEX before re-indexing.")

    admin_service = RAGDocumentAdminService.from_environment()

    deleted = admin_service.recreate_index()
    print(f"{'Deleted' if deleted else 'No'} existing index '{index_name}'.")
    if deleted:
        # OpenSearch Serverless's index deletion isn't synchronously complete
        # when the API call returns; writing to the (about to be recreated)
        # index too soon after can 404 or hit mapping-update races.
        print("Waiting for the deletion to settle before re-indexing...")
        time.sleep(10)

    sections_by_document: dict[str, list[tuple[str, str, DocumentMetadata]]] = {}
    for section_name, content, metadata in load_dummy_sections():
        sections_by_document.setdefault(metadata.document_name, []).append((section_name, content, metadata))

    total_chunks = 0
    for document_name, sections in sections_by_document.items():
        _replaced, indexed = _upsert_with_warmup_retry(admin_service, document_name, sections)
        total_chunks += indexed
        print(f"Indexed '{document_name}': {indexed} chunk(s).")

    print(
        f"Done. Re-indexed {len(sections_by_document)} document(s), {total_chunks} chunk(s) total, "
        "embedded with Azure OpenAI text-embedding-3-small."
    )


if __name__ == "__main__":
    main()
