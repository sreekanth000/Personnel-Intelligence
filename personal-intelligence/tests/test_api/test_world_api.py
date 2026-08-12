"""Unit and integration tests for Personal World Model Query API endpoints (/world/*).

Verifies:
- GET /world/entities/{id} (200 OK and 404 Not Found)
- GET /world/entities/{id}/relationships
- GET /world/entities/{id}/timeline
- GET /world/entities/{id}/evidence
- GET /world/people
- GET /world/organizations
- GET /world/projects
- GET /world/goals
- GET /world/decisions
- GET /world/current-state (Deterministic synthesis without GPT-4.1)
- GET /world/changes
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.world import set_evidence_service, set_world_model_service
from app.domain import (
    ConfidenceScore,
    Decision,
    DecisionStatus,
    Entity,
    EntityType,
    Goal,
    Project,
    ReconciliationOutcome,
    Relationship,
    RelationshipType,
    StateChange,
)
from app.main import app
from app.persistence.duckdb_store import DuckDBStore
from app.persistence.kuzu_store import KuzuStore
from app.services.evidence import EvidenceService
from app.services.world_model import WorldModelService


@pytest.fixture()
def client_and_services(
    test_settings: Settings,
) -> tuple[TestClient, WorldModelService, EvidenceService]:
    """Fixture initializing TestClient and populated WorldModelService + EvidenceService."""
    duckdb = DuckDBStore(test_settings.duckdb_path)
    kuzu = KuzuStore(test_settings.kuzu_path)
    wm = WorldModelService(duckdb_store=duckdb, kuzu_store=kuzu)
    ev = EvidenceService(duckdb_store=duckdb)

    set_world_model_service(wm)
    set_evidence_service(ev)

    client = TestClient(app)
    return client, wm, ev


@pytest.mark.asyncio
async def test_get_entity_by_id_200_and_404(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /world/entities/{id} returns entity if found, 404 if missing."""
    client, wm, _ = client_and_services

    alice = Entity(
        id="ent_alice_100",
        entity_type=EntityType.PERSON,
        name="Alice Smith",
        email="alice@acme.com",
        confidence=ConfidenceScore.from_score(0.95),
    )
    await wm.save_entity(alice)

    # 200 OK
    res = client.get("/world/entities/ent_alice_100")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "ent_alice_100"
    assert data["name"] == "Alice Smith"
    assert data["entity_type"] == "person"

    # 404 Not Found
    res_404 = client.get("/world/entities/non_existent_id")
    assert res_404.status_code == 404
    assert "not found" in res_404.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_entity_relationships(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /world/entities/{id}/relationships returns active relationships."""
    client, wm, _ = client_and_services

    bob = Entity(
        id="ent_bob",
        entity_type=EntityType.PERSON,
        name="Bob",
        confidence=ConfidenceScore.from_score(0.9),
    )
    acme = Entity(
        id="ent_acme",
        entity_type=EntityType.ORGANIZATION,
        name="Acme Corp",
        confidence=ConfidenceScore.from_score(0.9),
    )
    await wm.save_entity(bob)
    await wm.save_entity(acme)

    rel = Relationship(
        id="rel_bob_acme",
        subject="ent_bob",
        predicate=RelationshipType.WORKS_FOR,
        object="ent_acme",
        confidence=ConfidenceScore.from_score(0.95),
    )
    await wm.save_relationship(rel)

    res = client.get("/world/entities/ent_bob/relationships")
    assert res.status_code == 200
    rels = res.json()
    assert len(rels) == 1
    assert rels[0]["id"] == "rel_bob_acme"
    assert rels[0]["subject"] == "ent_bob"
    assert rels[0]["object"] == "ent_acme"


@pytest.mark.asyncio
async def test_get_entity_timeline_and_evidence(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /world/entities/{id}/timeline and /evidence return temporal lineage and evidence."""
    client, wm, ev = client_and_services

    charlie = Entity(
        id="ent_charlie",
        entity_type=EntityType.PERSON,
        name="Charlie",
        confidence=ConfidenceScore.from_score(0.9),
    )
    await wm.save_entity(charlie)

    change = StateChange(
        observation_id="obs_123",
        entity_id="ent_charlie",
        outcome=ReconciliationOutcome.NOVEL,
        description="Charlie added to World Model.",
    )
    await wm.record_state_change(change)

    await ev.record_evidence(
        observation_id="obs_123",
        target_id="ent_charlie",
        target_type="entity",
        content="Charlie joined the team.",
    )

    # Timeline endpoint
    res_timeline = client.get("/world/entities/ent_charlie/timeline")
    assert res_timeline.status_code == 200
    tl = res_timeline.json()
    assert len(tl) == 1
    assert tl[0]["type"] == "state_change"
    assert "Charlie added" in tl[0]["description"]

    # Evidence endpoint
    res_ev = client.get("/world/entities/ent_charlie/evidence")
    assert res_ev.status_code == 200
    evidence_list = res_ev.json()
    assert len(evidence_list) == 1
    assert evidence_list[0]["target_id"] == "ent_charlie"


@pytest.mark.asyncio
async def test_typed_collections_endpoints(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /world/people, /organizations, /projects, /goals, /decisions return filtered entity collections."""
    client, wm, _ = client_and_services

    person = Entity(
        entity_type=EntityType.PERSON, name="Dave", confidence=ConfidenceScore.from_score(0.9)
    )
    org = Entity(
        entity_type=EntityType.ORGANIZATION, name="Acme", confidence=ConfidenceScore.from_score(0.9)
    )
    project = Project(
        name="Project Omega", status="active", confidence=ConfidenceScore.from_score(0.9)
    )
    goal = Goal(name="Goal 2026", status="active", confidence=ConfidenceScore.from_score(0.9))
    decision = Decision(
        name="Architecture Decision",
        question="Which database?",
        alternatives=["DuckDB", "Postgres"],
        context="Local performance requirement",
        decision="DuckDB",
        status=DecisionStatus.MADE,
        confidence=ConfidenceScore.from_score(0.95),
    )

    await wm.save_entity(person)
    await wm.save_entity(org)
    await wm.save_entity(project)
    await wm.save_entity(goal)
    await wm.save_entity(decision)

    assert len(client.get("/world/people").json()) == 1
    assert len(client.get("/world/organizations").json()) == 1
    assert len(client.get("/world/projects").json()) == 1
    assert len(client.get("/world/goals").json()) == 1
    assert len(client.get("/world/decisions").json()) == 1


@pytest.mark.asyncio
async def test_get_current_state_synthesized(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /world/current-state synthesizes active people relationships, projects, goals, decisions, constraints."""
    client, wm, _ = client_and_services

    person = Entity(
        id="p1",
        entity_type=EntityType.PERSON,
        name="Eve",
        confidence=ConfidenceScore.from_score(0.9),
    )
    project = Project(
        id="prj1", name="AI Core", status="active", confidence=ConfidenceScore.from_score(0.9)
    )
    await wm.save_entity(person)
    await wm.save_entity(project)

    rel = Relationship(
        subject="p1",
        predicate=RelationshipType.MANAGES,
        object="prj1",
        confidence=ConfidenceScore.from_score(0.9),
    )
    await wm.save_relationship(rel)

    res = client.get("/world/current-state")
    assert res.status_code == 200
    state = res.json()

    assert "timestamp" in state
    assert len(state["active_people_relationships"]) == 1
    assert len(state["active_projects"]) == 1
    assert isinstance(state["unresolved_conflicts"], list)


@pytest.mark.asyncio
async def test_get_changes(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /world/changes returns StateChange audit trail."""
    client, wm, _ = client_and_services

    sc = StateChange(
        observation_id="obs_500",
        outcome=ReconciliationOutcome.CONFIRM,
        description="Relationship confirmed.",
    )
    await wm.record_state_change(sc)

    res = client.get("/world/changes")
    assert res.status_code == 200
    changes = res.json()
    assert len(changes) == 1
    assert changes[0]["observation_id"] == "obs_500"
