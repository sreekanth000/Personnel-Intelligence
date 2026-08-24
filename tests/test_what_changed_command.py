"""
Unit and Integration Tests for /pi what_changed Command and WhatChangedAnalyzer.

Validates:
1. Compares current Personal World Model against recent historical state.
2. Does NOT produce a generic event log dump or summarize every source independently.
3. Considers cross-domain signals:
   - goals
   - commitments
   - calendar
   - communication
   - documents
   - meetings
   - activity / sleep
   - patterns
   - situations
   - novelty
4. Returns at most 5 meaningful changes.
5. Each change adheres strictly to the 5-field schema:
   - WHAT CHANGED
   - WHY IT MATTERS
   - EVIDENCE
   - WHAT MAY HAPPEN NEXT
   - UNCERTAINTY
6. Clean handling when no significant changes have occurred.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest

from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.goals import Goal, GoalPriority, GoalStatus, GoalStore
from personal_intelligence.core.patterns import Pattern, PatternStatus, PatternStore, PatternType
from personal_intelligence.core.situations import Situation, SituationPriority, SituationStore
from personal_intelligence.core.state import StateEngine
from personal_intelligence.core.timeline import TimelineEngine
from personal_intelligence.core.world.changes import MeaningfulChange, WhatChangedAnalyzer
from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
from personal_intelligence.storage.db import DatabaseManager


class TestWhatChangedCommand(unittest.TestCase):
    """Test suite for /pi what_changed command and WhatChangedAnalyzer."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_what_changed.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.state_engine = StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)

        self.handler = PersonalIntelligenceCommandHandler(
            db_manager=self.db_manager,
            event_store=self.event_store,
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            pattern_store=self.pattern_store,
            state_engine=self.state_engine,
        )
        self.now = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Multi-Domain Meaningful Changes (Capped at 5)
    # -------------------------------------------------------------------------

    def test_what_changed_synthesizes_at_most_5_meaningful_changes(self) -> None:
        """
        Populate multi-domain historical events, active goals, emerged situations,
        calendar density, sleep deficit, and unread commitments.
        Verify that /pi what_changed returns at most 5 meaningful changes, each with
        the 5 required sections.
        """
        # 1. Goal
        self.goal_store.create_goal(
            name="Deliver Q3 Architecture Proposal",
            priority=GoalPriority.HIGH,
            description="Submit finalized architecture RFC for technical committee review.",
        )

        # 2. Acute Sleep Deficit (Activity / Biometrics)
        self.event_store.append(
            Event(
                id="evt-sleep-short",
                event_type="sleep_logged",
                source="health_tracker",
                event_time=self.now - timedelta(hours=6),
                payload={"duration_minutes": 210, "recovery_score": 35},  # 3.5h sleep
            )
        )

        # 3. Calendar meeting compression (4 meetings today)
        for i in range(4):
            self.event_store.append(
                Event(
                    id=f"evt-meet-{i}",
                    event_type="calendar_event",
                    source="calendar",
                    event_time=self.now - timedelta(hours=5 - i),
                    payload={"summary": f"Executive Sync {i+1}", "duration_minutes": 45},
                )
            )

        # 4. Document action item from Email (Communication / Commitments)
        self.event_store.append(
            Event(
                id="evt-comm-unresolved",
                event_type="unresolved_action",
                source="gmail",
                event_time=self.now - timedelta(hours=3),
                payload={"summary": "Pending signoff on security whitepaper from Alex", "status": "open"},
            )
        )

        # 5. Emerged Situation
        self.situation_store.create_situation(
            situation_type="unresolved_action_item_before_milestone",
            priority=SituationPriority.HIGH,
            context={"summary": "Security whitepaper signoff is blocking tomorrow's deployment."},
            evidence=["email:evt-comm-unresolved"],
        )

        # 6. Additional lower priority events
        for j in range(5):
            self.event_store.append(
                Event(
                    id=f"evt-extra-{j}",
                    event_type="document_modified",
                    source="drive",
                    event_time=self.now - timedelta(hours=10 + j),
                    payload={"summary": f"Minor edit on slide {j}"},
                )
            )

        # Execute /pi what_changed via handler
        output_str = self.handler.execute("/pi what_changed 24")

        # 1. Output must not be an empty string
        self.assertIn("Personal Intelligence: What Changed", output_str)
        self.assertIn("Meaningful World Model Changes", output_str)

        # 2. Must not be a generic event log dump grouped by source
        self.assertNotIn("### 1. Recent Observations by Source", output_str)
        self.assertNotIn("- **GMAIL** (", output_str)
        self.assertNotIn("- **DRIVE** (", output_str)

        # 3. Must contain structured fields
        self.assertIn("- **WHAT CHANGED**:", output_str)
        self.assertIn("- **WHY IT MATTERS**:", output_str)
        self.assertIn("- **EVIDENCE**:", output_str)
        self.assertIn("- **WHAT MAY HAPPEN NEXT**:", output_str)
        self.assertIn("- **UNCERTAINTY**:", output_str)

        # 4. Check structured list from get_meaningful_changes
        changes = self.handler.get_meaningful_changes(
            time_window_hours=24,
            max_changes=5,
            reference_time=self.now,
        )

        self.assertGreaterEqual(len(changes), 1)
        self.assertLessEqual(len(changes), 5)

        for c in changes:
            self.assertIsInstance(c, MeaningfulChange)
            self.assertTrue(bool(c.what_changed.strip()))
            self.assertTrue(bool(c.why_it_matters.strip()))
            self.assertTrue(len(c.evidence) > 0)
            self.assertTrue(bool(c.what_may_happen_next.strip()))
            self.assertTrue(bool(c.uncertainty.strip()))

    # -------------------------------------------------------------------------
    # 2. Active Pattern and Goal Trajectory Integration
    # -------------------------------------------------------------------------

    def test_pattern_and_goal_changes_integrated(self) -> None:
        """
        Verify that active pattern transitions and goal alignments are reflected in what_changed.
        """
        self.goal_store.create_goal(
            name="Half-Marathon Preparation",
            priority=GoalPriority.HIGH,
            description="Complete 4 training sessions weekly.",
        )

        self.pattern_store.create_pattern(
            description="Morning runs are frequently associated with higher post-workout recovery scores.",
            pattern_type=PatternType.BEHAVIORAL_PATTERN,
            status=PatternStatus.ACTIVE,
            support_count=12,
        )

        changes = self.handler.get_meaningful_changes(
            time_window_hours=48,
            max_changes=5,
            reference_time=self.now,
        )

        self.assertGreaterEqual(len(changes), 1)
        what_texts = [c.what_changed for c in changes]
        self.assertTrue(any("Half-Marathon Preparation" in t or "pattern" in t.lower() for t in what_texts))

    # -------------------------------------------------------------------------
    # 3. Empty State / No Significant Changes
    # -------------------------------------------------------------------------

    def test_what_changed_empty_window_handling(self) -> None:
        """
        When no events, situations, or baseline deviations have occurred,
        /pi what_changed returns a graceful informative message.
        """
        output_str = self.handler.execute("/pi what_changed 12")
        self.assertIn("No significant state deviations", output_str)

        changes = self.handler.get_meaningful_changes(
            time_window_hours=12,
            max_changes=5,
            reference_time=self.now,
        )
        self.assertEqual(len(changes), 0)


if __name__ == "__main__":
    unittest.main()
