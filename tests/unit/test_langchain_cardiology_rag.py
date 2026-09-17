from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag.retrieval.langchain_cardiology_rag import LangChainCardiologyRAGService


class FakeVectorStore:
    def __init__(self, hits=None, raises=None):
        self.hits = hits or []
        self.raises = raises
        self.last_call = None

    def similarity_search_with_score(self, query, k=4, **kwargs):
        self.last_call = (query, k)
        if self.raises:
            raise self.raises
        return self.hits


def make_doc(content, metadata):
    return SimpleNamespace(page_content=content, metadata=metadata)


def test_retrieval_returns_required_fields_and_score():
    doc = make_doc(
        "Synthetic content",
        {"document_name": "Policy", "section": "Scope", "version": "1.0", "effective_date": "2026-01-01", "source": "Synthetic"},
    )
    store = FakeVectorStore(hits=[(doc, 0.91)])
    result = LangChainCardiologyRAGService(store).retrieve("anticoagulation")
    assert result.available
    assert result.results[0].document == "Policy"
    assert result.results[0].content == "Synthetic content"
    assert result.results[0].similarity_score == 0.91
    assert store.last_call == ("anticoagulation", 5)


def test_empty_retrieval_does_not_fabricate_evidence():
    result = LangChainCardiologyRAGService(FakeVectorStore(hits=[])).retrieve("query")
    assert not result.results
    assert result.user_message == "Sufficient evidence was not found in the knowledge base."


def test_blank_query_is_rejected_without_calling_the_store():
    store = FakeVectorStore()
    result = LangChainCardiologyRAGService(store).retrieve("   ")
    assert not result.available or result.results == ()
    assert store.last_call is None


def test_store_error_degrades_gracefully():
    store = FakeVectorStore(raises=RuntimeError("connection refused"))
    result = LangChainCardiologyRAGService(store).retrieve("query")
    assert not result.available
    assert not result.results
    assert "temporarily unavailable" in result.user_message


def test_rejects_out_of_range_limit():
    with pytest.raises(ValueError, match="limit"):
        LangChainCardiologyRAGService(FakeVectorStore()).retrieve("query", limit=50)


def test_missing_metadata_fields_fall_back_to_unknown():
    doc = make_doc("content", {})
    store = FakeVectorStore(hits=[(doc, 0.5)])
    result = LangChainCardiologyRAGService(store).retrieve("query")
    assert result.results[0].document == "Unknown document"
    assert result.results[0].metadata.version == "Unknown"
