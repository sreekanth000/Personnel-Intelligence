"""
End-to-End Live Connection Flow Tests for Personal Intelligence & Hermes.

Simulates the complete 10-step lifecycle:
1. User starts Personal Intelligence.
2. App checks Hermes connection (detects disconnected).
3. User selects Connect Hermes.
4. App connects to local Hermes runtime context.
5. App discovers Hermes capabilities dynamically.
6. Gmail reported unauthenticated.
7. User selects Connect Gmail in Hermes (invokes official Hermes Google flow instructions).
8. Hermes completes official setup and status refreshes to authenticated.
9. Real Gmail investigation executes only after Hermes reports authenticated.
10. Dashboard & EventStore record ground truth evidence and safe provenance.

Verifies strict non-negotiable architectural guarantees:
- Zero Google OAuth client / tokens in Personal Intelligence.
- Zero secrets stored.
- Zero autonomous Gmail write operations.
- Clear recoverable error states and instructions.
"""

from datetime import datetime, timezone
import json
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import unittest
from unittest.mock import MagicMock

from personal_intelligence.api.server import DashboardDataService
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.hermes_bridge.capabilities import (
    CapabilityAuthStatus,
    CapabilityAvailability,
    HermesConnectionStatus,
)
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesRuntimeBridge,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.gmail_adapter import GmailCapabilityRequest
from personal_intelligence.security.guard import UnauthorizedWriteOperationError
from personal_intelligence.storage.db import DatabaseManager


class FakeHermesRuntimeContext:
    """
    Simulated host Hermes agent runtime context capable of transitioning
    from unauthenticated to authenticated Google Workspace and executing tools.
    """

    def __init__(self, is_authenticated: bool = False) -> None:
        self.available_tools = [
            "gmail_search",
            "calendar_list_events",
            "drive_get_document",
            "meet_list_recent_meetings",
            "fs_read",
            "web_search",
            "llm_reasoning",
        ]
        self.auth_status: Dict[str, str] = {}
        self.set_authenticated(is_authenticated)
        self.executed_tools: List[Tuple[str, Dict[str, Any]]] = []

    def set_authenticated(self, auth: bool = True) -> None:
        val = "authenticated" if auth else "unauthenticated"
        for cap in ["gmail", "calendar", "google", "drive", "meet", "web", "filesystem", "reasoning"]:
            self.auth_status[cap] = val

    def execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        self.executed_tools.append((tool_name, tool_args))

        if tool_name == "gmail_search":
            if self.auth_status.get("gmail") != "authenticated":
                return {
                    "status": "error",
                    "error": "Unauthenticated: User has not completed 'hermes auth google'.",
                }
            return {
                "status": "success",
                "messages": [
                    {
                        "id": "live-msg-101",
                        "thread_id": "live-thread-202",
                        "from": "sponsor@enterprise.com",
                        "subject": "Q3 Architectural Deliverable Milestones Confirmed",
                        "date": "2026-08-23T15:30:00Z",
                    }
                ],
            }
        elif tool_name == "llm_reasoning":
            return {
                "status": "success",
                "observations": ["Confirmed deliverable milestones from executive sponsor."],
                "inferences": ["Deliverable schedule tension resolved."],
                "predictions": ["Deployment schedule remains on track."],
                "recommendation": {"primary_action": "Proceed with stage 2 rollout."},
            }

        return {"status": "success", "result": f"Executed {tool_name}"}


class TestLiveConnectionFlow(unittest.TestCase):
    """
    Full End-to-End integration test of the 10-step Personal Intelligence & Hermes flow.
    """

    def setUp(self) -> None:
        set_active_hermes_context(None)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "e2e_live_test.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.service = DashboardDataService(db_manager=self.db_manager)
        self.service.is_demo_mode = False

    def tearDown(self) -> None:
        set_active_hermes_context(None)
        self.temp_dir.cleanup()

    def test_complete_10_step_live_connection_lifecycle(self) -> None:
        """
        Executes and asserts every step of the 10-step lifecycle:
        1. App startup
        2. Status check -> disconnected
        3. User selects Connect Hermes
        4. Runtime connects
        5. Capabilities discovered
        6. Gmail unauthenticated
        7. Official Hermes setup flow retrieved (zero OAuth tokens)
        8. Hermes completes auth -> status refreshes to connected
        9. Real Gmail investigation executes
        10. Ground-truth observation & provenance recorded in EventStore & Dashboard
        """
        # =====================================================================
        # Step 1 & 2: App starts & checks Hermes connection (Disconnected)
        # =====================================================================
        initial_status = self.service.get_data_sources_payload()
        self.assertEqual(initial_status["hermes"]["status"], "disconnected")
        self.assertFalse(initial_status["hermes"]["is_reachable"])
        self.assertEqual(initial_status["gmail"]["status"], "unavailable")
        self.assertIsNone(initial_status["gmail"]["last_successful_investigation"])

        # Attempting live flow while disconnected must return recoverable error
        flow_res = self.service.execute_live_google_flow()
        self.assertEqual(flow_res["status"], "error")
        self.assertEqual(flow_res["error_type"], "hermes_disconnected")
        self.assertEqual(flow_res["action_required"], "connect_hermes")
        self.assertIn("hermes agent start", flow_res["instructions"])

        # =====================================================================
        # Step 3, 4 & 5: User selects Connect Hermes -> App attaches & discovers
        # =====================================================================
        fake_hermes = FakeHermesRuntimeContext(is_authenticated=False)
        connect_res = self.service.connect_hermes(runtime_context=fake_hermes)
        self.assertEqual(connect_res["status"], "success")
        self.assertEqual(connect_res["connection_status"], "connected")

        # =====================================================================
        # Step 6: Gmail reported as unauthenticated while Hermes is connected
        # =====================================================================
        status_unauth = self.service.get_data_sources_payload()
        self.assertEqual(status_unauth["hermes"]["status"], "connected")
        self.assertEqual(status_unauth["gmail"]["status"], "unauthenticated")
        self.assertEqual(status_unauth["connection_stage"], "capabilities_discovered")
        self.assertFalse(status_unauth["gmail_authenticated"])
        self.assertIn("hermes auth google", status_unauth["actionable_instructions"])

        # Attempting live flow while unauthenticated must return actionable setup error
        flow_unauth = self.service.execute_live_google_flow()
        self.assertEqual(flow_unauth["status"], "error")
        self.assertEqual(flow_unauth["error_type"], "gmail_unauthenticated")
        self.assertEqual(flow_unauth["action_required"], "connect_gmail_in_hermes")

        # =====================================================================
        # Step 7: User selects "Connect Gmail in Hermes" -> returns official instructions
        # =====================================================================
        setup_flow = self.service.get_gmail_setup_flow()
        self.assertEqual(setup_flow["status"], "success")
        self.assertEqual(setup_flow["setup"]["command"], "hermes auth google")
        self.assertIn("hermes auth google", setup_flow["setup"]["instruction"])
        # Ensure zero OAuth client IDs, tokens, or client secrets in payload
        serialized = json.dumps(setup_flow).lower()
        for forbidden in ["client_secret", "access_token", "refresh_token", "api_key"]:
            self.assertNotIn(forbidden, serialized)

        # =====================================================================
        # Step 8: Hermes completes official auth -> App refreshes status
        # =====================================================================
        fake_hermes.set_authenticated(True)

        # Re-probe via connection manager
        connect_auth = self.service.connect_hermes(runtime_context=fake_hermes)
        self.assertEqual(connect_auth["connection_status"], "connected")
        status_auth = self.service.get_data_sources_payload()
        self.assertEqual(status_auth["gmail"]["status"], "connected")
        self.assertEqual(status_auth["capabilities"]["gmail"]["authenticated_status"], "authenticated")

        # =====================================================================
        # Step 9: Real Gmail investigation executes via host Hermes tool
        # =====================================================================
        flow_success = self.service.execute_live_google_flow()
        self.assertEqual(flow_success["status"], "success")
        self.assertEqual(flow_success["mode"], "LIVE_MODE")

        # Verify Hermes received actual gmail_search tool call
        executed_tool_names = [call[0] for call in fake_hermes.executed_tools]
        self.assertIn("gmail_search", executed_tool_names)

        # =====================================================================
        # Step 10: Ground truth evidence and safe provenance recorded in Dashboard
        # =====================================================================
        final_sources_status = self.service.get_data_sources_payload()
        last_inv = final_sources_status["gmail"]["last_successful_investigation"]
        self.assertIsNotNone(last_inv)
        self.assertEqual(last_inv["tool"], "gmail_search")
        self.assertIn("live-msg-101", last_inv["provenance"])
        self.assertIn("Deliverable Milestones Confirmed", last_inv["summary"])

        # Check EventStore recorded observation
        events = self.service.event_store.get_recent(limit=10)
        gmail_obs = next(e for e in events if e.source == "gmail")
        self.assertEqual(gmail_obs.observation_type, "gmail_evidence_observation")
        self.assertEqual(gmail_obs.provenance.get("source_id"), "gmail:live-msg-101")
        self.assertTrue(gmail_obs.provenance.get("is_untrusted_input"))

    def test_strict_zero_oauth_and_mutation_rejection_invariants(self) -> None:
        """Verifies zero Google OAuth clients and blocks all mutation operations."""
        import personal_intelligence

        self.assertFalse(hasattr(personal_intelligence, "GmailClient"))
        self.assertFalse(hasattr(personal_intelligence, "GoogleOAuth"))
        self.assertFalse(hasattr(personal_intelligence, "OAuth2Client"))

        # Rejection of write operations
        fake_hermes = FakeHermesRuntimeContext(is_authenticated=True)
        self.service.connection_manager.bridge.bind_context(fake_hermes)
        req = GmailCapabilityRequest(query="status")

        forbidden_tools = ["send_email", "gmail_send", "delete", "archive", "modify", "draft"]
        for tool in forbidden_tools:
            with self.assertRaises(UnauthorizedWriteOperationError):
                self.service.investigator.gmail_adapter.execute_query(req, tool_name=tool)


if __name__ == "__main__":
    unittest.main()
