"""
Complete Hermes/Gmail Connection Verification Suite.

Validates all 8 mandatory scenarios:
1. No Hermes installation or runtime → disconnected.
2. Hermes health endpoint responds but no runtime context exists → gateway_detected, not connected.
3. Runtime attached but no Gmail tool → Hermes connected; Gmail unavailable.
4. Runtime attached, Gmail tool available, auth unknown → Gmail unknown; Gmail queries blocked.
5. Runtime attached, Gmail tool available, Gmail unauthenticated → Gmail unauthenticated; show Hermes-managed setup guidance.
6. Runtime attached, Gmail authenticated → Gmail authenticated; a bounded read-only gmail_search succeeds.
7. Any Gmail send, delete, archive, label, draft, trash, or modify attempt is rejected.
8. Dashboard never claims Gmail was investigated without a recorded real Hermes tool result and provenance.
"""

from datetime import datetime, timezone
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from personal_intelligence.hermes_bridge.capabilities import (
    CapabilityAuthStatus,
    CapabilityAvailability,
    HermesCapabilityInspector,
    HermesConnectionStage,
    HermesConnectionStatus,
)
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesRuntimeBridge,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.connection_manager import (
    HermesConnectionManager,
    HermesFailureCategory,
)
from personal_intelligence.hermes_bridge.gmail_adapter import (
    ALLOWED_READ_ONLY_GMAIL_TOOLS,
    PROHIBITED_MUTATION_GMAIL_TOOLS,
    GmailCapabilityAdapter,
    GmailCapabilityRequest,
    HermesGmailResult,
)
from personal_intelligence.security.guard import UnauthorizedWriteOperationError
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.api.server import DashboardDataService
import os


class TestHermesGmailVerificationSuite(unittest.TestCase):
    """
    Exhaustive verification suite for Hermes and Gmail connection, authentication,
    boundary enforcement, and dashboard reporting invariants.
    """

    def setUp(self) -> None:
        set_active_hermes_context(None)
        self.bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        self.manager = HermesConnectionManager(bridge=self.bridge)
        self.adapter = GmailCapabilityAdapter(bridge=self.bridge)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "verify_test.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.service = DashboardDataService(db_manager=self.db_manager)
        self.service.is_demo_mode = False

    def tearDown(self) -> None:
        set_active_hermes_context(None)
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Scenario 1: No Hermes installation or runtime → disconnected
    # -------------------------------------------------------------------------
    def test_scenario_1_no_hermes_installation_or_runtime_disconnected(self) -> None:
        """Scenario 1: When no Hermes installation or runtime context exists, reports disconnected."""
        with patch.object(self.manager, "detect_installation") as mock_detect, \
             patch.object(self.manager, "check_reachability") as mock_reach:
            from personal_intelligence.hermes_bridge.connection_manager import HermesInstallationInfo, HermesReachabilityInfo
            mock_detect.return_value = HermesInstallationInfo(is_installed=False, binary_path=None, detection_mechanism="not_found")
            mock_reach.return_value = HermesReachabilityInfo(
                is_reachable=False,
                mechanism="none",
                execution_capable=False,
                failure_category=HermesFailureCategory.CONNECTION_REFUSED.value,
            )

            health = self.manager.check_health()
            self.assertEqual(health.connection_status, HermesConnectionStatus.DISCONNECTED)
            self.assertEqual(health.connection_stage, HermesConnectionStage.DISCONNECTED)
            self.assertFalse(health.is_reachable)
            self.assertFalse(health.runtime_attached)
            self.assertFalse(health.gateway_reachable)
            self.assertEqual(health.failure_category, HermesFailureCategory.CONNECTION_REFUSED.value)

            # Gmail status in payload is unavailable
            payload = self.service.get_data_sources_payload()
            self.assertEqual(payload["hermes"]["status"], "disconnected")
            self.assertEqual(payload["gmail"]["status"], "unavailable")

    # -------------------------------------------------------------------------
    # Scenario 2: Gateway responds but no runtime context → gateway_detected, not connected
    # -------------------------------------------------------------------------
    @patch("urllib.request.urlopen")
    def test_scenario_2_gateway_detected_not_connected_without_runtime(self, mock_urlopen: MagicMock) -> None:
        """Scenario 2: Responding health endpoint alone yields gateway_detected, never connected."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        reach = self.manager.check_reachability()
        self.assertTrue(reach.is_reachable)
        self.assertEqual(reach.mechanism, "gateway")
        self.assertFalse(reach.execution_capable)

        health = self.manager.check_health()
        self.assertEqual(health.connection_stage, HermesConnectionStage.GATEWAY_DETECTED)
        # Stage model contract: gateway_detected maps to DISCONNECTED
        self.assertEqual(health.connection_status, HermesConnectionStatus.DISCONNECTED)
        self.assertTrue(health.gateway_reachable)
        self.assertFalse(health.runtime_attached)
        self.assertFalse(health.capabilities_discovered)
        self.assertFalse(health.gmail_authenticated)
        self.assertEqual(health.failure_category, HermesFailureCategory.RUNTIME_NOT_ATTACHED.value)

        # Inquiries are rejected because no execution-capable context is attached
        req = GmailCapabilityRequest(query="urgent deliverable")
        res = self.adapter.execute_query(req)
        self.assertEqual(res.status, "unavailable")
        self.assertIn("Host Hermes runtime context is not attached", res.error or "")

    # -------------------------------------------------------------------------
    # Scenario 3: Runtime attached but no Gmail tool → Hermes connected; Gmail unavailable
    # -------------------------------------------------------------------------
    def test_scenario_3_runtime_attached_no_gmail_tool_gmail_unavailable(self) -> None:
        """Scenario 3: When runtime context lacks Gmail tools, Hermes is connected but Gmail is unavailable."""
        mock_context = MagicMock()
        mock_context.available_tools = ["calendar_list_events", "fs_read"]
        mock_context.auth_status = {"calendar": "authenticated"}

        self.bridge.bind_context(mock_context)
        self.service.connection_manager.bridge.bind_context(mock_context)

        health = self.manager.check_health()
        self.assertEqual(health.connection_status, HermesConnectionStatus.CONNECTED)
        self.assertEqual(health.connection_stage, HermesConnectionStage.CAPABILITIES_DISCOVERED)
        self.assertTrue(health.runtime_attached)

        gmail_cap = health.capabilities.get("gmail", {})
        self.assertEqual(gmail_cap.get("availability"), "unavailable")
        self.assertEqual(gmail_cap.get("failure_category"), HermesFailureCategory.CAPABILITY_NOT_DECLARED.value)

        payload = self.service.get_data_sources_payload()
        self.assertEqual(payload["hermes"]["status"], "connected")
        self.assertEqual(payload["gmail"]["status"], "unavailable")

        # Query returns unavailable status with clear message
        req = GmailCapabilityRequest(query="status")
        res = self.adapter.execute_query(req)
        self.assertEqual(res.status, "unavailable")
        self.assertEqual(len(res.findings), 0)

    # -------------------------------------------------------------------------
    # Scenario 4: Runtime attached, Gmail tool available, auth unknown → Gmail unknown & blocked
    # -------------------------------------------------------------------------
    def test_scenario_4_runtime_attached_auth_unknown_blocks_queries(self) -> None:
        """Scenario 4: When auth probe is unverified/unknown, Gmail status is unknown and queries are blocked."""
        class UnknownContext:
            available_tools = ["gmail_search"]
            def is_capability_authenticated(self, cap: str) -> None:
                return None  # UNKNOWN
            def execute_tool(self, tool_name: str, args: dict) -> dict:
                return {"status": "success"}

        ctx = UnknownContext()
        self.bridge.bind_context(ctx)
        self.service.connection_manager.bridge.bind_context(ctx)

        health = self.manager.check_health()
        self.assertEqual(health.connection_status, HermesConnectionStatus.CONNECTED)
        self.assertEqual(health.connection_stage, HermesConnectionStage.CAPABILITIES_DISCOVERED)
        self.assertFalse(health.gmail_authenticated)
        self.assertEqual(health.gmail_auth_status, "unknown")
        self.assertEqual(health.failure_category, HermesFailureCategory.AUTH_UNKNOWN.value)

        payload = self.service.get_data_sources_payload()
        self.assertEqual(payload["hermes"]["status"], "connected")
        self.assertEqual(payload["gmail"]["status"], "unknown")
        self.assertTrue(payload["gmail"]["needs_connection_in_hermes"])

        # Query blocked safely
        req = GmailCapabilityRequest(query="contract")
        res = self.adapter.execute_query(req)
        self.assertEqual(res.status, "unauthenticated")
        self.assertIn("auth_status=unknown", res.error or "")

    # -------------------------------------------------------------------------
    # Scenario 5: Runtime attached, Gmail tool available, Gmail unauthenticated → unauthenticated & guidance
    # -------------------------------------------------------------------------
    def test_scenario_5_runtime_attached_gmail_unauthenticated_shows_guidance(self) -> None:
        """Scenario 5: Explicitly unauthenticated Gmail reports unauthenticated with Hermes setup instructions."""
        mock_context = MagicMock()
        mock_context.available_tools = ["gmail_search"]
        mock_context.auth_status = {"gmail": "unauthenticated"}

        self.bridge.bind_context(mock_context)
        self.service.connection_manager.bridge.bind_context(mock_context)

        health = self.manager.check_health()
        self.assertEqual(health.connection_status, HermesConnectionStatus.CONNECTED)
        self.assertEqual(health.connection_stage, HermesConnectionStage.CAPABILITIES_DISCOVERED)
        self.assertFalse(health.gmail_authenticated)
        self.assertEqual(health.gmail_auth_status, "unauthenticated")
        self.assertEqual(health.failure_category, HermesFailureCategory.UNAUTHENTICATED.value)

        payload = self.service.get_data_sources_payload()
        self.assertEqual(payload["hermes"]["status"], "connected")
        self.assertEqual(payload["gmail"]["status"], "unauthenticated")
        self.assertTrue(payload["gmail"]["needs_connection_in_hermes"])

        setup_flow = self.service.get_gmail_setup_flow()
        self.assertIn("Open Hermes and connect/configure its Gmail capability", setup_flow["setup"]["instruction"])
        self.assertTrue(setup_flow["setup"]["zero_oauth_guarantee"])
        self.assertTrue(setup_flow["setup"]["read_only_enforced"])

        req = GmailCapabilityRequest(query="updates")
        res = self.adapter.execute_query(req)
        self.assertEqual(res.status, "unauthenticated")
        self.assertIn("unauthenticated in host Hermes", res.error or "")

    # -------------------------------------------------------------------------
    # Scenario 6: Runtime attached, Gmail authenticated → bounded read-only search succeeds
    # -------------------------------------------------------------------------
    def test_scenario_6_runtime_attached_gmail_authenticated_search_succeeds(self) -> None:
        """Scenario 6: Authenticated Gmail enables successful, bounded read-only search with provenance."""
        mock_context = MagicMock()
        mock_context.available_tools = ["gmail_search"]
        mock_context.auth_status = {"gmail": "authenticated"}
        mock_context.execute_tool.return_value = {
            "status": "success",
            "messages": [
                {
                    "id": "msg_verified_01",
                    "thread_id": "thread_verified_01",
                    "date": "2026-08-24T08:00:00Z",
                    "from": "lead_engineer@partner.org",
                    "subject": "System Verification Signed Off",
                }
            ],
        }

        self.bridge.bind_context(mock_context)
        self.service.connection_manager.bridge.bind_context(mock_context)

        health = self.manager.check_health()
        self.assertEqual(health.connection_status, HermesConnectionStatus.CONNECTED)
        self.assertEqual(health.connection_stage, HermesConnectionStage.GMAIL_AUTHENTICATED)
        self.assertTrue(health.gmail_authenticated)
        self.assertIsNone(health.failure_category)

        payload = self.service.get_data_sources_payload()
        self.assertEqual(payload["hermes"]["status"], "connected")
        self.assertEqual(payload["gmail"]["status"], "connected")
        self.assertFalse(payload["gmail"]["needs_connection_in_hermes"])

        req = GmailCapabilityRequest(query="Verification Signed Off", max_results=5, time_range_days=7)
        res = self.adapter.execute_query(req)

        self.assertEqual(res.status, "success")
        self.assertIsNone(res.error)
        self.assertEqual(len(res.findings), 1)
        self.assertIn("gmail:msg_verified_01", res.message_references)
        self.assertIn("gmail:thread:thread_verified_01", res.thread_references)
        self.assertIn("lead_engineer@partner.org", res.safe_summaries[0])
        self.assertEqual(res.tools_executed, ["gmail_search"])

    # -------------------------------------------------------------------------
    # Scenario 7: All mutation attempts are unconditionally rejected
    # -------------------------------------------------------------------------
    def test_scenario_7_all_mutation_operations_unconditionally_rejected(self) -> None:
        """Scenario 7: Send, delete, archive, label, draft, trash, and modify attempts are rejected."""
        mock_context = MagicMock()
        mock_context.available_tools = ["gmail_search"]
        mock_context.auth_status = {"gmail": "authenticated"}
        self.bridge.bind_context(mock_context)

        req = GmailCapabilityRequest(query="test mutation")

        for mutation_tool in PROHIBITED_MUTATION_GMAIL_TOOLS:
            # 1. Validation method rejects
            is_allowed, denial = self.adapter.validate_tool_operation(mutation_tool)
            self.assertFalse(is_allowed, f"{mutation_tool} must be rejected")
            self.assertIsNotNone(denial)
            self.assertIn("read-only", denial.lower())

            # 2. Execution attempt raises UnauthorizedWriteOperationError
            with self.assertRaises(UnauthorizedWriteOperationError, msg=f"Tool {mutation_tool} must raise error"):
                self.adapter.execute_query(req, tool_name=mutation_tool)

        # Verify allowed read-only whitelist passes
        for read_only_tool in ALLOWED_READ_ONLY_GMAIL_TOOLS:
            is_allowed, denial = self.adapter.validate_tool_operation(read_only_tool)
            self.assertTrue(is_allowed, f"{read_only_tool} should be allowed")
            self.assertIsNone(denial)

    # -------------------------------------------------------------------------
    # Scenario 8: Dashboard never claims Gmail investigated without real tool result & provenance
    # -------------------------------------------------------------------------
    def test_scenario_8_dashboard_never_claims_investigation_without_real_provenance(self) -> None:
        """Scenario 8: Dashboard displays last investigation only when a real tool event is recorded."""
        # 1. Initially, no investigation is recorded
        payload1 = self.service.get_data_sources_payload()
        self.assertIsNone(payload1["gmail"]["last_successful_investigation"])

        # 2. Add an unrelated event (e.g. biometric/sleep)
        sleep_evt = Event(
            id="evt-sleep-1",
            timestamp=datetime.now(timezone.utc),
            source="sleep_tracker",
            observation_type="sleep_summary",
            summary="8 hours restful sleep",
            structured_data={"hours": 8},
        )
        self.service.event_store.append(sleep_evt)

        payload2 = self.service.get_data_sources_payload()
        self.assertIsNone(payload2["gmail"]["last_successful_investigation"])

        # 3. Record an authentic Hermes Gmail observation with tool provenance
        now = datetime.now(timezone.utc)
        gmail_evt = Event(
            id="evt-gmail-real-101",
            timestamp=now,
            source="gmail",
            observation_type="gmail_evidence_observation",
            summary="[lead@co.com] Project milestone approved",
            source_id="gmail:msg_101",
            structured_data={"summary": "[lead@co.com] Project milestone approved"},
            provenance={
                "tool": "gmail_search",
                "source_id": "gmail:msg_101",
                "thread_id": "gmail:thread:thread_55",
            },
        )
        self.service.event_store.append(gmail_evt)

        # 4. Now dashboard accurately reflects the recorded investigation
        payload3 = self.service.get_data_sources_payload()
        last_inv = payload3["gmail"]["last_successful_investigation"]
        self.assertIsNotNone(last_inv)
        self.assertEqual(last_inv["tool"], "gmail_search")
        self.assertEqual(last_inv["provenance"], "gmail:msg_101")
        self.assertIn("Project milestone approved", last_inv["summary"])
        self.assertFalse(last_inv["is_demo"])


if __name__ == "__main__":
    unittest.main()
