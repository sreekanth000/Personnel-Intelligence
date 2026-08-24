"""
Unit and Integration Tests for Data Sources Status API, Hermes/Gmail Status Communication,
Last Successful Investigation Logging, and Epistemic Demarcation.
"""

from datetime import datetime, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from personal_intelligence.api.server import DashboardDataService
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.situations.models import Situation
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.hermes_bridge.capabilities import (
    CapabilityAuthStatus,
    CapabilityAvailability,
    CapabilityStatus,
    HermesConnectionStatus,
)
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesRuntimeBridge,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.connection_manager import (
    HermesConnectionManager,
    HermesHealthReport,
)
from personal_intelligence.storage.db import DatabaseManager


class TestDataSourcesPageAndStatus(unittest.TestCase):
    """
    Test suite for /api/pi/sources/status payload, Hermes & Gmail states,
    and accurate investigation logging without hardcoded false successes.
    """

    def setUp(self) -> None:
        set_active_hermes_context(None)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "sources_test.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.service = DashboardDataService(db_manager=self.db_manager)
        self.service.is_demo_mode = False

    def tearDown(self) -> None:
        set_active_hermes_context(None)
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Connected & Authenticated Hermes & Gmail State
    # -------------------------------------------------------------------------
    def test_connected_status_payload(self) -> None:
        """When Hermes and Gmail are fully connected and authenticated."""
        mock_context = MagicMock()
        mock_context.available_tools = [
            "gmail_search", "calendar_list_events", "drive_get_document",
            "meet_list_recent_meetings", "fs_read", "web_search", "llm_reasoning"
        ]
        mock_context.auth_status = {"gmail": "authenticated", "google": "authenticated"}

        self.service.hermes_client.bind_context(mock_context)
        self.service.connection_manager.bridge.bind_context(mock_context)

        payload = self.service.get_data_sources_payload()

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["hermes"]["status"], "connected")
        self.assertTrue(payload["hermes"]["is_reachable"])
        self.assertEqual(payload["gmail"]["status"], "connected")
        self.assertEqual(payload["gmail"]["managed_by"], "Hermes")
        self.assertEqual(payload["gmail"]["notice"], "Gmail connection and authentication are managed by Hermes.")
        self.assertEqual(payload["notice"], "Gmail connection and authentication are managed by Hermes.")
        self.assertIn("gmail", payload["capabilities"])
        self.assertEqual(payload["capabilities"]["gmail"]["availability"], "available")
        self.assertEqual(payload["capabilities"]["gmail"]["authenticated_status"], "authenticated")

    # -------------------------------------------------------------------------
    # 2. Unauthenticated Gmail State
    # -------------------------------------------------------------------------
    def test_unauthenticated_gmail_status_payload(self) -> None:
        """When Hermes is reachable but Gmail authentication is unauthenticated."""
        mock_context = MagicMock()
        mock_context.available_tools = ["gmail_search", "calendar_list_events"]
        mock_context.auth_status = {"gmail": "unauthenticated"}

        self.service.hermes_client.bind_context(mock_context)
        self.service.connection_manager.bridge.bind_context(mock_context)

        payload = self.service.get_data_sources_payload()

        self.assertEqual(payload["gmail"]["status"], "unauthenticated")
        self.assertIsNotNone(payload["actionable_instructions"])
        self.assertIn("hermes auth google", payload["actionable_instructions"])

    # -------------------------------------------------------------------------
    # 3. Disconnected / Unavailable Hermes State
    # -------------------------------------------------------------------------
    def test_disconnected_hermes_status_payload(self) -> None:
        """When Hermes host is disconnected and not attached."""
        payload = self.service.get_data_sources_payload()

        self.assertEqual(payload["hermes"]["status"], "disconnected")
        self.assertEqual(payload["gmail"]["status"], "unavailable")

    # -------------------------------------------------------------------------
    # 4. Demo Mode State & Explicit DEMO DATA Labeling
    # -------------------------------------------------------------------------
    def test_demo_mode_status_payload(self) -> None:
        """In DEMO mode, hermes and gmail report 'demo' status with demo markers."""
        self.service.is_demo_mode = True
        payload = self.service.get_data_sources_payload()

        self.assertEqual(payload["hermes"]["status"], "demo")
        self.assertEqual(payload["gmail"]["status"], "demo")
        self.assertTrue(payload["is_demo_mode"])

    # -------------------------------------------------------------------------
    # 5. Last Successful Investigation Logging
    # -------------------------------------------------------------------------
    def test_last_successful_gmail_investigation_tracking(self) -> None:
        """When a real Gmail observation is stored, last_successful_investigation reports metadata."""
        now = datetime.now(timezone.utc)
        evt = Event(
            id="evt-gmail-test-1",
            source="gmail",
            source_id="gmail:msg_888",
            observation_type="gmail_evidence_observation",
            timestamp=now,
            summary="Client deliverable review confirmation",
            structured_data={"summary": "Client deliverable review confirmation"},
            provenance={"tool": "gmail_search", "source_id": "gmail:msg_888"},
        )
        self.service.event_store.append(evt)

        payload = self.service.get_data_sources_payload()
        last_inv = payload["gmail"]["last_successful_investigation"]

        self.assertIsNotNone(last_inv)
        self.assertEqual(last_inv["tool"], "gmail_search")
        self.assertEqual(last_inv["provenance"], "gmail:msg_888")
        self.assertEqual(last_inv["summary"], "Client deliverable review confirmation")

    # -------------------------------------------------------------------------
    # 6. Absence of Hardcoded False Success Messages
    # -------------------------------------------------------------------------
    def test_no_hardcoded_gmail_investigated_without_actual_event(self) -> None:
        """Verifies pipeline payload does NOT output 'Gmail investigated' if no tool execution occurred."""
        now = datetime.now(timezone.utc)
        sit = self.service.situation_store.create_situation(
            type="possible_forgotten_commitment",
            priority="high",
            context={"summary": "Schedule conflict detected."},
        )

        # No Gmail events exist in EventStore
        report = self.service.get_situation_detail_payload(sit.id)
        investigations = report.get("investigation", {}).get("calls", [])

        # Confirm no hardcoded Gmail investigated call in LIVE mode when no event occurred
        gmail_calls = [inv for inv in investigations if inv.get("capability") == "Gmail"]
        self.assertEqual(len(gmail_calls), 0)


if __name__ == "__main__":
    unittest.main()
