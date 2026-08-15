"""Operator-only command that creates the OpenSearch index (if missing) and indexes
the 15 synthetic cardiology documents. This must never be invoked by the agent runtime."""
from __future__ import annotations

import os

from opensearchpy import OpenSearch

from rag.ingestion.dummy_documents import index_dummy_documents
from rag.ingestion.pipeline import HashEmbeddingProvider
from rag.opensearch_client import build_serverless_client


def create_index_if_missing(client: OpenSearch, index_name: str, dimensions: int) -> bool:
    """Create the k-NN index with a vector mapping matching `dimensions`. Returns True if created."""
    if client.indices.exists(index=index_name):
        return False
    client.indices.create(
        index=index_name,
        body={
            "settings": {"index": {"knn": True}},
            "mappings": {
                "properties": {
                    "document": {"type": "keyword"},
                    "section": {"type": "keyword"},
                    "content": {"type": "text"},
                    "metadata": {
                        "properties": {
                            "document_name": {"type": "keyword"},
                            "version": {"type": "keyword"},
                            "section": {"type": "keyword"},
                            "effective_date": {"type": "keyword"},
                            "source": {"type": "keyword"},
                        }
                    },
                    "embedding": {"type": "knn_vector", "dimension": dimensions},
                }
            },
        },
    )
    return True


def main() -> None:
    host = os.environ.get("OPENSEARCH_HOST")
    index_name = os.environ.get("OPENSEARCH_INDEX")
    region = os.environ.get("AWS_REGION")
    if not host or not index_name:
        raise SystemExit("Set OPENSEARCH_HOST and OPENSEARCH_INDEX before indexing.")
    if not region:
        raise SystemExit("Set AWS_REGION before indexing.")
    dimensions = int(os.environ.get("RAG_EMBEDDING_DIMENSIONS", "128"))

    client = build_serverless_client(host, region)
    created = create_index_if_missing(client, index_name, dimensions)
    print(f"{'Created' if created else 'Reusing existing'} index '{index_name}' ({dimensions}-dim embeddings).")

    written = index_dummy_documents(client, index_name, HashEmbeddingProvider(dimensions))
    try:
        client.indices.refresh(index=index_name)
    except Exception:
        pass  # OpenSearch Serverless does not support explicit refresh; indexing is near-real-time automatically.
    print(f"Indexed {written} chunks into '{index_name}'.")


if __name__ == "__main__":
    main()
