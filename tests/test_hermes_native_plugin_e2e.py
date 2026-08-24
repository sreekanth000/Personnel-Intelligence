"""
End-to-End Verification Test for Native Hermes Plugin Architecture.

Specifically verifies the 8 core operational milestones:
1. Hermes runtime starts (simulated host context).
2. Personal Intelligence plugin loads via official register(ctx).
3. SQLite persistence initializes schemas and tables.
4. /pi status executes and returns comprehensive subsystem status.
5. /pi goals executes and lists active goals.
6. /pi situations executes and lists open situations.
7. /pi patterns executes and lists non-causal empirical patterns.
8. /pi timeline executes and returns chronological bounded events.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.patterns.models import PatternStatus, PatternType
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.situations.models import SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.hermes_bridge.client import (
    HermesRuntimeBridge,
    get_active_hermes_context,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.plugin import register as register_plugin
from personal_intelligence.hermes_bridge.plugin.loader import HermesPluginLoader
from personal_intelligence.storage.db import DatabaseManager


class SimulatedHermesRuntime:
    """Simulates the host Hermes Agent runtime environment."""

    def __init__(self) -> None:
        self.tools = {}
        self.commands = {}
        self.hooks = {}
        self.tool_invocations = []
        self.llm_queries = []

    def register_tool(self, name: str, schema: dict, handler: object) -> None:
        self.tools[name] = {"schema": schema, "handler": handler}

    def register_command(self, name: str, description: str, handler: object) -> None:
        self.commands[name] = {"description": description, "handler": handler}

    def register_hook(self, name: str, handler: object) -> None:
        self.hooks.setdefault(name, []).append(handler)

    def prompt_llm(self, prompt: str) -> str:
        self.llm_queries.append(prompt)
        return json.dumps({
            "what_is_happening": "System operational and observing user context.",
            "why_it_matters": "Maintains situational awareness without user interruption.",
            "what_i_suggest": ["Continue monitoring state."],
            "evidence": ["All local systems healthy"],
            "uncertainty": "None",
            "urgency": "low",
            "actionability": "low",
            "relevance": "medium",
            "evidence_strength": "strong",
        })

    def execute_tool(self, tool_name: str, tool_args: dict) -> dict:
        self.tool_invocations.append((tool_name, tool_args))
        return {"status": "success", "tool": tool_name, "data": "Native tool output"}


class TestHermesNativePluginE2E(unittest.TestCase):
    """Formal test suite verifying the 8 native plugin integration milestones."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "hermes_e2e.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.hermes = SimulatedHermesRuntime()

    def tearDown(self) -> None:
        set_active_hermes_context(None)
        self.temp_dir.cleanup()

    def test_milestone_1_to_8_native_plugin_lifecycle(self) -> None:
        """
        Executes all 8 milestones in sequence:
        1. Hermes starts
        2. Personal Intelligence plugin loads
        3. SQLite initializes
        4. /pi status works
        5. /pi goals works
        6. /pi situations works
        7. /pi patterns works
        8. /pi timeline works
        """
        # [Milestone 1 & 2]: Plugin loads via register(ctx)
        register_plugin(self.hermes, db_manager=self.db_manager)

        self.assertIn("/pi", self.hermes.commands)
        self.assertEqual(len(self.hermes.tools), 10)
        self.assertIn("pre_tool_call", self.hermes.hooks)
        self.assertIn("post_tool_call", self.hermes.hooks)
        self.assertIs(get_active_hermes_context(), self.hermes)

        # [Milestone 3]: SQLite initializes and supports data ingestion
        goal_store = GoalStore(db_manager=self.db_manager)
        situation_store = SituationStore(db_manager=self.db_manager)
        event_store = EventStore(db_manager=self.db_manager)
        pattern_store = PatternStore(db_manager=self.db_manager)

        g1 = goal_store.create_goal(
            name="Quarterly Architecture Review",
            priority=GoalPriority.HIGH.value,
            description="Present system architecture and performance benchmarks.",
        )
        s1 = situation_store.create_situation(
            type="deadline_pressure",
            priority=SituationPriority.HIGH.value,
            context={"summary": "Review scheduled in 2 days."},
            related_goals=[g1.id],
        )
        e1 = event_store.append(Event(
            source="calendar",
            event_type="meeting_scheduled",
            event_time=datetime.now(timezone.utc),
            payload={"summary": "Architecture Review Sync", "duration": 60},
        ))
        p1 = pattern_store.create_pattern(
            description="Specific recommendations are more often accepted than generic reminders.",
            pattern_type=PatternType.INTERACTION_PATTERN.value,
            status=PatternStatus.ACTIVE.value,
            support_count=15,
            evidence_strength="strong",
        )

        pi_dispatch = self.hermes.commands["/pi"]["handler"]

        # [Milestone 4]: /pi status works
        status_result = pi_dispatch("status")
        self.assertIn("Personal Intelligence System Status", status_result)
        self.assertIn("Personal World Model", status_result)

        # [Milestone 5]: /pi goals works
        goals_result = pi_dispatch("goals")
        self.assertIn("Active Personal Goals", goals_result)
        self.assertIn("Quarterly Architecture Review", goals_result)

        # [Milestone 6]: /pi situations works
        situations_result = pi_dispatch("situations")
        self.assertIn("Open Situations", situations_result)
        self.assertIn("Deadline Pressure", situations_result)


        # [Milestone 7]: /pi patterns works
        patterns_result = pi_dispatch("patterns")
        self.assertIn("Personal Intelligence Learned Patterns", patterns_result)
        self.assertIn("Specific recommendations are more often accepted", patterns_result)

        # [Milestone 8]: /pi timeline works
        timeline_result = pi_dispatch("timeline")
        self.assertIn("Personal Intelligence Timeline", timeline_result)
        self.assertIn("Architecture Review Sync", timeline_result)


if __name__ == "__main__":
    unittest.main()
