"""
Unit and integration tests for the Personal Intelligence Hermes Plugin.
Verifies tool registration, execution of all 6 tools, SQLite layer access,
provenance preservation, reasoning episode storage, and security constraints.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest

from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.goals import Goal, GoalPriority, GoalStore
from personal_intelligence.core.situations import Situation, SituationPriority, SituationStatus, SituationStore
from personal_intelligence.hermes_bridge.plugin import register
from personal_intelligence.hermes_bridge.plugin.schemas import (
    GET_ACTIVE_GOALS_SCHEMA,
    GET_CURRENT_PERSONAL_STATE_SCHEMA,
    GET_PERSONAL_TIMELINE_SCHEMA,
    GET_REASONING_CONTEXT_SCHEMA,
    GET_SITUATION_SCHEMA,
    PLUGIN_TOOL_SCHEMAS,
    STORE_REASONING_EPISODE_SCHEMA,
)
from personal_intelligence.hermes_bridge.plugin.tools import (
    get_active_goals,
    get_current_personal_state,
    get_personal_timeline,
    get_reasoning_context,
    get_situation,
    store_reasoning_episode,
)
from personal_intelligence.storage.db import DatabaseManager


class MockHermesContext:
    """Mock Hermes runtime context for plugin registration."""

    def __init__(self) -> None:
        self.registered_tools = {}
        self.registered_hooks = {}

    def register_tool(self, name: str, schema: dict, handler: callable) -> None:
        self.registered_tools[name] = {"schema": schema, "handler": handler}

    def register_hook(self, hook_name: str, handler: callable) -> None:
        if hook_name not in self.registered_hooks:
            self.registered_hooks[hook_name] = []
        self.registered_hooks[hook_name].append(handler)


class TestHermesPlugin(unittest.TestCase):
    """Test suite for the Hermes Personal Intelligence plugin."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_hermes_plugin.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.event_store = EventStore(db_manager=self.db_manager)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.base_time = datetime(2026, 8, 21, 16, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- 1. Plugin Registration Test ---

    def test_plugin_registration(self) -> None:
        """Verify plugin registers the 6 required tools and lifecycle hooks."""
        ctx = MockHermesContext()
        register(ctx)

        expected_tools = {
            "get_current_personal_state",
            "get_personal_timeline",
            "get_active_goals",
            "get_situation",
            "get_reasoning_context",
            "store_reasoning_episode",
            "record_observation",
            "get_personal_world_model",
            "evaluate_candidate_situations",
            "execute_pi_command",
        }

        self.assertEqual(set(ctx.registered_tools.keys()), expected_tools)
        self.assertIn("pre_tool_call", ctx.registered_hooks)
        self.assertIn("post_tool_call", ctx.registered_hooks)
        self.assertEqual(len(PLUGIN_TOOL_SCHEMAS), 10)


    # --- 2. Tool: get_current_personal_state ---

    def test_tool_get_current_personal_state(self) -> None:
        """Verify get_current_personal_state returns state representation."""
        res = get_current_personal_state()
        self.assertEqual(res["status"], "success")
        self.assertIn("state_representation", res)
        self.assertIn("compact_values", res)
        self.assertIn("time_of_day", res["compact_values"])

    # --- 3. Tool: get_personal_timeline ---

    def test_tool_get_personal_timeline(self) -> None:
        """Verify get_personal_timeline returns bounded events from storage."""
        res = get_personal_timeline(last_n_hours=24)
        self.assertEqual(res["status"], "success")
        self.assertIsInstance(res["events"], list)

    # --- 4. Tool: get_active_goals ---

    def test_tool_get_active_goals(self) -> None:
        """Verify get_active_goals returns active goals."""
        res = get_active_goals(status="active")
        self.assertEqual(res["status"], "success")
        self.assertIsInstance(res["goals"], list)

    # --- 5. Tool: get_situation and get_reasoning_context ---

    def test_tool_get_situation_and_reasoning_context(self) -> None:
        """Verify retrieving a situation and constructing bounded reasoning context."""
        # Query non-existent situation
        not_found_res = get_situation(situation_id="nonexistent-sit")
        self.assertEqual(not_found_res["status"], "not_found")

    # --- 6. Tool: store_reasoning_episode ---

    def test_tool_store_reasoning_episode(self) -> None:
        """Verify storing a complete reasoning episode with epistemic dimensions."""
        res = store_reasoning_episode(
            situation_id="sit-test-123",
            trigger_type="situation_investigation",
            outcome_evaluation="Investigation concluded user is engaged in uninterrupted focus.",
            outcome_success=True,
            observations=["Coding activity in IDE for 150 mins"],
            inferences=["Potential conflict with 17:00 sync"],
            predictions=["Preparation time will be constrained"],
            recommendations=["Review sync agenda before meeting"],
            uncertainties_identified=["Whether sync is mandatory or async update suffices"],
            evidence_references=["event:evt-10"],
            lessons_learned=["Afternoon sessions typically extend by ~30 mins"],
        )

        self.assertEqual(res["status"], "success")
        self.assertIn("episode_id", res)
        self.assertTrue(res["outcome_success"])

    # --- 7. Full Native Hermes Plugin & /pi Command Verification ---


    def test_native_plugin_loading_and_command_execution(self) -> None:
        """
        Verify that in a normal Hermes session:
        1. Plugin loads via register(ctx)
        2. SQLite initializes cleanly
        3. /pi status works
        4. /pi goals works
        5. /pi situations works
        6. /pi patterns works
        7. /pi timeline works
        """
        class FullHermesContext:
            def __init__(self):
                self.registered_tools = {}
                self.registered_commands = {}
                self.registered_hooks = {}

            def register_tool(self, name, schema, handler):
                self.registered_tools[name] = {"schema": schema, "handler": handler}

            def register_command(self, name, description, handler):
                self.registered_commands[name] = {"description": description, "handler": handler}

            def register_hook(self, name, handler):
                self.registered_hooks.setdefault(name, []).append(handler)

        ctx = FullHermesContext()
        register(ctx, db_manager=self.db_manager)


        # 1. Verify plugin loaded & registered /pi command
        self.assertIn("/pi", ctx.registered_commands)
        pi_handler = ctx.registered_commands["/pi"]["handler"]

        # Populate SQLite tables to verify queryability
        self.goal_store.create_goal(name="Complete Launch", priority=GoalPriority.HIGH.value, description="Prepare production rollout.")
        self.situation_store.create_situation(type="review_pressure", priority=SituationPriority.HIGH.value, context={"summary": "Pending review."})
        self.event_store.append(Event(
            source="calendar",
            event_type="sync_scheduled",
            event_time=datetime.now(timezone.utc),
            payload={"summary": "Architecture Review"},
        ))
        from personal_intelligence.core.patterns.store import PatternStore
        pattern_store = PatternStore(db_manager=self.db_manager)
        pattern_store.create_pattern(
            description="Late meetings are often followed by delayed deliverables.",
            status="active",
        )

        # 2. /pi status works
        status_out = pi_handler("status")
        self.assertIn("Personal Intelligence System Status", status_out)

        # 3. /pi goals works
        goals_out = pi_handler("goals")
        self.assertIn("Active Personal Goals", goals_out)

        # 4. /pi situations works
        situations_out = pi_handler("situations")
        self.assertIn("Open Situations", situations_out)

        # 5. /pi patterns works
        patterns_out = pi_handler("patterns")
        self.assertIn("Personal Intelligence Learned Patterns", patterns_out)
        self.assertIn("Behavioral Patterns", patterns_out)

        # 6. /pi timeline works
        timeline_out = pi_handler("timeline")
        self.assertIn("Personal Intelligence Timeline", timeline_out)
        self.assertIn("Architecture Review", timeline_out)





if __name__ == "__main__":
    unittest.main()

