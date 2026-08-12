"""Validation tests for the Gmail-derived Personal World Model schema.

Verifies:
- EntityType enumerations (PERSON, ORGANIZATION, PROJECT, PRODUCT, ROLE, LOCATION, EVENT, DOCUMENT, CONCEPT)
- RelationshipType enumerations (WORKS_FOR, WORKS_WITH, MANAGES, REPORTS_TO, OWNS, CREATED, INVOLVED_IN, RELATED_TO, DEPENDS_ON, PART_OF, MENTIONS, REQUESTS, ASSIGNS, COMMUNICATES_WITH, INTERESTED_IN, RESPONSIBLE_FOR)
- Extracted Relationship required fields (subject, predicate, object, confidence, evidence_span, source_observation_id)
- TemporalReference aspects (before, after, during, since, until, current, unknown)
- EvidenceSpan excerpt grounding
- Distinguishability of Claims vs Observations
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain import (
    Claim,
    ClaimStatus,
    ConfidenceScore,
    Constraint,
    Decision,
    Entity,
    EntityType,
    Event,
    EvidenceSpan,
    Goal,
    Observation,
    ObservationSource,
    Preference,
    Project,
    Relationship,
    RelationshipType,
    TemporalAspect,
    TemporalRange,
    TemporalReference,
)


def test_entity_types_schema() -> None:
    """EntityType contains required Gmail-derived entity classifications."""
    required_types = [
        "person",
        "organization",
        "project",
        "product",
        "role",
        "location",
        "event",
        "document",
        "concept",
    ]
    for r_type in required_types:
        assert EntityType(r_type) in list(EntityType)

    # Instantiate Entity with specified types
    ent_person = Entity(
        entity_type=EntityType.PERSON,
        name="Alice Smith",
        confidence=ConfidenceScore.from_score(0.95),
    )
    assert ent_person.entity_type == EntityType.PERSON

    ent_product = Entity(
        entity_type=EntityType.PRODUCT,
        name="Gmail API",
        confidence=ConfidenceScore.from_score(0.9),
    )
    assert ent_product.entity_type == EntityType.PRODUCT


def test_relationship_types_schema() -> None:
    """RelationshipType contains required relationship predicates."""
    required_predicates = [
        "works_for",
        "works_with",
        "manages",
        "reports_to",
        "owns",
        "created",
        "involved_in",
        "related_to",
        "depends_on",
        "part_of",
        "mentions",
        "requests",
        "assigns",
        "communicates_with",
        "interested_in",
        "responsible_for",
    ]
    for pred in required_predicates:
        assert RelationshipType(pred) in list(RelationshipType)


def test_extracted_relationship_required_fields() -> None:
    """Extracted Relationship must contain subject, predicate, object, confidence, evidence_span, source_observation_id."""
    span = EvidenceSpan(
        text_snippet="Alice is the lead engineer for project Personal Intelligence.",
        start_char=0,
        end_char=60,
        confidence=ConfidenceScore.from_score(0.92),
    )

    rel = Relationship(
        subject="alice_id",
        predicate=RelationshipType.RESPONSIBLE_FOR,
        object="proj_pi_id",
        confidence=ConfidenceScore.from_score(0.95),
        evidence_span=span,
        source_observation_id="obs_gmail_123",
    )

    assert rel.subject == "alice_id"
    assert rel.predicate == RelationshipType.RESPONSIBLE_FOR
    assert rel.object == "proj_pi_id"
    assert rel.confidence.score == 0.95
    assert rel.evidence_span == span
    assert rel.source_observation_id == "obs_gmail_123"

    # Verify serialization/deserialization
    serialized = rel.model_dump()
    assert serialized["subject"] == "alice_id"
    assert serialized["predicate"] == "responsible_for"

    restored = Relationship.model_validate(serialized)
    assert restored.predicate == RelationshipType.RESPONSIBLE_FOR


def test_temporal_reference_aspects() -> None:
    """TemporalReference supports before, after, during, since, until, current, unknown."""
    aspects = [
        TemporalAspect.BEFORE,
        TemporalAspect.AFTER,
        TemporalAspect.DURING,
        TemporalAspect.SINCE,
        TemporalAspect.UNTIL,
        TemporalAspect.CURRENT,
        TemporalAspect.UNKNOWN,
    ]
    assert len(aspects) == 7

    now = datetime.now(UTC)
    temp_ref = TemporalReference(
        aspect=TemporalAspect.SINCE,
        point_in_time=now,
        relative_text="since last Monday",
        range=TemporalRange(valid_from=now),
    )

    assert temp_ref.aspect == TemporalAspect.SINCE
    assert temp_ref.relative_text == "since last Monday"
    assert temp_ref.range is not None
    assert temp_ref.range.valid_from == now


def test_evidence_span_validation() -> None:
    """EvidenceSpan validates character bounds and confidence score."""
    span = EvidenceSpan(
        text_snippet="Meeting at 3pm with Bob",
        start_char=10,
        end_char=33,
        confidence=ConfidenceScore.from_score(0.85),
    )
    assert span.text_snippet == "Meeting at 3pm with Bob"
    assert span.start_char == 10
    assert span.end_char == 33

    # Negative character index validation
    with pytest.raises(ValidationError):
        EvidenceSpan(
            text_snippet="Test",
            start_char=-5,
            confidence=ConfidenceScore.from_score(0.5),
        )


def test_claim_distinguishable_from_observation() -> None:
    """Claims must be clearly distinguishable from raw Observations."""
    raw_obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="gmail_msg_555",
        content="Subject: Promotion\nBody: Alice was promoted to Tech Lead.",
    )

    claim = Claim(
        subject="Alice",
        predicate="role",
        value="Tech Lead",
        status=ClaimStatus.PROPOSED,
        confidence=ConfidenceScore.from_score(0.88),
        evidence_ids=["ev_1"],
        evidence_spans=[
            EvidenceSpan(
                text_snippet="Alice was promoted to Tech Lead.",
                confidence=ConfidenceScore.from_score(0.9),
            )
        ],
    )

    # 1. Type distinction
    assert type(raw_obs) is not type(claim)
    assert not isinstance(raw_obs, Claim)
    assert not isinstance(claim, Observation)

    # 2. Semantic distinction
    assert raw_obs.source == ObservationSource.GMAIL
    assert hasattr(raw_obs, "content")
    assert not hasattr(raw_obs, "status")

    assert claim.status == ClaimStatus.PROPOSED
    assert hasattr(claim, "subject")
    assert hasattr(claim, "predicate")
    assert hasattr(claim, "value")
    assert not hasattr(claim, "source")


def test_domain_entity_subtypes_schema() -> None:
    """Event, Goal, Project, Decision, Constraint, Preference schema validation."""
    now = datetime.now(UTC)

    evt = Event(
        name="Architecture Review",
        confidence=ConfidenceScore.from_score(0.9),
        starts_at=now,
        location="Google Meet",
    )
    assert evt.entity_type == EntityType.EVENT

    goal = Goal(
        name="Complete V0 Gmail Pipeline",
        confidence=ConfidenceScore.from_score(0.95),
    )
    assert goal.entity_type == EntityType.GOAL

    proj = Project(
        name="Personal Intelligence",
        confidence=ConfidenceScore.from_score(0.99),
    )
    assert proj.entity_type == EntityType.PROJECT

    dec = Decision(
        name="Adopt Kuzu for World Model Graph",
        confidence=ConfidenceScore.from_score(0.9),
        question="Which graph database for in-process Python 3.12?",
        alternatives=["Kuzu", "Neo4j"],
        context="Local-first requirement",
        decision="Use Kuzu",
    )
    assert dec.entity_type == EntityType.DECISION

    pref = Preference(
        name="Email Briefing Frequency",
        confidence=ConfidenceScore.from_score(0.8),
        domain="notifications",
        value="daily",
    )
    assert pref.entity_type == EntityType.PREFERENCE

    con = Constraint(
        name="Single User V0 Boundary",
        confidence=ConfidenceScore.from_score(1.0),
        constraint_type="architectural",
        severity="hard",
    )
    assert con.entity_type == EntityType.CONSTRAINT
