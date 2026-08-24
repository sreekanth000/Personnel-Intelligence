"""
Unit and Integration Tests for Background Sync Scheduler & Native Desktop Notifications.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from personal_intelligence.core.notifications.notifier import DesktopNotifier, send_desktop_alert
from personal_intelligence.core.scheduler.background_sync import BackgroundSyncScheduler
from personal_intelligence.api.server import DashboardDataService
from personal_intelligence.storage.db import DatabaseManager


class TestDesktopNotifier(unittest.TestCase):
    """Tests for native desktop notification provider."""

    def test_notifier_initialization(self) -> None:
        notifier = DesktopNotifier(app_name="TestApp")
        self.assertEqual(notifier.app_name, "TestApp")
        self.assertIsNotNone(notifier.os_type)

    @patch("subprocess.run")
    def test_send_desktop_notification_dispatch(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        notifier = DesktopNotifier()
        success = notifier._send_sync(
            title="Security Alert",
            message="Suspicious activity detected on Google account",
            priority="high",
        )
        self.assertTrue(success)


class TestBackgroundSyncScheduler(unittest.TestCase):
    """Tests for periodic background sync and triage scheduler."""

    def test_scheduler_lifecycle_and_trigger(self) -> None:
        dispatched_notifications = []

        class DummyNotifier(DesktopNotifier):
            def send(self, title: str, message: str, priority: str = "high", timeout_seconds: int = 7) -> bool:
                dispatched_notifications.append({"title": title, "message": message, "priority": priority})
                return True

        dummy_notifier = DummyNotifier()

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

        scheduler = BackgroundSyncScheduler(
            sync_interval_minutes=15,
            sync_callback=mock_cb,
            notifier=dummy_notifier,
            auto_start=False,
        )

        status = scheduler.get_status()
        self.assertFalse(status["is_running"])
        self.assertEqual(status["sync_interval_minutes"], 15)

        # Trigger manual sync cycle
        res = scheduler.trigger_now()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["high_priority_detected"], 1)
        self.assertEqual(res["notifications_dispatched"], 1)
        self.assertEqual(len(dispatched_notifications), 1)
        self.assertIn("Google Security Alert", dispatched_notifications[0]["title"])

        # Second sync with same situation ID should deduplicate and NOT send second notification
        res2 = scheduler.trigger_now()
        self.assertEqual(res2["status"], "success")
        self.assertEqual(res2["notifications_dispatched"], 0)
        self.assertEqual(len(dispatched_notifications), 1)

    def test_dashboard_service_sync_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_sync.db"
            db = DatabaseManager(db_path=str(db_path))
            ds = DashboardDataService(db_manager=db, sync_interval_minutes=20)

            # Test sync status endpoint payload
            status = ds.get_sync_status_payload()
            self.assertTrue(status["is_running"])
            self.assertEqual(status["sync_interval_minutes"], 20)

            # Test test notification trigger
            notify_res = ds.trigger_test_notification()
            self.assertEqual(notify_res["status"], "success")

            # Clean shutdown
            ds.bg_scheduler.stop()


if __name__ == "__main__":
    unittest.main()
