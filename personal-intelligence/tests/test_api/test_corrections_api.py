import pytest
from fastapi.testclient import TestClient

import app.api.world as world_api
from app.config.settings import Settings
from app.domain.entities import Relationship
from app.domain.values import ConfidenceScore
from app.main import app as main_app
from app.persistence.duckdb_store import DuckDBStore
from app.persistence.kuzu_store import KuzuStore
from app.services.evidence import EvidenceService
from app.services.world_model import WorldModelService


@pytest.fixture
def client():
    return TestClient(main_app)


@pytest.fixture
async def mock_services(test_settings: Settings):
    duckdb = DuckDBStore(test_settings.duckdb_path)
    kuzu = KuzuStore(test_settings.kuzu_path)
    wm = WorldModelService(duckdb_store=duckdb, kuzu_store=kuzu)
    ev = EvidenceService(duckdb_store=duckdb)

    # Pre-populate some dummy relationships
    rel1 = Relationship(
        id="rel1",
        subject="Alice",
        predicate="works_for",
        object="Acme Corp",
        confidence=ConfidenceScore(score=0.5, category="medium"),
    )
    await wm.save_relationship(rel1)

    world_api.set_world_model_service(wm)
    world_api.set_evidence_service(ev)

    return wm, ev


@pytest.mark.asyncio
async def test_correction_confirm(client, mock_services):
    wm, _ev = mock_services
    resp = client.post(
        "/world/corrections/relationship/rel1",
        json={"action": "confirm", "reason": "Because I know it's true"},
    )

    print("Confirm Response:", resp.text)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"

    # Check wm
    all_rels = await wm.get_all_relationships()
    rel = all_rels[0]
    assert rel.id == "rel1"
    assert rel.confidence.score == 1.0
    assert rel.properties.get("status") == "CONFIRMED"


@pytest.mark.asyncio
async def test_correction_correct(client, mock_services):
    wm, _ev = mock_services
    resp = client.post(
        "/world/corrections/relationship/rel1",
        json={
            "action": "correct",
            "reason": "Actually she works for Global Corp",
            "new_subject": "Alice",
            "new_predicate": "works_for",
            "new_object": "Global Corp",
        },
    )

    print("Correct Response:", resp.text)
    assert resp.status_code == 200
    data = resp.json()
    new_id = data["new_target_id"]
    assert new_id != "rel1"

    all_rels = await wm.get_all_relationships()

    # Check old was outdated
    old_rel = next(r for r in all_rels if r.id == "rel1")
    assert old_rel.properties.get("status") == "HISTORICAL"
    assert not old_rel.validity.is_open_ended

    # Check new was added
    new_rel = next(r for r in all_rels if r.id == new_id)
    assert new_rel.object == "Global Corp"
    assert new_rel.confidence.score == 1.0


@pytest.mark.asyncio
async def test_correction_reject(client, mock_services):
    wm, _ev = mock_services
    resp = client.post(
        "/world/corrections/relationship/rel1",
        json={"action": "reject", "reason": "This is entirely false"},
    )

    print("Reject Response:", resp.text)
    assert resp.status_code == 200

    all_rels = await wm.get_all_relationships()
    rel = next(r for r in all_rels if r.id == "rel1")
    assert rel.properties.get("status") == "CONFLICT"
    assert not rel.validity.is_open_ended
