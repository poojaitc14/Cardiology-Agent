from __future__ import annotations

from rag.ingestion.pipeline import HashEmbeddingProvider, chunk_sections
from rag.ingestion.dummy_documents import load_dummy_sections
from rag.models import DocumentMetadata
from rag.retrieval.cardiology_rag import CardiologyRAGService


class FakeSearch:
    def __init__(self, response): self.response, self.request = response, None
    def search(self, *, index, body): self.request = (index, body); return self.response


def test_chunking_preserves_document_metadata():
    metadata = DocumentMetadata("Policy", "1.0", "Scope", "2026-01-01", "Synthetic")
    chunks = chunk_sections([("Scope", "one two three", metadata)], chunk_size=2, overlap=1)
    assert chunks[0].metadata == metadata and chunks[0].section == "Scope"


def test_dummy_document_list_contains_all_requested_documents():
    sections = load_dummy_sections()
    assert len(sections) == 15
    assert {metadata.source for _, _, metadata in sections} == {"Synthetic RAG fixture"}


def test_retrieval_returns_required_fields_and_score():
    response = {"hits": {"hits": [{"_score": 0.91, "_source": {"document": "Policy", "section": "Scope", "content": "Synthetic content", "metadata": {"document_name": "Policy", "version": "1.0", "section": "Scope", "effective_date": "2026-01-01", "source": "Synthetic"}}}]}}
    client = FakeSearch(response)
    result = CardiologyRAGService(client, "cardiology-index", HashEmbeddingProvider(8)).retrieve("anticoagulation")
    assert result.available and result.results[0].document == "Policy"
    assert result.results[0].similarity_score == 0.91
    assert client.request[0] == "cardiology-index"


def test_empty_retrieval_does_not_fabricate_evidence():
    result = CardiologyRAGService(FakeSearch({"hits": {"hits": []}}), "index").retrieve("query")
    assert not result.results and result.user_message == "Sufficient evidence was not found in the knowledge base."
