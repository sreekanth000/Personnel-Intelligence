"""
Unit Tests for Interactive User Feedback Loop in Situations, EpisodeStore, and PatternLearningEngine.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.episodes.models import (
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.patterns.models import PatternStatus, PatternType
from personal_intelligence.core.situations.models import (
    Situation,
    SituationPriority,
    SituationStatus,
)
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.api.server import DashboardDataService
from personal_intelligence.storage.db import DatabaseManager


class TestInteractiveFeedbackLoop(unittest.TestCase):
    """Tests for user feedback actions: [Acknowledged], [Snooze 2 Days], [Not Relevant]."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_feedback.db"
        self.db_manager = DatabaseManager(db_path=str(self.db_path))
        self.db_manager.initialize_schema()
        self.world_model = PersonalWorldModel(db_manager=self.db_manager)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_acknowledge_feedback_flow(self) -> None:
        # Create situation
        sit = self.world_model.situation_store.create(
            type="financial_deadline",
            priority="high",
            context={"summary": "SBI BPCL credit card assessment due"},
            situation_id="sit-test-ack-01",
        )
        self.assertEqual(sit.status, SituationStatus.OPEN.value)

        # Process user acknowledgement
        res = self.world_model.process_user_feedback(
            situation_id="sit-test-ack-01",
            action="acknowledge",
            feedback_notes="Card already reviewed and verified.",
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["user_response"], RecommendationResult.ACCEPTED.value)

        # Verify Situation updated in DB
        updated_sit = self.world_model.situation_store.get("sit-test-ack-01")
        self.assertIsNotNone(updated_sit)
        self.assertEqual(updated_sit.status, SituationStatus.RESOLVED.value)

        # Verify Episode recorded in EpisodeStore
        episodes = self.world_model.episode_store.list_by_situation("sit-test-ack-01")
        self.assertEqual(len(episodes), 1)
        ep = episodes[0]
        self.assertIsNotNone(ep.user_response)
        self.assertEqual(ep.user_response.get("response"), RecommendationResult.ACCEPTED.value)

        # Verify EventStore recorded user feedback
        events = self.world_model.event_store.get_events_by_type("user_feedback_recorded")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["situation_id"], "sit-test-ack-01")

    def test_snooze_2_days_feedback_flow(self) -> None:
        sit = self.world_model.situation_store.create(
            type="career_opportunity",
            priority="medium",
            context={"summary": "LinkedIn Head of Data opportunity"},
            situation_id="sit-test-snooze-01",
        )

        res = self.world_model.process_user_feedback(
            situation_id="sit-test-snooze-01",
            action="snooze",
            snooze_days=2,
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["user_response"], RecommendationResult.DEFERRED.value)

        updated_sit = self.world_model.situation_store.get("sit-test-snooze-01")
        self.assertIsNotNone(updated_sit)
        self.assertEqual(updated_sit.status, SituationStatus.SUPPRESSED.value)
        self.assertIsNotNone(updated_sit.next_evaluation_at)

        # Verify next_evaluation_at is ~2 days in the future
        delta = updated_sit.next_evaluation_at - datetime.now(timezone.utc)
        self.assertGreater(delta.total_seconds(), 86400 * 1.8)

    def test_not_relevant_feedback_trains_pattern_learning(self) -> None:
        sit = self.world_model.situation_store.create(
            type="communication_digest",
            priority="low",
            context={"summary": "Daily marketing newsletter digest"},
            situation_id="sit-test-dismiss-01",
        )

        res = self.world_model.process_user_feedback(
            situation_id="sit-test-dismiss-01",
            action="dismiss",
            feedback_notes="Not relevant to my active priorities.",
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["user_response"], RecommendationResult.DISMISSED.value)

        # Check situation is suppressed
        updated_sit = self.world_model.situation_store.get("sit-test-dismiss-01")
        self.assertEqual(updated_sit.status, SituationStatus.SUPPRESSED.value)

        # Check PatternLearningEngine learned suppression preference
        suppressed_types = self.world_model.get_suppressed_situation_types()
        self.assertIn("communication_digest", suppressed_types)

        # Verify learned patterns exist in PatternStore
        patterns = self.world_model.pattern_store.list_patterns()
        suppression_pats = [p for p in patterns if "suppresses" in p.description]
        self.assertTrue(len(suppression_pats) > 0)
        self.assertIn("communication digest", suppression_pats[0].description.lower())

    def test_dashboard_service_feedback_endpoint(self) -> None:
        ds = DashboardDataService(db_manager=self.db_manager)
        sit = ds.world_model.situation_store.create(
            type="security_alert",
            priority="high",
            context={"summary": "Google security login alert"},
            situation_id="sit-test-ds-01",
        )

        resp = ds.handle_situation_feedback(
            situation_id="sit-test-ds-01",
            action="acknowledge",
            feedback_notes="Checked device, was me.",
        )
        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["situation_status"], SituationStatus.RESOLVED.value)

        ds.bg_scheduler.stop()


if __name__ == "__main__":
    unittest.main()
