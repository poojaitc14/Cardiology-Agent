"""Approved-document vector retrieval for the clinical RAG knowledge base."""

import os
from datetime import UTC, datetime

import requests


def _embedding_for(query: str) -> list[float]:
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"]
    api_version = os.environ["AZURE_OPENAI_API_VERSION"]

    try:
        response = requests.post(
            f"{endpoint}/openai/deployments/{deployment}/embeddings",
            params={"api-version": api_version},
            headers={
                "api-key": os.environ["AZURE_OPENAI_API_KEY"],
                "Content-Type": "application/json",
            },
            json={"input": query},
            timeout=30,
        )

        response.raise_for_status()

        embedding = response.json()["data"][0]["embedding"]

        if len(embedding) != 1536:
            raise RuntimeError(
                f"Expected 1536-dimensional embedding, received {len(embedding)}."
            )

        return embedding

    except (requests.RequestException, KeyError, IndexError, ValueError) as error:
        raise RuntimeError("Embedding service is unavailable.") from error

def search_approved_documents(query: str, limit: int = 5) -> list[dict]:
    """Return only APPROVED OpenSearch vector matches as ClinicalFact-compatible dicts."""
    host = os.getenv("OPENSEARCH_HOST", "")
    index_name = os.getenv("OPENSEARCH_RAG_INDEX", "")
    if not host or not index_name:
        return []
    try:
        from opensearchpy import OpenSearch
    except ImportError as error:
        raise RuntimeError("OpenSearch client dependency is not installed.") from error

    vector = _embedding_for(query)
    client = OpenSearch(
    hosts=[
        {
            "host": host,
            "port": int(os.getenv("OPENSEARCH_PORT", "443")),
        }
    ],
    http_auth=(
        os.getenv("OPENSEARCH_USERNAME"),
        os.getenv("OPENSEARCH_PASSWORD"),
    ),
    use_ssl=True,
    verify_certs=True,
    timeout=60,
    max_retries=3,
    retry_on_timeout=True,
)
    response = client.search(
    index=index_name,
    body={
        "size": min(max(limit, 1), 10),
        "query": {
            "knn": {
                "embedding": {
                    "vector": vector,
                    "k": min(max(limit, 1), 10)
                }
            }
        },
        "_source": [
            "text",
            "document_id",
            "title",
            "version",
            "section",
            "effective_date",
            "status"
        ],
    },
)

    results = []
    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        # Defense in depth: do not return stale, draft, or malformed documents.
        if source.get("status") != "APPROVED" or not source.get("text"):
            continue
        results.append({
            "fact": source["text"],
            "source": {
                "source_id": source.get("document_id", hit.get("_id", "unknown-document")),
                "source_type": "hospital_policy",
                "observed_at": datetime.now(UTC).isoformat(),
                "document_version": source.get("version"),
                "section": source.get("section"),
            },
        })
    return results
