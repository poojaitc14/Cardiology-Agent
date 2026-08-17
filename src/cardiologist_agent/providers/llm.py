from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from cardiologist_agent.config.settings import Settings, get_settings


class LLMProvider(ABC):
    @abstractmethod
    async def synthesize(self, system_prompt: str, user_prompt: str) -> str: ...

    @property
    @abstractmethod
    def available(self) -> bool: ...


class FakeLLMProvider(LLMProvider):
    @property
    def available(self) -> bool:
        return True

    async def synthesize(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(
            {
                "clinical_rationale": (
                    "Deterministic draft based on verified patient facts and retrieved policy excerpts. "
                    "No signed medication order is available."
                ),
                "attention_items": ["Review active medications and monitoring data."],
                "future_course_of_action": ["Complete clinician review of draft recommendation."],
            }
        )


class OpenAILLMProvider(LLMProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: Any = None
        provider = self.settings.effective_llm_provider()
        if provider == "openai":
            self._client = ChatOpenAI(
                model=self.settings.openai_model,
                api_key=self.settings.openai_api_key,
                temperature=0,
            )
        elif provider == "azure":
            self._client = AzureChatOpenAI(
                azure_endpoint=self.settings.azure_openai_endpoint,
                api_key=self.settings.azure_openai_api_key,
                azure_deployment=self.settings.azure_openai_deployment,
                temperature=0,
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    async def synthesize(self, system_prompt: str, user_prompt: str) -> str:
        if not self._client:
            raise RuntimeError("OpenAI provider not configured")
        response = await self._client.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        return str(response.content)


def build_llm_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    if settings.effective_llm_provider() == "fake":
        return FakeLLMProvider()
    return OpenAILLMProvider(settings)
