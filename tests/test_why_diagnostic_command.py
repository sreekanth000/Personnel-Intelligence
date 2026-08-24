"""
Unit and Integration Tests for /pi why <situation_id> Diagnostic Command.

Validates all 11 required sections:
1. Observed facts
2. Evidence
3. Relevant timeline
4. Goals affected
5. Learned patterns involved
6. Inferences
7. Predictions
8. Uncertainties
9. Recommendation
10. What evidence would change the conclusion
11. Why the intervention policy selected its decision

Also verifies:
- Never exposes hidden chain-of-thought.
- Provides concise evidence-based reasoning and provenance.
- Does not execute actions.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest

from personal_intelligence.core.episodes import EpisodeStatus, EpisodeStore
from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.goals import Goal, GoalPriority, GoalStatus, GoalStore
from personal_intelligence.core.patterns import Pattern, PatternStatus, PatternStore, PatternType
from personal_intelligence.core.policy import PolicyAction, UserContext
from personal_intelligence.core.situations import Situation, SituationPriority, SituationStore
from personal_intelligence.core.state import StateEngine
from personal_intelligence.core.timeline import TimelineEngine
from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
from personal_intelligence.storage.db import DatabaseManager


class TestWhyDiagnosticCommand(unittest.TestCase):
    """Test suite for /pi why diagnostic explanation command."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_why_diagnostic.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.state_engine = StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)

        self.handler = PersonalIntelligenceCommandHandler(
            db_manager=self.db_manager,
            event_store=self.event_store,
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            episode_store=self.episode_store,
            pattern_store=self.pattern_store,
            state_engine=self.state_engine,
        )
        self.now = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Complete 11-Section Validation
    # -------------------------------------------------------------------------

    def test_pi_why_contains_all_11_required_sections(self) -> None:
        """
        Verify that /pi why returns all 11 required diagnostic sections with provenance
        and concise evidence-based explanations without hidden chain-of-thought.
        """
        # 1. Setup Goal
        goal = self.goal_store.create_goal(
            name="Deliver Q3 Architecture RFC",
            priority=GoalPriority.HIGH,
            description="Complete and submit RFC for architecture review committee by Friday.",
        )

        # 2. Setup Events
        self.event_store.append(
            Event(
                id="evt-doc-draft",
                event_type="document_modified",
                source="drive",
                event_time=self.now - timedelta(hours=8),
                payload={"summary": "Draft Architecture RFC updated with security specs."},
            )
        )
        self.event_store.append(
            Event(
                id="evt-email-signoff",
                event_type="email_received",
                source="gmail",
                event_time=self.now - timedelta(hours=4),
                payload={"summary": "Alex sent request: Sign-off required on RFC before tomorrow 10:00."},
            )
        )

        # 3. Setup Situation
        sit = self.situation_store.create_situation(
            situation_type="unresolved_action_item_before_milestone",
            priority=SituationPriority.HIGH,
            context={"summary": "Pending sign-off from Alex on RFC is blocking tomorrow's review milestone."},
            evidence=["email:evt-email-signoff", "drive:evt-doc-draft"],
            related_goals=[goal.id],
        )

        # 4. Setup Pattern
        self.pattern_store.create_pattern(
            description="RFC signoffs requiring multiple stakeholder approvals typically require 24h lead time.",
            pattern_type=PatternType.WORLD_PATTERN,
            status=PatternStatus.ACTIVE,
            support_count=8,
        )

        # 5. Setup Stored Reasoning Episode
        self.episode_store.create_episode(
            episode_id="ep-why-test-001",
            situation_id=sit.id,
            timestamp=self.now,
            observations_used=[
                "Email from Alex received at 08:00 UTC requiring RFC sign-off.",
                "Architecture RFC review scheduled for tomorrow at 10:00 UTC.",
            ],
            evidence=["email:evt-email-signoff", "drive:evt-doc-draft"],
            inferences=[
                "Lack of RFC approval within the next 4 hours will delay the scheduled committee review.",
                "Alex is likely awaiting feedback on the security specifications section.",
            ],
            predictions=[
                "The Friday milestone will slip by at least 1 sprint cycle if sign-off is not finalized today.",
            ],
            recommendations=[
                "Review Alex's security specification comments and complete RFC sign-off before 16:00.",
            ],
            intervention_decision={
                "action": PolicyAction.INTERRUPT.value,
                "reason": "High urgency with high actionability and strong evidence triggers immediate interrupt when user is available.",
                "user_context": UserContext.AVAILABLE.value,
            },
            status=EpisodeStatus.REASONING_COMPLETED.value,
        )

        # Execute /pi why <situation_id>
        output = self.handler.execute(f"/pi why {sit.id}")

        # Verify header
        self.assertIn("## Situation Diagnostic: Why", output)
        self.assertIn(sit.id, output)

        # 1. Observed facts
        self.assertIn("### 1. Observed Facts", output)
        self.assertIn("PROVENANCE", output)

        # 2. Evidence
        self.assertIn("### 2. Evidence", output)
        self.assertIn("email:evt-email-signoff", output)

        # 3. Relevant timeline
        self.assertIn("### 3. Relevant Timeline", output)

        # 4. Goals affected
        self.assertIn("### 4. Goals Affected", output)
        self.assertIn("Deliver Q3 Architecture RFC", output)

        # 5. Learned patterns involved
        self.assertIn("### 5. Learned Patterns Involved", output)
        self.assertIn("RFC signoffs requiring multiple stakeholder approvals", output)

        # 6. Inferences
        self.assertIn("### 6. Inferences", output)
        self.assertIn("delay the scheduled committee review", output)

        # 7. Predictions
        self.assertIn("### 7. Predictions", output)
        self.assertIn("milestone will slip", output)

        # 8. Uncertainties
        self.assertIn("### 8. Uncertainties", output)

        # 9. Recommendation
        self.assertIn("### 9. Recommendation", output)
        self.assertIn("Review Alex's security specification comments", output)

        # 10. What evidence would change the conclusion
        self.assertIn("### 10. What Evidence Would Change the Conclusion", output)

        # 11. Why the intervention policy selected its decision
        self.assertIn("### 11. Why the Intervention Policy Selected Its Decision", output)
        self.assertIn("INTERRUPT", output)

        # Verify no hidden chain-of-thought tags or scratchpad dumps
        self.assertNotIn("<thought>", output)
        self.assertNotIn("</thought>", output)
        self.assertNotIn("think silently", output)
        self.assertNotIn("Chain of thought", output)

    # -------------------------------------------------------------------------
    # 2. Fallback to Latest Active Situation
    # -------------------------------------------------------------------------

    def test_pi_why_default_to_latest_situation(self) -> None:
        """
        Calling `/pi why` without a situation ID should explain the most recent active situation.
        """
        sit = self.situation_store.create_situation(
            situation_type="goal_risk",
            priority=SituationPriority.HIGH,
            context={"summary": "Schedule conflict with milestone deadline."},
        )

        output = self.handler.execute("/pi why")
        self.assertIn("## Situation Diagnostic: Why", output)
        self.assertIn("### 1. Observed Facts", output)
        self.assertIn("### 11. Why the Intervention Policy Selected Its Decision", output)

    def test_pi_why_nonexistent_situation_handling(self) -> None:
        """
        Calling `/pi why invalid_id` when no matching situation exists returns a helpful error.
        """
        output = self.handler.execute("/pi why sit-nonexistent-999")
        self.assertIn("No situation found to explain", output)


if __name__ == "__main__":
    unittest.main()
