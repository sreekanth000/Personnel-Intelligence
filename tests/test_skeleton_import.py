"""
Basic validation tests for Personal Intelligence package skeleton and models.
"""

import os
import tempfile
import unittest
from datetime import datetime

from personal_intelligence.core.events import (
    Event,
    EventBatch,
    EventBuffer,
)
from personal_intelligence.core.state import (
    EntityState,
    UserState,
    StateSnapshot,
)
from personal_intelligence.core.timeline import (
    TimelineEntry,
    TimelineEntryType,
    TimelineInterval,
)
from personal_intelligence.core.goals import (
    Goal,
    GoalStatus,
    GoalPriority,
)
from personal_intelligence.core.situations import (
    Situation,
    SituationPriority,
    SituationStatus,
)
from personal_intelligence.core.novelty import (
    NoveltyScore,
    NoveltyType,
)
from personal_intelligence.core.context import (
    ContextBuilder,
    HermesInvestigationContext,
)
from personal_intelligence.core.patterns import (
    LearnedPattern,
    PatternCadence,
)
from personal_intelligence.core.policy import (
    InterventionDecision,
    InterruptionBudget,
    DeliveryMode,
    UserFeedback,
)
from personal_intelligence.core.episodes import (
    ReasoningEpisode,
    HermesExecutionRecord,
    EpisodeStatus,
)
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.hermes_bridge.client import (
    HermesClient,
    HermesExecutionMode,
    HermesInvocationRequest,
)
from personal_intelligence.hermes_bridge.plugin import register


class TestPersonalIntelligenceSkeleton(unittest.TestCase):
    """Test suite validating structure, typing, schemas, and database initialization."""

    def test_event_instantiation_and_buffer(self) -> None:
        """Verify arbitrary event creation and buffering."""
        from datetime import timezone
        event = Event(
            event_type="device_location_ping",
            source="phone_gps",
            payload={"latitude": 37.7749, "longitude": -122.4194, "speed": 0},
            event_time=datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc),
            subject_id="device_primary",
        )
        self.assertIsNotNone(event.id)
        self.assertEqual(event.source, "phone_gps")

        buffer = EventBuffer(capacity=10)
        buffer.push(event)
        self.assertEqual(buffer.size(), 1)
        drained = buffer.drain()
        self.assertEqual(len(drained), 1)
        self.assertEqual(buffer.size(), 0)

    def test_state_and_timeline_models(self) -> None:
        """Verify state snapshots and timeline models."""
        user_state = UserState(
            current_activity="deep_work",
            focus_mode=True,
            signal_context={"load": "high"},
        )
        snapshot = StateSnapshot(user_state=user_state)
        self.assertTrue(snapshot.user_state.focus_mode)

        timeline_entry = TimelineEntry(
            entry_type=TimelineEntryType.EVENT,
            timestamp=datetime.utcnow(),
            title="Started Deep Work Block",
        )
        self.assertIsNotNone(timeline_entry.entry_id)

    def test_goals_and_situations(self) -> None:
        """Verify goal models and cross-domain situation frames."""
        goal = Goal(
            name="Complete Product Architecture",
            description="Finalize design specifications for personal intelligence",
            priority=GoalPriority.HIGH,
            status=GoalStatus.ACTIVE,
        )
        self.assertEqual(goal.priority, "high")

        situation = Situation(
            type="conflicting_commitments",
            context={"summary": "User scheduled deep work overlaps with unexpected sync"},
            priority=SituationPriority.HIGH,
            status=SituationStatus.OPEN,
            related_goals=[goal.id],
            novelty=0.75,
        )
        self.assertEqual(situation.type, "conflicting_commitments")
        self.assertEqual(situation.priority, "high")

    def test_context_builder(self) -> None:
        """Verify prompt and context construction for Hermes."""
        builder = ContextBuilder()
        goal = Goal(
            name="Health Regimen",
            description="Maintain consistent 8 hour sleep schedule",
            priority=GoalPriority.MEDIUM,
        )
        situation = Situation(
            type="late_schedule_shift",
            priority=SituationPriority.MEDIUM,
            context={"summary": "Upcoming evening events risk disrupting sleep window"},
        )
        ctx = builder.build_investigation_context(
            objective="Evaluate whether evening event can be rescheduled",
            situation=situation,
            goals=[goal],
            constraints=["Do not notify user if in focus mode"],
        )
        prompt = builder.format_prompt_for_hermes(ctx)
        self.assertIn("Personal Intelligence Investigation Request", prompt)
        self.assertIn("late_schedule_shift", prompt)
        self.assertIn("Health Regimen", prompt)

    def test_database_initialization(self) -> None:
        """Verify local SQLite schema creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "test_pi.db")
            db_mgr = DatabaseManager(db_path=db_file)
            db_mgr.initialize_schema()

            conn = db_mgr.get_connection()
            try:
                cursor = conn.cursor()
                tables = cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
                table_names = {row["name"] for row in tables}

                expected_tables = {
                    "event_log",
                    "timeline_entries",
                    "state_snapshots",
                    "goals",
                    "situations",
                    "novelty_scores",
                    "learned_patterns",
                    "intervention_decisions",
                    "reasoning_episodes",
                }
                for t in expected_tables:
                    self.assertIn(t, table_names)
            finally:
                conn.close()

    def test_hermes_bridge_client_and_plugin(self) -> None:
        """Verify Hermes client bridge and plugin registration mock."""
        client = HermesClient(mode=HermesExecutionMode.CLI)
        req = HermesInvocationRequest(prompt="Analyze situational risks")
        res = client.invoke_reasoning(req)
        self.assertTrue(res.success)

        # Mock Hermes context for plugin registration
        class MockHermesContext:
            def __init__(self):
                self.tools = {}
                self.hooks = {}

            def register_tool(self, name, schema, handler):
                self.tools[name] = {"schema": schema, "handler": handler}

            def register_hook(self, name, handler):
                self.hooks[name] = handler

        mock_ctx = MockHermesContext()
        register(mock_ctx)
        self.assertIn("get_personal_timeline", mock_ctx.tools)
        self.assertIn("get_current_personal_state", mock_ctx.tools)
        self.assertIn("get_active_goals", mock_ctx.tools)
        self.assertIn("get_situation", mock_ctx.tools)
        self.assertIn("get_reasoning_context", mock_ctx.tools)
        self.assertIn("store_reasoning_episode", mock_ctx.tools)
        self.assertIn("record_observation", mock_ctx.tools)
        self.assertIn("get_personal_world_model", mock_ctx.tools)
        self.assertIn("evaluate_candidate_situations", mock_ctx.tools)
        self.assertIn("pre_tool_call", mock_ctx.hooks)
        self.assertIn("post_tool_call", mock_ctx.hooks)


if __name__ == "__main__":
    unittest.main()
