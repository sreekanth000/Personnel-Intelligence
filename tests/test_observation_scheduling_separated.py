"""
Unit & Integration Tests for Hermes-Owned Observation Scheduling (Prompt 4).

Verifies:
1. Scheduled Gmail observation acquisition via Hermes
2. Scheduled Calendar observation acquisition via Hermes
3. Connector normalizer standardizes raw outputs
4. Normalized observations inserted into EventStore
5. Duplicate observations safely prevented
6. Source failures handled gracefully without crashing
7. Authentication failures safely reported without exposing OAuth credentials
8. Malformed connector payloads safely filtered out
9. Scheduler operates headlessly when Hive UI is closed
10. No duplicate connector implementations exist in PI
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.store import EventStore
from personal_intelligence.hermes_bridge.scheduler import (
    ConnectorNormalizer,
    HermesObservationScheduler,
)
from personal_intelligence.storage.db import DatabaseManager


class TestObservationSchedulingSeparated(unittest.TestCase):
    """Test suite for Prompt 4 scheduler separation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_sched_sep.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.event_store = EventStore(db_manager=self.db_manager)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_1_scheduled_gmail_observation(self) -> None:
        """Requirement 1: Scheduled sweep of Gmail via Hermes connector delivers observations."""
        mock_gmail_data = [
            {
                "id": "msg-101",
                "date": "2026-09-02T10:00:00Z",
                "subject": "Q3 Planning Meeting",
                "from": "alice@company.com",
                "snippet": "Let's align on Q3 roadmap goals tomorrow at 10 AM.",
            }
        ]

        scheduler = HermesObservationScheduler(
            event_store=self.event_store,
            gmail_connector_fn=lambda: mock_gmail_data,
        )

        res = scheduler.sweep_gmail()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ingested_count"], 1)

        # Verify event was stored in EventStore
        events = self.event_store.query_by_time()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, "gmail")
        self.assertEqual(events[0].source_id, "msg-101")
        self.assertIn("Q3 Planning Meeting", events[0].payload.get("summary", ""))

    def test_2_scheduled_calendar_observation(self) -> None:
        """Requirement 2: Scheduled sweep of Calendar via Hermes connector delivers observations."""
        mock_calendar_data = [
            {
                "id": "cal-202",
                "start": {"dateTime": "2026-09-02T14:30:00Z"},
                "summary": "Product Design Sync",
                "location": "Virtual Room 4",
                "attendees": [{"email": "bob@company.com"}],
            }
        ]

        scheduler = HermesObservationScheduler(
            event_store=self.event_store,
            calendar_connector_fn=lambda: mock_calendar_data,
        )

        res = scheduler.sweep_calendar()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ingested_count"], 1)

        # Verify event was stored in EventStore
        events = self.event_store.query_by_time()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, "google_calendar")
        self.assertEqual(events[0].source_id, "cal-202")
        self.assertIn("Product Design Sync", events[0].payload.get("summary", ""))

    def test_3_normalization(self) -> None:
        """Requirement 3: ConnectorNormalizer enforces clean, typed observation representation."""
        raw_gmail = {
            "id": "msg-303",
            "date": "2026-09-02T12:00:00Z",
            "subject": "Invoice Paid",
            "from": "billing@vendor.com",
            "snippet": "Your payment of $120.00 has cleared.",
        }

        norm = ConnectorNormalizer.normalize_gmail_observation(raw_gmail)
        self.assertIsNotNone(norm)
        self.assertEqual(norm["source"], "gmail")
        self.assertEqual(norm["source_id"], "msg-303")
        self.assertEqual(norm["observation_type"], "email_received")
        self.assertEqual(norm["provenance"]["tool"], "hermes_gmail_connector")
        self.assertEqual(norm["confidence"], 1.0)

    def test_4_eventstore_insertion(self) -> None:
        """Requirement 4: Observations are written directly to EventStore with full provenance."""
        mock_data = [
            {"id": "msg-404", "date": "2026-09-02T08:00:00Z", "subject": "Test Insertion", "from": "test@test.com"}
        ]
        scheduler = HermesObservationScheduler(
            event_store=self.event_store,
            gmail_connector_fn=lambda: mock_data,
        )
        scheduler.sweep_gmail()

        stored = self.event_store.get_by_source_id(source="gmail", source_id="msg-404")
        self.assertIsNotNone(stored)
        self.assertEqual(stored.event_type, "email_received")
        self.assertEqual(stored.provenance.get("tool"), "hermes_gmail_connector")

    def test_5_duplicate_prevention(self) -> None:
        """Requirement 5: Repeated sweeps with identical items do not create duplicate events."""
        mock_data = [
            {"id": "msg-dup-01", "date": "2026-09-02T09:00:00Z", "subject": "Repeat Message", "from": "test@test.com"}
        ]
        scheduler = HermesObservationScheduler(
            event_store=self.event_store,
            gmail_connector_fn=lambda: mock_data,
        )

        res1 = scheduler.sweep_gmail()
        self.assertEqual(res1["ingested_count"], 1)
        self.assertEqual(res1["duplicates_count"], 0)

        # Second sweep with identical data
        res2 = scheduler.sweep_gmail()
        self.assertEqual(res2["ingested_count"], 0)
        self.assertEqual(res2["duplicates_count"], 1)

        # Confirm only one event stored
        events = self.event_store.query_by_time()
        self.assertEqual(len(events), 1)

    def test_6_source_failure(self) -> None:
        """Requirement 6: External source connection error is handled safely without crashing."""
        def failing_connector():
            raise ConnectionError("Network timeout connecting to external API")

        scheduler = HermesObservationScheduler(
            event_store=self.event_store,
            gmail_connector_fn=failing_connector,
        )

        res = scheduler.sweep_gmail()
        self.assertEqual(res["status"], "source_error")
        self.assertIn("Network timeout", res["error"])
        telemetry = scheduler.get_telemetry()
        self.assertEqual(telemetry["errors"], 1)
        self.assertEqual(telemetry["gmail_status"], "error")

    def test_7_authentication_failure(self) -> None:
        """Requirement 7: Authentication failure is safely reported without exposing OAuth credentials."""
        def unauthenticated_connector():
            raise PermissionError("OAuth token expired or revoked. Reauthentication required.")

        scheduler = HermesObservationScheduler(
            event_store=self.event_store,
            calendar_connector_fn=unauthenticated_connector,
        )

        res = scheduler.sweep_calendar()
        self.assertEqual(res["status"], "auth_required")
        self.assertIn("OAuth token expired", res["error"])
        telemetry = scheduler.get_telemetry()
        self.assertEqual(telemetry["auth_failures"], 1)
        self.assertEqual(telemetry["calendar_status"], "auth_required")

    def test_8_malformed_connector_result(self) -> None:
        """Requirement 8: Malformed connector outputs (missing IDs, non-dict) are safely filtered out."""
        malformed_data = [
            "not a dict",
            {"missing_id": True, "subject": "No ID here"},
            {"id": "", "subject": "Empty ID"},
            {"id": "valid-msg-888", "subject": "Valid item", "from": "sender@test.com"},
        ]

        scheduler = HermesObservationScheduler(
            event_store=self.event_store,
            gmail_connector_fn=lambda: malformed_data,
        )

        res = scheduler.sweep_gmail()
        self.assertEqual(res["status"], "success")
        # Only the 1 valid item is ingested
        self.assertEqual(res["ingested_count"], 1)

        stored = self.event_store.get_by_source_id(source="gmail", source_id="valid-msg-888")
        self.assertIsNotNone(stored)

    def test_9_hive_closed_headless_execution(self) -> None:
        """Requirement 9: Scheduler runs headlessly in background without any UI active."""
        call_count = [0]

        def headless_connector():
            call_count[0] += 1
            return [{"id": f"msg-headless-{call_count[0]}", "subject": "Headless Email"}]

        scheduler = HermesObservationScheduler(
            event_store=self.event_store,
            gmail_connector_fn=headless_connector,
            poll_interval_seconds=1,
        )

        # Start daemon thread and let it run
        scheduler.start()
        import time
        time.sleep(1.2)
        scheduler.stop()

        self.assertGreater(call_count[0], 0)
        events = self.event_store.query_by_time()
        self.assertGreater(len(events), 0)

    def test_10_no_duplicate_connector_implementation(self) -> None:
        """Requirement 10: PI does not contain duplicate Gmail/Calendar connector implementations."""
        # Ensure PI core does not own external API clients or OAuth storage
        import personal_intelligence.core as pi_core
        core_attrs = dir(pi_core)
        self.assertNotIn("GmailClient", core_attrs)
        self.assertNotIn("CalendarClient", core_attrs)
        self.assertNotIn("OAuthManager", core_attrs)


if __name__ == "__main__":
    unittest.main()
