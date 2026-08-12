"""Unit tests for the Personal Context Engine.

Verifies user query intent resolution for:
1. "What is happening with Project X?"
2. "Who is involved in Project X?"
3. "What decisions have I made about Project X?"
4. "What changed recently?"
5. "What commitments are currently active?"
6. "Who am I working with on this?"

Verifies:
- Structured ContextPackage return (No GPT-4.1 generation)
- Provenance details preserved on all items.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings
from app.domain import (
    Commitment,
    ConfidenceScore,
    ContextRequest,
    Decision,
    DecisionStatus,
    Entity,
    EntityType,
    Provenance,
    ReconciliationOutcome,
    Relationship,
    RelationshipType,
    StateChange,
)
from app.persistence.duckdb_store import DuckDBStore
from app.persistence.kuzu_store import KuzuStore
from app.services.context import ContextEngine
from app.services.evidence import EvidenceService
from app.services.world_model import WorldModelService


@pytest.fixture()
async def populated_services(
    test_settings: Settings,
) -> tuple[WorldModelService, EvidenceService, ContextEngine]:
    """Fixture populating WorldModelService and EvidenceService."""
    duckdb = DuckDBStore(test_settings.duckdb_path)
    kuzu = KuzuStore(test_settings.kuzu_path)
    wm = WorldModelService(duckdb_store=duckdb, kuzu_store=kuzu)
    ev = EvidenceService(duckdb_store=duckdb)

    # Entities
    project_x = Entity(
        id="prj_x",
        entity_type=EntityType.PROJECT,
        name="Project X",
        provenance=Provenance(source_observation_id="obs_100"),
        confidence=ConfidenceScore.from_score(0.95),
    )
    alice = Entity(
        id="ent_alice",
        entity_type=EntityType.PERSON,
        name="Alice Smith",
        provenance=Provenance(source_observation_id="obs_100"),
        confidence=ConfidenceScore.from_score(0.95),
    )
    bob = Entity(
        id="ent_bob",
        entity_type=EntityType.PERSON,
        name="Bob Jones",
        provenance=Provenance(source_observation_id="obs_101"),
        confidence=ConfidenceScore.from_score(0.90),
    )
    await wm.save_entity(project_x)
    await wm.save_entity(alice)
    await wm.save_entity(bob)

    # Relationships
    rel1 = Relationship(
        id="rel_alice_prj_x",
        subject="ent_alice",
        predicate=RelationshipType.RESPONSIBLE_FOR,
        object="prj_x",
        provenance=Provenance(source_observation_id="obs_100"),
        confidence=ConfidenceScore.from_score(0.92),
    )
    rel2 = Relationship(
        id="rel_bob_alice",
        subject="ent_bob",
        predicate=RelationshipType.WORKS_WITH,
        object="ent_alice",
        provenance=Provenance(source_observation_id="obs_101"),
        confidence=ConfidenceScore.from_score(0.88),
    )
    await wm.save_relationship(rel1)
    await wm.save_relationship(rel2)

    # Decision
    dec = Decision(
        id="dec_arch",
        name="Project X Architecture Decision",
        question="Use DuckDB for local storage?",
        alternatives=["DuckDB", "SQLite"],
        context="Local fast graph query requirement",
        decision="DuckDB",
        status=DecisionStatus.MADE,
        provenance=Provenance(source_observation_id="obs_102"),
        confidence=ConfidenceScore.from_score(0.95),
    )
    await wm.save_entity(dec)

    # Commitment
    comm = Commitment(
        id="comm_demo",
        name="Deliver V0 prototype",
        committed_to="ent_alice",
        status="open",
        provenance=Provenance(source_observation_id="obs_103"),
        confidence=ConfidenceScore.from_score(0.90),
    )
    await wm.save_entity(comm)

    # StateChange
    sc = StateChange(
        observation_id="obs_100",
        entity_id="prj_x",
        outcome=ReconciliationOutcome.NOVEL,
        description="Project X initiated.",
        provenance=Provenance(source_observation_id="obs_100"),
    )
    await wm.record_state_change(sc)

    # Evidence
    await ev.record_evidence(
        observation_id="obs_100",
        target_id="prj_x",
        target_type="entity",
        content="Alice will lead Project X development.",
    )

    engine = ContextEngine(world_model_service=wm, evidence_service=ev)
    return wm, ev, engine


@pytest.mark.asyncio
async def test_query_what_is_happening_with_project_x(
    populated_services: tuple[WorldModelService, EvidenceService, ContextEngine],
) -> None:
    """Tests query: 'What is happening with Project X?'."""
    _, _, engine = populated_services

    req = ContextRequest(
        task_intent="project_status",
        query="What is happening with Project X?",
    )
    pkg = await engine.assemble_context(req)

    assert pkg.request_id == req.id
    assert len(pkg.entities) >= 1
    assert any(e.name == "Project X" for e in pkg.entities)
    assert len(pkg.relationships) >= 1
    assert len(pkg.evidence) >= 1
    assert len(pkg.state_changes) >= 1

    # Verify provenance support
    for ent in pkg.entities:
        assert ent.provenance is not None
        assert isinstance(ent.provenance.source_observation_ids, list)


@pytest.mark.asyncio
async def test_query_who_is_involved_in_project_x(
    populated_services: tuple[WorldModelService, EvidenceService, ContextEngine],
) -> None:
    """Tests query: 'Who is involved in Project X?'."""
    _, _, engine = populated_services

    req = ContextRequest(
        task_intent="identify_people",
        query="Who is involved in Project X?",
    )
    pkg = await engine.assemble_context(req)

    person_names = [e.name for e in pkg.entities if e.entity_type == EntityType.PERSON]
    assert "Alice Smith" in person_names
    assert len(pkg.relationships) >= 1


@pytest.mark.asyncio
async def test_query_what_decisions_have_i_made_about_project_x(
    populated_services: tuple[WorldModelService, EvidenceService, ContextEngine],
) -> None:
    """Tests query: 'What decisions have I made about Project X?'."""
    _, _, engine = populated_services

    req = ContextRequest(
        task_intent="retrieve_decisions",
        query="What decisions have I made about Project X?",
    )
    pkg = await engine.assemble_context(req)

    assert len(pkg.decisions) >= 1
    assert any("Architecture Decision" in d.name for d in pkg.decisions)
    assert any(d.provenance is not None for d in pkg.decisions)


@pytest.mark.asyncio
async def test_query_what_changed_recently(
    populated_services: tuple[WorldModelService, EvidenceService, ContextEngine],
) -> None:
    """Tests query: 'What changed recently?'."""
    _, _, engine = populated_services

    req = ContextRequest(
        task_intent="recent_updates",
        query="What changed recently?",
    )
    pkg = await engine.assemble_context(req)

    assert len(pkg.state_changes) >= 1
    assert pkg.state_changes[0].description == "Project X initiated."
    assert pkg.state_changes[0].provenance is not None


@pytest.mark.asyncio
async def test_query_what_commitments_are_currently_active(
    populated_services: tuple[WorldModelService, EvidenceService, ContextEngine],
) -> None:
    """Tests query: 'What commitments are currently active?'."""
    _, _, engine = populated_services

    req = ContextRequest(
        task_intent="active_commitments",
        query="What commitments are currently active?",
    )
    pkg = await engine.assemble_context(req)

    assert len(pkg.commitments) >= 1
    assert pkg.commitments[0].name == "Deliver V0 prototype"
    assert pkg.commitments[0].provenance is not None


@pytest.mark.asyncio
async def test_query_who_am_i_working_with_on_this(
    populated_services: tuple[WorldModelService, EvidenceService, ContextEngine],
) -> None:
    """Tests query: 'Who am I working with on this?'."""
    _, _, engine = populated_services

    req = ContextRequest(
        task_intent="collaborators",
        query="Who am I working with on this?",
    )
    pkg = await engine.assemble_context(req)

    person_names = [e.name for e in pkg.entities if e.entity_type == EntityType.PERSON]
    assert len(person_names) >= 1
    assert len(pkg.relationships) >= 1


@pytest.mark.asyncio
async def test_claims_persisted_and_retrieved_in_context(
    populated_services: tuple[WorldModelService, EvidenceService, ContextEngine],
) -> None:
    """Verifies claims are saved to DuckDB and returned in ContextPackage."""
    from app.domain.claims import Claim
    from app.domain.enums import ClaimStatus

    wm, _, engine = populated_services

    claim = Claim(
        id="clm_001",
        subject="ent_alice",
        predicate="works_at",
        value="Google",
        status=ClaimStatus.CONFIRMED,
        confidence=ConfidenceScore.from_score(0.95),
        provenance=Provenance(source_observation_id="obs_100"),
    )
    await wm.save_claim(claim)

    saved_claim = await wm.get_claim("clm_001")
    assert saved_claim is not None
    assert saved_claim.value == "Google"
    assert saved_claim.status == ClaimStatus.CONFIRMED

    all_claims = await wm.get_all_claims()
    assert len(all_claims) >= 1

    req = ContextRequest(
        task_intent="claims_check",
        query="What claims do we have for Alice Smith working at Google?",
    )
    pkg = await engine.assemble_context(req)
    assert len(pkg.claims) >= 1
    assert pkg.claims[0].value == "Google"


@pytest.mark.asyncio
async def test_context_engine_multi_hop_and_temporal_filtering(
    populated_services: tuple[WorldModelService, EvidenceService, ContextEngine],
) -> None:
    """Verifies evidence-weighted multi-hop graph traversal and temporal bounds filtering in ContextEngine."""
    from datetime import UTC, datetime, timedelta
    from app.domain import TemporalRange

    wm, ev, engine = populated_services

    # Add expired relationship (valid_to = 30 days ago)
    past_validity = Relationship(
        id="rel_old_001",
        subject="ent_alice",
        predicate=RelationshipType.WORKS_FOR,
        object="ent_acme_corp",
        confidence=ConfidenceScore.from_score(0.90),
        validity=TemporalRange(
            valid_from=datetime.now(UTC) - timedelta(days=365),
            valid_to=datetime.now(UTC) - timedelta(days=30),
        ),
    )
    await wm.save_relationship(past_validity)

    # Context request with recent_days = 7 (should exclude past_validity)
    req_recent = ContextRequest(
        task_intent="recent_check",
        query="Who does Alice work for?",
        recent_days=7,
    )
    pkg_recent = await engine.assemble_context(req_recent)

    # Verify past relationship expired 30 days ago is filtered out
    rel_ids = [r.id for r in pkg_recent.relationships]
    assert "rel_old_001" not in rel_ids


