"""Create the approved-policy OpenSearch vector index when it does not exist.

Run from the repository root after setting OpenSearch environment variables:
    python scripts/create_opensearch_index.py
"""
from __future__ import annotations

import os

from opensearchpy import OpenSearch
from dotenv import load_dotenv
load_dotenv()
EMBEDDING_DIMENSION = 1536


def get_client() -> OpenSearch:
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


def index_definition() -> dict:
    return {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                "document_id": {"type": "keyword"},
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "version": {"type": "keyword"},
                "status": {"type": "keyword"},
                "effective_date": {"type": "date", "format": "strict_date_optional_time||yyyy-MM-dd"},
                "section": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "page": {"type": "keyword"},
                "text": {"type": "text"},
                "embedding": {"type": "knn_vector", "dimension": EMBEDDING_DIMENSION},
            }
        },
    }


def main() -> None:
    index_name = os.environ["OPENSEARCH_RAG_INDEX"]
    client = get_client()
    if client.indices.exists(index=index_name):
        print(f"Index already exists: {index_name}")
        return
    client.indices.create(index=index_name, body=index_definition())
    print(f"Index created: {index_name}")


if __name__ == "__main__":
    main()
