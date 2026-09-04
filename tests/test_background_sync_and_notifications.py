"""
Unit and Integration Tests for Local Maintenance Scheduler.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from personal_intelligence.core.scheduler.local_maintenance import LocalMaintenanceScheduler, BackgroundSyncScheduler
from personal_intelligence.api.server import DashboardDataService
from personal_intelligence.storage.db import DatabaseManager


class TestLocalMaintenanceScheduler(unittest.TestCase):
    """Tests for local maintenance scheduler and situation triage."""

    def test_scheduler_lifecycle_and_trigger(self) -> None:
        mock_cb = MagicMock(return_value={
            "high_priority_situations": [
                {
                    "id": "sit-test-sec-01",
                    "title": "Google Security Alert",
                    "summary": "Urgent review required",
                    "priority": "high",
                    "context": {"summary": "Google Security Alert", "why_detected": "New login from unknown location"},
                }
            ],
            "total_active_situations": 1,
        })

        scheduler = LocalMaintenanceScheduler(
            maintenance_interval_minutes=15,
            maintenance_callback=mock_cb,
            auto_start=False,
        )

        status = scheduler.get_status()
        self.assertFalse(status["is_running"])
        self.assertEqual(status["maintenance_interval_minutes"], 15)

        # Trigger manual maintenance cycle
        res = scheduler.trigger_now()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["high_priority_detected"], 1)
        self.assertEqual(res["notifications_dispatched"], 1)

        # Second maintenance with same situation ID should deduplicate
        res2 = scheduler.trigger_now()
        self.assertEqual(res2["status"], "success")
        self.assertEqual(res2["notifications_dispatched"], 0)

    def test_dashboard_service_sync_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_sync.db"
            db = DatabaseManager(db_path=str(db_path))
            ds = DashboardDataService(db_manager=db, sync_interval_minutes=20)

            # Test sync status endpoint payload
            status = ds.get_sync_status_payload()
            self.assertTrue(status["is_running"])
            self.assertEqual(status["sync_interval_minutes"], 20)

            # Test test notification trigger payload
            notify_res = ds.trigger_test_notification()
            self.assertEqual(notify_res["status"], "success")

            # Clean shutdown
            ds.bg_scheduler.stop()


if __name__ == "__main__":
    unittest.main()

