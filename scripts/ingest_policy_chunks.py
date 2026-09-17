"""Embed approved policy chunks and index them in OpenSearch.

Run from the repository root after configuring Azure OpenAI and OpenSearch
environment variables:
    python scripts/ingest_policy_chunks.py
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import requests
from opensearchpy import OpenSearch
from dotenv import load_dotenv
load_dotenv()

CHUNKS_PATH = Path("data/synthetic_hospital_medication_safety_policy_chunks.json")
EMBEDDING_DIMENSION = 1536


def azure_embedding(text: str) -> list[float]:
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"]
    api_version = os.environ["AZURE_OPENAI_API_VERSION"]
    response = requests.post(
        f"{endpoint}/openai/deployments/{deployment}/embeddings",
        params={"api-version": api_version},
        headers={"api-key": os.environ["AZURE_OPENAI_API_KEY"], "Content-Type": "application/json"},
        json={"input": text},
        timeout=30,
    )
    response.raise_for_status()
    embedding = response.json()["data"][0]["embedding"]
    if len(embedding) != EMBEDDING_DIMENSION:
        raise ValueError(f"Expected {EMBEDDING_DIMENSION}-dimension embedding, received {len(embedding)}.")
    return embedding


def opensearch_client() -> OpenSearch:
    return OpenSearch(
        hosts=[{
            "host": os.environ["OPENSEARCH_HOST"],
            "port": int(os.environ["OPENSEARCH_PORT"]),
        }],
        http_auth=(
            os.environ["OPENSEARCH_USERNAME"],
            os.environ["OPENSEARCH_PASSWORD"],
        ),
        use_ssl=True,
        verify_certs=True,
        timeout=60,
        max_retries=3,
        retry_on_timeout=True,
    )


def chunk_id(chunk: dict) -> str:
    identity = "|".join(str(chunk.get(field, "")) for field in ("document_id", "version", "section", "page", "text"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def main() -> None:
    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    client = opensearch_client()
    index_name = os.environ["OPENSEARCH_RAG_INDEX"]
    indexed = 0
    failed_ids: list[str] = []

    for chunk in chunks:
        identifier = chunk_id(chunk)
        try:
            document = {**chunk, "chunk_id": identifier, "embedding": azure_embedding(chunk["text"])}
            client.index(index=index_name, id=identifier, body=document)
            indexed += 1
        except Exception:
            failed_ids.append(identifier)

    print(f"Chunks successfully indexed: {indexed}")
    print(f"Failed chunk IDs: {', '.join(failed_ids) if failed_ids else 'none'}")


if __name__ == "__main__":
    main()
