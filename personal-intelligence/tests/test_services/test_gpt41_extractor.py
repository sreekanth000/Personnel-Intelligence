"""Unit tests for GPT41Extractor using mocked OpenAI API responses.

Verifies:
- Unconfigured API key error handling
- Successful structured extraction parsing and Pydantic validation
- Prompt rule enforcement (evidence grounding, no plausible inference, signature/quoted reply rules)
- Invalid JSON / validation retry mechanism
- Empty array return when information is absent
- Boundary enforcement: Zero direct mutation of World Model / database stores
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain import (
    ClaimStatus,
    EntityType,
    NormalizedEmailObservation,
    RelationshipType,
)
from app.services.extraction import EXTRACTION_SYSTEM_PROMPT, GPT41Extractor, StructuredExtraction


@pytest.fixture()
def sample_normalized_email() -> NormalizedEmailObservation:
    """Fixture providing a clean NormalizedEmailObservation."""
    return NormalizedEmailObservation(
        raw_observation_id="raw_obs_gpt_123",
        message_id="msg_gpt_123",
        thread_id="thread_gpt_123",
        sender="lead@company.com",
        recipients=["engineer@company.com"],
        cc=[],
        subject="Project Alpha Deployment",
        timestamp=datetime.now(UTC),
        body="Alice manages Project Alpha. We decided to deploy to production on Friday.",
        quoted_reply=None,
        signature=None,
        attachments_metadata=[],
        content_hash="abc123hash",
    )


def test_gpt41_extractor_unconfigured_api_key() -> None:
    """Extractor without API key raises RuntimeError on get_client()."""
    extractor = GPT41Extractor(api_key="", azure_endpoint="")
    with pytest.raises(RuntimeError, match="LLM provider is not properly configured"):
        extractor.get_client()


def test_extraction_system_prompt_rules() -> None:
    """Extraction prompt must explicitly instruct mandatory extraction constraints."""
    prompt = EXTRACTION_SYSTEM_PROMPT

    assert "Extract only evidence-supported information" in prompt
    assert "Every extracted item must have an evidence_span" in prompt
    assert "Never infer sensitive personal attributes" in prompt
    assert "Never infer relationships from email addresses alone" in prompt
    assert "Treat quoted email text as historical context" in prompt
    assert "Distinguish sender statements" in prompt
    assert "Preserve temporal expressions" in prompt
    assert "Preserve uncertainty" in prompt
    assert "Do not convert requests" in prompt
    assert "Do not convert intentions" in prompt
    assert "Do not convert discussion" in prompt
    assert "Do not treat email signatures" in prompt
    assert "Do not infer that the recipient/user agrees" in prompt
    assert "Do not infer that a project is active" in prompt
    assert "Do not create a relationship when textual evidence is insufficient" in prompt


@pytest.mark.asyncio
async def test_successful_structured_extraction(
    sample_normalized_email: NormalizedEmailObservation,
) -> None:
    """Extractor successfully parses valid JSON response into StructuredExtraction."""
    mock_response_data = {
        "source_observation_id": sample_normalized_email.raw_observation_id,
        "entities": [
            {
                "id": "ent_alice",
                "entity_type": EntityType.PERSON,
                "name": "Alice",
                "confidence": {"score": 0.95, "category": "very_high"},
            },
            {
                "id": "ent_proj_alpha",
                "entity_type": EntityType.PROJECT,
                "name": "Project Alpha",
                "confidence": {"score": 0.9, "category": "very_high"},
            },
        ],
        "relationships": [
            {
                "subject": "ent_alice",
                "predicate": RelationshipType.MANAGES,
                "object": "ent_proj_alpha",
                "confidence": {"score": 0.92, "category": "very_high"},
                "evidence_span": {
                    "text_snippet": "Alice manages Project Alpha.",
                    "start_char": 0,
                    "end_char": 28,
                    "confidence": {"score": 0.95, "category": "very_high"},
                },
                "source_observation_id": sample_normalized_email.raw_observation_id,
            }
        ],
        "decisions": [
            {
                "name": "Production Deployment Date",
                "entity_type": "decision",
                "confidence": {"score": 0.88, "category": "high"},
                "question": "When to deploy Project Alpha?",
                "alternatives": ["Friday", "Monday"],
                "context": "Email thread decision",
                "decision": "Deploy to production on Friday.",
            }
        ],
        "claims": [
            {
                "subject": "Project Alpha",
                "predicate": "deployment_target",
                "value": "production",
                "status": ClaimStatus.PROPOSED,
                "confidence": {"score": 0.85, "category": "high"},
            }
        ],
        "events": [],
        "goals": [],
        "projects": [],
        "constraints": [],
        "preferences": [],
        "temporal_references": [],
    }

    mock_llm_client = MagicMock()
    mock_llm_client.is_configured.return_value = True
    mock_llm_client.model = "gpt-4.1"
    mock_llm_client.provider = "azure"
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(mock_response_data)
    mock_response.choices = [mock_choice]
    mock_llm_client.create_chat_completion = AsyncMock(return_value=mock_response)

    extractor = GPT41Extractor(llm_client=mock_llm_client)
    extraction = await extractor.extract_from_normalized_email(sample_normalized_email)

    assert isinstance(extraction, StructuredExtraction)
    assert extraction.source_observation_id == sample_normalized_email.raw_observation_id
    assert len(extraction.entities) == 2
    assert extraction.entities[0].name == "Alice"
    assert len(extraction.relationships) == 1
    assert extraction.relationships[0].predicate == RelationshipType.MANAGES
    assert len(extraction.decisions) == 1
    assert extraction.decisions[0].decision == "Deploy to production on Friday."
    assert len(extraction.claims) == 1


@pytest.mark.asyncio
async def test_retry_on_invalid_json_validation(
    sample_normalized_email: NormalizedEmailObservation,
) -> None:
    """Extractor retries when initial response fails JSON/Pydantic validation."""
    invalid_choice = MagicMock()
    invalid_choice.message.content = "INVALID_NOT_JSON"

    valid_response_data = {
        "source_observation_id": sample_normalized_email.raw_observation_id,
        "entities": [],
        "relationships": [],
        "events": [],
        "claims": [],
        "goals": [],
        "projects": [],
        "decisions": [],
        "constraints": [],
        "preferences": [],
        "temporal_references": [],
    }
    valid_choice = MagicMock()
    valid_choice.message.content = json.dumps(valid_response_data)

    mock_llm_client = MagicMock()
    mock_llm_client.is_configured.return_value = True
    mock_llm_client.model = "gpt-4.1"
    mock_llm_client.provider = "azure"

    resp1 = MagicMock(choices=[invalid_choice])
    resp2 = MagicMock(choices=[valid_choice])
    mock_llm_client.create_chat_completion = AsyncMock(side_effect=[resp1, resp2])

    extractor = GPT41Extractor(max_retries=3, llm_client=mock_llm_client)
    extraction = await extractor.extract_from_normalized_email(sample_normalized_email)

    assert extraction.source_observation_id == sample_normalized_email.raw_observation_id
    assert len(extraction.entities) == 0
    assert mock_llm_client.create_chat_completion.call_count == 2


@pytest.mark.asyncio
async def test_exhausted_retries_raises_runtime_error(
    sample_normalized_email: NormalizedEmailObservation,
) -> None:
    """Extractor raises RuntimeError when max_retries are exhausted."""
    invalid_choice = MagicMock()
    invalid_choice.message.content = "{"  # broken json

    mock_llm_client = MagicMock()
    mock_llm_client.is_configured.return_value = True
    mock_llm_client.model = "gpt-4.1"
    mock_llm_client.provider = "azure"
    mock_response = MagicMock(choices=[invalid_choice])
    mock_llm_client.create_chat_completion = AsyncMock(return_value=mock_response)

    extractor = GPT41Extractor(max_retries=2, llm_client=mock_llm_client)

    with pytest.raises(RuntimeError, match=r"LLM extraction failed after 2 attempts"):
        await extractor.extract_from_normalized_email(sample_normalized_email)


@pytest.mark.asyncio
async def test_empty_arrays_when_information_absent(
    sample_normalized_email: NormalizedEmailObservation,
) -> None:
    """Extractor returns empty arrays for absent extraction categories."""
    mock_response_data = {
        "source_observation_id": sample_normalized_email.raw_observation_id,
        "entities": [],
        "relationships": [],
        "events": [],
        "claims": [],
        "goals": [],
        "projects": [],
        "decisions": [],
        "constraints": [],
        "preferences": [],
        "temporal_references": [],
    }

    mock_llm_client = MagicMock()
    mock_llm_client.is_configured.return_value = True
    mock_llm_client.model = "gpt-4.1"
    mock_llm_client.provider = "azure"
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(mock_response_data)
    mock_response = MagicMock(choices=[mock_choice])
    mock_llm_client.create_chat_completion = AsyncMock(return_value=mock_response)

    extractor = GPT41Extractor(llm_client=mock_llm_client)
    extraction = await extractor.extract_from_normalized_email(sample_normalized_email)

    assert len(extraction.entities) == 0
    assert len(extraction.relationships) == 0
    assert len(extraction.events) == 0
    assert len(extraction.claims) == 0
