"""Unit and integration tests for read-only UI API endpoints (/api/v1/ui/*).

Verifies presentation DTO output and pagination across:
- GET /api/v1/ui/overview
- GET /api/v1/ui/emails (paginated)
- GET /api/v1/ui/emails/{id}
- GET /api/v1/ui/entities (paginated & filtered)
- GET /api/v1/ui/entities/{id}
- GET /api/v1/ui/entities/{id}/relationships
- GET /api/v1/ui/entities/{id}/timeline
- GET /api/v1/ui/graph (small payload, nodes & edges schemas)
- GET /api/v1/ui/timeline
- GET /api/v1/ui/evidence/{id} (paginated)
- GET /api/v1/ui/decisions
- GET /api/v1/ui/changes
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.world import set_evidence_service, set_world_model_service
from app.config.settings import Settings
from app.domain import (
    ConfidenceScore,
    Decision,
    DecisionStatus,
    Entity,
    EntityType,
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
    """Fixture mounting populated WorldModelService & EvidenceService."""
    duckdb = DuckDBStore(test_settings.duckdb_path)
    kuzu = KuzuStore(test_settings.kuzu_path)
    wm = WorldModelService(duckdb_store=duckdb, kuzu_store=kuzu)
    ev = EvidenceService(duckdb_store=duckdb)

    set_world_model_service(wm)
    set_evidence_service(ev)

    client = TestClient(app)
    return client, wm, ev


@pytest.mark.asyncio
async def test_ui_overview_endpoint(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /api/v1/ui/overview returns UIOverviewDTO payload."""
    client, wm, _ = client_and_services

    alice = Entity(
        id="ent_alice",
        entity_type=EntityType.PERSON,
        name="Alice Smith",
        confidence=ConfidenceScore.from_score(0.95),
    )
    prj_v0 = Entity(
        id="prj_v0",
        entity_type=EntityType.PROJECT,
        name="Personal Intelligence V0",
        confidence=ConfidenceScore.from_score(0.95),
    )
    await wm.save_entity(alice)
    await wm.save_entity(prj_v0)

    res = client.get("/api/v1/ui/overview")
    assert res.status_code == 200
    data = res.json()

    assert "active_projects_count" in data
    assert "active_relationships_count" in data
    assert "recent_state_changes" in data
    assert len(data["active_projects"]) == 1
    assert data["active_projects"][0]["name"] == "Personal Intelligence V0"


@pytest.mark.asyncio
async def test_ui_emails_and_email_by_id(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /api/v1/ui/emails and GET /api/v1/ui/emails/{id}."""
    client, wm, _ = client_and_services

    sc = StateChange(
        observation_id="msg_999",
        outcome=ReconciliationOutcome.NOVEL,
        description="Kickoff email received.",
    )
    await wm.record_state_change(sc)

    # Paginated list
    res = client.get("/api/v1/ui/emails?page=1&limit=10")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["limit"] == 10
    assert data["items"][0]["message_id"] == "msg_999"

    # Single email by ID
    res_single = client.get("/api/v1/ui/emails/msg_999")
    assert res_single.status_code == 200
    assert res_single.json()["message_id"] == "msg_999"

    # 404
    res_404 = client.get("/api/v1/ui/emails/non_existent_msg")
    assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_ui_entities_and_entity_by_id(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /api/v1/ui/entities and GET /api/v1/ui/entities/{id}."""
    client, wm, _ = client_and_services

    person = Entity(
        id="ent_p1",
        entity_type=EntityType.PERSON,
        name="Bob Jones",
        confidence=ConfidenceScore.from_score(0.9),
    )
    org = Entity(
        id="ent_o1",
        entity_type=EntityType.ORGANIZATION,
        name="Acme Corp",
        confidence=ConfidenceScore.from_score(0.9),
    )
    await wm.save_entity(person)
    await wm.save_entity(org)

    # All entities paginated
    res = client.get("/api/v1/ui/entities?page=1&limit=20")
    assert res.status_code == 200
    assert res.json()["total"] == 2

    # Filtered by entity_type
    res_filtered = client.get("/api/v1/ui/entities?entity_type=person")
    assert res_filtered.status_code == 200
    assert res_filtered.json()["total"] == 1
    assert res_filtered.json()["items"][0]["name"] == "Bob Jones"

    # Single entity
    res_single = client.get("/api/v1/ui/entities/ent_p1")
    assert res_single.status_code == 200
    assert res_single.json()["name"] == "Bob Jones"

    # 404
    assert client.get("/api/v1/ui/entities/missing").status_code == 404


@pytest.mark.asyncio
async def test_ui_entity_relationships_and_timeline(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /api/v1/ui/entities/{id}/relationships and timeline."""
    client, wm, _ = client_and_services

    alice = Entity(
        id="ent_a",
        entity_type=EntityType.PERSON,
        name="Alice",
        confidence=ConfidenceScore.from_score(0.9),
    )
    acme = Entity(
        id="ent_b",
        entity_type=EntityType.ORGANIZATION,
        name="Acme",
        confidence=ConfidenceScore.from_score(0.9),
    )
    await wm.save_entity(alice)
    await wm.save_entity(acme)

    rel = Relationship(
        id="rel_a_b",
        subject="ent_a",
        predicate=RelationshipType.WORKS_FOR,
        object="ent_b",
        confidence=ConfidenceScore.from_score(0.95),
    )
    await wm.save_relationship(rel)

    # Relationships
    res_rel = client.get("/api/v1/ui/entities/ent_a/relationships")
    assert res_rel.status_code == 200
    rels = res_rel.json()
    assert len(rels) == 1
    assert rels[0]["subject_name"] == "Alice"
    assert rels[0]["object_name"] == "Acme"
    assert rels[0]["status"] == "active"

    # Timeline
    res_tl = client.get("/api/v1/ui/entities/ent_a/timeline")
    assert res_tl.status_code == 200
    assert isinstance(res_tl.json(), list)


@pytest.mark.asyncio
async def test_ui_graph_endpoint(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /api/v1/ui/graph returns UIGraphDTO payload with nodes and edges."""
    client, wm, ev = client_and_services

    charlie = Entity(
        id="ent_c",
        entity_type=EntityType.PERSON,
        name="Charlie",
        confidence=ConfidenceScore.from_score(0.9),
    )
    prj_phx = Entity(
        id="prj_p",
        entity_type=EntityType.PROJECT,
        name="Project Phoenix",
        confidence=ConfidenceScore.from_score(0.9),
    )
    await wm.save_entity(charlie)
    await wm.save_entity(prj_phx)

    rel = Relationship(
        id="rel_c_p",
        subject="ent_c",
        predicate=RelationshipType.RESPONSIBLE_FOR,
        object="prj_p",
        confidence=ConfidenceScore.from_score(0.9),
    )
    await wm.save_relationship(rel)

    await ev.record_evidence(
        observation_id="obs_77",
        target_id="rel_c_p",
        target_type="relationship",
        content="Charlie leads Project Phoenix.",
    )

    res = client.get("/api/v1/ui/graph")
    assert res.status_code == 200
    graph = res.json()

    assert "nodes" in graph
    assert "edges" in graph
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1

    edge = graph["edges"][0]
    assert edge["id"] == "rel_c_p"
    assert edge["source"] == "ent_c"
    assert edge["target"] == "prj_p"
    assert edge["relationship_type"] == "responsible_for"
    assert edge["status"] == "active"
    assert edge["evidence_count"] == 1


@pytest.mark.asyncio
async def test_ui_timeline_evidence_decisions_and_changes(
    client_and_services: tuple[TestClient, WorldModelService, EvidenceService],
) -> None:
    """GET /api/v1/ui/timeline, /evidence/{id}, /decisions, /changes."""
    client, wm, ev = client_and_services

    sc = StateChange(
        observation_id="obs_505",
        outcome=ReconciliationOutcome.CONFIRM,
        description="Confirmed relationship.",
    )
    await wm.record_state_change(sc)

    dec = Decision(
        id="dec_10",
        name="DB Selection",
        question="DuckDB vs SQLite?",
        alternatives=["DuckDB", "SQLite"],
        context="Local performance requirement",
        decision="DuckDB",
        status=DecisionStatus.MADE,
        confidence=ConfidenceScore.from_score(0.95),
    )
    await wm.save_entity(dec)

    await ev.record_evidence(
        observation_id="obs_505",
        target_id="dec_10",
        target_type="entity",
        content="DuckDB selected for local persistence.",
    )

    # Timeline
    res_tl = client.get("/api/v1/ui/timeline")
    assert res_tl.status_code == 200
    assert len(res_tl.json()) >= 1

    # Evidence
    res_ev = client.get("/api/v1/ui/evidence/dec_10?page=1&limit=10")
    assert res_ev.status_code == 200
    ev_data = res_ev.json()
    assert ev_data["total"] == 1
    assert ev_data["items"][0]["target_id"] == "dec_10"
    assert "DuckDB" in ev_data["items"][0]["text_snippet"]

    # Decisions
    res_dec = client.get("/api/v1/ui/decisions")
    assert res_dec.status_code == 200
    assert len(res_dec.json()) == 1
    assert res_dec.json()[0]["name"] == "DB Selection"

    # Changes
    res_ch = client.get("/api/v1/ui/changes")
    assert res_ch.status_code == 200
    assert len(res_ch.json()) == 1
    assert res_ch.json()[0]["observation_id"] == "obs_505"
