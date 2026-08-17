from __future__ import annotations

from cardiologist_agent.config.settings import Settings
from cardiologist_agent.repositories.policy import PolicyRetriever, RetrievalResult


class OpenSearchPolicyRetriever(PolicyRetriever):
    """Configuration-driven adapter — requires ENABLE_OPENSEARCH and provisioned cluster."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not settings.opensearch_endpoint:
            raise ValueError("OPENSEARCH_ENDPOINT is required when OpenSearch retriever is enabled")

    async def retrieve(self, query: str, top_k: int = 5) -> RetrievalResult:
        raise NotImplementedError(
            "OpenSearch Serverless adapter is defined but not provisioned in local build."
        )
