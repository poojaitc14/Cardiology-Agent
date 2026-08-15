"""Unit tests for Azure OpenAI integration."""
import os
import pytest
from unittest.mock import MagicMock, patch, Mock

from backend.services.azure_openai import (
    AzureOpenAIConfig,
    AzureOpenAIEmbedding,
    AzureOpenAILLM,
)


class TestAzureOpenAIConfig:
    """Test Azure OpenAI configuration."""

    def test_config_loads_from_environment(self, monkeypatch):
        """Test configuration loads from environment variables."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-123")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
        monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini")
        
        config = AzureOpenAIConfig()
        
        assert config.api_key == "test-key-123"
        assert config.endpoint == "https://test.openai.azure.com/"
        assert config.deployment_name == "gpt-4o-mini"

    def test_config_defaults(self, monkeypatch):
        """Test configuration defaults."""
        # Clear environment variables
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_NAME", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_EMBEDDING_MODEL", raising=False)

        config = AzureOpenAIConfig()
        
        assert config.api_key == ""
        assert config.endpoint == ""
        assert config.api_version == "2024-08-01-preview"
        assert config.embedding_model == "text-embedding-3-small"

    def test_is_configured_true(self, monkeypatch):
        """Test is_configured returns True when properly configured."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
        
        config = AzureOpenAIConfig()
        
        assert config.is_configured() is True

    def test_is_configured_false_missing_key(self, monkeypatch):
        """Test is_configured returns False when API key is missing."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
        
        config = AzureOpenAIConfig()
        
        assert config.is_configured() is False

    def test_is_configured_false_missing_endpoint(self, monkeypatch):
        """Test is_configured returns False when endpoint is missing."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
        
        config = AzureOpenAIConfig()
        
        assert config.is_configured() is False


class TestAzureOpenAIEmbedding:
    """Test Azure OpenAI embedding provider."""

    @patch("backend.services.azure_openai.AzureOpenAI")
    def test_embed_single_text(self, mock_azure_openai):
        """Test embedding a single text."""
        # Setup mock
        mock_client = MagicMock()
        mock_azure_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3, 0.4])]
        mock_client.embeddings.create.return_value = mock_response
        
        config = AzureOpenAIConfig()
        config.api_key = "test-key"
        config.endpoint = "https://test.openai.azure.com/"
        
        embedder = AzureOpenAIEmbedding(config)
        result = embedder.embed("test text")
        
        assert result == [0.1, 0.2, 0.3, 0.4]
        mock_client.embeddings.create.assert_called_once()

    @patch("backend.services.azure_openai.AzureOpenAI")
    def test_embed_batch(self, mock_azure_openai):
        """Test batch embedding."""
        # Setup mock
        mock_client = MagicMock()
        mock_azure_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(index=0, embedding=[0.1, 0.2]),
            MagicMock(index=1, embedding=[0.3, 0.4]),
            MagicMock(index=2, embedding=[0.5, 0.6]),
        ]
        mock_client.embeddings.create.return_value = mock_response
        
        config = AzureOpenAIConfig()
        config.api_key = "test-key"
        config.endpoint = "https://test.openai.azure.com/"
        
        embedder = AzureOpenAIEmbedding(config)
        results = embedder.embed_batch(["text1", "text2", "text3"])
        
        assert len(results) == 3
        assert results[0] == [0.1, 0.2]
        assert results[1] == [0.3, 0.4]
        assert results[2] == [0.5, 0.6]

    def test_embed_not_configured(self):
        """Test embedding fails when not configured."""
        config = AzureOpenAIConfig()
        config.api_key = ""
        config.endpoint = ""
        
        with pytest.raises(ValueError, match="Azure OpenAI is not configured"):
            AzureOpenAIEmbedding(config)

    @patch("backend.services.azure_openai.AzureOpenAI")
    def test_embed_error_handling(self, mock_azure_openai):
        """Test error handling during embedding."""
        mock_client = MagicMock()
        mock_azure_openai.return_value = mock_client
        mock_client.embeddings.create.side_effect = Exception("API error")
        
        config = AzureOpenAIConfig()
        config.api_key = "test-key"
        config.endpoint = "https://test.openai.azure.com/"
        
        embedder = AzureOpenAIEmbedding(config)
        
        with pytest.raises(Exception, match="API error"):
            embedder.embed("test text")


class TestAzureOpenAILLM:
    """Test Azure OpenAI LLM provider."""

    @patch("backend.services.azure_openai.AzureOpenAI")
    def test_generate_text(self, mock_azure_openai):
        """Test generating text."""
        # Setup mock
        mock_client = MagicMock()
        mock_azure_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Generated response"))]
        mock_client.chat.completions.create.return_value = mock_response
        
        config = AzureOpenAIConfig()
        config.api_key = "test-key"
        config.endpoint = "https://test.openai.azure.com/"
        
        llm = AzureOpenAILLM(config)
        result = llm.generate("Test prompt")
        
        assert result == "Generated response"
        mock_client.chat.completions.create.assert_called_once()

    @patch("backend.services.azure_openai.AzureOpenAI")
    def test_generate_clinical_response(self, mock_azure_openai):
        """Test generating clinical response."""
        # Setup mock
        mock_client = MagicMock()
        mock_azure_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Clinical recommendations..."))]
        mock_client.chat.completions.create.return_value = mock_response
        
        config = AzureOpenAIConfig()
        config.api_key = "test-key"
        config.endpoint = "https://test.openai.azure.com/"
        
        llm = AzureOpenAILLM(config)
        result = llm.generate_clinical_response(
            patient_info="Patient: 65-year-old",
            question="What medications?",
            retrieved_docs=["Guideline 1", "Guideline 2"],
        )
        
        assert result == "Clinical recommendations..."
        mock_client.chat.completions.create.assert_called_once()

    def test_llm_not_configured(self):
        """Test LLM fails when not configured."""
        config = AzureOpenAIConfig()
        config.api_key = ""
        config.endpoint = ""
        
        with pytest.raises(ValueError, match="Azure OpenAI is not configured"):
            AzureOpenAILLM(config)

    @patch("backend.services.azure_openai.AzureOpenAI")
    def test_generate_with_parameters(self, mock_azure_openai):
        """Test generating text with custom parameters."""
        # Setup mock
        mock_client = MagicMock()
        mock_azure_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Response"))]
        mock_client.chat.completions.create.return_value = mock_response
        
        config = AzureOpenAIConfig()
        config.api_key = "test-key"
        config.endpoint = "https://test.openai.azure.com/"
        
        llm = AzureOpenAILLM(config)
        result = llm.generate(
            prompt="Test",
            max_tokens=500,
            temperature=0.3,
        )
        
        # Verify parameters were passed
        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["max_tokens"] == 500
        assert call_args.kwargs["temperature"] == 0.3
