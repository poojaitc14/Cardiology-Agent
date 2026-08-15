"""Azure OpenAI enabled RAG ingestion pipeline."""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol

from backend.services.azure_openai import AzureOpenAIConfig, AzureOpenAIEmbedding
from rag.models import DocumentChunk, DocumentMetadata

LOGGER = logging.getLogger(__name__)


class SearchIndex(Protocol):
    def index(self, *, index: str, id: str, body: dict[str, Any], refresh: bool = False) -> Any: ...


def get_embedding_provider():
    """Get the appropriate embedding provider based on configuration.
    
    Returns:
        AzureOpenAIEmbedding if Azure OpenAI is configured, otherwise HashEmbeddingProvider
    """
    azure_config = AzureOpenAIConfig()
    
    if azure_config.is_configured():
        LOGGER.info("Using Azure OpenAI for embeddings (text-embedding-3-small)")
        try:
            return AzureOpenAIEmbedding(azure_config)
        except ImportError:
            LOGGER.warning("Azure OpenAI libraries not installed, falling back to hash embeddings")
            from rag.ingestion.pipeline import HashEmbeddingProvider
            return HashEmbeddingProvider()
        except Exception as e:
            LOGGER.warning(f"Failed to initialize Azure OpenAI embeddings: {e}, falling back to hash embeddings")
            from rag.ingestion.pipeline import HashEmbeddingProvider
            return HashEmbeddingProvider()
    else:
        LOGGER.info("Azure OpenAI not configured, using hash embeddings for development")
        from rag.ingestion.pipeline import HashEmbeddingProvider
        return HashEmbeddingProvider()


def index_chunks_with_azure(
    index: SearchIndex, 
    index_name: str, 
    chunks: list[DocumentChunk],
) -> int:
    """Index chunks with Azure OpenAI embeddings into OpenSearch.
    
    Args:
        index: OpenSearch index client
        index_name: Name of the index
        chunks: Document chunks to index
        
    Returns:
        Number of chunks indexed
    """
    embedder = get_embedding_provider()
    
    # For Azure OpenAI, batch embed all chunks for efficiency
    if hasattr(embedder, 'embed_batch'):
        chunk_texts = [chunk.content for chunk in chunks]
        try:
            embeddings = embedder.embed_batch(chunk_texts)
        except Exception as e:
            LOGGER.error(f"Batch embedding failed: {e}, falling back to single embeddings")
            embeddings = [embedder.embed(chunk.content) for chunk in chunks]
    else:
        embeddings = [embedder.embed(chunk.content) for chunk in chunks]
    
    # Index chunks with embeddings
    for chunk, embedding in zip(chunks, embeddings):
        index.index(
            index=index_name,
            id=chunk.chunk_id,
            refresh=False,
            body={
                "document": chunk.document_name,
                "section": chunk.section,
                "content": chunk.content,
                "metadata": {
                    "document_name": chunk.metadata.document_name,
                    "version": chunk.metadata.version,
                    "section": chunk.metadata.section,
                    "effective_date": chunk.metadata.effective_date,
                    "source": chunk.metadata.source,
                },
                "embedding": embedding,
            }
        )
    
    LOGGER.info(f"Indexed {len(chunks)} chunks with Azure OpenAI embeddings (text-embedding-3-small)")
    return len(chunks)
