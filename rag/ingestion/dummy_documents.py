"""Load synthetic RAG fixtures into the regular ingestion pipeline."""
from __future__ import annotations

import json
from pathlib import Path

from rag.ingestion.pipeline import HashEmbeddingProvider, SearchIndex, chunk_sections, index_chunks
from rag.models import DocumentMetadata

DEFAULT_DUMMY_DOCUMENTS = Path(__file__).parent.parent / "documents" / "dummy_cardiology_documents.json"


def load_dummy_sections(path: Path = DEFAULT_DUMMY_DOCUMENTS) -> list[tuple[str, str, DocumentMetadata]]:
    """Load the generated synthetic documents as metadata-bearing RAG sections."""
    documents = json.loads(path.read_text(encoding="utf-8"))
    return [
        (section["name"], section["content"], DocumentMetadata(document["document_name"], document["version"], section["name"], document["effective_date"], document["source"]))
        for document in documents for section in document["sections"]
    ]


def index_dummy_documents(index: SearchIndex, index_name: str, embedder: HashEmbeddingProvider | None = None) -> int:
    """Index all 15 synthetic documents through extraction, chunking, and embedding."""
    chunks = chunk_sections(load_dummy_sections())
    return index_chunks(index, index_name, chunks, embedder or HashEmbeddingProvider())
