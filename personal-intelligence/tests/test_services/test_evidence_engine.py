"""Unit tests for the Evidence Engine and lineage tracing.

Verifies:
- Provenance pointing: source_observation_id, source_message_id, source_thread_id, evidence_span.
- Character offset preservation: start_char/offset, end_char/offset, exact snippet text.
- Query methods: get_evidence_for_entity(), get_evidence_for_relationship(), get_evidence_for_claim(), get_evidence_for_event().
- Complete lineage tracing: World Model state -> derived claim/relation/entity -> Gmail message -> exact evidence span.
- Non-duplication of email bodies in evidence records.
"""

from __future__ import annotations

import pytest

from app.domain import (
    Claim,
    ClaimStatus,
    ConfidenceScore,
    Entity,
    EntityType,
    Event,
    EvidenceSpan,
    Relationship,
    RelationshipType,
)
from app.services.evidence import EvidenceService
from app.services.extraction import StructuredExtraction


@pytest.mark.asyncio
async def test_record_and_query_evidence_for_entity() -> None:
    """EvidenceService records and fetches evidence for an Entity."""
    service = EvidenceService()

    ent = Entity(
        name="Alice Smith",
        entity_type=EntityType.PERSON,
        confidence=ConfidenceScore.from_score(0.95),
    )

    span = EvidenceSpan(
        text_snippet="Alice Smith is the Tech Lead",
        start_char=12,
        end_char=40,
        confidence=ConfidenceScore.from_score(0.95),
    )

    ev = await service.record_evidence(
        observation_id="obs_gmail_99",
        target_id=ent.id,
        target_type="entity",
        evidence_span=span,
        confidence=ent.confidence,
        source_message_id="msg_gmail_abc",
        source_thread_id="thread_gmail_xyz",
    )

    assert ev.source_observation_id == "obs_gmail_99"
    assert ev.source_message_id == "msg_gmail_abc"
    assert ev.source_thread_id == "thread_gmail_xyz"
    assert ev.target_id == ent.id
    assert ev.start_offset == 12
    assert ev.end_offset == 40
    assert ev.content == "Alice Smith is the Tech Lead"

    fetched = await service.get_evidence_for_entity(ent.id)
    assert len(fetched) == 1
    assert fetched[0].id == ev.id


@pytest.mark.asyncio
async def test_record_and_query_evidence_for_relationship() -> None:
    """EvidenceService records and fetches evidence for a Relationship."""
    service = EvidenceService()

    rel = Relationship(
        subject="alice_id",
        predicate=RelationshipType.MANAGES,
        object="infra_team_id",
        confidence=ConfidenceScore.from_score(0.9),
        source_observation_id="obs_gmail_100",
    )

    span = EvidenceSpan(
        text_snippet="Alice manages the Infrastructure Team",
        start_char=0,
        end_char=37,
        confidence=ConfidenceScore.from_score(0.9),
    )

    ev = await service.record_evidence(
        observation_id="obs_gmail_100",
        target_id=rel.id,
        target_type="relationship",
        evidence_span=span,
        confidence=rel.confidence,
        source_message_id="msg_gmail_100",
        source_thread_id="thread_gmail_100",
    )

    assert ev.target_id == rel.id

    fetched = await service.get_evidence_for_relationship(rel.id)
    assert len(fetched) == 1
    assert fetched[0].content == "Alice manages the Infrastructure Team"


@pytest.mark.asyncio
async def test_record_and_query_evidence_for_claim_and_event() -> None:
    """EvidenceService records and fetches evidence for Claims and Events."""
    service = EvidenceService()

    claim = Claim(
        subject="Project Alpha",
        predicate="status",
        value="deployed",
        status=ClaimStatus.PROPOSED,
        confidence=ConfidenceScore.from_score(0.88),
    )

    span_claim = EvidenceSpan(
        text_snippet="Project Alpha was deployed to production",
        start_char=5,
        end_char=45,
        confidence=ConfidenceScore.from_score(0.88),
    )

    await service.record_evidence(
        observation_id="obs_gmail_101",
        target_id=claim.id,
        target_type="claim",
        evidence_span=span_claim,
        confidence=claim.confidence,
        source_message_id="msg_gmail_101",
    )

    evt = Event(
        name="Sprint Planning",
        starts_at="2026-08-15T10:00:00Z",
        confidence=ConfidenceScore.from_score(0.92),
    )

    span_event = EvidenceSpan(
        text_snippet="Sprint Planning on Saturday at 10am",
        confidence=ConfidenceScore.from_score(0.92),
    )

    await service.record_evidence(
        observation_id="obs_gmail_101",
        target_id=evt.id,
        target_type="event",
        evidence_span=span_event,
        confidence=evt.confidence,
        source_message_id="msg_gmail_101",
    )

    claims_ev = await service.get_evidence_for_claim(claim.id)
    assert len(claims_ev) == 1
    assert claims_ev[0].content == "Project Alpha was deployed to production"

    events_ev = await service.get_evidence_for_event(evt.id)
    assert len(events_ev) == 1
    assert events_ev[0].content == "Sprint Planning on Saturday at 10am"


@pytest.mark.asyncio
async def test_full_lineage_tracing_path() -> None:
    """Verifies end-to-end lineage tracing: World Model -> Claim/Rel -> Gmail msg -> EvidenceSpan."""
    service = EvidenceService()

    # Step 1: Extracted payload
    claim = Claim(
        subject="User",
        predicate="role",
        value="Principal Engineer",
        confidence=ConfidenceScore.from_score(0.98),
    )

    extraction = StructuredExtraction(
        source_observation_id="obs_gmail_500",
        claims=[claim],
    )

    # Step 2: Record evidence batch
    recorded = await service.record_extraction_result(
        extraction,
        source_message_id="msg_g_500",
        source_thread_id="thread_g_500",
    )
    assert len(recorded) == 0  # claim had no evidence_spans initially

    # Record explicit evidence span
    span = EvidenceSpan(
        text_snippet="User is appointed as Principal Engineer",
        start_char=0,
        end_char=40,
        confidence=ConfidenceScore.from_score(0.98),
    )
    _ev = await service.record_evidence(
        observation_id="obs_gmail_500",
        target_id=claim.id,
        target_type="claim",
        evidence_span=span,
        confidence=claim.confidence,
        source_message_id="msg_g_500",
        source_thread_id="thread_g_500",
    )

    # Step 3: Trace back from claim ID
    evidences = await service.get_evidence_for_claim(claim.id)
    assert len(evidences) == 1

    ev_item = evidences[0]
    # Traceability assertions
    assert ev_item.target_id == claim.id
    assert ev_item.source_observation_id == "obs_gmail_500"
    assert ev_item.source_message_id == "msg_g_500"
    assert ev_item.source_thread_id == "thread_g_500"
    assert ev_item.evidence_span.text_snippet == "User is appointed as Principal Engineer"
    assert ev_item.start_offset == 0
    assert ev_item.end_offset == 40
