"""
Unit tests for minimal Personal Goals model and GoalStore.
Tests goal creation, updates, querying, archiving, and arbitrary goal seeds.
"""

from datetime import datetime, timezone
import os
import tempfile
import time
import unittest

from personal_intelligence.core.goals import (
    Goal,
    GoalPriority,
    GoalStatus,
    GoalStore,
)
from personal_intelligence.storage.db import DatabaseManager


class TestPersonalGoals(unittest.TestCase):
    """Test suite for minimal Goal model and GoalStore."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_goals.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.goal_store = GoalStore(db_manager=self.db_manager)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_goal_defaults(self) -> None:
        """Verify creating a goal with default priority and status."""
        goal = self.goal_store.create_goal(
            name="Improve fitness",
            description="Exercise 3 times a week and maintain cardiovascular stamina.",
        )
        self.assertIsNotNone(goal.id)
        self.assertEqual(goal.name, "Improve fitness")
        self.assertEqual(goal.priority, "medium")
        self.assertEqual(goal.status, "active")
        self.assertIsNotNone(goal.created_at)
        self.assertIsNotNone(goal.updated_at)

        # Retrieve and verify persistence
        retrieved = self.goal_store.get_goal(goal.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "Improve fitness")
        self.assertEqual(retrieved.description, goal.description)
        self.assertEqual(retrieved.status, "active")

    def test_create_goal_custom_priority_and_status(self) -> None:
        """Verify creating a goal with custom priority and status."""
        goal = self.goal_store.create_goal(
            name="Complete project",
            description="Deliver release milestone before end of sprint.",
            priority=GoalPriority.CRITICAL.value,
            status=GoalStatus.ACTIVE.value,
        )
        self.assertEqual(goal.priority, "critical")
        self.assertEqual(goal.status, "active")

    def test_update_goal_fields_and_timestamp(self) -> None:
        """Verify updating goal fields updates updated_at timestamp."""
        goal = self.goal_store.create_goal(
            name="Reduce work fatigue",
            description="Take short breaks every 90 minutes.",
            priority="medium",
        )
        initial_updated_at = goal.updated_at

        # Sleep briefly to ensure updated_at timestamp advances
        time.sleep(0.01)

        updated = self.goal_store.update_goal(
            goal_id=goal.id,
            description="Take regular stretch breaks and disengage after 7pm.",
            priority="high",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.description, "Take regular stretch breaks and disengage after 7pm.")
        self.assertEqual(updated.priority, "high")
        self.assertEqual(updated.name, "Reduce work fatigue")  # Unchanged
        self.assertGreater(updated.updated_at, initial_updated_at)

        # Verify persisted state
        persisted = self.goal_store.get_goal(goal.id)
        self.assertEqual(persisted.priority, "high")
        self.assertEqual(persisted.description, "Take regular stretch breaks and disengage after 7pm.")

    def test_update_nonexistent_goal_returns_none(self) -> None:
        """Updating a non-existent goal returns None."""
        res = self.goal_store.update_goal("nonexistent_id", name="New Name")
        self.assertIsNone(res)

    def test_list_active_goals_and_archive(self) -> None:
        """Verify list_active_goals returns only active goals, and archiving removes it from active list."""
        g1 = self.goal_store.create_goal(name="Improve fitness", priority="high")
        g2 = self.goal_store.create_goal(name="Reduce work fatigue", priority="medium")
        g3 = self.goal_store.create_goal(name="Travel without missing commitments", priority="low", status="paused")

        active_goals = self.goal_store.list_active_goals()
        self.assertEqual(len(active_goals), 2)
        active_names = {g.name for g in active_goals}
        self.assertIn("Improve fitness", active_names)
        self.assertIn("Reduce work fatigue", active_names)
        self.assertNotIn("Travel without missing commitments", active_names)

        # Archive g1
        archived = self.goal_store.archive_goal(g1.id)
        self.assertIsNotNone(archived)
        self.assertEqual(archived.status, "archived")

        active_after = self.goal_store.list_active_goals()
        self.assertEqual(len(active_after), 1)
        self.assertEqual(active_after[0].name, "Reduce work fatigue")

    def test_seed_arbitrary_goals(self) -> None:
        """Verify seeding diverse, arbitrary goals as contextual inputs."""
        seed_goals = [
            ("Improve fitness", "Maintain regular weekly exercise and sleep discipline", "high"),
            ("Reduce work fatigue", "Enforce boundaries around late evening screen time", "high"),
            ("Complete project", "Finalize Personal Intelligence system deliverables", "critical"),
            ("Travel without missing commitments", "Coordinate calendar and travel transitions smoothly", "medium"),
        ]

        created_ids = []
        for name, desc, priority in seed_goals:
            g = self.goal_store.create_goal(name=name, description=desc, priority=priority)
            created_ids.append(g.id)

        all_active = self.goal_store.list_active_goals()
        self.assertEqual(len(all_active), 4)

        names = [g.name for g in all_active]
        self.assertEqual(names, [s[0] for s in seed_goals])

        # Test dictionary serialization
        sample_dict = all_active[0].to_dict()
        self.assertEqual(sample_dict["name"], "Improve fitness")
        self.assertEqual(sample_dict["priority"], "high")
        self.assertIn("created_at", sample_dict)
        self.assertIn("updated_at", sample_dict)


if __name__ == "__main__":
    unittest.main()
