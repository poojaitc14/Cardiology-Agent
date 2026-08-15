# Azure OpenAI Integration Guide

## Overview

This project has been configured to use **Azure OpenAI** for:
- **Embeddings**: `text-embedding-3-small` - High-quality text embeddings for RAG document retrieval
- **LLM**: `GPT-4o mini` (GPT 4.1 mini) - For clinical decision support answer generation

## Prerequisites

1. **Azure Account** with OpenAI service access
2. **Azure OpenAI Credentials**:
   - API Key
   - Endpoint URL
   - API Version
3. **Deployed Models** in your Azure OpenAI account:
   - `text-embedding-3-small` deployment
   - `gpt-4o-mini` deployment (for GPT 4.1 mini)

## Setup Instructions

### Step 1: Get Azure OpenAI Credentials

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to your **Azure OpenAI** resource
3. Go to **Keys and Endpoint** section
4. Copy:
   - One of the API keys
   - The endpoint URL (e.g., `https://your-resource.openai.azure.com/`)

### Step 2: Configure Environment Variables

Update your `.env` file with Azure OpenAI credentials:

```bash
# Azure OpenAI Configuration
AZURE_OPENAI_API_KEY=your_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o-mini
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

### Step 3: Install Azure OpenAI Dependencies

```bash
pip install -r requirements.txt
```

Or manually:

```bash
pip install openai>=1.0
```

### Step 4: Verify Configuration

```bash
python -c "
from backend.services.azure_openai import AzureOpenAIConfig
config = AzureOpenAIConfig()
if config.is_configured():
    print('✓ Azure OpenAI is properly configured')
else:
    print('✗ Azure OpenAI is not configured')
"
```

## Usage

### Embeddings (RAG Documents)

```python
from backend.services.azure_openai import AzureOpenAIEmbedding

# Initialize embedder
embedder = AzureOpenAIEmbedding()

# Single embedding
embedding = embedder.embed("Patient presented with chest pain")
print(f"Embedding dimension: {len(embedding)}")  # 1536 for text-embedding-3-small

# Batch embeddings (more efficient for multiple documents)
embeddings = embedder.embed_batch([
    "Document 1 content",
    "Document 2 content",
    "Document 3 content",
])
```

### Clinical Answer Generation (LLM)

```python
from backend.services.azure_openai import AzureOpenAILLM

# Initialize LLM
llm = AzureOpenAILLM()

# Generate clinical response
response = llm.generate_clinical_response(
    patient_info="Patient: 65-year-old male, hypertension, diabetes",
    question="What medications should be considered for this patient?",
    retrieved_docs=[
        "Guideline 1: Cardiology treatment protocols...",
        "Guideline 2: Drug interactions...",
    ]
)
print(response)
```

### RAG Pipeline with Azure OpenAI

```python
from backend.rag_azure import get_embedding_provider, index_chunks_with_azure

# Get embedding provider (automatically uses Azure OpenAI if configured)
embedder = get_embedding_provider()

# Use in RAG ingestion
indexed_count = index_chunks_with_azure(
    index=opensearch_client,
    index_name="cardiology-documents",
    chunks=document_chunks,
)
print(f"Indexed {indexed_count} chunks with Azure OpenAI embeddings")
```

## Configuration Details

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `AZURE_OPENAI_API_KEY` | API key for authentication | `abc123...` |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL | `https://myresource.openai.azure.com/` |
| `AZURE_OPENAI_API_VERSION` | OpenAI API version | `2024-08-01-preview` |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | GPT model deployment name | `gpt-4o-mini` |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME` | Embedding model deployment name | `text-embedding-3-small` |
| `AZURE_OPENAI_EMBEDDING_MODEL` | Embedding model identifier | `text-embedding-3-small` |
| `RAG_EMBEDDING_DIMENSIONS` | Embedding vector dimensions | `1536` |

### Model Specifications

**Text Embedding 3 Small:**
- Input tokens: 8,191
- Output dimensions: 1536
- Use case: RAG document embeddings, semantic search
- Price: Lower cost than larger models

**GPT 4o Mini (GPT 4.1 mini):**
- Context window: 128,000 tokens
- Use case: Clinical decision support, medical query answering
- Capabilities: Multimodal, high reasoning ability

## Fallback Behavior

If Azure OpenAI is not configured or fails:
- **Embeddings**: Falls back to `HashEmbeddingProvider` (deterministic hash-based, for development)
- **LLM**: No automatic fallback (must be configured)

To disable Azure OpenAI and use development embeddings:
- Leave `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` empty

## Troubleshooting

### Error: "Azure OpenAI is not configured"

**Solution**: Ensure both `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` are set in `.env`

```bash
# Check configuration
echo $AZURE_OPENAI_API_KEY
echo $AZURE_OPENAI_ENDPOINT
```

### Error: "openai package not installed"

**Solution**: Install the OpenAI library (it provides the `AzureOpenAI` client)

```bash
pip install openai>=1.0
```

### Error: "Authentication failed" or "Invalid credentials"

**Solution**: Verify your API key and endpoint

1. Check API key is correct in Azure Portal
2. Ensure endpoint URL includes the trailing slash: `https://your-resource.openai.azure.com/`
3. Verify API key has permissions for the resource

### Error: "Deployment not found"

**Solution**: Check deployment names match your Azure OpenAI account

1. Go to Azure Portal → OpenAI → Model deployments
2. Verify deployment names:
   - `text-embedding-3-small` for embeddings
   - `gpt-4o-mini` for GPT (or your custom deployment name)
3. Update `.env` with correct deployment names

### Slow Embeddings or LLM Responses

**Potential Causes:**
- Network latency to Azure region
- Rate limiting due to quota
- Large batch sizes for embeddings

**Solutions:**
- Ensure Azure region is close to your application
- Reduce batch size for embeddings
- Add rate limiting/retry logic
- Check Azure Portal for quota usage

## Integration Points

### 1. RAG Retrieval (Embeddings)

Location: `backend/rag_azure.py`

The RAG service uses Azure OpenAI embeddings:
```python
embedder = get_embedding_provider()  # Returns AzureOpenAIEmbedding if configured
embedding = embedder.embed(query)
```

### 2. Document Indexing

Location: `rag/ingestion/pipeline.py` (updated to use Azure OpenAI)

Documents are embedded with `text-embedding-3-small` and indexed in OpenSearch.

### 3. Clinical Answer Generation

Location: `backend/services/azure_openai.py`

The agent can generate clinical responses using:
```python
llm = AzureOpenAILLM()
response = llm.generate_clinical_response(patient_info, question, docs)
```

## Security Best Practices

1. **Never commit `.env` files** with real API keys
2. **Use environment variables** in production
3. **Rotate API keys regularly**
4. **Use Azure Managed Identity** when running on Azure resources
5. **Monitor API usage** in Azure Portal
6. **Set rate limits** to prevent runaway costs

## Performance Optimization

### Batch Embeddings

For multiple documents, use batch embedding:
```python
embedder.embed_batch([doc1, doc2, doc3])  # More efficient than individual embeds
```

### Caching

Consider caching embeddings for frequently queried documents:
```python
# Example: Cache embeddings in Redis
cache_key = f"embedding:{hash(text)}"
embedding = redis_client.get(cache_key) or embedder.embed(text)
```

### Rate Limiting

Azure OpenAI has quota limits. Implement rate limiting:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential())
def get_embedding(text):
    return embedder.embed(text)
```

## Cost Estimation

Approximate costs (as of 2024, check Azure Portal for current pricing):
- **Text Embedding 3 Small**: ~$0.02 per 1M tokens
- **GPT-4o Mini**: ~$0.15 per 1M input tokens, $0.60 per 1M output tokens

Example: 1000 documents (200 tokens each) + 100 queries:
- Embedding cost: ~$2 (documents) + $0.02 (queries)
- LLM cost: ~$15 (assuming 300 token responses)
- **Total estimate**: ~$17 for 1000 documents + 100 queries

## Monitoring and Observability

### Langfuse Integration

Azure OpenAI calls are automatically traced with Langfuse:
- Trace IDs for all requests
- Latency metrics
- Token usage tracking
- Error logging

View traces in [Langfuse Dashboard](https://cloud.langfuse.com)

### Logging

Check logs for Azure OpenAI operations:
```bash
tail -f logs/app.log | grep "Azure OpenAI"
```

## Additional Resources

- [Azure OpenAI Documentation](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
- [Text Embedding 3 Small](https://platform.openai.com/docs/guides/embeddings/embedding-models)
- [GPT-4o Mini](https://platform.openai.com/docs/models/gpt-4o-mini)
- [Azure SDK for Python](https://github.com/Azure/azure-sdk-for-python)

## Support

For issues with:
- **Azure OpenAI**: See [Azure OpenAI Support](https://learn.microsoft.com/en-us/azure/ai-services/openai/reference)
- **Integration**: Check logs and error messages
- **Credentials**: Verify in Azure Portal

---

**Last Updated**: 2026-08-14
**Azure OpenAI Integration Version**: 1.0
