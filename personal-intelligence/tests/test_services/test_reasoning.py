"""Unit tests for GPT41ReasoningService using mocked OpenAI responses.

Verifies:
- Prompt rules compliance ("representation of personal state", "Do not assume information not present", etc.)
- Architectural isolation: GPT-4.1 receives ONLY filtered ContextPackage
- Answer synthesis and uncertainties extraction
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config.settings import Settings
from app.domain import ConfidenceScore, Entity, EntityType, Provenance
from app.domain.context import ContextPackage
from app.services.context import ContextEngine
from app.services.privacy_filter import PrivacyFilter
from app.services.reasoning import (
    REASONING_SYSTEM_PROMPT,
    GPT41ReasoningService,
    StructuredReasoningOutput,
)


def test_reasoning_system_prompt_rules() -> None:
    """Verifies all mandatory rules are present in the system reasoning prompt."""
    assert "supplied context is a representation of personal state" in REASONING_SYSTEM_PROMPT
    assert "Do not assume information not present in the context" in REASONING_SYSTEM_PROMPT
    assert (
        "Distinguish facts, user-confirmed state, inferred state and uncertainty"
        in REASONING_SYSTEM_PROMPT
    )
    assert "Do not fabricate missing details" in REASONING_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_gpt41_reasoning_isolated_context_pipeline() -> None:
    """Verifies end-to-end reasoning pipeline with mocked LLMProviderClient."""
    mock_context_engine = AsyncMock(spec=ContextEngine)
    mock_privacy_filter = MagicMock(spec=PrivacyFilter)

    dummy_entity = Entity(
        id="prj_alpha",
        entity_type=EntityType.PROJECT,
        name="Project Alpha",
        provenance=Provenance(source_observation_id="obs_999"),
        confidence=ConfidenceScore.from_score(0.95),
    )

    raw_package = ContextPackage(
        request_id="req_123",
        purpose="user_query",
        entities=[dummy_entity],
        summary="Context for Project Alpha.",
    )
    mock_context_engine.assemble_context.return_value = raw_package
    mock_privacy_filter.filter_package.return_value = raw_package

    parsed_output = StructuredReasoningOutput(
        answer="Project Alpha is an active local project led by Alice.",
        uncertainties=["Target completion date is not specified in context."],
    )
    mock_choice = MagicMock()
    mock_choice.message.parsed = parsed_output
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_llm_client = MagicMock()
    mock_llm_client.is_configured.return_value = True
    mock_llm_client.model = "gpt-4.1"
    mock_llm_client.provider = "azure"
    mock_llm_client.create_chat_completion = AsyncMock(return_value=mock_response)

    settings = Settings()
    reasoning_service = GPT41ReasoningService(
        settings=settings,
        context_engine=mock_context_engine,
        privacy_filter=mock_privacy_filter,
        llm_client=mock_llm_client,
    )

    res = await reasoning_service.answer_question(
        question="What is the status of Project Alpha?",
        purpose="user_query",
    )

    assert res.answer == "Project Alpha is an active local project led by Alice."
    assert len(res.uncertainties) == 1
    assert "completion date" in res.uncertainties[0]
    assert res.supporting_context.id == raw_package.id

    mock_llm_client.create_chat_completion.assert_called_once()
    call_kwargs = mock_llm_client.create_chat_completion.call_args.kwargs
    messages = call_kwargs["messages"]

    assert messages[0]["role"] == "system"
    assert "representation of personal state" in messages[0]["content"]

    assert messages[1]["role"] == "user"
    assert "User Question: What is the status of Project Alpha?" in messages[1]["content"]
    assert "Filtered ContextPackage:" in messages[1]["content"]
    assert "Project Alpha" in messages[1]["content"]
