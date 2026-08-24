"""
Unit Tests for Hermes-Owned Read-Only GmailCapabilityAdapter:
- Declarative generic capability request handling.
- Normalized Hermes Gmail result schema validation.
- Connected state with mocked Hermes context and gmail_search tool.
- Unavailable capability state handling.
- Unauthenticated capability state handling.
- Strict rejection of send, delete, archive, label, draft, and modify operations.
- Zero-OAuth and zero-credential storage guarantees.
"""

from datetime import datetime, timezone
import json
from typing import Any, Optional
import unittest
from unittest.mock import MagicMock

from personal_intelligence.hermes_bridge.capabilities import (
    CapabilityAuthStatus,
    CapabilityAvailability,
    HermesCapabilityInspector,
)
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesRuntimeBridge,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.gmail_adapter import (
    ALLOWED_READ_ONLY_GMAIL_TOOLS,
    PROHIBITED_MUTATION_GMAIL_TOOLS,
    GmailCapabilityAdapter,
    GmailCapabilityRequest,
    HermesGmailResult,
)
from personal_intelligence.security.guard import UnauthorizedWriteOperationError


class TestGmailCapabilityAdapter(unittest.TestCase):
    """
    Test suite for GmailCapabilityAdapter and read-only Hermes Gmail contract.
    """

    def setUp(self) -> None:
        set_active_hermes_context(None)
        self.bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        self.adapter = GmailCapabilityAdapter(bridge=self.bridge)

    def tearDown(self) -> None:
        set_active_hermes_context(None)

    # -------------------------------------------------------------------------
    # 1. Connected & Authenticated Execution with Schema Normalization
    # -------------------------------------------------------------------------
    def test_connected_gmail_search_normalized_schema(self) -> None:
        """Verifies successful search query execution and normalized schema output."""
        mock_context = MagicMock()
        mock_context.available_tools = ["gmail_search", "calendar_list_events"]
        mock_context.auth_status = {"gmail": "authenticated"}

        # Simulate host Hermes returning structured message items
        mock_context.execute_tool.return_value = {
            "status": "success",
            "messages": [
                {
                    "id": "msg_901",
                    "thread_id": "thread_801",
                    "date": "2026-08-23T16:00:00Z",
                    "from": "lead_architect@company.com",
                    "subject": "System deliverable section draft complete",
                },
                {
                    "id": "msg_902",
                    "thread_id": "thread_801",
                    "date": "2026-08-23T16:30:00Z",
                    "from": "pm@company.com",
                    "subject": "Re: System deliverable review meeting scheduled",
                },
            ],
        }

        self.bridge.bind_context(mock_context)
        req = GmailCapabilityRequest(query="deliverable review", max_results=5)
        result = self.adapter.execute_query(req)

        self.assertEqual(result.status, "success")
        self.assertIsNone(result.error)
        self.assertEqual(len(result.message_references), 2)
        self.assertIn("gmail:msg_901", result.message_references)
        self.assertIn("gmail:msg_902", result.message_references)
        self.assertIn("gmail:thread:thread_801", result.thread_references)
        self.assertEqual(len(result.timestamps), 2)
        self.assertEqual(len(result.safe_summaries), 2)
        self.assertIn("[lead_architect@company.com] System deliverable section draft complete", result.safe_summaries[0])
        self.assertIn("gmail_search:gmail:msg_901", result.provenance[0])
        self.assertEqual(result.tools_executed, ["gmail_search"])

    # -------------------------------------------------------------------------
    # 2. Unavailable Capability Handling
    # -------------------------------------------------------------------------
    def test_unavailable_state_when_tool_not_in_hermes(self) -> None:
        """When Hermes context does not expose gmail_search, returns status='unavailable'."""
        mock_context = MagicMock()
        mock_context.available_tools = ["calendar_list_events", "fs_read"]  # No gmail_search
        mock_context.auth_status = {"calendar": "authenticated"}

        self.bridge.bind_context(mock_context)
        req = GmailCapabilityRequest(query="contract draft")
        result = self.adapter.execute_query(req)

        self.assertEqual(result.status, "unavailable")
        self.assertIn("Gmail capability", result.error or "")
        self.assertEqual(len(result.findings), 0)

    def test_unavailable_state_when_context_not_attached(self) -> None:
        """When no host Hermes context is attached in LIVE mode, returns status='unavailable'."""
        req = GmailCapabilityRequest(query="urgent status")
        result = self.adapter.execute_query(req)

        self.assertEqual(result.status, "unavailable")
        self.assertIn("Host Hermes runtime context is not attached", result.error or "")

    # -------------------------------------------------------------------------
    # 3. Unauthenticated Capability Handling
    # -------------------------------------------------------------------------
    def test_unauthenticated_state_returns_clear_instruction(self) -> None:
        """When Hermes reports Gmail is unauthenticated, returns status='unauthenticated'."""
        mock_context = MagicMock()
        mock_context.available_tools = ["gmail_search"]
        mock_context.auth_status = {"gmail": "unauthenticated"}

        self.bridge.bind_context(mock_context)
        req = GmailCapabilityRequest(query="schedule updates")
        result = self.adapter.execute_query(req)

        self.assertEqual(result.status, "unauthenticated")
        self.assertIn("Gmail capability is unauthenticated in host Hermes", result.error or "")
        self.assertIn("hermes auth google", result.error or "")

    # -------------------------------------------------------------------------
    # 4. Strict Read-Only Enforcement & Mutation Rejection
    # -------------------------------------------------------------------------
    def test_rejects_all_mutation_tools(self) -> None:
        """Rejects send, delete, archive, label, draft, and modify operations with UnauthorizedWriteOperationError."""
        req = GmailCapabilityRequest(query="test")

        for forbidden_tool in PROHIBITED_MUTATION_GMAIL_TOOLS:
            with self.assertRaises(UnauthorizedWriteOperationError, msg=f"Should reject {forbidden_tool}"):
                self.adapter.execute_query(req, tool_name=forbidden_tool)

    def test_allowed_read_only_tools_pass_validation(self) -> None:
        """Validates that all allowed read-only tools pass validation."""
        for allowed_tool in ALLOWED_READ_ONLY_GMAIL_TOOLS:
            is_allowed, denial = self.adapter.validate_tool_operation(allowed_tool)
            self.assertTrue(is_allowed, f"{allowed_tool} should be allowed")
            self.assertIsNone(denial)

    # -------------------------------------------------------------------------
    # 5. DEMO Mode Execution
    # -------------------------------------------------------------------------
    def test_demo_mode_returns_visibly_labelled_findings(self) -> None:
        """In DEMO mode, execute_query returns synthetic fixture findings visibly marked [DEMO MODE]."""
        self.bridge.execution_mode = HermesBridgeExecutionMode.DEMO
        req = GmailCapabilityRequest(query="action items")
        result = self.adapter.execute_query(req)

        self.assertEqual(result.status, "success")
        self.assertTrue(len(result.findings) > 0)
        self.assertIn("[DEMO MODE]", result.findings[0])
        self.assertIn("demo://gmail", result.message_references[0])

    # -------------------------------------------------------------------------
    # 6. Zero-OAuth & Zero Direct Integration Guarantee
    # -------------------------------------------------------------------------
    def test_zero_oauth_or_custom_source_client(self) -> None:
        """Guarantees Personal Intelligence contains no GmailClient, GoogleOAuth, or tokens."""
        import personal_intelligence

        self.assertFalse(hasattr(personal_intelligence, "GmailClient"))
        self.assertFalse(hasattr(personal_intelligence, "GoogleOAuth"))
        self.assertFalse(hasattr(personal_intelligence, "GoogleWorkspaceClient"))

        # Verify normalized result carries no private credential fields
        result = HermesGmailResult(status="success", findings=["Test finding"])
        d = result.to_dict()
        serialized = json.dumps(d).lower()
        for forbidden in ["client_secret", "refresh_token", "access_token", "api_key", "password"]:
            self.assertNotIn(forbidden, serialized)

    # -------------------------------------------------------------------------
    # 7. Regression Tests for Hermes Auth Modes & Metadata Resolution
    # -------------------------------------------------------------------------
    def test_authenticated_via_auth_status_dictionary(self) -> None:
        """Explicit context.auth_status['gmail'] = 'authenticated' executes tool and returns success."""
        mock_context = MagicMock()
        mock_context.available_tools = ["gmail_search"]
        mock_context.auth_status = {"gmail": "authenticated"}
        mock_context.execute_tool.return_value = {
            "status": "success",
            "messages": [{"id": "m1", "subject": "Architecture Approval", "from": "lead@company.com", "date": "2026-08-23T10:00:00Z"}]
        }
        self.bridge.bind_context(mock_context)
        req = GmailCapabilityRequest(query="Architecture")
        result = self.adapter.execute_query(req)

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.findings), 1)
        self.assertIn("Architecture Approval", result.safe_summaries[0])
        self.assertEqual(result.tools_executed, ["gmail_search"])

    def test_authenticated_via_is_capability_authenticated_callable(self) -> None:
        """Explicit context.is_capability_authenticated('gmail') = True executes tool and returns success."""
        class CustomHermesContext:
            available_tools = ["gmail_search"]
            def is_capability_authenticated(self, cap: str) -> bool:
                return cap == "gmail"
            def execute_tool(self, tool_name: str, args: dict) -> dict:
                return {
                    "status": "success",
                    "messages": [{"id": "m2", "subject": "Quarterly Plan", "from": "vp@company.com", "date": "2026-08-23T11:00:00Z"}]
                }

        ctx = CustomHermesContext()
        self.bridge.bind_context(ctx)
        req = GmailCapabilityRequest(query="Plan")
        result = self.adapter.execute_query(req)

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.findings), 1)
        self.assertIn("Quarterly Plan", result.safe_summaries[0])

    def test_unknown_auth_returns_unauthenticated_status(self) -> None:
        """When auth probe returns None / unrecognised value, returns unauthenticated status."""
        class UnknownAuthContext:
            available_tools = ["gmail_search"]
            def is_capability_authenticated(self, cap: str) -> Any:
                return None  # Unknown
            def execute_tool(self, tool_name: str, args: dict) -> dict:
                return {"status": "success"}

        ctx = UnknownAuthContext()
        self.bridge.bind_context(ctx)
        req = GmailCapabilityRequest(query="status check")
        result = self.adapter.execute_query(req)

        self.assertEqual(result.status, "unauthenticated")
        self.assertIn("auth_status=unknown", result.error or "")

    def test_unauthenticated_auth_returns_unauthenticated_status(self) -> None:
        """Explicitly unauthenticated Hermes context returns status='unauthenticated'."""
        class UnauthContext:
            available_tools = ["gmail_search"]
            auth_status = {"gmail": "unauthenticated"}
            def execute_tool(self, tool_name: str, args: dict) -> dict:
                return {"status": "success"}

        ctx = UnauthContext()
        self.bridge.bind_context(ctx)
        req = GmailCapabilityRequest(query="inquiry")
        result = self.adapter.execute_query(req)

        self.assertEqual(result.status, "unauthenticated")
        self.assertIn("Gmail capability is unauthenticated", result.error or "")

    def test_missing_gmail_tool_returns_unavailable_status(self) -> None:
        """When Hermes context is attached but gmail tool is missing from available_tools, returns status='unavailable'."""
        class MissingToolContext:
            available_tools = ["calendar_list_events", "drive_get_document"]
            auth_status = {"gmail": "authenticated"}
            def execute_tool(self, tool_name: str, args: dict) -> dict:
                return {"status": "success"}

        ctx = MissingToolContext()
        self.bridge.bind_context(ctx)
        req = GmailCapabilityRequest(query="meeting query")
        result = self.adapter.execute_query(req)

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(len(result.findings), 0)

    def test_dynamic_capability_metadata_preserves_authenticated_status(self) -> None:
        """Dynamic metadata declared via get_capability_metadata executes properly when authenticated."""
        class MetadataDeclaredContext:
            available_tools = ["gmail_search"]
            auth_status = {"gmail": "authenticated"}
            def get_capability_metadata(self, cap: str) -> dict:
                return {
                    "primary_tool": "gmail_search",
                    "tool_names": ["gmail_search"],
                    "setup_command": "hermes auth workspace --scope=gmail",
                    "auth_required": True,
                    "is_read_only": True,
                }
            def execute_tool(self, tool_name: str, args: dict) -> dict:
                return {
                    "status": "success",
                    "messages": [{"id": "m3", "subject": "Dynamic Metadata Finding", "from": "eng@company.com"}]
                }

        ctx = MetadataDeclaredContext()
        self.bridge.bind_context(ctx)
        req = GmailCapabilityRequest(query="Finding")
        result = self.adapter.execute_query(req, tool_name="gmail_search")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.tools_executed, ["gmail_search"])
        self.assertEqual(len(result.findings), 1)


if __name__ == "__main__":
    unittest.main()
