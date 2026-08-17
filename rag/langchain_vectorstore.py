"""LangChain-based vector store construction for the cardiology RAG knowledge
base: Azure OpenAI (text-embedding-3-small) embeddings over an OpenSearch
Serverless collection.

This is the one place SigV4 auth, the embedding model, and the index name come
together for every LangChain-backed RAG code path (retrieval and admin alike),
replacing the HashEmbeddingProvider development stand-in with real semantic
embeddings.

Uses `langchain_community.vectorstores.OpenSearchVectorSearch` rather than the
newer standalone `langchain-opensearch` package: as of this writing that
package is at v0.0.x and doesn't yet have `langchain_community`'s
battle-tested AOSS (OpenSearch Serverless) handling -- worth revisiting once it
matures.
"""
from __future__ import annotations

import os

import boto3
from langchain_community.vectorstores import OpenSearchVectorSearch
from langchain_openai import AzureOpenAIEmbeddings
from opensearchpy import AWSV4SignerAuth, RequestsHttpConnection

# OpenSearch Serverless's k-NN implementation only supports the "nmslib" or
# "faiss" engines; AWS's own guidance for Serverless vector search collections
# recommends "faiss".
AOSS_ENGINE = "faiss"


def build_azure_embeddings() -> AzureOpenAIEmbeddings:
    """Build the Azure OpenAI text-embedding-3-small embedding function from env vars."""
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    if not endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT must be configured.")
    if not api_key:
        raise ValueError("AZURE_OPENAI_API_KEY must be configured.")
    return AzureOpenAIEmbeddings(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        azure_deployment=os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small"),
    )


def build_vector_store(embeddings: AzureOpenAIEmbeddings | None = None) -> OpenSearchVectorSearch:
    """Build the LangChain OpenSearch Serverless vector store from env vars.

    Uses the same AWS SigV4 (service "aoss") authentication as every other AWS
    call in this app -- there is no username/password to configure.
    """
    host = os.environ.get("OPENSEARCH_HOST")
    index_name = os.environ.get("OPENSEARCH_INDEX")
    region = os.environ.get("AWS_REGION")
    if not host:
        raise ValueError("OPENSEARCH_HOST must be configured.")
    if not index_name:
        raise ValueError("OPENSEARCH_INDEX must be configured.")
    if not region:
        raise ValueError("AWS_REGION must be configured.")

    bare_host = host.replace("https://", "").replace("http://", "").rstrip("/")
    credentials = boto3.Session().get_credentials()
    auth = AWSV4SignerAuth(credentials, region, "aoss")
    return OpenSearchVectorSearch(
        opensearch_url=f"https://{bare_host}:443",
        index_name=index_name,
        embedding_function=embeddings or build_azure_embeddings(),
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        engine=AOSS_ENGINE,
        # opensearch-py's default 10s read timeout is too tight for a bulk
        # write of several real (1536-dim) embeddings, especially right after
        # an index is (re)created and its mapping is still settling.
        timeout=30,
    )
