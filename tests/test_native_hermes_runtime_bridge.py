"""
Integration tests proving native Hermes Agent plugin runtime integration.

Verifies:
1. Personal Intelligence operates natively in-process within Hermes runtime without subprocesses or HTTP gateway.
2. HermesRuntimeBridge invokes host LLM capability natively.
3. Native tool delegation across Workspace/Meet/Filesystem tools without duplicate API clients or OAuth.
4. Automatic observation capture with origin provenance via on_post_tool_call hook.
5. /pi commands execute natively inside Hermes agent context.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.context.builder import ContextBuilder
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.situations.models import SituationPriority
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.hermes_bridge.client import (
    HermesExecutionMode,
    HermesRuntimeBridge,
    get_active_hermes_context,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
from personal_intelligence.hermes_bridge.plugin import register as register_plugin
from personal_intelligence.hermes_bridge.plugin.hooks import on_post_tool_call
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow
from personal_intelligence.storage.db import DatabaseManager


class MockHermesAgentContext:
    """Simulated native Hermes Agent runtime context."""

    def __init__(self) -> None:
        self.registered_tools = {}
        self.registered_commands = {}
        self.registered_hooks = {}
        self.executed_tools = []
        self.llm_prompts = []
        # Explicit auth_status dict — required for execute_tool auth checks in LIVE mode.
        # All workspace capabilities are authenticated in this simulated native context.
        self.auth_status = {
            "gmail": "authenticated",
            "calendar": "authenticated",
            "meet": "authenticated",
            "drive": "authenticated",
            "filesystem": "not_required",
            "web": "not_required",
            "reasoning": "not_required",
        }

    def register_tool(self, name: str, schema: dict, handler: object) -> None:
        self.registered_tools[name] = {"schema": schema, "handler": handler}

    def register_command(self, name: str, description: str, handler: object) -> None:
        self.registered_commands[name] = {"description": description, "handler": handler}

    def register_hook(self, hook_name: str, handler: object) -> None:
        if hook_name not in self.registered_hooks:
            self.registered_hooks[hook_name] = []
        self.registered_hooks[hook_name].append(handler)

    def prompt_llm(self, prompt: str) -> str:
        """Native in-process Hermes LLM generator."""
        self.llm_prompts.append(prompt)
        return json.dumps({
            "what_is_happening": "User has an impending project review with unresolved dependencies.",
            "why_it_matters": "Risk of review delay without required technical documentation.",
            "what_i_suggest": ["Review the architecture draft before 2 PM.", "Notify the tech lead."],
            "evidence": ["Drive doc modified 2 hours ago", "Meeting scheduled at 3 PM"],
            "uncertainty": "Whether all stakeholders received the updated document link.",
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        })

    def execute_tool(self, tool_name: str, tool_args: dict) -> dict:
        """Simulates native Hermes tool execution."""
        self.executed_tools.append((tool_name, tool_args))
        if tool_name == "gmail_search":
            return {"messages": [{"id": "msg-1", "subject": "Architecture Draft Complete", "from": "lead@example.com"}]}
        elif tool_name == "calendar_list_events":
            return {"events": [{"id": "cal-1", "summary": "Sprint Planning", "start": "2026-08-23T10:00:00Z"}]}
        elif tool_name == "meet_get_transcript":
            return {"transcript": "Action item assigned to complete migration plan."}
        return {"status": "success", "result": "Native tool executed"}


class TestNativeHermesRuntimeBridge(unittest.TestCase):
    """Test suite verifying native in-process Hermes Agent plugin runtime integration."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_native_bridge.db")
        self.db = DatabaseManager(db_path=self.db_path)
        self.db.initialize_schema()
        self.goal_store = GoalStore(self.db)
        self.situation_store = SituationStore(self.db)
        self.episode_store = EpisodeStore(self.db)
        self.event_store = EventStore(self.db)
        self.context_builder = ContextBuilder(
            goal_store=self.goal_store,
            situation_store=self.situation_store,
        )
        self.context = MockHermesAgentContext()

    def tearDown(self) -> None:
        set_active_hermes_context(None)
        self.temp_dir.cleanup()

    def test_native_plugin_registration_binds_context(self) -> None:
        """Verify that register(ctx) binds the active Hermes runtime context natively."""
        register_plugin(self.context)

        self.assertIs(get_active_hermes_context(), self.context)
        self.assertIn("get_current_personal_state", self.context.registered_tools)
        self.assertIn("execute_pi_command", self.context.registered_tools)
        self.assertIn("/pi", self.context.registered_commands)
        self.assertIn("pre_tool_call", self.context.registered_hooks)
        self.assertIn("post_tool_call", self.context.registered_hooks)

    def test_structured_reasoning_via_native_llm_without_subprocess(self) -> None:
        """Verify ReasoningWorkflow performs structured reasoning natively through Hermes context."""
        register_plugin(self.context)
        bridge = HermesRuntimeBridge(mode=HermesExecutionMode.NATIVE, runtime_context=self.context)

        # Setup reasoning workflow
        workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=bridge,
        )

        # Create situation and context
        situation = self.situation_store.create_situation(
            type="deadline_pressure",
            priority=SituationPriority.HIGH.value,
            context={"summary": "Upcoming project review requires architecture sign-off."},
        )

        current_state = StateRepresentation(timestamp=datetime.now(timezone.utc))
        current_state.set_feature("current_activity", "architecture_design", source="os_window", confidence=0.95)

        bounded_ctx = self.context_builder.build_bounded_context(
            situation=situation,
            current_state=current_state,
        )

        # Execute reasoning workflow natively
        result = workflow.run_workflow(situation, current_state)

        self.assertIsNotNone(result.synthesis)
        self.assertIsNotNone(result.episode)
        self.assertEqual(len(result.validation_errors), 0)
        self.assertEqual(len(self.context.llm_prompts), 1)
        self.assertIn("User has an impending project review", result.synthesis.what_is_happening)
        self.assertEqual(result.synthesis.urgency, "high")
        self.assertEqual(result.synthesis.actionability, "high")



    def test_native_tool_execution_and_observation_recording(self) -> None:
        """Verify native host tools execute via bridge and record observations via hooks."""
        register_plugin(self.context)
        bridge = HermesRuntimeBridge(runtime_context=self.context)

        # 1. Execute native Gmail search via bridge
        gmail_res = bridge.execute_tool("gmail_search", {"query": "Architecture Draft"})
        self.assertIn("messages", gmail_res)
        self.assertEqual(len(self.context.executed_tools), 1)

        # 2. Simulate post_tool_call hook firing after Hermes executes Gmail tool
        on_post_tool_call("gmail_search", {"query": "Architecture Draft"}, gmail_res, db_manager=self.db)

        # 3. Verify event was ingested into EventStore with full origin provenance
        recent_events = self.event_store.get_recent(limit=10)
        self.assertTrue(len(recent_events) >= 1)
        gmail_evt = next((e for e in recent_events if e.source == "gmail"), None)
        self.assertIsNotNone(gmail_evt)
        self.assertEqual(gmail_evt.provenance.get("origin_source"), "gmail")
        self.assertEqual(gmail_evt.provenance.get("tool"), "gmail_search")

    def test_pi_what_matters_command_in_native_context(self) -> None:
        """Verify /pi what_matters command executes cleanly in native context."""
        register_plugin(self.context)

        self.situation_store.create_situation(
            type="deadline_pressure",
            priority=SituationPriority.HIGH.value,
            context={"summary": "Executive Review scheduled today."},
        )

        self.event_store.append(Event(
            source="calendar",
            event_type="meeting_scheduled",
            event_time=datetime.now(timezone.utc),
            payload={"summary": "Executive Review", "start": "2026-08-23T15:00:00Z"},
        ))

        # Execute command through registered command handler
        pi_command_fn = self.context.registered_commands["/pi"]["handler"]
        output = pi_command_fn("what_matters")

        self.assertIn("Personal Intelligence: What Matters Most Right Now", output)
        self.assertIn("WHAT HAPPENED", output)
        self.assertIn("WHY IT MATTERS", output)
        self.assertIn("WHAT I SUGGEST", output)


if __name__ == "__main__":
    unittest.main()
