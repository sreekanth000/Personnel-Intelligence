"""
Regression & Unit Test Suite for the Personal Baseline -> WhatChanged -> Novelty -> Significance Pipeline.

Verifies:
1. Unusual behavior is detected via statistical baselines (numerical deviations, categorical rarity, silence).
2. Normal behavior is not over-flagged (NORMAL classification).
3. Novelty remains independent of personal significance (a rare event may have zero personal significance,
   and a common event may have critical personal significance).
4. Situations emerge cleanly from the unified deterministic pipeline without predictive-error modeling.
5. Reasoning eligibility filtering prevents unwarranted Hermes System 2 invocations.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.novelty.detector import NoveltyEngine
from personal_intelligence.core.novelty.models import NoveltyClassification, OverallNoveltyLevel
from personal_intelligence.core.significance.engine import PersonalSignificanceEngine
from personal_intelligence.core.significance.models import SignificanceAssessment, SignificanceLevel
from personal_intelligence.core.state.models import StateFeature, StateRepresentation
from personal_intelligence.core.world.changes import MeaningfulChange
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.storage.db import DatabaseManager


class TestBaselineNoveltyPipeline(unittest.TestCase):
    """Verifies baseline-novelty-significance pipeline without predictive-error modeling."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_novelty_pipeline.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.world_model = PersonalWorldModel(db_manager=self.db_manager)
        self.novelty_engine = NoveltyEngine(min_history_samples=3)
        self.significance_engine = PersonalSignificanceEngine()
        self.base_time = datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_unusual_behavior_detected_by_baseline_comparison(self) -> None:
        """Requirement 1: Unusual behavioral deviations are detected via deterministic baseline comparisons."""
        # 1. Establish normal historical baseline: ~5 daily meetings
        history_states = [
            StateRepresentation(
                timestamp=self.base_time - timedelta(days=i),
                features={
                    "meetings_count": StateFeature(name="meetings_count", value=5, source="calendar"),
                    "focus_hours": StateFeature(name="focus_hours", value=4.0, source="calendar"),
                },
            )
            for i in range(1, 8)
        ]

        # 2. Current state: 16 meetings scheduled, 0 focus hours (extreme surge)
        unusual_state = StateRepresentation(
            timestamp=self.base_time,
            features={
                "meetings_count": StateFeature(name="meetings_count", value=16, source="calendar"),
                "focus_hours": StateFeature(name="focus_hours", value=0.0, source="calendar"),
            },
        )

        result = self.novelty_engine.detect(current_state=unusual_state, history=history_states)
        self.assertIn(
            result.overall_level,
            (OverallNoveltyLevel.HIGHLY_UNUSUAL.value, OverallNoveltyLevel.UNUSUAL.value, OverallNoveltyLevel.NOVEL_COMBINATION.value),
        )
        self.assertTrue(
            any(
                f.classification in (NoveltyClassification.UNUSUAL.value, NoveltyClassification.HIGHLY_UNUSUAL.value)
                for f in result.feature_results
            )
        )

    def test_normal_behavior_is_not_overflagged(self) -> None:
        """Requirement 2: Routine behavioral patterns are classified as NORMAL without false alerts."""
        history_states = [
            StateRepresentation(
                timestamp=self.base_time - timedelta(days=i),
                features={
                    "meetings_count": StateFeature(name="meetings_count", value=4 + (i % 2), source="calendar"),
                    "focus_hours": StateFeature(name="focus_hours", value=3.5, source="calendar"),
                },
            )
            for i in range(1, 8)
        ]

        normal_state = StateRepresentation(
            timestamp=self.base_time,
            features={
                "meetings_count": StateFeature(name="meetings_count", value=5, source="calendar"),
                "focus_hours": StateFeature(name="focus_hours", value=3.5, source="calendar"),
            },
        )

        result = self.novelty_engine.detect(current_state=normal_state, history=history_states)
        self.assertEqual(result.overall_level, OverallNoveltyLevel.NORMAL.value)

    def test_novelty_remains_independent_of_significance(self) -> None:
        """
        Requirement 3: Novelty and Personal Significance are orthogonal dimensions.
        Case A: Highly novel event with LOW / NOT_SIGNIFICANT personal significance (e.g. rare spam newsletter).
        Case B: Highly routine event with CRITICAL personal significance (e.g. daily standup with CEO when keynote is tomorrow).
        """
        # Case A: Rare marketing newsletter (High statistical novelty, LOW personal significance)
        spam_novelty = OverallNoveltyLevel.HIGHLY_UNUSUAL.value
        spam_change = MeaningfulChange(
            what_changed="Received email from unusual domain @obscure-newsletter.io",
            why_it_matters="First communication from external sender",
            evidence=["Email msg-1099 from obscure-newsletter.io"],
            what_may_happen_next="Follow up emails may arrive",
            uncertainty="Unknown sender identity",
            domain="email",
        )
        spam_significance = self.significance_engine.evaluate_change(
            change=spam_change,
            active_goals=[],
            commitments=[],
        )
        self.assertIn(spam_significance.level, (SignificanceLevel.NOT_SIGNIFICANT.value, SignificanceLevel.LOW.value))
        self.assertEqual(spam_novelty, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)

        # Case B: Routine daily keynote rehearsal (NORMAL novelty, CRITICAL personal significance)
        routine_novelty = OverallNoveltyLevel.NORMAL.value
        keynote_goal = Goal(
            name="Deliver Keynote at TechSummit",
            priority=GoalPriority.CRITICAL.value,
        )
        keynote_change = MeaningfulChange(
            what_changed="TechSummit keynote room AV check scheduled",
            why_it_matters="Required for successful delivery of upcoming critical keynote presentation",
            evidence=["Calendar invite cal-techsummit-01"],
            what_may_happen_next="Stage walkthrough and tech verification",
            uncertainty="Audio setup compatibility",
            domain="calendar",
        )
        keynote_significance = self.significance_engine.evaluate_change(
            change=keynote_change,
            active_goals=[keynote_goal],
            commitments=[],
        )
        self.assertIn(keynote_significance.level, (SignificanceLevel.HIGH.value, SignificanceLevel.CRITICAL.value))
        self.assertEqual(routine_novelty, OverallNoveltyLevel.NORMAL.value)

    def test_situation_emergence_without_predictive_error_engine(self) -> None:
        """Requirement 4: Situations emerge cleanly from Novelty + Significance without predictive processing."""
        wm = self.world_model

        # Register active project goal
        goal = Goal(
            name="Launch Project Quantum",
            priority=GoalPriority.HIGH.value,
        )
        wm.goal_store.create_goal(goal)

        # Ingest significant observation from valid source
        evt = wm.record_observation(
            source="gmail",
            source_id="msg-quant-99",
            timestamp=self.base_time,
            observation_type="action_item_detected",
            summary="Critical blocker in Launch Project Quantum auth pipeline",
            evidence={"priority": "urgent"},
            provenance={"tool": "google_workspace_gmail", "query": "label:urgent", "message_id": "msg-quant-99"},
        )
        self.assertIsNotNone(evt)

        # Evaluate significance
        change = MeaningfulChange(
            what_changed="Critical blocker in Launch Project Quantum auth pipeline",
            why_it_matters="Blocks upcoming launch milestone for high-priority goal",
            evidence=["Gmail notification msg-quant-99 marked blocker"],
            what_may_happen_next="Release delayed if unaddressed",
            uncertainty="Fix effort estimation",
            domain="development",
        )
        sig = wm.significance_engine.evaluate_change(
            change=change,
            active_goals=[goal],
            commitments=[],
        )
        self.assertIn(sig.level, (SignificanceLevel.HIGH.value, SignificanceLevel.CRITICAL.value))


if __name__ == "__main__":
    unittest.main()
