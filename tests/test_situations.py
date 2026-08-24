"""
Unit tests for the generic Situation Model and SituationStore.
Tests creation, updates, querying, closing, expiration sweeps, and similarity matching.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import time
import unittest

from personal_intelligence.core.situations import (
    Situation,
    SituationPriority,
    SituationStatus,
    SituationStore,
)
from personal_intelligence.storage.db import DatabaseManager


class TestSituationStore(unittest.TestCase):
    """Test suite for generic Situation model and SituationStore."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_situations.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.base_time = datetime(2026, 8, 21, 14, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- 1. Creation & Retrieval ---

    def test_create_and_get_situation(self) -> None:
        """Verify creating a situation with context, evidence, and related goals."""
        sit = self.situation_store.create(
            type="unusual_state",
            priority="high",
            novelty=0.85,
            context={"anomaly_metric": "heart_rate_variability", "divergence_sigma": 2.8},
            evidence=["evt-sensor-101", "evt-sensor-102"],
            related_goals=["goal-fitness-1", "goal-fatigue-2"],
            expires_at=self.base_time + timedelta(hours=4),
        )

        self.assertIsNotNone(sit.id)
        self.assertEqual(sit.type, "unusual_state")
        self.assertEqual(sit.status, "open")
        self.assertEqual(sit.priority, "high")
        self.assertEqual(sit.novelty, 0.85)
        self.assertEqual(sit.context["anomaly_metric"], "heart_rate_variability")
        self.assertEqual(sit.evidence, ["evt-sensor-101", "evt-sensor-102"])
        self.assertEqual(sit.related_goals, ["goal-fitness-1", "goal-fatigue-2"])
        self.assertIsNotNone(sit.created_at)
        self.assertIsNotNone(sit.updated_at)
        self.assertIsNotNone(sit.expires_at)

        # Retrieve and verify persistence
        retrieved = self.situation_store.get(sit.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, sit.id)
        self.assertEqual(retrieved.type, "unusual_state")
        self.assertEqual(retrieved.novelty, 0.85)
        self.assertEqual(retrieved.evidence, ["evt-sensor-101", "evt-sensor-102"])
        self.assertEqual(retrieved.related_goals, ["goal-fitness-1", "goal-fatigue-2"])

    def test_get_nonexistent_returns_none(self) -> None:
        """Querying a non-existent situation ID returns None."""
        self.assertIsNone(self.situation_store.get("nonexistent_situation_id"))
        self.assertIsNone(self.situation_store.get(""))

    # --- 2. Updating Fields ---

    def test_update_situation(self) -> None:
        """Verify updating fields advances updated_at timestamp."""
        sit = self.situation_store.create(
            type="schedule_conflict",
            priority="medium",
            context={"conflict_count": 1},
        )
        initial_updated_at = sit.updated_at
        time.sleep(0.01)

        eval_time = datetime(2026, 8, 21, 14, 30, 0, tzinfo=timezone.utc)
        updated = self.situation_store.update(
            situation_id=sit.id,
            priority="critical",
            novelty=0.9,
            context={"conflict_count": 2, "overlap_minutes": 45},
            last_evaluated_at=eval_time,
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated.priority, "critical")
        self.assertEqual(updated.novelty, 0.9)
        self.assertEqual(updated.context["overlap_minutes"], 45)
        self.assertEqual(updated.last_evaluated_at, eval_time)
        self.assertGreater(updated.updated_at, initial_updated_at)

        # Verify persisted
        persisted = self.situation_store.get(sit.id)
        self.assertEqual(persisted.priority, "critical")
        self.assertEqual(persisted.novelty, 0.9)

    # --- 3. List Open & Close ---

    def test_list_open_and_close(self) -> None:
        """Verify list_open returns open situations and close marks situation as closed."""
        s1 = self.situation_store.create(type="travel_risk", priority="high")
        s2 = self.situation_store.create(type="prolonged_activity", priority="low")
        s3 = self.situation_store.create(type="unusual_state", priority="high", status="investigating")

        open_situations = self.situation_store.list_open()
        self.assertEqual(len(open_situations), 2)
        types = {s.type for s in open_situations}
        self.assertIn("travel_risk", types)
        self.assertIn("prolonged_activity", types)

        # Filter by priority
        high_open = self.situation_store.list_open(priority="high")
        self.assertEqual(len(high_open), 1)
        self.assertEqual(high_open[0].type, "travel_risk")

        # Close s1
        closed = self.situation_store.close(s1.id, resolution_notes="Flight rebooked successfully.")
        self.assertIsNotNone(closed)
        self.assertEqual(closed.status, "closed")
        self.assertEqual(closed.context["resolution_notes"], "Flight rebooked successfully.")

        open_after = self.situation_store.list_open()
        self.assertEqual(len(open_after), 1)
        self.assertEqual(open_after[0].type, "prolonged_activity")

    # --- 4. Expiration Sweep ---

    def test_expire_situations(self) -> None:
        """Verify expire sweeps situations whose expires_at is in the past."""
        past_expire = self.base_time - timedelta(minutes=10)
        future_expire = self.base_time + timedelta(hours=2)

        s_expiring = self.situation_store.create(
            type="temporary_traffic_delay",
            expires_at=past_expire,
            status="open",
        )
        s_persisting = self.situation_store.create(
            type="ongoing_project_risk",
            expires_at=future_expire,
            status="open",
        )
        s_no_expire = self.situation_store.create(
            type="lifestyle_shift",
            expires_at=None,
            status="open",
        )

        expired_list = self.situation_store.expire(as_of_time=self.base_time)
        self.assertEqual(len(expired_list), 1)
        self.assertEqual(expired_list[0].id, s_expiring.id)
        self.assertEqual(expired_list[0].status, "expired")

        # Verify in database
        check_s1 = self.situation_store.get(s_expiring.id)
        self.assertEqual(check_s1.status, "expired")

        check_s2 = self.situation_store.get(s_persisting.id)
        self.assertEqual(check_s2.status, "open")

        check_s3 = self.situation_store.get(s_no_expire.id)
        self.assertEqual(check_s3.status, "open")

    # --- 5. Deterministic Similarity Queries ---

    def test_find_similar(self) -> None:
        """Verify find_similar matches by type and/or shared related goals."""
        s1 = self.situation_store.create(
            type="schedule_conflict",
            related_goals=["goal-project-x", "goal-sleep-1"],
            status="open",
        )
        s2 = self.situation_store.create(
            type="schedule_conflict",
            related_goals=["goal-finance-1"],
            status="open",
        )
        s3 = self.situation_store.create(
            type="travel_risk",
            related_goals=["goal-project-x"],
            status="open",
        )
        s4 = self.situation_store.create(
            type="unrelated_alert",
            related_goals=["goal-other"],
            status="open",
        )

        # Match by type only
        same_type = self.situation_store.find_similar(situation_type="schedule_conflict")
        self.assertEqual(len(same_type), 2)
        self.assertEqual({s.id for s in same_type}, {s1.id, s2.id})

        # Match by shared goal "goal-project-x"
        shared_goal = self.situation_store.find_similar(related_goals=["goal-project-x"])
        self.assertEqual(len(shared_goal), 2)
        self.assertEqual({s.id for s in shared_goal}, {s1.id, s3.id})

    # --- 6. Arbitrary Situation Types ---

    def test_arbitrary_situation_types(self) -> None:
        """Verify support for arbitrary, domain-agnostic situation types."""
        types_to_test = [
            "unusual_state",
            "schedule_conflict",
            "travel_risk",
            "prolonged_activity",
            "custom_user_situation_99",
        ]
        created = []
        for t in types_to_test:
            sit = self.situation_store.create(type=t, context={"type_label": t})
            created.append(sit)

        self.assertEqual(len(created), 5)
        for i, t in enumerate(types_to_test):
            self.assertEqual(created[i].type, t)
            self.assertEqual(created[i].context["type_label"], t)


if __name__ == "__main__":
    unittest.main()
