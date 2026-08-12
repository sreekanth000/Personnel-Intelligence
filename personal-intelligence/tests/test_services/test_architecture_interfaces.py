"""Unit tests verifying the 7 separated architectural components and interfaces:

1. Connectors (GmailConnector interface)
2. Observation Ingestion (ObservationIngestionService)
3. Extraction (GPT41Extractor interface)
4. Evidence (EvidenceService)
5. World Model (WorldModelService)
6. Reconciliation (ReconciliationEngine)
7. Context (ContextEngine)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.connectors.gmail import GmailConnector
from app.domain import (
    Claim,
    ConfidenceScore,
    ContextRequest,
    EvidenceType,
    Observation,
    ObservationSource,
)
from app.services.context import ContextEngine
from app.services.evidence import EvidenceService
from app.services.extraction import ExtractionResult, GPT41Extractor
from app.services.ingestion import ObservationIngestionService
from app.services.reconciliation import ReconciliationEngine
from app.services.world_model import WorldModelService

if TYPE_CHECKING:
    from app.persistence.duckdb_store import DuckDBStore
    from app.persistence.kuzu_store import KuzuStore

# ---------------------------------------------------------------------------
# 1. Connectors (Gmail)
# ---------------------------------------------------------------------------


def test_gmail_connector_interface() -> None:
    """GmailConnector metadata and unauthenticated status."""
    connector = GmailConnector()
    assert connector.name == "gmail"
    assert isinstance(connector.is_authenticated(), bool)


@pytest.mark.asyncio
async def test_gmail_connector_unauthenticated_fetch_raises() -> None:
    """Unauthenticated fetch should raise RuntimeError if unauthenticated."""
    connector = GmailConnector()
    if not connector.is_authenticated():
        with pytest.raises(RuntimeError, match="Gmail authentication is required"):
            async for _ in connector.fetch_observations():
                pass


# ---------------------------------------------------------------------------
# 2. Observation Ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observation_ingestion_service(duckdb_store: DuckDBStore) -> None:
    """Ingestion service receives, validates, and accepts observations."""
    service = ObservationIngestionService(duckdb_store)
    obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_001",
        content="Subject: Project Kickoff\nBody: Starting tomorrow at 9am.",
    )
    obs_id = await service.ingest_observation(obs)
    assert obs_id == obs.id


# ---------------------------------------------------------------------------
# 3. Extraction (GPT-4.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gpt41_extractor_unconfigured_api_key_raises() -> None:
    """GPT41Extractor without API key raises RuntimeError on extraction."""
    extractor = GPT41Extractor(api_key="", azure_endpoint="")
    obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_002",
        content="Meeting with Bob on Friday.",
    )
    with pytest.raises(RuntimeError, match="LLM provider is not properly configured"):
        await extractor.extract_from_observation(obs)


@pytest.mark.asyncio
async def test_gpt41_extractor_interface_stub() -> None:
    """GPT41Extractor interface contract returns ExtractionResult when configured."""
    from unittest.mock import AsyncMock, MagicMock

    mock_llm_client = MagicMock()
    mock_llm_client.is_configured.return_value = True
    mock_llm_client.model = "gpt-4.1"
    mock_llm_client.provider = "azure"
    mock_choice = MagicMock()
    mock_choice.message.content = '{"source_observation_id": "obs_003", "entities": [], "relationships": [], "events": [], "claims": []}'
    mock_response = MagicMock(choices=[mock_choice])
    mock_llm_client.create_chat_completion = AsyncMock(return_value=mock_response)

    extractor = GPT41Extractor(llm_client=mock_llm_client)
    obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_003",
        content="Extracted event content.",
    )
    result = await extractor.extract_from_observation(obs)
    assert isinstance(result, ExtractionResult)
    assert result.source_observation_id == obs.id


# ---------------------------------------------------------------------------
# 4. Evidence Service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_service_recording() -> None:
    """EvidenceService records and retrieves evidence linking observations to claims."""
    service = EvidenceService()
    ev = await service.record_evidence(
        observation_id="obs_001",
        claim_id="claim_001",
        evidence_type=EvidenceType.SUPPORTS,
        content="Snippet supporting claim.",
        confidence=ConfidenceScore.from_score(0.88),
    )
    assert ev.observation_id == "obs_001"
    assert ev.claim_id == "claim_001"
    assert ev.evidence_type == EvidenceType.SUPPORTS


# ---------------------------------------------------------------------------
# 5. World Model Service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_world_model_service_interface(
    duckdb_store: DuckDBStore, kuzu_store: KuzuStore
) -> None:
    """WorldModelService provides unified operations for entities, relationships, claims, and state."""
    service = WorldModelService(duckdb_store, kuzu_store)
    state = await service.get_current_state()
    assert state is not None
    assert isinstance(state.active_entity_ids, list)


# ---------------------------------------------------------------------------
# 6. Reconciliation Engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_engine_interface(
    duckdb_store: DuckDBStore, kuzu_store: KuzuStore
) -> None:
    """ReconciliationEngine processes claims against world state and returns StateChange audit trail."""
    wm_service = WorldModelService(duckdb_store, kuzu_store)
    engine = ReconciliationEngine(wm_service)

    obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_005",
        content="Subject: Office Location\nBody: Moved to London.",
    )
    claim = Claim(
        subject="company",
        predicate="located_in",
        value="London",
        confidence=ConfidenceScore.from_score(0.9),
    )

    change = await engine.reconcile_claim(claim, obs)
    assert change.observation_id == obs.id
    assert change.claim_id == claim.id
    assert change.outcome.value in ("novel", "created")


# ---------------------------------------------------------------------------
# 7. Context Engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_engine_interface(duckdb_store: DuckDBStore, kuzu_store: KuzuStore) -> None:
    """ContextEngine receives ContextRequest and produces task-specific ContextPackage."""
    wm_service = WorldModelService(duckdb_store, kuzu_store)
    engine = ContextEngine(wm_service)

    request = ContextRequest(
        task_intent="draft_reply",
        query="Office location history",
        max_items=10,
    )
    package = await engine.assemble_context(request)
    assert package.request_id == request.id
    assert package.purpose == "general"
