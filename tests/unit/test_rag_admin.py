from __future__ import annotations

import pytest
from opensearchpy.exceptions import NotFoundError

from rag.ingestion.admin import RAGDocumentAdminService


class FakeIndicesClient:
    def __init__(self):
        self.index_exists = True

    def exists(self, *, index):
        return self.index_exists

    def delete(self, *, index):
        self.index_exists = False


class FakeRawClient:
    """Stands in for the raw opensearch-py client OpenSearchVectorSearch.client exposes."""

    def __init__(self, docs: dict[str, dict]):
        self._docs = docs
        self.indices = FakeIndicesClient()

    def search(self, *, index, body):
        if not self.indices.index_exists:
            raise NotFoundError(404, "index_not_found_exception", f"no such index [{index}]")
        if "aggs" in body:
            counts: dict[str, int] = {}
            for doc in self._docs.values():
                name = doc["metadata"]["document_name"]
                counts[name] = counts.get(name, 0) + 1
            buckets = [{"key": name, "doc_count": count} for name, count in counts.items()]
            return {"aggregations": {"documents": {"buckets": buckets}}}
        term = body.get("query", {}).get("term", {}).get("metadata.document_name.keyword")
        hits = [{"_id": doc_id, "_source": doc} for doc_id, doc in self._docs.items() if doc["metadata"]["document_name"] == term]
        size = body.get("size", len(hits))
        return {"hits": {"hits": hits[:size]}}


class FakeVectorStore:
    def __init__(self):
        self._docs: dict[str, dict] = {}
        self._next_id = 0
        self.client = FakeRawClient(self._docs)
        self.index_name = "cardiology-index"

    def documents(self) -> list[dict]:
        return list(self._docs.values())

    def add_texts(self, texts, metadatas=None, **kwargs):
        metadatas = metadatas or [{} for _ in texts]
        ids = []
        for text, metadata in zip(texts, metadatas):
            self._next_id += 1
            doc_id = str(self._next_id)
            self._docs[doc_id] = {"text": text, "metadata": metadata}
            ids.append(doc_id)
        return ids

    def delete(self, ids=None, refresh_indices=True, **kwargs):
        for doc_id in ids or []:
            self._docs.pop(doc_id, None)
        return True


def service(store: FakeVectorStore) -> RAGDocumentAdminService:
    # delete_retry_delay_seconds=0 -- the fake store has no indexing lag to wait out.
    return RAGDocumentAdminService(store, delete_retry_delay_seconds=0)


def test_recreate_index_deletes_existing_index():
    store = FakeVectorStore()
    assert service(store).recreate_index() is True
    assert store.client.indices.index_exists is False


def test_recreate_index_returns_false_when_no_index():
    store = FakeVectorStore()
    store.client.indices.index_exists = False
    assert service(store).recreate_index() is False


def test_delete_document_returns_zero_when_index_does_not_exist():
    """Regression test: right after recreate_index() (or for a brand-new
    knowledge base), the index doesn't exist at all yet -- delete_document()
    must treat that as "nothing to delete," not crash."""
    store = FakeVectorStore()
    store.client.indices.index_exists = False
    assert service(store).delete_document("Anything") == 0


def test_upsert_sections_works_when_index_does_not_exist_yet():
    from rag.models import DocumentMetadata

    store = FakeVectorStore()
    store.client.indices.index_exists = False
    metadata = DocumentMetadata("Policy A", "1.0", "Scope", "2026-01-01", "Synthetic")
    replaced, indexed = service(store).upsert_sections("Policy A", [("Scope", "some content here", metadata)])
    assert replaced == 0
    assert indexed == 1


def test_upsert_sections_indexes_presectioned_content():
    from rag.models import DocumentMetadata

    store = FakeVectorStore()
    metadata = DocumentMetadata("Policy A", "1.0", "Scope", "2026-01-01", "Synthetic")
    replaced, indexed = service(store).upsert_sections("Policy A", [("Scope", "some content here", metadata)])
    assert replaced == 0
    assert indexed == 1
    assert store.documents()[0]["metadata"]["document_name"] == "Policy A"


def test_upsert_document_indexes_new_content():
    store = FakeVectorStore()
    replaced, indexed = service(store).upsert_document(
        document_name="Anticoagulation Policy",
        version="1.0",
        effective_date="2026-01-01",
        source="Clinical policy",
        content_markdown="## Scope\nApplies to all inpatients on warfarin.",
    )
    assert replaced == 0
    assert indexed == 1
    docs = store.documents()
    assert docs[0]["metadata"]["document_name"] == "Anticoagulation Policy"
    assert docs[0]["metadata"]["section"] == "Scope"


def test_upsert_document_replaces_existing_chunks():
    store = FakeVectorStore()
    svc = service(store)
    svc.upsert_document(
        document_name="Anticoagulation Policy", version="1.0", effective_date="2026-01-01", source="Clinical policy",
        content_markdown="## Scope\nOriginal text.",
    )
    replaced, indexed = svc.upsert_document(
        document_name="Anticoagulation Policy", version="2.0", effective_date="2026-06-01", source="Clinical policy",
        content_markdown="## Scope\nUpdated text.",
    )
    assert replaced == 1
    assert indexed == 1
    assert len(store.documents()) == 1
    assert "Updated" in store.documents()[0]["text"]


def test_upsert_document_rejects_content_with_no_sections():
    with pytest.raises(ValueError, match="No content sections"):
        service(FakeVectorStore()).upsert_document(
            document_name="Empty Doc", version="1.0", effective_date="2026-01-01", source="Src", content_markdown="# Just a title"
        )


def test_upsert_document_rejects_blank_name():
    with pytest.raises(ValueError, match="document_name"):
        service(FakeVectorStore()).upsert_document(
            document_name="  ", version="1.0", effective_date="2026-01-01", source="Src", content_markdown="## Scope\ntext"
        )


def test_list_documents_returns_summary_per_document():
    store = FakeVectorStore()
    svc = service(store)
    svc.upsert_document(
        document_name="Policy A", version="1.0", effective_date="2026-01-01", source="Src", content_markdown="## Scope\ntext one"
    )
    docs = svc.list_documents()
    assert len(docs) == 1
    assert docs[0]["document_name"] == "Policy A"
    assert docs[0]["chunk_count"] == 1


def test_delete_document_removes_all_its_chunks():
    store = FakeVectorStore()
    svc = service(store)
    svc.upsert_document(
        document_name="Policy A", version="1.0", effective_date="2026-01-01", source="Src", content_markdown="## Scope\ntext one"
    )
    deleted = svc.delete_document("Policy A")
    assert deleted == 1
    assert svc.list_documents() == []


def test_delete_document_retries_to_catch_a_not_yet_visible_straggler():
    """Regression test: OpenSearch Serverless indexes near-real-time, not instantly, so a
    chunk written moments before a delete call may not appear in the delete's first search.
    delete_document() must retry rather than silently leaving that chunk orphaned."""
    store = FakeVectorStore()
    store.add_texts(["visible now"], metadatas=[{"document_name": "Policy A", "section": "Scope"}])
    straggler_id = store.add_texts(["not yet visible"], metadatas=[{"document_name": "Policy A", "section": "Detail"}])[0]

    real_search = store.client.search
    calls = {"n": 0}

    def flaky_search(*, index, body):
        calls["n"] += 1
        response = real_search(index=index, body=body)
        if calls["n"] == 1 and "query" in body:
            hits = [h for h in response["hits"]["hits"] if h["_id"] != straggler_id]
            return {"hits": {"hits": hits}}
        return response

    store.client.search = flaky_search
    svc = RAGDocumentAdminService(store, delete_retry_delay_seconds=0)

    deleted = svc.delete_document("Policy A")

    assert deleted == 2
    assert store.documents() == []
