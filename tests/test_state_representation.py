"""
Unit tests for the Personal State Representation layer and StateEngine.

Tests StateFeature, StateRepresentation container, deterministic feature extraction,
compact representations, and custom extractor extensibility.

Domain-Neutral Design Verification
-----------------------------------
All tests use generic event types that carry no domain-specific assumptions.
Biometric signals (e.g. sleep_deficit_hours) are verified only through the
register_extractor() path, confirming they are optional and not baked into built-ins.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.goals import GoalPriority, GoalStore
from personal_intelligence.core.state import (
    StateEngine,
    StateFeature,
    StateRepresentation,
)
from personal_intelligence.core.timeline import TimelineEngine
from personal_intelligence.storage.db import DatabaseManager


class TestPersonalStateRepresentation(unittest.TestCase):
    """Test suite for StateFeature, StateRepresentation, and StateEngine."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_state.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.event_store = EventStore(db_manager=self.db_manager)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.state_engine = StateEngine(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
        )
        self.base_time = datetime(2026, 8, 21, 14, 30, 0, tzinfo=timezone.utc)  # 14:30 UTC -> afternoon

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- 1. StateFeature Model Tests ---

    def test_state_feature_validation_and_serialization(self) -> None:
        """Verify StateFeature validation, timestamp handling, and serialization."""
        feat = StateFeature(
            name="recent_context_signal",
            value="architecture_review_doc",
            source="drive_observation",
            timestamp=self.base_time,
            confidence=0.92,
            metadata={"doc_type": "architecture"},
        )
        self.assertEqual(feat.name, "recent_context_signal")
        self.assertEqual(feat.value, "architecture_review_doc")
        self.assertEqual(feat.source, "drive_observation")
        self.assertEqual(feat.confidence, 0.92)

        # Dictionary serialization
        d = feat.to_dict()
        self.assertEqual(d["name"], "recent_context_signal")
        self.assertEqual(d["value"], "architecture_review_doc")
        self.assertEqual(d["confidence"], 0.92)
        self.assertIn("timestamp", d)

        # Deserialization
        restored = StateFeature.from_dict(d)
        self.assertEqual(restored.name, feat.name)
        self.assertEqual(restored.value, feat.value)
        self.assertEqual(restored.confidence, feat.confidence)

    def test_state_feature_invalid_inputs(self) -> None:
        """Verify rejection of invalid feature names, sources, or confidence scores."""
        with self.assertRaises(ValueError):
            StateFeature(name="", value="val", source="src")

        with self.assertRaises(ValueError):
            StateFeature(name="valid", value="val", source="")

        with self.assertRaises(ValueError):
            StateFeature(name="valid", value="val", source="src", confidence=1.5)

    # --- 2. StateRepresentation Container Tests ---

    def test_state_representation_container_operations(self) -> None:
        """Verify setting, getting, and compact formats of StateRepresentation."""
        rep = StateRepresentation(timestamp=self.base_time)
        self.assertEqual(len(rep), 0)

        rep.set_feature("active_signal_type", "document_review", source="drive_obs", confidence=0.95)
        rep.set_feature("event_density", 0.5, source="timeline", confidence=1.0)

        self.assertEqual(len(rep), 2)
        self.assertIn("active_signal_type", rep)
        self.assertEqual(rep.get_value("active_signal_type"), "document_review")
        self.assertEqual(rep.get_value("event_density"), 0.5)
        self.assertIsNone(rep.get_value("nonexistent_feature"))

        # Compact dict
        compact_dict = rep.to_compact_dict()
        self.assertEqual(compact_dict["values"]["active_signal_type"], "document_review")
        self.assertEqual(compact_dict["confidences"]["active_signal_type"], 0.95)

        # Compact text
        compact_text = rep.to_compact_text()
        self.assertIn("active_signal_type=document_review", compact_text)
        self.assertIn("event_density=0.5", compact_text)

    # --- 3. Deterministic StateEngine Feature Derivation ---

    def test_state_engine_empty_state(self) -> None:
        """Verify baseline state representation when no events exist in event log."""
        rep = self.state_engine.compute_current_state(reference_time=self.base_time)

        # 9 standard domain-neutral dimensions must be present
        self.assertIn("time_of_day", rep)
        self.assertIn("recent_context_signal", rep)
        self.assertIn("active_signal_type", rep)
        self.assertIn("event_density", rep)
        self.assertIn("recent_activity_duration", rep)
        self.assertIn("routine_deviation", rep)
        self.assertIn("goal_pressure", rep)
        self.assertIn("commitment_load", rep)
        self.assertIn("communication_activity", rep)

        # time_of_day at 14:30 is afternoon
        tod = rep.get_value("time_of_day")
        self.assertEqual(tod["bucket"], "afternoon")
        self.assertEqual(tod["hour"], 14.5)

        # Fallbacks when empty
        self.assertEqual(rep.get_value("recent_context_signal"), "unknown")
        self.assertEqual(rep.get_value("active_signal_type"), "idle")
        self.assertEqual(rep.get_value("event_density"), 0.0)
        self.assertEqual(rep.get_value("recent_activity_duration"), 0.0)
        self.assertEqual(rep.get_value("routine_deviation"), 0.0)
        self.assertEqual(rep.get_value("commitment_load"), 0)
        self.assertEqual(rep.get_value("communication_activity"), 0)

    def test_state_engine_with_generic_signal_events(self) -> None:
        """
        Verify state feature extraction from generic, domain-neutral events.

        Uses signal_observed (no GPS types) and activity_observed (no device-specific
        types) to confirm StateEngine works without domain coupling.
        """
        t0 = self.base_time - timedelta(minutes=45)
        t1 = self.base_time - timedelta(minutes=30)
        t2 = self.base_time - timedelta(minutes=15)
        t3 = self.base_time - timedelta(minutes=5)

        # Generic context signal (e.g., from calendar or document observation)
        self.event_store.append(
            Event(
                id="evt-ctx-1",
                event_type="signal_observed",
                source="calendar_obs",
                payload={"context": "architecture_review_prep"},
                event_time=t0,
                confidence=0.98,
            )
        )

        # Generic activity observations (continuous: code review)
        for i, t in enumerate([t1, t2, t3]):
            self.event_store.append(
                Event(
                    id=f"evt-act-{i}",
                    event_type="activity_observed",
                    source="productivity_obs",
                    payload={"activity": "code_review"},
                    event_time=t,
                    confidence=0.95,
                )
            )

        rep = self.state_engine.compute_current_state(reference_time=self.base_time)

        # recent_context_signal — scans for generic context keys across ALL events
        # The signal_observed event at t0 carries "context" key -> picked up as context
        # The activity_observed events at t1/t2/t3 carry "activity" key, which is NOT
        # in the context_keys set, so the extractor falls back to the earlier event.
        ctx_feat = rep.get_feature("recent_context_signal")
        self.assertEqual(ctx_feat.value, "architecture_review_prep")
        self.assertIn("event:", ctx_feat.source)

        # active_signal_type — not current_activity
        act_feat = rep.get_feature("active_signal_type")
        self.assertEqual(act_feat.value, "code_review")
        self.assertEqual(act_feat.confidence, 0.95)

        # Density: 4 events in last 60 minutes = 4 / 60.0 = 0.067
        density = rep.get_value("event_density")
        self.assertAlmostEqual(density, 4 / 60.0, places=2)

        # Recent activity duration: started at t1 (30 mins before base_time)
        dur = rep.get_value("recent_activity_duration")
        self.assertAlmostEqual(dur, 30.0, delta=1.0)

    def test_state_engine_goal_pressure(self) -> None:
        """Verify goal pressure calculation reflects active goals and priority weights."""
        self.goal_store.create_goal(name="Deliver V1", priority=GoalPriority.CRITICAL.value)
        self.goal_store.create_goal(name="Daily run", priority=GoalPriority.HIGH.value)
        self.goal_store.create_goal(name="Read paper", priority=GoalPriority.LOW.value)
        self.goal_store.create_goal(name="Old goal", priority="high", status="archived")

        rep = self.state_engine.compute_current_state(reference_time=self.base_time)
        gp = rep.get_value("goal_pressure")

        # Critical (3.0) + High (2.0) + Low (0.5) = 5.5
        self.assertEqual(gp["active_goal_count"], 3)
        self.assertEqual(gp["critical_goal_count"], 1)
        self.assertEqual(gp["pressure_score"], 5.5)

    def test_state_engine_commitment_load_from_calendar_and_document_signals(self) -> None:
        """
        Verify commitment_load counts commitment-type observations regardless of domain.

        Mixes calendar, email, and document commitment signals and verifies they
        are all counted by the generic commitment_load extractor.
        """
        t_base = self.base_time

        commitment_events = [
            ("evt-c1", "calendar_event",      "calendar",  {"subject": "Architecture Review"}),
            ("evt-c2", "upcoming_milestone",   "drive",     {"doc": "arch-v3.md"}),
            ("evt-c3", "email_received",       "gmail",     {"summary": "Please send final arch"}),
            ("evt-c4", "meeting_decision",     "meet",      {"summary": "Two changes to resolve"}),
        ]
        for i, (eid, etype, src, payload) in enumerate(commitment_events):
            self.event_store.append(
                Event(
                    id=eid,
                    event_type=etype,
                    source=src,
                    payload=payload,
                    event_time=t_base - timedelta(hours=i + 1),
                    confidence=1.0,
                )
            )

        # One non-commitment event — should not be counted
        self.event_store.append(
            Event(
                id="evt-noise",
                event_type="signal_observed",
                source="productivity_obs",
                payload={"status": "focused"},
                event_time=t_base - timedelta(minutes=10),
                confidence=0.9,
            )
        )

        rep = self.state_engine.compute_current_state(reference_time=t_base)
        commitment_load = rep.get_value("commitment_load")

        # 4 commitment-type events
        self.assertEqual(commitment_load, 4)
        meta = rep.get_feature("commitment_load").metadata
        self.assertEqual(meta["commitment_observation_count"], 4)
        self.assertEqual(meta["window_hours"], 24)

    def test_state_engine_communication_activity_from_email_and_meet_signals(self) -> None:
        """
        Verify communication_activity counts observations from communication sources only.

        Sources: gmail, meet, calendar qualify. productivity_obs does not.
        """
        t_base = self.base_time

        comm_events = [
            ("evt-g1", "email_received",    "gmail",    {}),
            ("evt-g2", "email_received",    "gmail",    {}),
            ("evt-m1", "meeting_decision",  "meet",     {}),
            ("evt-cal", "calendar_event",   "calendar", {}),
        ]
        for i, (eid, etype, src, payload) in enumerate(comm_events):
            self.event_store.append(
                Event(
                    id=eid,
                    event_type=etype,
                    source=src,
                    payload=payload,
                    event_time=t_base - timedelta(hours=i + 1),
                    confidence=1.0,
                )
            )

        # Non-communication source — should not be counted
        self.event_store.append(
            Event(
                id="evt-prod",
                event_type="task_created",
                source="productivity_obs",
                payload={},
                event_time=t_base - timedelta(minutes=30),
                confidence=0.9,
            )
        )

        rep = self.state_engine.compute_current_state(reference_time=t_base)
        comm_activity = rep.get_value("communication_activity")

        # Only the 4 communication-sourced events count
        self.assertEqual(comm_activity, 4)
        meta = rep.get_feature("communication_activity").metadata
        self.assertEqual(meta["communication_observation_count"], 4)

    def test_state_engine_cross_domain_signals_coexist_in_one_state(self) -> None:
        """
        Verify that signals from different domains coexist in a single StateRepresentation.

        Introduces productivity, calendar, document, and communication signals
        simultaneously and verifies the state representation captures all dimensions
        without any domain overwriting another.
        """
        t_base = self.base_time

        mixed_events = [
            # Communication domain
            ("e-com-1", "email_received",    "gmail",           {"topic": "architecture_review"}),
            ("e-com-2", "meeting_decision",  "meet",            {"status": "two_items_unresolved"}),
            # Calendar domain
            ("e-cal-1", "calendar_event",    "calendar",        {"context": "Architecture Review - Friday"}),
            # Document domain
            ("e-doc-1", "document_changed",  "drive",           {"project": "arch-v3", "status": "recently_modified"}),
            # Productivity domain (generic)
            ("e-prd-1", "activity_observed", "productivity_obs", {"activity": "deep_work", "topic": "architecture"}),
        ]
        for i, (eid, etype, src, payload) in enumerate(mixed_events):
            self.event_store.append(
                Event(
                    id=eid,
                    event_type=etype,
                    source=src,
                    payload=payload,
                    event_time=t_base - timedelta(hours=i),
                    confidence=0.95,
                )
            )

        rep = self.state_engine.compute_current_state(reference_time=t_base)

        # All 9 built-in dimensions are present regardless of domain mix
        for dim in ("time_of_day", "recent_context_signal", "active_signal_type",
                    "event_density", "recent_activity_duration", "routine_deviation",
                    "goal_pressure", "commitment_load", "communication_activity"):
            self.assertIn(dim, rep, f"Missing dimension: {dim}")

        # 3 commitment-type events (email_received, calendar_event, document_changed)
        self.assertGreaterEqual(rep.get_value("commitment_load"), 3)

        # 3 communication-source events (gmail, meet, calendar)
        self.assertGreaterEqual(rep.get_value("communication_activity"), 3)

        # State is serializable across all domains
        d = rep.to_dict()
        self.assertIn("features", d)
        self.assertEqual(d["feature_count"], len(rep))

    def test_state_engine_custom_extractor_for_optional_biometric_signals(self) -> None:
        """
        Verify biometric signals are supported ONLY through register_extractor().

        Biometric signals are NOT built into the StateEngine — they are opt-in.
        This test verifies the extensibility path works correctly.
        """
        def sleep_quality_extractor(timeline, goal_store, ref_dt) -> StateFeature:
            """Example optional biometric extractor — not a built-in dimension."""
            return StateFeature(
                name="sleep_quality_score",
                value=0.72,
                source="wearable_device",
                timestamp=ref_dt,
                confidence=0.85,
                metadata={"hours_slept": 6.5, "baseline_hours": 8.0, "domain": "biometric"},
            )

        self.state_engine.register_extractor("sleep_quality_score", sleep_quality_extractor)
        rep = self.state_engine.compute_current_state(reference_time=self.base_time)

        # Biometric signal present via register_extractor — not a built-in
        self.assertIn("sleep_quality_score", rep)
        feat = rep.get_feature("sleep_quality_score")
        self.assertEqual(feat.value, 0.72)
        self.assertEqual(feat.source, "wearable_device")
        self.assertEqual(feat.confidence, 0.85)
        self.assertEqual(feat.metadata["domain"], "biometric")

        # The 9 built-in dimensions are still all present
        self.assertIn("commitment_load", rep)
        self.assertIn("communication_activity", rep)
        self.assertEqual(len(rep), 10)  # 9 built-ins + 1 biometric custom


if __name__ == "__main__":
    unittest.main()

