"""
Tests for Synthetic Personal Intelligence World Demo UI Endpoints:
- Personal World Model & Context Graph (/api/pi/context_graph)
- Hermes Reasoning Results with zero private CoT and 6 mandatory recommendation sections (/api/pi/hermes/reasoning_results)
- Intervention Decisions (/api/pi/interventions)
- Synthetic Chronological Live Replay stream & Next Event stepping (/api/pi/demo/replay/*)
"""

import os
import tempfile
import pytest
from datetime import datetime, timezone

from personal_intelligence.api.server import DashboardDataService
from personal_intelligence.core.episodes.models import RecommendationResult
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.storage.db import DatabaseManager


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_ui_endpoints.db")
    db = DatabaseManager(db_path=db_path)
    db.initialize_schema()
    yield db
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.fixture
def data_service(temp_db):
    service = DashboardDataService(
        db_manager=temp_db,
        is_demo_mode=True,
        auto_seed_sample_data=True,
    )
    return service


def test_context_graph_endpoint_payload(data_service):
    """Verifies Context Graph returns nodes, edges, entity type breakdown, and statistics."""
    payload = data_service.get_context_graph_payload()
    assert payload["status"] == "success"
    assert "nodes" in payload
    assert "edges" in payload
    assert "stats" in payload
    assert "entity_types" in payload
    assert "relation_types" in payload

    stats = payload["stats"]
    assert stats["total_nodes"] == len(payload["nodes"])
    assert stats["total_edges"] == len(payload["edges"])


def test_hermes_reasoning_results_endpoint_payload(data_service):
    """
    Verifies Hermes Reasoning Results:
    1. Strictly zero chain-of-thought tokens or private scratchpads exposed.
    2. Every recommendation contains the 6 required labeled sections:
       - WHAT HAPPENED
       - WHY IT MATTERS
       - WHAT I SUGGEST
       - EVIDENCE
       - UNCERTAINTY
       - DECISION
    """
    payload = data_service.get_hermes_reasoning_results_payload()
    assert payload["status"] == "success"
    assert "results" in payload
    results = payload["results"]
    assert len(results) > 0

    for r in results:
        # Mandatory 6 fields assertion
        assert "what_happened" in r and r["what_happened"]
        assert "why_it_matters" in r and r["why_it_matters"]
        assert "what_i_suggest" in r and r["what_i_suggest"]
        assert "evidence" in r and r["evidence"]
        assert "uncertainty" in r and r["uncertainty"]
        assert "decision" in r and r["decision"]

        # Strict Zero Chain-of-Thought (CoT) Invariant
        raw_keys = set(r.keys())
        assert "chain_of_thought" not in raw_keys
        assert "thought" not in raw_keys
        assert "cot" not in raw_keys
        assert "scratchpad" not in raw_keys
        assert "raw_prompt" not in raw_keys

        # Check content strings do not leak CoT markers
        combined_text = f"{r['what_happened']} {r['why_it_matters']} {r['what_i_suggest']} {r['uncertainty']}".lower()
        assert "<thought>" not in combined_text
        assert "</thought>" not in combined_text
        assert "internal reasoning:" not in combined_text


def test_intervention_decisions_endpoint_payload(data_service):
    """Verifies Intervention Decisions endpoint returns policy action records."""
    payload = data_service.get_intervention_decisions_payload()
    assert payload["status"] == "success"
    assert "decisions" in payload
    assert payload["count"] == len(payload["decisions"])
    assert len(payload["decisions"]) > 0

    for d in payload["decisions"]:
        assert "action" in d
        assert "reason" in d
        assert "user_context" in d
        assert "urgency" in d


def test_recommendations_endpoint_has_all_6_sections(data_service):
    """Verifies get_recommendations_payload returns all 6 required sections."""
    recs = data_service.get_recommendations_payload()
    assert len(recs) > 0
    for r in recs:
        assert "what_happened" in r and r["what_happened"]
        assert "why_it_matters" in r and r["why_it_matters"]
        assert "what_i_suggest" in r and r["what_i_suggest"]
        assert "evidence" in r and r["evidence"]
        assert "uncertainty" in r and r["uncertainty"]
        assert "decision" in r and r["decision"]


def test_synthetic_replay_lifecycle(data_service):
    """
    Verifies Chronological Synthetic Replay:
    - init_stream
    - step_next
    - get_status
    - reset_replay
    """
    # 1. Initialize stream
    status = data_service.replay_init(days=30, seed=42, reset_db=False)
    assert status["is_initialized"] is True
    assert status["total_events"] > 0
    assert status["current_index"] == 0
    total = status["total_events"]

    # 2. Step next event
    step1 = data_service.replay_next()
    assert step1["status"] == "stepped"
    assert step1["status_info"]["current_index"] == 1
    assert step1["status_info"]["has_more"] is True

    # 3. Step another event
    step2 = data_service.replay_next()
    assert step2["status"] == "stepped"
    assert step2["status_info"]["current_index"] == 2

    # 4. Check status
    cur_status = data_service.replay_status()
    assert cur_status["current_index"] == 2
    assert cur_status["progress_percentage"] > 0.0

    # 5. Reset replay
    reset_status = data_service.replay_reset()
    assert reset_status["current_index"] == 0
