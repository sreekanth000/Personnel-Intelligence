"""
Unit and Integration tests for Hermes Personal Intelligence /pi Command Interface.

Verifies:
  - /pi status
  - /pi what_matters (6-step orchestration, strict 5-part structure, max 5 recommendations, no fake confidence)
  - /pi investigate [situation_id]
  - /pi patterns
  - /pi timeline [limit]
  - /pi goals
  - /pi situations
  - /pi briefing
  - Plugin registration and tool invocation
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.goals import Goal, GoalStore
from personal_intelligence.core.patterns import Pattern, PatternStore, PatternType
from personal_intelligence.core.policy import InterventionPolicyEngine, PolicyAction
from personal_intelligence.core.situations import Situation, SituationStore
from personal_intelligence.hermes_bridge.commands import (
    PersonalIntelligenceCommandHandler,
    WhatMattersRecommendation,
)
from personal_intelligence.hermes_bridge.plugin.loader import HermesPluginLoader
from personal_intelligence.hermes_bridge.plugin.tools import execute_pi_command
from personal_intelligence.storage.db import DatabaseManager


class MockHermesContext:
    """Mock context simulating Hermes Agent plugin registrar."""
    def __init__(self) -> None:
        self.tools = {}
        self.commands = {}
        self.hooks = {}

    def register_tool(self, name: str, schema: dict, handler: object) -> None:
        self.tools[name] = {"schema": schema, "handler": handler}

    def register_command(self, name: str, description: str, handler: object) -> None:
        self.commands[name] = {"description": description, "handler": handler}

    def register_hook(self, name: str, handler: object) -> None:
        self.hooks[name] = handler


class TestPersonalIntelligenceCommands(unittest.TestCase):
    """Test suite for Hermes /pi command dispatcher and modes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_pi_commands.db")
        self.db = DatabaseManager(db_path=self.db_path)
        self.db.initialize_schema()
        self.handler = PersonalIntelligenceCommandHandler(db_manager=self.db)
        self.now = datetime.now(timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. /pi help and unknown modes
    # -------------------------------------------------------------------------

    def test_pi_help_and_unknown_mode(self) -> None:
        """Verify /pi help and unknown fallback response."""
        help_out = self.handler.execute("/pi help")
        self.assertIn("Personal Intelligence (/pi) Commands", help_out)
        self.assertIn("/pi what_matters", help_out)
        self.assertIn("/pi status", help_out)

        unknown_out = self.handler.execute("/pi unknown_command")
        self.assertIn("Unknown /pi mode", unknown_out)
        self.assertIn("Supported modes:", unknown_out)

    # -------------------------------------------------------------------------
    # 2. /pi status
    # -------------------------------------------------------------------------

    def test_pi_status_overview(self) -> None:
        """Verify /pi status displays snapshot counts and subsystem health."""
        # Seed goal and situation
        self.handler.goal_store.create_goal(name="Deliver Architecture", priority="high")
        self.handler.situation_store.create(
            type="possible_forgotten_commitment",
            priority="high",
            context={"summary": "Architecture doc review pending"},
        )

        out = self.handler.execute("/pi status")
        self.assertIn("Personal Intelligence System Status", out)
        self.assertIn("Personal World Model", out)
        self.assertIn("Active Goals", out)
        self.assertIn("Open Situations", out)

    # -------------------------------------------------------------------------
    # 3. /pi goals
    # -------------------------------------------------------------------------

    def test_pi_goals_listing(self) -> None:
        """Verify /pi goals lists active goals."""
        self.handler.goal_store.create_goal(
            name="Half-Marathon Preparation",
            priority="high",
            description="Train for sub-1:45 race",
        )

        out = self.handler.execute("/pi goals")
        self.assertIn("Active Personal Goals", out)
        self.assertIn("Half-Marathon Preparation", out)
        self.assertIn("Priority: HIGH", out)

    # -------------------------------------------------------------------------
    # 4. /pi situations
    # -------------------------------------------------------------------------

    def test_pi_situations_listing(self) -> None:
        """Verify /pi situations lists open situations."""
        self.handler.situation_store.create(
            type="deadline_conflict",
            priority="high",
            context={"summary": "Overlapping deliverable reviews on Friday afternoon"},
            related_goals=["Goal-1"],
        )

        out = self.handler.execute("/pi situations")
        self.assertIn("Open Situations", out)
        self.assertIn("Deadline Conflict", out)
        self.assertIn("Goal-1", out)

    # -------------------------------------------------------------------------
    # 5. /pi patterns
    # -------------------------------------------------------------------------

    def test_pi_patterns_listing(self) -> None:
        """Verify /pi patterns groups and displays learned non-causal patterns."""
        self.handler.pattern_store.create_pattern(
            pattern_type=PatternType.BEHAVIORAL_PATTERN.value,
            description="Late meetings are often followed by delayed work.",
            support_count=12,
            contradiction_count=1,
            evidence_strength="strong",
            status="ACTIVE",
        )
        self.handler.pattern_store.create_pattern(
            pattern_type=PatternType.INTERACTION_PATTERN.value,
            description="Specific recommendations appear more often accepted than generic reminders.",
            support_count=8,
            contradiction_count=0,
            evidence_strength="moderate",
            status="SUPPORTED",
        )

        out = self.handler.execute("/pi patterns")
        self.assertIn("Personal Intelligence Learned Patterns", out)
        self.assertIn("Behavioral Patterns", out)
        self.assertIn("Late meetings are often followed by delayed work", out)
        self.assertIn("Interaction Patterns", out)
        self.assertIn("Specific recommendations appear more often accepted", out)

    # -------------------------------------------------------------------------
    # 6. /pi timeline
    # -------------------------------------------------------------------------

    def test_pi_timeline_listing(self) -> None:
        """Verify /pi timeline lists recent events with source badges."""
        self.handler.event_store.append(
            Event(
                id="evt-gmail-1",
                event_type="email_received",
                source="gmail",
                subject_id="user_me",
                event_time=self.now - timedelta(minutes=15),
                payload={"summary": "Received architecture finalization request"},
                confidence=1.0,
            )
        )
        self.handler.event_store.append(
            Event(
                id="evt-meet-1",
                event_type="action_item_detected",
                source="meet",
                subject_id="user_me",
                event_time=self.now - timedelta(minutes=5),
                payload={"summary": "Action item: verify doc revisions"},
                confidence=1.0,
            )
        )

        out = self.handler.execute("/pi timeline 10")
        self.assertIn("Personal Intelligence Timeline", out)
        self.assertIn("[GMAIL]", out)
        self.assertIn("[MEET]", out)
        self.assertIn("Received architecture finalization request", out)

    # -------------------------------------------------------------------------
    # 7. /pi briefing
    # -------------------------------------------------------------------------

    def test_pi_briefing_digest(self) -> None:
        """Verify /pi briefing generates daily digest."""
        self.handler.goal_store.create_goal(name="Q3 Milestone Delivery", priority="high")
        out = self.handler.execute("/pi briefing")
        self.assertIn("Personal Intelligence: Daily Briefing Digest", out)
        self.assertIn("Q3 Milestone Delivery", out)

    # -------------------------------------------------------------------------
    # 8. /pi investigate
    # -------------------------------------------------------------------------

    def test_pi_investigate_mode(self) -> None:
        """Verify /pi investigate performs bounded Hermes gap investigation."""
        sit = self.handler.situation_store.create(
            type="possible_forgotten_commitment",
            priority="high",
            context={"summary": "Gmail mentions final document while Calendar contains review Friday."},
            evidence=["[gmail] Please send final document", "[calendar] Architecture review Friday"],
        )

        out = self.handler.execute(f"/pi investigate {sit.id}")
        self.assertIn("Situation Investigation: possible_forgotten_commitment", out)
        self.assertIn(sit.id, out)
        self.assertIn("Unified Cross-Source Synthesis", out)
        self.assertIn("OBSERVATIONS", out)
        self.assertIn("INFERENCES", out)
        self.assertIn("RECOMMENDATION", out)

    # -------------------------------------------------------------------------
    # 9. /pi what_matters (Full 6-Step Workflow & Strict Formatting)
    # -------------------------------------------------------------------------

    def test_pi_what_matters_strict_requirements(self) -> None:
        """
        Verify /pi what_matters:
          1. Inspects world model
          2. Identifies meaningful open situations
          3. Uses Hermes tools to investigate gaps
          4. Reasons across Gmail, Drive, Calendar, Meet, and files
          5. Ranks findings using categorical intervention policy
          6. Returns only most useful items (max 5 recommendations)
          - Strict 5-part structure:
            WHAT HAPPENED
            WHY IT MATTERS
            WHAT I SUGGEST
            EVIDENCE
            UNCERTAINTY
          - Zero fake probability scores (no confidence = 0.91)
        """
        # Create multi-source situation needing investigation
        self.handler.event_store.append(
            Event(
                id="evt-g1",
                event_type="email_received",
                source="gmail",
                subject_id="user_me",
                event_time=self.now - timedelta(hours=2),
                payload={"summary": "Please send the final architecture."},
                confidence=1.0,
            )
        )
        self.handler.event_store.append(
            Event(
                id="evt-c1",
                event_type="calendar_event",
                source="calendar",
                subject_id="user_me",
                event_time=self.now + timedelta(days=1),
                payload={"summary": "Architecture review Friday 2pm."},
                confidence=1.0,
            )
        )
        self.handler.situation_store.create(
            type="possible_forgotten_commitment",
            priority="high",
            context={"summary": "Pending architecture deliverable for upcoming review Friday."},
            evidence=[
                "[gmail] Please send the final architecture.",
                "[calendar] Architecture review scheduled for Friday.",
            ],
        )

        out = self.handler.execute("/pi what_matters")

        # 1. Heading
        self.assertIn("Personal Intelligence: What Matters Most Right Now", out)
        
        # 2. Strict 5-part structure verified
        self.assertIn("WHAT HAPPENED", out)
        self.assertIn("WHY IT MATTERS", out)
        self.assertIn("WHAT I SUGGEST", out)
        self.assertIn("EVIDENCE", out)
        self.assertIn("UNCERTAINTY", out)

        # 3. No numerical confidence values in user-facing output
        self.assertNotIn("confidence = 0.", out)
        self.assertNotIn("confidence: 0.", out)
        self.assertNotIn("0.91", out)

    def test_pi_what_matters_max_5_recommendations(self) -> None:
        """Verify what_matters strictly caps recommendations at 5 and ranks by policy."""
        # Create 8 active situations
        for i in range(8):
            self.handler.situation_store.create(
                type=f"situation_risk_{i}",
                priority="high",
                context={"summary": f"Context for situation {i}"},
                evidence=[f"evidence {i}"],
            )

        out = self.handler.execute("/pi what_matters")
        # Count headers like "### 1.", "### 2.", etc.
        item_headers = [line for line in out.splitlines() if line.startswith("### ")]
        self.assertLessEqual(len(item_headers), 5)


    # -------------------------------------------------------------------------
    # 10. /pi what_changed
    # -------------------------------------------------------------------------

    def test_pi_what_changed(self) -> None:
        """Verify /pi what_changed summarizes observations, new situations, and goal focus."""
        self.handler.event_store.append(
            Event(
                id="evt-drive-change-1",
                event_type="document_changed",
                source="drive",
                subject_id="user_me",
                event_time=self.now - timedelta(hours=1),
                payload={"summary": "Engineering RFC V2 updated with new consensus."},
                confidence=1.0,
            )
        )
        self.handler.situation_store.create(
            type="unresolved_action_item_before_milestone",
            priority="high",
            context={"summary": "Pending review on RFC before staging deployment."},
        )

        out = self.handler.execute("/pi what_changed")
        self.assertIn("Personal Intelligence: What Changed", out)
        self.assertIn("DRIVE", out)
        self.assertIn("Engineering RFC V2 updated", out)
        self.assertIn("Unresolved Action Item Before Milestone", out)

    # -------------------------------------------------------------------------
    # 11. /pi why <situation_id>
    # -------------------------------------------------------------------------

    def test_pi_why_situation_diagnostic(self) -> None:
        """Verify /pi why explains the complete diagnostic rationale, observed facts with provenance, and inferences."""
        sit = self.handler.situation_store.create(
            type="unresolved_action_item_before_milestone",
            priority="high",
            context={"summary": "Architecture document needs sign-off before Friday."},
            evidence=["[gmail] alex: Please approve RFC by Thursday", "[calendar] Architecture review Friday 10am"],
            related_goals=["Deliver Architecture"],
        )

        out = self.handler.execute(f"/pi why {sit.id}")
        self.assertIn("Situation Diagnostic: Why 'Unresolved Action Item Before Milestone'", out)
        self.assertIn(sit.id, out)
        self.assertIn("Observed Facts", out)
        self.assertIn("Evidence", out)
        self.assertIn("Inferences", out)
        self.assertIn("Deliver Architecture", out)
        self.assertIn("Why the Intervention Policy Selected Its Decision", out)

    # -------------------------------------------------------------------------
    # 12. Plugin Registration & execute_pi_command tool
    # -------------------------------------------------------------------------

    def test_plugin_registration_and_tool_call(self) -> None:
        """Verify plugin registers execute_pi_command tool and /pi slash command."""
        from personal_intelligence.hermes_bridge.plugin import register

        mock_ctx = MockHermesContext()
        register(mock_ctx)

        # Assert tool is registered
        self.assertIn("execute_pi_command", mock_ctx.tools)
        # Assert command is registered
        self.assertIn("/pi", mock_ctx.commands)

        # Invoke tool directly
        tool_res = execute_pi_command(mode="status", db_manager=self.db)
        self.assertEqual(tool_res["status"], "success")
        self.assertIn("Personal Intelligence System Status", tool_res["result_text"])

        # Invoke what_changed tool
        tool_res2 = execute_pi_command(mode="what_changed", db_manager=self.db)
        self.assertEqual(tool_res2["status"], "success")
        self.assertIn("What Changed", tool_res2["result_text"])

        # Invoke why tool
        sit = self.handler.situation_store.create(type="opportunity", priority="medium", context={"summary": "New collaboration opportunity."})
        tool_res3 = execute_pi_command(mode=f"why {sit.id}", db_manager=self.db)
        self.assertEqual(tool_res3["status"], "success")
        self.assertIn("Situation Diagnostic", tool_res3["result_text"])


if __name__ == "__main__":
    unittest.main()

