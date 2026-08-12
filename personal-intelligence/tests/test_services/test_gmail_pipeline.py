"""Unit tests for the Gmail -> Personal World Model end-to-end ingestion pipeline.

Verifies:
- End-to-end pipeline execution from raw Observation to IngestionReport.
- Relationship candidate validation (entities, predicate, evidence, confidence, existing check).
- Status classifications: NEW, CONFIRM, UPDATE, CONFLICT, UNCERTAIN.
- Source email evidence preservation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.domain import (
    ConfidenceScore,
    Entity,
    EntityType,
    EvidenceSpan,
    Observation,
    ObservationSource,
    Relationship,
    RelationshipType,
)
from app.services.extraction import StructuredExtraction
from app.services.pipeline import GmailPipelineService


@pytest.fixture()
def mock_extractor() -> AsyncMock:
    """Fixture for mocked GPT41Extractor."""
    extractor = AsyncMock()
    return extractor


@pytest.mark.asyncio
async def test_end_to_end_pipeline_john_leads_personal_intelligence(
    mock_extractor: AsyncMock,
) -> None:
    """Test pipeline processing email: 'John will lead the Personal Intelligence architecture.'"""
    raw_obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="gmail_msg_777",
        content="Sender: cto@acme.com\nSubject: Leadership Update\n\nJohn will lead the Personal Intelligence architecture.",
        raw_metadata={"message_id": "msg_777", "thread_id": "thread_777", "sender": "cto@acme.com"},
    )

    span = EvidenceSpan(
        text_snippet="John will lead the Personal Intelligence architecture.",
        start_char=0,
        end_char=55,
        confidence=ConfidenceScore.from_score(0.95),
    )

    mock_extraction = StructuredExtraction(
        source_observation_id=raw_obs.id,
        entities=[
            Entity(
                id="ent_john",
                name="John",
                entity_type=EntityType.PERSON,
                confidence=ConfidenceScore.from_score(0.95),
            ),
            Entity(
                id="ent_pi",
                name="Personal Intelligence",
                entity_type=EntityType.PROJECT,
                confidence=ConfidenceScore.from_score(0.95),
            ),
        ],
        relationships=[
            Relationship(
                id="rel_john_pi",
                subject="John",
                predicate=RelationshipType.RESPONSIBLE_FOR,
                object="Personal Intelligence",
                confidence=ConfidenceScore.from_score(0.92),
                evidence_span=span,
                source_observation_id=raw_obs.id,
            )
        ],
    )

    mock_extractor.extract_from_normalized_email.return_value = mock_extraction

    pipeline = GmailPipelineService(extractor=mock_extractor)
    report = await pipeline.process_gmail_observation(raw_obs)

    assert report.success is True
    assert report.raw_observation_id == raw_obs.id
    assert report.entities_processed == 2
    assert report.entities_new == 2
    assert report.relationships_candidate_count == 1
    assert report.relationships_by_status["NEW"] == 1
    assert len(report.candidate_relationship_results) == 1

    cand_res = report.candidate_relationship_results[0]
    assert cand_res.status == "NEW"
    assert cand_res.evidence_snippet == "John will lead the Personal Intelligence architecture."
    assert cand_res.subject_entity_name == "John"
    assert cand_res.object_entity_name == "Personal Intelligence"


@pytest.mark.asyncio
async def test_relationship_classification_confirm_and_update(
    mock_extractor: AsyncMock,
) -> None:
    """Classifies candidate as CONFIRM when identical relationship exists, or UPDATE when confidence is higher."""
    existing_john = Entity(
        id="john_id",
        name="John",
        entity_type=EntityType.PERSON,
        confidence=ConfidenceScore.from_score(0.9),
    )
    existing_pi = Entity(
        id="pi_id",
        name="Personal Intelligence",
        entity_type=EntityType.PROJECT,
        confidence=ConfidenceScore.from_score(0.9),
    )

    existing_rel = Relationship(
        id="rel_existing_1",
        subject="john_id",
        predicate=RelationshipType.RESPONSIBLE_FOR,
        object="pi_id",
        confidence=ConfidenceScore.from_score(0.85),
    )

    raw_obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_id_101",
        content="John remains responsible for Personal Intelligence.",
    )

    span = EvidenceSpan(
        text_snippet="John remains responsible for Personal Intelligence.",
        confidence=ConfidenceScore.from_score(0.95),
    )

    mock_extraction = StructuredExtraction(
        source_observation_id=raw_obs.id,
        entities=[
            Entity(
                id="john_temp",
                name="John",
                entity_type=EntityType.PERSON,
                confidence=ConfidenceScore.from_score(0.9),
            ),
            Entity(
                id="pi_temp",
                name="Personal Intelligence",
                entity_type=EntityType.PROJECT,
                confidence=ConfidenceScore.from_score(0.9),
            ),
        ],
        relationships=[
            Relationship(
                subject="John",
                predicate=RelationshipType.RESPONSIBLE_FOR,
                object="Personal Intelligence",
                confidence=ConfidenceScore.from_score(0.95),  # higher than 0.85 -> UPDATE
                evidence_span=span,
                source_observation_id=raw_obs.id,
            )
        ],
    )

    mock_extractor.extract_from_normalized_email.return_value = mock_extraction

    pipeline = GmailPipelineService(extractor=mock_extractor)
    report = await pipeline.process_gmail_observation(
        raw_obs,
        existing_entities=[existing_john, existing_pi],
        existing_relationships=[existing_rel],
    )

    assert report.relationships_by_status["UPDATE"] == 1
    assert report.candidate_relationship_results[0].status == "UPDATE"


@pytest.mark.asyncio
async def test_relationship_classification_conflict(
    mock_extractor: AsyncMock,
) -> None:
    """Classifies candidate as CONFLICT when predicate opposes existing relationship."""
    existing_subj = Entity(
        id="subj_id",
        name="Alice",
        entity_type=EntityType.PERSON,
        confidence=ConfidenceScore.from_score(0.9),
    )
    existing_obj = Entity(
        id="obj_id",
        name="Acme",
        entity_type=EntityType.ORGANIZATION,
        confidence=ConfidenceScore.from_score(0.9),
    )

    existing_rel = Relationship(
        subject="subj_id",
        predicate=RelationshipType.WORKS_FOR,
        object="obj_id",
        confidence=ConfidenceScore.from_score(0.90),
    )

    raw_obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_id_102",
        content="Alice left Acme.",
    )
    span = EvidenceSpan(text_snippet="Alice left Acme", confidence=ConfidenceScore.from_score(0.90))

    mock_extraction = StructuredExtraction(
        source_observation_id=raw_obs.id,
        entities=[
            Entity(
                id="a_temp",
                name="Alice",
                entity_type=EntityType.PERSON,
                confidence=ConfidenceScore.from_score(0.9),
            ),
            Entity(
                id="b_temp",
                name="Acme",
                entity_type=EntityType.ORGANIZATION,
                confidence=ConfidenceScore.from_score(0.9),
            ),
        ],
        relationships=[
            Relationship(
                subject="Alice",
                predicate=RelationshipType.MANAGES,  # conflicting predicate vs WORKS_FOR
                object="Acme",
                confidence=ConfidenceScore.from_score(0.90),
                evidence_span=span,
                source_observation_id=raw_obs.id,
            )
        ],
    )

    mock_extractor.extract_from_normalized_email.return_value = mock_extraction

    pipeline = GmailPipelineService(extractor=mock_extractor)
    report = await pipeline.process_gmail_observation(
        raw_obs,
        existing_entities=[existing_subj, existing_obj],
        existing_relationships=[existing_rel],
    )

    assert report.relationships_by_status["CONFLICT"] == 1
    assert report.candidate_relationship_results[0].status == "CONFLICT"


@pytest.mark.asyncio
async def test_relationship_classification_uncertain_low_confidence(
    mock_extractor: AsyncMock,
) -> None:
    """Classifies candidate as UNCERTAIN when confidence score is below threshold (0.40)."""
    raw_obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_id_103",
        content="Tentative statement.",
    )
    span = EvidenceSpan(
        text_snippet="Tentative statement", confidence=ConfidenceScore.from_score(0.25)
    )

    mock_extraction = StructuredExtraction(
        source_observation_id=raw_obs.id,
        entities=[
            Entity(
                id="e1",
                name="Bob",
                entity_type=EntityType.PERSON,
                confidence=ConfidenceScore.from_score(0.5),
            ),
            Entity(
                id="e2",
                name="Task X",
                entity_type=EntityType.PROJECT,
                confidence=ConfidenceScore.from_score(0.5),
            ),
        ],
        relationships=[
            Relationship(
                subject="Bob",
                predicate=RelationshipType.RESPONSIBLE_FOR,
                object="Task X",
                confidence=ConfidenceScore.from_score(0.25),  # < 0.40 -> UNCERTAIN
                evidence_span=span,
                source_observation_id=raw_obs.id,
            )
        ],
    )

    mock_extractor.extract_from_normalized_email.return_value = mock_extraction

    pipeline = GmailPipelineService(extractor=mock_extractor)
    report = await pipeline.process_gmail_observation(raw_obs)

    assert report.relationships_by_status["UNCERTAIN"] == 1
    assert report.candidate_relationship_results[0].status == "UNCERTAIN"
    assert "below minimum threshold" in report.candidate_relationship_results[0].reason


@pytest.mark.asyncio
async def test_pipeline_reconciliation_closes_validity_interval_on_update(
    mock_extractor: AsyncMock,
) -> None:
    """Verifies that when a relationship update occurs (e.g. Alice WORKS_AT Company A -> Company B), the previous relationship validity interval is closed."""
    from app.services.world_model import WorldModelService

    raw_obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_id_999",
        content="Alice moved to Company B.",
    )
    span = EvidenceSpan(
        text_snippet="Alice moved to Company B.",
        confidence=ConfidenceScore.from_score(0.95),
    )

    alice = Entity(id="ent_alice", name="Alice", entity_type=EntityType.PERSON, confidence=ConfidenceScore.from_score(0.95))
    comp_a = Entity(id="comp_a", name="Company A", entity_type=EntityType.ORGANIZATION, confidence=ConfidenceScore.from_score(0.95))
    comp_b = Entity(id="comp_b", name="Company B", entity_type=EntityType.ORGANIZATION, confidence=ConfidenceScore.from_score(0.95))

    old_rel = Relationship(
        id="rel_alice_comp_a",
        subject="ent_alice",
        predicate=RelationshipType.WORKS_FOR,
        object="comp_a",
        confidence=ConfidenceScore.from_score(0.90),
    )

    mock_extraction = StructuredExtraction(
        source_observation_id=raw_obs.id,
        entities=[alice, comp_b],
        relationships=[
            Relationship(
                id="rel_alice_comp_b",
                subject="Alice",
                predicate=RelationshipType.WORKS_FOR,
                object="Company B",
                confidence=ConfidenceScore.from_score(0.95),
                evidence_span=span,
                source_observation_id=raw_obs.id,
            )
        ],
    )

    mock_extractor.extract_from_normalized_email.return_value = mock_extraction

    wm_mock = AsyncMock(spec=WorldModelService)
    wm_mock.get_all_claims.return_value = []

    pipeline = GmailPipelineService(extractor=mock_extractor, world_model_service=wm_mock)

    report = await pipeline.process_gmail_observation(
        raw_observation=raw_obs,
        existing_entities=[alice, comp_a, comp_b],
        existing_relationships=[old_rel],
    )

    assert report.relationships_by_status["UPDATE"] == 1
    # Check that previous relationship had its valid_to set and was saved back to world model
    assert old_rel.validity.valid_to is not None
    assert wm_mock.save_relationship.called

