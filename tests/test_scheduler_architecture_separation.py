"""
Acceptance Test Suite for Scheduler Architecture Separation.

Verifies the strict separation between:
1. HERMES EXTERNAL OBSERVATION SCHEDULER (Hermes owns all external acquisition)
   External World -> Hermes Connectors -> Hermes Scheduled Observations -> PI record_observation()
2. PI LOCAL MAINTENANCE SCHEDULER (PI owns local maintenance only)
   Local Event Store -> Local Memory Maintenance -> Situation Re-evaluation -> Local DB optimization

Acceptance Criteria:
- PI contains zero external polling loops.
- PI contains zero connector-specific schedulers.
- PI contains zero OAuth scheduling.
- Hermes can schedule Gmail/Calendar/etc. observations.
- Hermes sends acquired observations through record_observation().
- PI can independently schedule local maintenance.
- No duplicate scheduler executes the same external acquisition.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import unittest
from unittest.mock import MagicMock, patch
import warnings

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.loop import PersonalIntelligenceEvaluationLoop
from personal_intelligence.core.scheduler.local_maintenance import (
    BackgroundSyncScheduler,
    LocalMaintenanceScheduler,
)
from personal_intelligence.hermes_bridge.scheduler import (
    ConnectorNormalizer,
    HermesObservationScheduler,
)
from personal_intelligence.scheduler.daemon import (
    LocalEvaluationDaemon,
    PollingDaemon,
    SourcePoller,
)
from personal_intelligence.storage.db import DatabaseManager


class TestSchedulerArchitectureSeparation(unittest.TestCase):

    def setUp(self) -> None:
        self.db = DatabaseManager(":memory:")
        self.db.initialize_schema()
        self.event_store = EventStore(self.db)
        self.loop = PersonalIntelligenceEvaluationLoop(db_manager=self.db)

    def test_pi_contains_zero_external_polling_loops(self) -> None:
        """Verify PI's LocalEvaluationDaemon defaults to zero external pollers and purely evaluates local state."""
        daemon = LocalEvaluationDaemon(loop=self.loop, interval_minutes=5)
        self.assertEqual(len(daemon.source_pollers), 0)

        # Running a cycle without legacy pollers evaluates purely local state
        with patch.object(self.loop, "run_cycle", wraps=self.loop.run_cycle) as mock_run_cycle:
            daemon.run_once()
            mock_run_cycle.assert_called_once_with(incoming_events=None)

    def test_pi_contains_zero_connector_specific_schedulers(self) -> None:
        """Verify LocalMaintenanceScheduler has zero connector-specific methods (no Gmail/Calendar polling)."""
        scheduler = LocalMaintenanceScheduler(maintenance_interval_minutes=15)
        # Ensure forbidden connector-specific methods do not exist on PI's maintenance scheduler
        self.assertFalse(hasattr(scheduler, "sweep_gmail"))
        self.assertFalse(hasattr(scheduler, "sweep_calendar"))
        self.assertFalse(hasattr(scheduler, "poll_gmail"))
        self.assertFalse(hasattr(scheduler, "poll_calendar"))
        self.assertFalse(hasattr(scheduler, "poll_slack"))

        status = scheduler.get_status()
        self.assertEqual(status["scheduler_type"], "local_pi_maintenance_only")
        self.assertFalse(status["external_polling"])

    def test_pi_contains_zero_oauth_scheduling(self) -> None:
        """Verify PI schedulers do not handle OAuth token refresh or credential scheduling."""
        scheduler = LocalMaintenanceScheduler(maintenance_interval_minutes=15)
        self.assertFalse(hasattr(scheduler, "refresh_oauth_tokens"))
        self.assertFalse(hasattr(scheduler, "oauth_refresh_job"))

        daemon = LocalEvaluationDaemon(loop=self.loop, interval_minutes=5)
        self.assertFalse(hasattr(daemon, "refresh_oauth"))

    def test_hermes_can_schedule_gmail_and_calendar_observations(self) -> None:
        """Verify HermesObservationScheduler owns external Gmail and Calendar sweeps."""
        mock_gmail = MagicMock(return_value=[
            {
                "id": "msg-sched-001",
                "subject": "Quarterly Planning",
                "from": "manager@company.com",
                "date": "2026-09-03T10:00:00Z",
                "snippet": "Let's align on Q4 deliverables.",
            }
        ])
        mock_calendar = MagicMock(return_value=[
            {
                "id": "cal-sched-001",
                "summary": "1:1 with Manager",
                "start": {"dateTime": "2026-09-03T14:00:00Z"},
                "end": {"dateTime": "2026-09-03T14:30:00Z"},
            }
        ])

        hermes_scheduler = HermesObservationScheduler(
            event_store=self.event_store,
            gmail_connector_fn=mock_gmail,
            calendar_connector_fn=mock_calendar,
            poll_interval_seconds=900,
        )

        gmail_res = hermes_scheduler.sweep_gmail()
        self.assertEqual(gmail_res["status"], "success")
        self.assertEqual(gmail_res["ingested_count"], 1)

        cal_res = hermes_scheduler.sweep_calendar()
        self.assertEqual(cal_res["status"], "success")
        self.assertEqual(cal_res["ingested_count"], 1)

        # Verify Hermes schedules.yaml contains explicit external observation schedules
        schedules_path = Path(__file__).resolve().parent.parent / "personal_intelligence" / "hermes_bridge" / "cron" / "schedules.yaml"
        with open(schedules_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("scheduled_gmail_observation", content)
        self.assertIn("scheduled_calendar_observation", content)
        self.assertIn("pi_local_intelligence_evaluation", content)
        self.assertIn("pi_memory_maintenance", content)

    def test_hermes_sends_acquired_observations_through_record_observation(self) -> None:
        """Verify Hermes scheduler normalizes observations and records them into EventStore."""
        raw_message = {
            "id": "msg-norm-999",
            "subject": "System Status Update",
            "from": "devops@company.com",
            "date": "2026-09-03T11:00:00Z",
            "snippet": "All services nominal.",
        }
        normalized = ConnectorNormalizer.normalize_gmail_observation(raw_message)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["source"], "gmail")
        self.assertEqual(normalized["source_id"], "msg-norm-999")
        self.assertEqual(normalized["observation_type"], "email_received")

        hermes_scheduler = HermesObservationScheduler(
            event_store=self.event_store,
            gmail_connector_fn=lambda: [raw_message],
        )
        res = hermes_scheduler.sweep_gmail()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ingested_count"], 1)

        # Check that observation is persisted in PI's EventStore
        event = self.event_store.get_by_source_id("gmail", "msg-norm-999")
        self.assertIsNotNone(event)
        self.assertEqual(event.source_id, "msg-norm-999")
        self.assertEqual(event.event_type, "email_received")

    def test_pi_can_independently_schedule_local_maintenance(self) -> None:
        """Verify PI can schedule and run local maintenance without Hermes or Hive UI."""
        maintenance_runs = []

        def local_maintenance_task() -> Dict[str, Any]:
            maintenance_runs.append(datetime.now(timezone.utc))
            return {
                "high_priority_situations": [],
                "total_active_situations": 0,
            }

        scheduler = LocalMaintenanceScheduler(
            maintenance_interval_minutes=30,
            maintenance_callback=local_maintenance_task,
            auto_start=False,
        )

        res = scheduler.trigger_now()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["cycle_number"], 1)
        self.assertEqual(len(maintenance_runs), 1)
        self.assertEqual(scheduler.maintenance_count, 1)

    def test_no_duplicate_scheduler_executes_same_external_acquisition(self) -> None:
        """Verify PI's LocalMaintenanceScheduler and HermesObservationScheduler have mutually exclusive responsibilities."""
        pi_scheduler = LocalMaintenanceScheduler(maintenance_interval_minutes=30)
        hermes_scheduler = HermesObservationScheduler(event_store=self.event_store)

        # PI scheduler handles only local maintenance
        self.assertTrue(hasattr(pi_scheduler, "maintenance_interval_minutes"))
        self.assertFalse(hasattr(pi_scheduler, "gmail_connector_fn"))
        self.assertFalse(hasattr(pi_scheduler, "calendar_connector_fn"))

        # Hermes scheduler handles external observation sweeps
        self.assertTrue(hasattr(hermes_scheduler, "gmail_connector_fn"))
        self.assertTrue(hasattr(hermes_scheduler, "calendar_connector_fn"))
        self.assertTrue(hasattr(hermes_scheduler, "sweep_gmail"))
        self.assertTrue(hasattr(hermes_scheduler, "sweep_calendar"))

    def test_deprecation_and_backward_compatibility_aliases(self) -> None:
        """Verify backward compatibility aliases and deprecation warnings."""
        # 1. BackgroundSyncScheduler is an alias for LocalMaintenanceScheduler
        self.assertIs(BackgroundSyncScheduler, LocalMaintenanceScheduler)

        # 2. Importing background_sync module emits a DeprecationWarning
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import personal_intelligence.core.scheduler.background_sync as bsync_mod
            importlib.reload(bsync_mod)
            self.assertTrue(any(issubclass(item.category, DeprecationWarning) for item in w))

        # 3. PollingDaemon is an alias for LocalEvaluationDaemon
        self.assertIs(PollingDaemon, LocalEvaluationDaemon)

        # 4. Calling register_source emits a DeprecationWarning
        daemon = LocalEvaluationDaemon(loop=self.loop, interval_minutes=5)
        class DummyPoller(SourcePoller):
            name = "dummy"
            def poll(self) -> List[Event]:
                return []

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            daemon.register_source(DummyPoller())
            self.assertTrue(any(issubclass(item.category, DeprecationWarning) for item in w))


if __name__ == "__main__":
    unittest.main()
