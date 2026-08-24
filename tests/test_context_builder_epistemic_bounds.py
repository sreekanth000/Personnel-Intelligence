"""
Dedicated Test Suite for Bounded ContextBuilder Epistemic Contracts.

Verifies:
1. Context is bounded (500–2,000 tokens configurable budget, no whole-PWM or full-inbox dumping).
2. Irrelevant data is excluded (unrelated historical logs, irrelevant completed goals omitted).
3. Provenance is preserved (every observed fact and timeline event has provenance coordinates).
4. Inference is not promoted to fact (strict separation of OBSERVED_FACTS and INFERENCES).
5. Assessment-change conditions are included (ASSESSMENT_CHANGE_CONDITIONS section present).
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from typing import Any, Dict, List

from personal_intelligence.core.context import (
    BoundedReasoningContext,
    ContextBuilder,
    estimate_token_count,
)
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.patterns.models import Pattern, PatternStatus, PatternType
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.storage.db import DatabaseManager


class TestContextBuilderEpistemicBounds(unittest.TestCase):
    """Test suite proving bounded epistemic guarantees of ContextBuilder."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_epistemic_context.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.base_time = datetime(2026, 8, 23, 10, 0, 0, tzinfo=timezone.utc)

        self.builder = ContextBuilder(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            recent_window_minutes=120,
            max_recent_events=10,
            max_historical_events=5,
            max_goals=4,
            max_patterns=4,
            max_facts=10,
            max_tokens=2000,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Context is Bounded
    # -------------------------------------------------------------------------

    def test_context_is_bounded(self) -> None:
        """
        Verify that even with dozens of timeline events, state features, goals, and patterns,
        the assembled reasoning context is strictly bounded within the configured token budget (500–2,000 tokens).
        """
        # Create situation
        sit = self.situation_store.create_situation(
            situation_type="schedule_conflict",
            priority=SituationPriority.HIGH,
            context={"summary": "Overlapping executive roadmap review and client delivery sync"},
            evidence=["event:evt-meeting-1", "event:evt-meeting-2"],
        )

        # Create populated state
        state = StateRepresentation(timestamp=self.base_time)
        state.set_feature("current_activity", "meeting", source="google_calendar", confidence=0.98)
        state.set_feature("workload_index", 3.4, source="calendar_density", confidence=0.92)
        state.set_feature("sleep_duration_minutes", 340.0, source="biometrics_sleep", confidence=0.95)

        # Create 50 events in timeline (simulating heavy background history)
        timeline_events = []
        for i in range(50):
            evt = Event(
                id=f"evt-bg-{i}",
                event_type="app_log" if i % 2 == 0 else "status_update",
                source="system_monitor",
                event_time=self.base_time - timedelta(hours=i),
                payload={"metric": i, "detail": f"Background telemetry event {i}"},
            )
            timeline_events.append(evt)

        # Add relevant conflicting events
        evt1 = Event(
            id="evt-meeting-1",
            event_type="calendar_meeting",
            source="google_calendar",
            event_time=self.base_time + timedelta(minutes=15),
            payload={"summary": "Executive Roadmap Review", "attendees": 8},
        )
        evt2 = Event(
            id="evt-meeting-2",
            event_type="calendar_meeting",
            source="google_calendar",
            event_time=self.base_time + timedelta(minutes=15),
            payload={"summary": "Client Delivery Sync", "attendees": 4},
        )
        timeline_events.extend([evt1, evt2])
        timeline = Timeline(events=timeline_events)

        # Build bounded context
        ctx = self.builder.build_bounded_context(
            situation=sit,
            current_state=state,
            timeline=timeline,
        )

        prompt_str = ctx.to_prompt_string()
        token_estimate = estimate_token_count(prompt_str)

        # Check bounds: must be bounded and <= max_tokens (2000)
        self.assertLessEqual(token_estimate, 2000)
        self.assertGreaterEqual(token_estimate, 50)

        # Verify not dumping all 50 background events
        total_timeline_in_context = len(ctx.relevant_recent_timeline) + len(ctx.relevant_historical_events)
        self.assertLessEqual(total_timeline_in_context, 15)

    # -------------------------------------------------------------------------
    # 2. Irrelevant Data is Excluded
    # -------------------------------------------------------------------------

    def test_irrelevant_data_is_excluded(self) -> None:
        """
        Verify that unrelated background events (e.g. random sensor logs from 5 days ago)
        and irrelevant completed goals are excluded from the bounded reasoning context.
        """
        sit = self.situation_store.create_situation(
            situation_type="goal_risk",
            priority=SituationPriority.HIGH,
            related_goals=["goal-infra-migration"],
            context={"summary": "Database migration deadline at risk"},
            evidence=["event:evt-migration-blocker"],
        )

        state = StateRepresentation(timestamp=self.base_time)
        state.set_feature("current_activity", "coding", source="vscode", confidence=0.90)

        # Create active relevant goal and irrelevant completed goal
        g_rel = self.goal_store.create_goal(
            name="Database Migration",
            description="Complete AWS to GCP Cloud SQL migration",
            priority=GoalPriority.HIGH,
        )
        g_unrel_done = self.goal_store.create_goal(
            name="Old Completed Project",
            description="2025 archival task",
            priority=GoalPriority.LOW,
            status=GoalStatus.COMPLETED,
        )

        # Relevant event
        rel_evt = Event(
            id="evt-migration-blocker",
            event_type="issue_blocker",
            source="jira",
            event_time=self.base_time - timedelta(minutes=30),
            payload={"summary": "Schema lock timeout on migration script"},
        )
        # Irrelevant distant event
        irrel_evt = Event(
            id="evt-random-sensor-99",
            event_type="thermostat_log",
            source="iot_home",
            event_time=self.base_time - timedelta(days=9),
            payload={"temp_f": 72.1},
        )
        timeline = Timeline(events=[rel_evt, irrel_evt])

        ctx = self.builder.build_bounded_context(
            situation=sit,
            current_state=state,
            timeline=timeline,
            goals=[g_rel, g_unrel_done],
        )

        # Verify relevant event is present
        relevant_ids = [e["event_id"] for e in ctx.relevant_recent_timeline + ctx.relevant_historical_events]
        self.assertIn("evt-migration-blocker", relevant_ids)

        # Verify irrelevant distant sensor event is NOT included
        self.assertNotIn("evt-random-sensor-99", relevant_ids)

        # Verify irrelevant completed goal is NOT included in active goals
        active_goal_names = [g["name"] for g in ctx.active_goals]
        self.assertIn("Database Migration", active_goal_names)
        self.assertNotIn("Old Completed Project", active_goal_names)

    # -------------------------------------------------------------------------
    # 3. Provenance is Preserved
    # -------------------------------------------------------------------------

    def test_provenance_is_preserved(self) -> None:
        """
        Verify every observed fact and timeline event retains its exact origin provenance
        (source, event_id/state_key, timestamp, confidence).
        """
        sit = self.situation_store.create_situation(
            situation_type="unusual_state",
            priority=SituationPriority.MEDIUM,
            evidence=["finding:Sleep duration is 2.5 sigma below baseline"],
        )

        state = StateRepresentation(timestamp=self.base_time)
        state.set_feature("hrv_rmssd", 28.0, source="biometrics_whoop", timestamp=self.base_time - timedelta(hours=2), confidence=0.96)
        state.set_feature("active_window", "Terminal", source="os_window_watcher", timestamp=self.base_time, confidence=0.99)

        ctx = self.builder.build_bounded_context(
            situation=sit,
            current_state=state,
        )

        # Every observed fact must have non-empty provenance
        self.assertGreater(len(ctx.observed_facts), 0)
        for fact in ctx.observed_facts:
            self.assertIn("provenance", fact)
            self.assertTrue(bool(fact["provenance"]))
            self.assertIn("source", fact)
            self.assertIn("timestamp", fact)

        # In prompt string, provenance headers must appear
        prompt_str = ctx.to_prompt_string()
        self.assertIn("[PROVENANCE:", prompt_str)
        self.assertIn("biometrics_whoop", prompt_str)

    # -------------------------------------------------------------------------
    # 4. Inference is Not Promoted to Fact
    # -------------------------------------------------------------------------

    def test_inference_is_not_promoted_to_fact(self) -> None:
        """
        Verify that analytical inferences remain strictly categorized under INFERENCES
        and are NEVER placed into OBSERVED_FACTS.
        """
        sit = self.situation_store.create_situation(
            situation_type="cognitive_physical_strain_risk",
            priority=SituationPriority.HIGH,
        )

        state = StateRepresentation(timestamp=self.base_time)
        state.set_feature("sleep_duration_minutes", 240.0, source="oura_ring", confidence=0.95)
        state.set_feature("calendar_meeting_count", 6, source="google_calendar", confidence=0.99)

        ctx = self.builder.build_bounded_context(
            situation=sit,
            current_state=state,
        )

        prompt_str = ctx.to_prompt_string()

        # In prompt, INFERENCES and OBSERVED_FACTS must be distinct sections
        self.assertIn("=== OBSERVED_FACTS ===", prompt_str)
        self.assertIn("=== INFERENCES ===", prompt_str)

        # Inferences must have origin tags
        for inf in ctx.inferences:
            self.assertIn("origin", inf)
            self.assertIn("statement", inf)

        # Ensure no observed fact is labelled as an inference
        for fact in ctx.observed_facts:
            self.assertNotIn("[INFERENCE:", fact.get("statement", ""))

    # -------------------------------------------------------------------------
    # 5. Assessment-Change Conditions are Included
    # -------------------------------------------------------------------------

    def test_assessment_change_conditions_included(self) -> None:
        """
        Verify that concrete, explicit conditions that would alter or resolve the assessment
        are populated in the context and serialized in the epistemic prompt.
        """
        sit = self.situation_store.create_situation(
            situation_type="schedule_conflict",
            priority=SituationPriority.HIGH,
            context={"summary": "Double booked client meeting and board prep"},
        )

        state = StateRepresentation(timestamp=self.base_time)
        state.set_feature("current_activity", "focus_work", source="os_watcher", confidence=0.90)

        ctx = self.builder.build_bounded_context(
            situation=sit,
            current_state=state,
        )

        # Verify assessment_change_conditions is non-empty
        self.assertGreater(len(ctx.assessment_change_conditions), 0)

        # Verify conditions have structured condition and effect fields
        first_cond = ctx.assessment_change_conditions[0]
        self.assertIn("condition", first_cond)
        self.assertIn("effect", first_cond)
        self.assertIn("rescheduled", first_cond["condition"].lower())

        # Verify presence in prompt string
        prompt_str = ctx.to_prompt_string()
        self.assertIn("=== ASSESSMENT_CHANGE_CONDITIONS ===", prompt_str)
        self.assertIn("* [CONDITION]", prompt_str)


if __name__ == "__main__":
    unittest.main()
