"""Universal LLM Provider Client.

Supports any LLM provider and model through a unified OpenAI-compatible interface:
- Azure OpenAI (azure)
- OpenAI (openai)
- Ollama / Local Open-Source Models (ollama)
- DeepSeek (deepseek)
- Groq (groq)
- OpenRouter (openrouter)
- Custom OpenAI-Compatible Endpoints / vLLM / LM Studio (custom)
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.config.logging import get_logger
from app.config.settings import get_settings

logger = get_logger(__name__)

# Default base URLs for popular providers
PROVIDER_BASE_URLS: dict[str, str] = {
    "ollama": "http://localhost:11434/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class LLMProviderClient:
    """Configurable client capable of invoking any LLM provider."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
        azure_endpoint: str | None = None,
    ) -> None:
        settings = get_settings()

        self.provider = (provider or settings.llm_provider).lower()
        self.model = model or settings.llm_model or settings.azure_openai_deployment
        self.api_key = (settings.llm_api_key or settings.azure_ai_api_key) if api_key is None else api_key
        self.api_base = settings.llm_api_base if api_base is None else api_base
        self.api_version = (settings.llm_api_version or settings.azure_ai_api_version) if api_version is None else api_version
        self.azure_endpoint = settings.azure_ai_endpoint if azure_endpoint is None else azure_endpoint

        self._client: AsyncOpenAI | AsyncAzureOpenAI | None = None

    def is_configured(self) -> bool:
        """Return True if required credentials/endpoints are set for the provider."""
        if self.provider == "azure":
            return bool(self.api_key and self.azure_endpoint)
        if self.provider in ("ollama", "custom"):
            return True  # Local models often run without API keys
        return bool(self.api_key)

    def get_client(self) -> AsyncOpenAI | AsyncAzureOpenAI:
        """Initialize and return the appropriate OpenAI or Azure client."""
        if self._client is not None:
            return self._client

        if self.provider == "azure":
            if not self.api_key or not self.azure_endpoint:
                raise RuntimeError(
                    "Azure OpenAI not configured. Set PI_AZURE_AI_API_KEY and PI_AZURE_AI_ENDPOINT in .env file."
                )
            self._client = AsyncAzureOpenAI(
                azure_endpoint=self.azure_endpoint,
                api_key=self.api_key,
                api_version=self.api_version,
            )
            return self._client

        # Build standard OpenAI client for openai, ollama, deepseek, groq, openrouter, or custom
        base_url = self.api_base or PROVIDER_BASE_URLS.get(self.provider)
        key = self.api_key or ("ollama" if self.provider == "ollama" else "custom")

        kwargs: dict[str, Any] = {"api_key": key}
        if base_url:
            kwargs["base_url"] = base_url

        logger.info(
            "llm_provider.initialized_client",
            provider=self.provider,
            model=self.model,
            base_url=base_url or "default_openai",
        )
        self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def create_chat_completion(
        self,
        messages: list[dict[str, str]],
        response_format: type[Any] | dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> Any:
        """Execute a chat completion request against the configured provider."""
        client = self.get_client()

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        if response_format is not None:
            if hasattr(client, "beta") and hasattr(client.beta, "chat") and hasattr(client.beta.chat, "completions") and not isinstance(response_format, dict):
                try:
                    return await client.beta.chat.completions.parse(
                        model=self.model,
                        messages=messages,
                        temperature=temperature,
                        response_format=response_format,
                    )
                except Exception as err:
                    logger.warning("llm_provider.parse_failed_falling_back_to_json_object", error=str(err))

            try:
                kwargs["response_format"] = {"type": "json_object"}
                return await client.chat.completions.create(**kwargs)
            except Exception as err2:
                logger.warning("llm_provider.json_object_failed_falling_back_to_standard", error=str(err2))
                kwargs.pop("response_format", None)

        return await client.chat.completions.create(**kwargs)
