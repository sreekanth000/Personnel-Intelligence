"""
Comprehensive Unit Tests for Refactored HermesRuntimeBridge:
- Explicit execution modes (LIVE, DEMO, TEST).
- Typed error propagation in LIVE mode (elimination of silent success).
- Visibly labelled DEMO mode outputs.
- Mocked TEST mode execution.
- Safe diagnostic telemetry (zero credential/email content logging).
"""

from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock

from personal_intelligence.hermes_bridge.client import (
    HermesBridgeError,
    HermesBridgeExecutionMode,
    HermesClient,
    HermesInvocationRequest,
    HermesInvocationResponse,
    HermesRuntimeBridge,
    InvalidResultError,
    MissingCapabilityError,
    MissingRuntimeContextError,
    ToolExecutionFailureError,
    UnauthenticatedCapabilityError,
    get_active_hermes_context,
    set_active_hermes_context,
)
from personal_intelligence.security.guard import UnauthorizedWriteOperationError


class TestHermesRuntimeBridgeRefactor(unittest.TestCase):
    """
    Test suite verifying the elimination of silent success in LIVE mode,
    typed error hierarchy, DEMO labelling, and safe diagnostics.
    """

    def setUp(self) -> None:
        set_active_hermes_context(None)

    def tearDown(self) -> None:
        set_active_hermes_context(None)

    # -------------------------------------------------------------------------
    # 1. LIVE Mode: Missing Runtime Context Error
    # -------------------------------------------------------------------------
    def test_live_mode_execute_tool_fails_when_unattached(self) -> None:
        """In LIVE mode, execute_tool must raise MissingRuntimeContextError if no host Hermes is attached."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        self.assertIsNone(bridge.runtime_context)

        with self.assertRaises(MissingRuntimeContextError) as ctx:
            bridge.execute_tool("gmail_search", {"query": "deliverable"})

        self.assertIn("Host Hermes runtime context is not attached in LIVE mode", str(ctx.exception))
        self.assertEqual(ctx.exception.safe_diagnostics.get("tool"), "gmail_search")
        self.assertEqual(ctx.exception.safe_diagnostics.get("execution_mode"), "live")

    def test_live_mode_invoke_reasoning_fails_clearly_when_unattached(self) -> None:
        """In LIVE mode, invoke_reasoning must return success=False and clear error instead of silent fake stub."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        req = HermesInvocationRequest(prompt="Analyze situational conflict")

        res = bridge.invoke_reasoning(req)
        self.assertFalse(res.success)
        self.assertIn("Host Hermes runtime context is not attached in LIVE mode", res.error or "")
        self.assertFalse(res.is_demo)

    # -------------------------------------------------------------------------
    # 2. LIVE Mode: Missing Capability Error
    # -------------------------------------------------------------------------
    def test_live_mode_missing_capability_error(self) -> None:
        """In LIVE mode, execute_tool must raise MissingCapabilityError if tool is not in available Hermes tools."""
        mock_ctx = MagicMock()
        mock_ctx.available_tools = ["gmail_search", "calendar_list_events"]

        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE, runtime_context=mock_ctx)

        with self.assertRaises(MissingCapabilityError) as ctx:
            bridge.execute_tool("unknown_custom_tool", {"param": 1})

        self.assertIn("not in available Hermes tools", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 3. LIVE Mode: Unauthenticated Capability Error
    # -------------------------------------------------------------------------
    def test_live_mode_unauthenticated_capability_error(self) -> None:
        """In LIVE mode, execute_tool must raise UnauthenticatedCapabilityError if Hermes reports capability unauthenticated."""
        mock_ctx = MagicMock()
        mock_ctx.available_tools = ["gmail_search"]
        mock_ctx.is_capability_authenticated.return_value = False

        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE, runtime_context=mock_ctx)

        with self.assertRaises(UnauthenticatedCapabilityError) as ctx:
            bridge.execute_tool("gmail_search", {"query": "status"})

        self.assertIn("is unauthenticated in host Hermes", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 4. LIVE Mode: Unauthorized Write Safety Guard
    # -------------------------------------------------------------------------
    def test_live_mode_blocks_autonomous_write_operations(self) -> None:
        """OperationSafetyGuard must block autonomous write tools (e.g. send_email, modify_calendar)."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)

        forbidden_tools = ["send_email", "modify_calendar", "modify_drive", "delete_file", "send_meet_message"]
        for tool in forbidden_tools:
            with self.assertRaises(UnauthorizedWriteOperationError):
                bridge.execute_tool(tool, {"content": "test payload"})

    # -------------------------------------------------------------------------
    # 5. DEMO Mode: Visibly Labelled Outputs
    # -------------------------------------------------------------------------
    def test_demo_mode_tool_execution_is_visibly_labelled(self) -> None:
        """In DEMO mode, execute_tool must return fixture data with visible [DEMO MODE] marker."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.DEMO)

        res = bridge.execute_tool("gmail_search", {"query": "contract"})
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["is_demo"])
        self.assertIn("[DEMO MODE]", res["demo_label"])

    def test_demo_mode_reasoning_is_visibly_labelled(self) -> None:
        """In DEMO mode, invoke_reasoning must return findings visibly labelled [DEMO MODE]."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.DEMO)
        req = HermesInvocationRequest(prompt="Evaluate situation")

        res = bridge.invoke_reasoning(req)
        self.assertTrue(res.success)
        self.assertTrue(res.is_demo)
        self.assertIn("[DEMO MODE]", res.raw_response)

    # -------------------------------------------------------------------------
    # 6. TEST Mode: Mock Context & Tool Overrides
    # -------------------------------------------------------------------------
    def test_test_mode_tool_overrides(self) -> None:
        """In TEST mode, tool overrides are invoked directly."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.TEST)
        bridge.register_tool_override("custom_test_tool", lambda query: f"Echo: {query}")

        res = bridge.execute_tool("custom_test_tool", {"query": "hello"})
        self.assertEqual(res, "Echo: hello")

    def test_test_mode_llm_callable(self) -> None:
        """In TEST mode, llm_callable hook is invoked for reasoning."""
        bridge = HermesRuntimeBridge(
            mode=HermesBridgeExecutionMode.TEST,
            llm_callable=lambda p: f"Reasoning output for: {p}",
        )
        res = bridge.invoke_reasoning(HermesInvocationRequest(prompt="Test Prompt"))
        self.assertTrue(res.success)
        self.assertEqual(res.raw_response, "Reasoning output for: Test Prompt")

    # -------------------------------------------------------------------------
    # 7. Safe Diagnostics: Zero Credential & Sensitive Content Leakage
    # -------------------------------------------------------------------------
    def test_safe_diagnostics_sanitizes_sensitive_tool_arguments(self) -> None:
        """Diagnostics must record argument keys and non-sensitive metadata, never raw email bodies or passwords."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.DEMO)
        sensitive_payload = {
            "query": "super confidential executive compensation details",
            "password": "secret_password_123",
            "access_token": "ya29.secret_token",
            "limit": 10,
        }

        diag = bridge._sanitize_diagnostics("gmail_search", sensitive_payload)

        # Assert only keys are stored, not sensitive values
        self.assertIn("query", diag["argument_keys"])
        self.assertIn("password", diag["argument_keys"])
        self.assertIn("access_token", diag["argument_keys"])
        self.assertEqual(diag["limit"], 10)

        serialized_diag = str(diag).lower()
        self.assertNotIn("secret_password_123", serialized_diag)
        self.assertNotIn("super confidential executive", serialized_diag)
        self.assertNotIn("ya29.secret_token", serialized_diag)


if __name__ == "__main__":
    unittest.main()
