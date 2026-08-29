"""
Unit tests for Goal satisfaction_criteria and Commitment last_activity (Blueprint §9, §10).
"""

from datetime import datetime, timedelta, timezone
import unittest

from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.world.models import Commitment, CommitmentStatus, FactProvenance


class TestGoalAndCommitmentFields(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 8, 29, 10, 0, 0, tzinfo=timezone.utc)

    def test_goal_satisfaction_criteria_serialization(self) -> None:
        """Verify Goal.satisfaction_criteria field serialization and deserialization."""
        goal = Goal(
            name="Deploy V1 Release",
            description="Complete the personal intelligence engine V1",
            priority=GoalPriority.HIGH.value,
            satisfaction_criteria="All 49 blueprint sections satisfied and test suite passes 100%",
        )
        d = goal.to_dict()
        self.assertEqual(d["satisfaction_criteria"], "All 49 blueprint sections satisfied and test suite passes 100%")

        restored = Goal.from_dict(d)
        self.assertEqual(restored.satisfaction_criteria, "All 49 blueprint sections satisfied and test suite passes 100%")

    def test_commitment_last_activity_serialization(self) -> None:
        """Verify Commitment.last_activity field serialization and deserialization."""
        prov = FactProvenance(origin_source="gmail", source_id="msg_999")
        commitment = Commitment(
            description="Send Q3 roadmap to VP",
            status=CommitmentStatus.PENDING.value,
            due_at=self.base_time + timedelta(days=2),
            last_activity=self.base_time,
            provenance=prov,
        )
        d = commitment.to_dict()
        self.assertIsNotNone(d["last_activity"])

        restored = Commitment.from_dict(d)
        self.assertEqual(restored.last_activity, self.base_time)
        self.assertEqual(restored.description, "Send Q3 roadmap to VP")


if __name__ == "__main__":
    unittest.main()
