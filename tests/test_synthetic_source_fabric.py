"""
Tests for Synthetic Source Fabric in Personal Intelligence.
Verifies determinism, category coverage, schema compliance, timeline range, and direct PI pipeline ingestion.
"""

from datetime import datetime, timezone
import pytest

from personal_intelligence.api.interface import PersonalIntelligenceCapabilityInterface
from personal_intelligence.demo.synthetic_fabric import SyntheticSourceFabric
from personal_intelligence.demo.synthetic_world import SyntheticWorldDemo
from personal_intelligence.storage.db import DatabaseManager


def test_fabric_determinism():
    """Verifies that SyntheticSourceFabric produces identical output with the same seed."""
    fabric1 = SyntheticSourceFabric(seed=42, days=30)
    obs1 = fabric1.generate_observations()

    fabric2 = SyntheticSourceFabric(seed=42, days=30)
    obs2 = fabric2.generate_observations()

    assert len(obs1) == len(obs2)
    for e1, e2 in zip(obs1, obs2):
        assert e1.id == e2.id
        assert e1.event_time == e2.event_time
        assert e1.source == e2.source
        assert e1.source_id == e2.source_id
        assert e1.event_type == e2.event_type
        assert e1.entity_refs == e2.entity_refs
        assert e1.payload == e2.payload
        assert e1.provenance == e2.provenance

    # Different seed produces different events
    fabric_diff = SyntheticSourceFabric(seed=999, days=30)
    obs_diff = fabric_diff.generate_observations()
    assert obs1[0].id != obs_diff[0].id


def test_fabric_category_coverage():
    """Verifies that all 8 categories are represented in generated observation specs."""
    fabric = SyntheticSourceFabric(seed=42, days=45)
    events = fabric.generate_observations()

    found_categories = set()
    for evt in events:
        cat = evt.payload.get("category")
        if cat:
            found_categories.add(cat)

    expected_categories = set(SyntheticSourceFabric.CATEGORIES)
    assert found_categories == expected_categories, f"Missing categories: {expected_categories - found_categories}"


def test_fabric_observation_schema():
    """Verifies every observation satisfies all required schema attributes."""
    fabric = SyntheticSourceFabric(seed=123, days=30)
    events = fabric.generate_observations()

    assert len(events) >= 100, f"Expected at least 100 events across 30 days, got {len(events)}"

    for evt in events:
        # 1. event_id / id
        assert evt.id and isinstance(evt.id, str) and evt.id.startswith("evt-")
        # 2. timestamp / event_time (timezone-aware)
        assert evt.event_time and isinstance(evt.event_time, datetime)
        assert evt.event_time.tzinfo is not None
        # 3. source
        assert evt.source and isinstance(evt.source, str)
        # 4. source_event_id / source_id
        assert evt.source_id and isinstance(evt.source_id, str)
        # 5. event_type / observation_type
        assert evt.event_type and isinstance(evt.event_type, str)
        # 6. entities / entity_refs
        assert isinstance(evt.entity_refs, list) and len(evt.entity_refs) > 0
        # 7. payload / structured_data
        assert isinstance(evt.payload, dict) and "summary" in evt.payload and "evidence" in evt.payload
        # 8. provenance
        assert isinstance(evt.provenance, dict) and "tool" in evt.provenance and "source_system" in evt.provenance


def test_fabric_timeline_range_and_ordering():
    """Verifies observations span requested days and are strictly chronologically ordered."""
    days = 60
    fabric = SyntheticSourceFabric(seed=42, days=days)
    events = fabric.generate_observations()

    # Chronological order check
    for i in range(len(events) - 1):
        assert events[i].event_time <= events[i + 1].event_time

    # Timeline span check
    time_span = events[-1].event_time - events[0].event_time
    assert time_span.days >= days - 1, f"Expected span of ~{days} days, got {time_span.days} days"


def test_fabric_pi_ingestion_and_pipeline_execution():
    """Verifies direct ingestion into PI PersonalWorldModel, ContextGraph, and evaluation loop execution."""
    db_manager = DatabaseManager(db_path=":memory:")
    demo = SyntheticWorldDemo(db_manager=db_manager)

    result = demo.run_fabric_demo(seed=42, days=30, events_per_day=4)

    assert result.observations_ingested >= 100
    assert result.context_graph_nodes >= 10
    assert result.context_graph_edges >= 10
    assert result.episodes_recorded >= 1
    assert result.active_situations_count >= 0

    assert result.episodes_recorded >= 1
