"""Azure OpenAI integration for embeddings and LLM inference."""
from __future__ import annotations

import logging
import os
from typing import Any

try:
    from openai import AzureOpenAI
    AZURE_OPENAI_AVAILABLE = True
except ImportError:
    AZURE_OPENAI_AVAILABLE = False

LOGGER = logging.getLogger(__name__)


class AzureOpenAIConfig:
    """Configuration for Azure OpenAI API."""
    
    def __init__(self):
        """Initialize Azure OpenAI configuration from environment variables."""
        self.api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        self.endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        self.api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
        self.deployment_name = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini")
        self.embedding_deployment_name = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small")
        self.embedding_model = os.environ.get("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    
    def is_configured(self) -> bool:
        """Check if Azure OpenAI is properly configured."""
        return bool(self.api_key and self.endpoint)


class AzureOpenAIEmbedding:
    """Azure OpenAI embedding provider using text-embedding-3-small."""
    
    def __init__(self, config: AzureOpenAIConfig | None = None):
        """Initialize Azure OpenAI embedding provider.
        
        Args:
            config: Azure OpenAI configuration (will load from env if not provided)
        """
        if not AZURE_OPENAI_AVAILABLE:
            raise ImportError("openai package not installed. Install with: pip install openai")

        self.config = config or AzureOpenAIConfig()

        if not self.config.is_configured():
            raise ValueError(
                "Azure OpenAI is not configured. Please set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT"
            )

        self.client = AzureOpenAI(
            api_key=self.config.api_key,
            api_version=self.config.api_version,
            azure_endpoint=self.config.endpoint,
            timeout=30.0,
            max_retries=1,
        )

    def embed(self, text: str) -> list[float]:
        """Generate embedding for text using Azure OpenAI text-embedding-3-small.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector as list of floats
        """
        try:
            response = self.client.embeddings.create(
                input=text,
                model=self.config.embedding_deployment_name,
            )
            return response.data[0].embedding
        except Exception as e:
            LOGGER.error(f"Azure OpenAI embedding failed: {e}")
            raise
    
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        try:
            response = self.client.embeddings.create(
                input=texts,
                model=self.config.embedding_deployment_name,
            )
            # Sort by index to ensure correct ordering
            embeddings_by_index = {item.index: item.embedding for item in response.data}
            return [embeddings_by_index[i] for i in range(len(texts))]
        except Exception as e:
            LOGGER.error(f"Azure OpenAI batch embedding failed: {e}")
            raise


class AzureOpenAILLM:
    """Azure OpenAI LLM provider using GPT 4.1 mini."""
    
    def __init__(self, config: AzureOpenAIConfig | None = None):
        """Initialize Azure OpenAI LLM provider.
        
        Args:
            config: Azure OpenAI configuration (will load from env if not provided)
        """
        if not AZURE_OPENAI_AVAILABLE:
            raise ImportError("openai package not installed. Install with: pip install openai")

        self.config = config or AzureOpenAIConfig()

        if not self.config.is_configured():
            raise ValueError(
                "Azure OpenAI is not configured. Please set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT"
            )

        self.client = AzureOpenAI(
            api_key=self.config.api_key,
            api_version=self.config.api_version,
            azure_endpoint=self.config.endpoint,
            timeout=30.0,
            max_retries=1,
        )

    def generate(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.7) -> str:
        """Generate text using Azure OpenAI GPT 4.1 mini.
        
        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0-2)
            
        Returns:
            Generated text response
        """
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.deployment_name,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content
        except Exception as e:
            LOGGER.error(f"Azure OpenAI LLM generation failed: {e}")
            raise
    
    def generate_clinical_response(
        self,
        patient_info: str,
        question: str,
        retrieved_docs: list[str],
        max_tokens: int = 2000,
    ) -> str:
        """Generate a clinical decision support response.

        Args:
            patient_info: Patient clinical information
            question: Clinical question
            retrieved_docs: All retrieved evidence (patient record facts, drug label
                facts, and/or guideline excerpts) -- the only source of fact available
            max_tokens: Maximum tokens in response

        Returns:
            Clinical decision support response
        """
        evidence_context = "\n".join(f"- {doc}" for doc in retrieved_docs) if retrieved_docs else "- No evidence was retrieved."

        prompt = f"""You are a clinical decision support AI assistant for cardiology.

PATIENT CONTEXT:
{patient_info}

CLINICAL QUESTION:
{question}

RETRIEVED EVIDENCE (patient record data, drug label data, and/or clinical guideline excerpts -- this is the ONLY source of fact available; nothing outside it may be treated as known):
{evidence_context}

INSTRUCTIONS:
1. State every value present in RETRIEVED EVIDENCE explicitly and verbatim (a drug name, dose, allergen, lab result, vital sign, condition, etc.). Never say a fact "is not available," "is not specified," or "is not included" if it appears above.
2. Do not substitute a list of hypothetical categories (e.g. "such as current smoker, former smoker, never smoker") for stating the actual retrieved value -- state the one that was actually retrieved.
3. If something was genuinely not retrieved, say so plainly and specifically by naming what's missing, rather than a generic disclaimer.
4. Cite specific guidelines and documents when applicable.
5. Do not provide direct clinical diagnosis or treatment without clear evidence.
6. Always recommend consultation with qualified healthcare professionals.

Please provide a concise, evidence-grounded clinical decision support response:"""

        return self.generate(prompt, max_tokens=max_tokens, temperature=0.5)
