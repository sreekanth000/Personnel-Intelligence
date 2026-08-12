"""Unit tests for universal LLMProviderClient."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.llm_provider import LLMProviderClient, PROVIDER_BASE_URLS


def test_llm_provider_configuration_check() -> None:
    """Test configuration status for various providers."""
    # Azure OpenAI
    azure_configured = LLMProviderClient(provider="azure", api_key="key", azure_endpoint="https://test.openai.azure.com")
    assert azure_configured.is_configured()

    azure_unconfigured = LLMProviderClient(provider="azure", api_key="", azure_endpoint="")
    assert not azure_unconfigured.is_configured()

    # Ollama (Local open source model)
    ollama_client = LLMProviderClient(provider="ollama", model="llama3.3")
    assert ollama_client.is_configured()

    # Custom OpenAI compatible endpoint
    custom_client = LLMProviderClient(provider="custom", api_base="http://localhost:8000/v1")
    assert custom_client.is_configured()

    # OpenAI / DeepSeek / Groq
    openai_client = LLMProviderClient(provider="openai", api_key="sk-test")
    assert openai_client.is_configured()


def test_llm_provider_base_urls() -> None:
    """Default base URLs mapping verification."""
    assert PROVIDER_BASE_URLS["ollama"] == "http://localhost:11434/v1"
    assert PROVIDER_BASE_URLS["deepseek"] == "https://api.deepseek.com/v1"
    assert PROVIDER_BASE_URLS["groq"] == "https://api.groq.com/openai/v1"
    assert PROVIDER_BASE_URLS["openrouter"] == "https://openrouter.ai/api/v1"


@pytest.mark.asyncio
async def test_llm_provider_completion_call() -> None:
    """Verifies completion execution with mocked AsyncOpenAI client."""
    client = LLMProviderClient(provider="openai", model="gpt-4o", api_key="sk-test")

    mock_openai_client = AsyncMock()
    mock_choice = MagicMock()
    mock_choice.message.content = '{"status": "ok"}'
    mock_response = MagicMock(choices=[mock_choice])
    mock_openai_client.chat.completions.create.return_value = mock_response

    client._client = mock_openai_client

    res = await client.create_chat_completion(
        messages=[{"role": "user", "content": "Hello"}],
        temperature=0.0,
    )

    assert res.choices[0].message.content == '{"status": "ok"}'
    mock_openai_client.chat.completions.create.assert_called_once()
