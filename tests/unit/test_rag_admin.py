from __future__ import annotations

import pytest

from rag.ingestion.admin import RAGDocumentAdminService
from rag.ingestion.pipeline import HashEmbeddingProvider


class FakeAdminClient:
    """In-memory OpenSearch stand-in: id -> indexed body, supporting search/index/delete."""

    def __init__(self):
        self._docs: dict[str, dict] = {}
        self._next_id = 0

    def documents(self) -> list[dict]:
        return list(self._docs.values())

    def index(self, *, index, body, refresh=False):
        self._next_id += 1
        doc_id = str(self._next_id)
        self._docs[doc_id] = body
        return {"_id": doc_id}

    def search(self, *, index, body):
        if "aggs" in body:
            counts: dict[str, int] = {}
            for doc in self._docs.values():
                counts[doc["document"]] = counts.get(doc["document"], 0) + 1
            buckets = [{"key": name, "doc_count": count} for name, count in counts.items()]
            return {"aggregations": {"documents": {"buckets": buckets}}}
        term = body.get("query", {}).get("term", {}).get("document")
        hits = [{"_id": doc_id, "_source": doc} for doc_id, doc in self._docs.items() if doc["document"] == term]
        size = body.get("size", len(hits))
        return {"hits": {"hits": hits[:size]}}

    def delete(self, *, index, id):
        self._docs.pop(id, None)


def service(client: FakeAdminClient) -> RAGDocumentAdminService:
    # delete_retry_delay_seconds=0 -- the fake client has no indexing lag to wait out.
    return RAGDocumentAdminService(
        client, "cardiology-index", HashEmbeddingProvider(8), delete_retry_delay_seconds=0
    )


def test_upsert_document_indexes_new_content():
    client = FakeAdminClient()
    replaced, indexed = service(client).upsert_document(
        document_name="Anticoagulation Policy",
        version="1.0",
        effective_date="2026-01-01",
        source="Clinical policy",
        content_markdown="## Scope\nApplies to all inpatients on warfarin.",
    )
    assert replaced == 0
    assert indexed == 1
    docs = client.documents()
    assert docs[0]["document"] == "Anticoagulation Policy"
    assert docs[0]["section"] == "Scope"


def test_upsert_document_replaces_existing_chunks():
    client = FakeAdminClient()
    svc = service(client)
    svc.upsert_document(
        document_name="Anticoagulation Policy",
        version="1.0",
        effective_date="2026-01-01",
        source="Clinical policy",
        content_markdown="## Scope\nOriginal text.",
    )
    replaced, indexed = svc.upsert_document(
        document_name="Anticoagulation Policy",
        version="2.0",
        effective_date="2026-06-01",
        source="Clinical policy",
        content_markdown="## Scope\nUpdated text.",
    )
    assert replaced == 1
    assert indexed == 1
    assert len(client.documents()) == 1
    assert "Updated" in client.documents()[0]["content"]


def test_upsert_document_rejects_content_with_no_sections():
    # A bare "# Title" line is treated as a document title, not section content,
    # and is excluded -- leaving no sections to index.
    with pytest.raises(ValueError, match="No content sections"):
        service(FakeAdminClient()).upsert_document(
            document_name="Empty Doc", version="1.0", effective_date="2026-01-01", source="Src", content_markdown="# Just a title"
        )


def test_upsert_document_rejects_blank_name():
    with pytest.raises(ValueError, match="document_name"):
        service(FakeAdminClient()).upsert_document(
            document_name="  ", version="1.0", effective_date="2026-01-01", source="Src", content_markdown="## Scope\ntext"
        )


def test_list_documents_returns_summary_per_document():
    svc = service(FakeAdminClient())
    svc.upsert_document(
        document_name="Policy A", version="1.0", effective_date="2026-01-01", source="Src", content_markdown="## Scope\ntext one"
    )
    docs = svc.list_documents()
    assert len(docs) == 1
    assert docs[0]["document_name"] == "Policy A"
    assert docs[0]["chunk_count"] == 1


def test_delete_document_retries_to_catch_a_not_yet_visible_straggler():
    """Regression test: OpenSearch Serverless indexes near-real-time, not instantly, so a
    chunk written moments before a delete call may not appear in the delete's first search.
    delete_document() must retry rather than silently leaving that chunk orphaned."""
    client = FakeAdminClient()
    client.index(index="cardiology-index", body={"document": "Policy A", "section": "Scope", "content": "visible now"})
    straggler_id = client.index(
        index="cardiology-index", body={"document": "Policy A", "section": "Detail", "content": "not yet visible"}
    )["_id"]

    real_search = client.search
    calls = {"n": 0}

    def flaky_search(*, index, body):
        calls["n"] += 1
        response = real_search(index=index, body=body)
        if calls["n"] == 1 and "query" in body:
            # Simulate the straggler chunk not yet being visible on the first search.
            hits = [h for h in response["hits"]["hits"] if h["_id"] != straggler_id]
            return {"hits": {"hits": hits}}
        return response

    client.search = flaky_search
    svc = RAGDocumentAdminService(client, "cardiology-index", HashEmbeddingProvider(8), delete_retry_delay_seconds=0)

    deleted = svc.delete_document("Policy A")

    assert deleted == 2
    assert client.documents() == []


def test_delete_document_removes_all_its_chunks():
    svc = service(FakeAdminClient())
    svc.upsert_document(
        document_name="Policy A", version="1.0", effective_date="2026-01-01", source="Src", content_markdown="## Scope\ntext one"
    )
    deleted = svc.delete_document("Policy A")
    assert deleted == 1
    assert svc.list_documents() == []
