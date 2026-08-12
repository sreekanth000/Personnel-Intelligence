"""Unit tests for domain models: validation, serialization, required fields, temporal fields, provenance, and contradictory claims handling."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain import (
    Claim,
    ClaimStatus,
    Commitment,
    ConfidenceCategory,
    ConfidenceScore,
    Constraint,
    ContextPackage,
    ContextRequest,
    Decision,
    DecisionStatus,
    Entity,
    EntityType,
    Event,
    Evidence,
    EvidenceType,
    Goal,
    Observation,
    ObservationSource,
    Preference,
    Project,
    Provenance,
    ReconciliationOutcome,
    Relationship,
    StateChange,
    Task,
    TemporalRange,
    WorldState,
)

# ---------------------------------------------------------------------------
# Value Objects & Enums
# ---------------------------------------------------------------------------


def test_confidence_score_auto_category() -> None:
    """ConfidenceScore should map scores to appropriate qualitative categories."""
    assert ConfidenceScore.from_score(0.1).category == ConfidenceCategory.VERY_LOW
    assert ConfidenceScore.from_score(0.3).category == ConfidenceCategory.LOW
    assert ConfidenceScore.from_score(0.5).category == ConfidenceCategory.MEDIUM
    assert ConfidenceScore.from_score(0.7).category == ConfidenceCategory.HIGH
    assert ConfidenceScore.from_score(0.9).category == ConfidenceCategory.VERY_HIGH


def test_confidence_score_range_validation() -> None:
    """ConfidenceScore should reject values outside [0.0, 1.0]."""
    with pytest.raises(ValidationError):
        ConfidenceScore(score=-0.1, category=ConfidenceCategory.LOW)
    with pytest.raises(ValidationError):
        ConfidenceScore(score=1.1, category=ConfidenceCategory.HIGH)


def test_temporal_range_bounds_and_contains() -> None:
    """TemporalRange contains() logic and open-ended status."""
    now = datetime.utcnow()
    past = now - timedelta(days=1)
    future = now + timedelta(days=1)

    t_range = TemporalRange(valid_from=past, valid_to=future)
    assert not t_range.is_open_ended
    assert t_range.contains(now)
    assert not t_range.contains(past - timedelta(hours=1))
    assert not t_range.contains(future + timedelta(hours=1))

    open_range = TemporalRange(valid_from=past)
    assert open_range.is_open_ended
    assert open_range.contains(future + timedelta(days=100))


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


def test_observation_creation_and_serialization() -> None:
    """Observation creation, serialization, and required fields."""
    obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_123",
        content="Meeting with Alice at 3pm tomorrow.",
        metadata={"subject": "Sync meeting"},
    )
    assert obs.id is not None
    assert obs.source == ObservationSource.GMAIL

    # Serialization
    data = obs.model_dump()
    assert data["source_identifier"] == "msg_123"
    restored = Observation.model_validate(data)
    assert restored.id == obs.id
    assert restored.metadata["subject"] == "Sync meeting"


def test_observation_required_fields() -> None:
    """Observation should fail if required fields are missing."""
    with pytest.raises(ValidationError):
        Observation(source=ObservationSource.GMAIL)  # missing source_identifier and content


# ---------------------------------------------------------------------------
# Evidence & Claims
# ---------------------------------------------------------------------------


def test_evidence_requires_observation() -> None:
    """Evidence must reference an observation ID."""
    with pytest.raises(ValidationError, match="Evidence must reference an observation"):
        Evidence(
            observation_id="   ",
            claim_id="claim_1",
            evidence_type=EvidenceType.SUPPORTS,
            content="Supporting text snippet",
            confidence=ConfidenceScore.from_score(0.85),
        )


def test_contradictory_claims_and_evidence() -> None:
    """Claims should track opposing evidence without overwriting truth."""
    obs1 = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_1",
        content="Alice lives in Seattle.",
    )
    obs2 = Observation(
        source=ObservationSource.LOCAL_FILESYSTEM,
        source_identifier="/docs/resume.pdf",
        content="Alice lives in New York.",
    )

    claim = Claim(
        subject="alice",
        predicate="lives_in",
        value="Seattle",
        confidence=ConfidenceScore.from_score(0.7),
        status=ClaimStatus.PROPOSED,
    )

    ev1 = Evidence(
        observation_id=obs1.id,
        claim_id=claim.id,
        evidence_type=EvidenceType.SUPPORTS,
        content="Alice lives in Seattle.",
        confidence=ConfidenceScore.from_score(0.9),
    )

    ev2 = Evidence(
        observation_id=obs2.id,
        claim_id=claim.id,
        evidence_type=EvidenceType.CONTRADICTS,
        content="Alice lives in New York.",
        confidence=ConfidenceScore.from_score(0.95),
    )

    claim.evidence_ids.extend([ev1.id, ev2.id])
    # Mark as contested due to contradiction
    claim.status = ClaimStatus.CONTESTED

    assert len(claim.evidence_ids) == 2
    assert claim.status == ClaimStatus.CONTESTED
    assert claim.provenance is not None


# ---------------------------------------------------------------------------
# Entities & Subtypes (including Decision)
# ---------------------------------------------------------------------------


def test_decision_required_fields() -> None:
    """Decision must contain question, alternatives, context, constraints, reasoning, decision, outcome."""
    d = Decision(
        name="Database Selection",
        confidence=ConfidenceScore.from_score(0.9),
        question="Which database to use for graph model?",
        alternatives=["Kuzu", "Neo4j", "Memgraph"],
        context="Local-first requirement, in-process Python 3.12 compatibility.",
        constraints=["Local execution", "No server process needed"],
        reasoning="Kuzu is in-process, supports Cypher queries, and integrates cleanly with Python.",
        decision="Use Kuzu for graph persistence.",
        outcome="Fast local queries without infrastructure overhead.",
        status=DecisionStatus.MADE,
    )
    assert d.entity_type == EntityType.DECISION
    assert d.question == "Which database to use for graph model?"
    assert len(d.alternatives) == 3
    assert d.status == DecisionStatus.MADE

    # Missing required question/alternatives/context
    with pytest.raises(ValidationError):
        Decision(
            name="Incomplete Decision",
            confidence=ConfidenceScore.from_score(0.5),
        )


def test_entity_subtypes() -> None:
    """Event, Goal, Project, Task, Preference, Constraint, Commitment validation."""
    now = datetime.utcnow()

    event = Event(
        name="Team Sync",
        confidence=ConfidenceScore.from_score(0.9),
        starts_at=now,
        location="Room 404",
    )
    assert event.entity_type == EntityType.EVENT

    goal = Goal(
        name="Launch V0",
        confidence=ConfidenceScore.from_score(0.8),
        status="active",
    )
    assert goal.entity_type == EntityType.GOAL

    project = Project(
        name="Personal Intelligence Core",
        confidence=ConfidenceScore.from_score(0.95),
        goal_ids=[goal.id],
    )
    assert project.entity_type == EntityType.PROJECT

    task = Task(
        name="Implement Domain Models",
        confidence=ConfidenceScore.from_score(0.99),
        priority="high",
    )
    assert task.entity_type == EntityType.TASK

    pref = Preference(
        name="Dark Mode Preference",
        confidence=ConfidenceScore.from_score(0.8),
        domain="ui",
        value="dark",
    )
    assert pref.entity_type == EntityType.PREFERENCE

    constraint = Constraint(
        name="Memory Limit",
        confidence=ConfidenceScore.from_score(0.9),
        constraint_type="resource",
        severity="hard",
    )
    assert constraint.entity_type == EntityType.CONSTRAINT

    commitment = Commitment(
        name="Deliver V0 Spec",
        confidence=ConfidenceScore.from_score(0.85),
        committed_to="User",
    )
    assert commitment.entity_type == EntityType.COMMITMENT


def test_relationship_validity_interval() -> None:
    """Relationships must support temporal validity intervals."""
    past = datetime.utcnow() - timedelta(days=365)
    now = datetime.utcnow()

    rel = Relationship(
        source_entity_id="person_1",
        target_entity_id="org_1",
        relationship_type="worked_at",
        validity=TemporalRange(valid_from=past, valid_to=now),
        confidence=ConfidenceScore.from_score(0.9),
        provenance=Provenance(source_observation_ids=["obs_99"]),
    )
    assert rel.validity.valid_from == past
    assert rel.validity.valid_to == now
    assert not rel.validity.is_open_ended
    assert rel.provenance.source_observation_ids == ["obs_99"]


# ---------------------------------------------------------------------------
# WorldState & StateChange
# ---------------------------------------------------------------------------


def test_world_state_temporal_snapshot() -> None:
    """WorldState is a temporal snapshot tracking active entities, relationships, claims, and state changes."""
    sc = StateChange(
        observation_id="obs_100",
        outcome=ReconciliationOutcome.CREATED,
        description="Created entity for new task.",
        entity_id="task_55",
    )

    ws = WorldState(
        active_entity_ids=["task_55", "person_1"],
        active_relationship_ids=["rel_1"],
        active_claim_ids=["claim_1"],
        recent_changes=[sc.id],
    )
    assert ws.id is not None
    assert isinstance(ws.timestamp, datetime)
    assert len(ws.active_entity_ids) == 2


# ---------------------------------------------------------------------------
# ContextRequest & ContextPackage
# ---------------------------------------------------------------------------


def test_context_request_and_package_serialization() -> None:
    """ContextRequest and ContextPackage validation and JSON roundtrip."""
    req = ContextRequest(
        task_intent="prepare_briefing",
        query="What decisions were made about database?",
        max_items=10,
    )
    assert req.task_intent == "prepare_briefing"

    entity = Entity(
        entity_type=EntityType.PERSON,
        name="Sreekanth",
        confidence=ConfidenceScore.from_score(0.99),
    )

    pkg = ContextPackage(
        request_id=req.id,
        purpose="daily_briefing",
        entities=[entity],
        summary="Briefing package containing Sreekanth entity.",
        filtered_count=2,
    )
    assert pkg.request_id == req.id
    assert len(pkg.entities) == 1

    # Roundtrip serialization
    json_data = pkg.model_dump_json()
    restored = ContextPackage.model_validate_json(json_data)
    assert restored.entities[0].name == "Sreekanth"
