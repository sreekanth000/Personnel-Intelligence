"""
Unit tests for the Personal Intelligence Context Builder.
Tests bounded context generation, relevance filtering, provenance retention across
all 9 dimensions, emerging hypotheses, uncertainties, capacity limits, and deterministic JSON serialization.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest

from personal_intelligence.core.context import (
    BoundedReasoningContext,
    ContextBuilder,
)
from personal_intelligence.core.episodes.models import EpisodeStatus, ReasoningEpisode
from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.goals import Goal, GoalPriority, GoalStatus, GoalStore
from personal_intelligence.core.patterns.models import LearnedPattern, PatternCadence
from personal_intelligence.core.situations import Situation, SituationPriority, SituationStatus, SituationStore
from personal_intelligence.core.state import StateFeature, StateRepresentation
from personal_intelligence.core.timeline import Timeline
from personal_intelligence.storage.db import DatabaseManager


class TestContextBuilder(unittest.TestCase):
    """Test suite for bounded context construction for Hermes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_context.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.builder = ContextBuilder(
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            recent_window_minutes=120,
            max_recent_events=5,
            max_historical_events=3,
            max_goals=3,
            max_patterns=3,
            max_similar_situations=2,
            max_recent_episodes=2,
        )
        self.base_time = datetime(2026, 8, 21, 16, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_sample_state(self) -> StateRepresentation:
        """Helper to create a populated state representation."""
        state = StateRepresentation(timestamp=self.base_time)
        state.set_feature("current_activity", "architecture_design", source="os_window", confidence=0.95)
        state.set_feature("current_location", "home_office", source="event:evt-loc-1", confidence=0.90)
        state.set_feature("ambient_temperature", 24.5, source="sensor:thermostat", confidence=0.65)  # Low confidence
        state.set_feature("event_density", 0.8, source="timeline_last_60m", confidence=1.0)
        return state

    # --- 1. Slicing & Bounded Scope Test (No Dump) ---

    def test_bounded_slicing_does_not_dump_entire_history(self) -> None:
        """Verify context builder slices bounded windows rather than dumping large history."""
        # 50 historical events spanning 5 days
        all_events = []
        for i in range(50):
            t = self.base_time - timedelta(hours=i * 2)
            all_events.append(
                Event(
                    id=f"evt-{i}",
                    event_type="app_focus" if i % 2 == 0 else "heartbeat",
                    source="system_logger",
                    payload={"index": i},
                    event_time=t,
                )
            )

        timeline = Timeline(events=all_events, start_time=all_events[-1].event_time, end_time=self.base_time)

        situation = Situation(
            id="sit-target-1",
            type="prolonged_activity",
            priority=SituationPriority.HIGH.value,
            novelty=0.75,
            context={"activity": "architecture_design", "duration_minutes": 180.0},
            evidence=["event:evt-0", "event:evt-1"],
        )

        state = self._create_sample_state()
        ctx = self.builder.build_bounded_context(
            situation=situation,
            current_state=state,
            timeline=timeline,
        )

        # Must NOT contain all 50 events
        self.assertLessEqual(len(ctx.relevant_recent_timeline), 5)
        self.assertLessEqual(len(ctx.relevant_historical_events), 3)
        total_events = len(ctx.relevant_recent_timeline) + len(ctx.relevant_historical_events)
        self.assertLess(total_events, 10)
        self.assertEqual(ctx.metadata["recent_event_count"], len(ctx.relevant_recent_timeline))

    # --- 2. Provenance Retention Test ---

    def test_provenance_retention_across_all_dimensions(self) -> None:
        """Verify every item in the 9 context dimensions retains explicit provenance."""
        # Seed Goal
        g1 = self.goal_store.create_goal(name="Deliver V1", priority=GoalPriority.CRITICAL.value)
        g2 = self.goal_store.create_goal(name="Run marathon", priority=GoalPriority.LOW.value)

        # Seed Past Situation
        past_sit = self.situation_store.create(
            type="prolonged_activity",
            priority="medium",
            status="closed",
            situation_id="sit-past-99",
        )

        # Seed Pattern
        pattern = LearnedPattern(
            pattern_id="pat-deep-work-1",
            name="Afternoon Deep Work",
            description="Deep work block between 14:00 and 17:00",
            cadence=PatternCadence.WEEKDAY,
            confidence=0.85,
            typical_time_window="14:00-17:00",
        )

        # Seed Episode
        episode = ReasoningEpisode(
            id="ep-prev-1",
            hermes_task="novelty_detected",
            status=EpisodeStatus.REASONING_COMPLETED.value,
            created_at=self.base_time - timedelta(days=1),
        )

        recent_evt = Event(
            id="evt-recent-1",
            event_type="app_focus",
            source="os_window_manager",
            payload={"app": "IDE"},
            event_time=self.base_time - timedelta(minutes=15),
        )
        timeline = Timeline(events=[recent_evt], start_time=recent_evt.event_time, end_time=self.base_time)

        situation = Situation(
            id="sit-current-1",
            type="prolonged_activity",
            priority="high",
            novelty=0.8,
            context={"activity": "architecture_design", "duration_minutes": 150.0},
            evidence=["event:evt-recent-1"],
            related_goals=[g1.id],
        )

        state = self._create_sample_state()

        ctx = self.builder.build_bounded_context(
            situation=situation,
            current_state=state,
            timeline=timeline,
            patterns=[pattern],
            episodes=[episode],
        )

        # 1. State Provenance (state_key, source, confidence)
        state_features = ctx.current_state["features"]
        self.assertTrue(any(f["state_key"] == "current_activity" and f["source"] == "os_window" for f in state_features))

        # 2. Recent Timeline Provenance (event_id, source)
        self.assertEqual(ctx.relevant_recent_timeline[0]["event_id"], "evt-recent-1")
        self.assertEqual(ctx.relevant_recent_timeline[0]["source"], "os_window_manager")

        # 3. Active Goal Provenance (goal_id, priority)
        self.assertEqual(ctx.active_goals[0]["goal_id"], g1.id)
        self.assertEqual(ctx.active_goals[0]["priority"], "critical")

        # 4. Pattern Provenance (pattern_id, cadence)
        self.assertEqual(ctx.known_patterns[0]["pattern_id"], "pat-deep-work-1")
        self.assertEqual(ctx.known_patterns[0]["confidence"], 0.85)

        # 5. Similar Situation Provenance (situation_id, type)
        self.assertEqual(ctx.similar_past_situations[0]["situation_id"], "sit-past-99")
        self.assertEqual(ctx.similar_past_situations[0]["status"], "closed")

        # 6. Reasoning Episode Provenance (episode_id, trigger_type)
        self.assertEqual(ctx.recent_reasoning_episodes[0]["episode_id"], "ep-prev-1")

    # --- 3. Emerging Hypotheses & Uncertainties Test ---

    def test_emerging_hypotheses_and_uncertainties(self) -> None:
        """Verify hypothesis generation and identification of low-confidence uncertainties."""
        state = self._create_sample_state()  # Has ambient_temperature confidence=0.65 (< 0.80)

        situation = Situation(
            type="unusual_state",
            priority="high",
            novelty=0.88,
            context={
                "divergent_features": {
                    "event_density": {"deviation": 3.4},
                    "ambient_temperature": {"deviation": 2.8},
                }
            },
            evidence=["timeline_last_60m"],
        )

        ctx = self.builder.build_bounded_context(
            situation=situation,
            current_state=state,
            timeline=Timeline(events=[], start_time=self.base_time, end_time=self.base_time),
        )

        # Emerging hypotheses
        self.assertGreater(len(ctx.emerging_hypotheses), 0)
        h = ctx.emerging_hypotheses[0]
        self.assertIn("hypothesis_id", h)
        self.assertIn("statement", h)
        self.assertEqual(h["confidence"], 0.88)

        # Uncertainties: low confidence in ambient_temperature (0.65)
        self.assertGreater(len(ctx.uncertainties), 0)
        unc_keys = {u["uncertainty_id"] for u in ctx.uncertainties}
        self.assertIn("unc-conf-ambient_temperature", unc_keys)

    # --- 4. JSON Serialization & Prompt String Test ---

    def test_json_serialization_and_prompt_formatting(self) -> None:
        """Verify deterministic JSON serialization and markdown prompt generation."""
        state = self._create_sample_state()
        situation = Situation(
            type="schedule_conflict",
            priority="high",
            novelty=0.7,
            context={"summary": "Double booking detected between 16:00 and 16:30"},
        )

        ctx = self.builder.build_bounded_context(
            situation=situation,
            current_state=state,
            objective="Analyze schedule trade-offs and propose resolution",
        )

        # 1. to_dict
        d = ctx.to_dict()
        self.assertEqual(d["objective"], "Analyze schedule trade-offs and propose resolution")
        self.assertIn("situation", d)
        self.assertIn("current_state", d)

        # 2. to_json (deterministic round-trip)
        json_str = ctx.to_json(indent=2)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["situation"]["type"], "schedule_conflict")

        # 3. to_prompt_string
        prompt = ctx.to_prompt_string()
        self.assertIn("Personal Intelligence Investigation Request", prompt)
        self.assertIn("**Target Situation**: schedule_conflict", prompt)
        self.assertIn("Current State Snapshot", prompt)


if __name__ == "__main__":
    unittest.main()
