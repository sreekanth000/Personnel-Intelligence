"""
Unit and Integration Tests for Hermes Connection Diagnostics in HermesConnectionManager.

Validates:
1. All 8 safe failure categories:
   - connection_refused
   - timeout
   - unsupported_endpoint
   - invalid_response
   - runtime_not_attached
   - capability_not_declared
   - auth_unknown
   - unauthenticated
2. Sanitization guarantee: Zero credentials, tokens, email content, raw bodies, or stack traces.
3. Plain-language recommended next actions for each category.
4. Strict distinction between gateway_detected and runtime_attached.
"""

from datetime import datetime, timezone
import json
import socket
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
    get_failure_recommended_action,
)


class TestHermesConnectionDiagnostics(unittest.TestCase):
    """
    Test suite for structured failure category reporting and diagnostics sanitization.
    """

    def setUp(self) -> None:
        set_active_hermes_context(None)
        self.bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        self.manager = HermesConnectionManager(bridge=self.bridge)

    def tearDown(self) -> None:
        set_active_hermes_context(None)

    # -------------------------------------------------------------------------
    # 1. Reachability Failure Categories: connection_refused, timeout, unsupported_endpoint, invalid_response
    # -------------------------------------------------------------------------
    @patch("urllib.request.urlopen")
    def test_diagnostic_connection_refused(self, mock_urlopen: MagicMock) -> None:
        """When gateway port is closed or connection is refused, reports failure_category='connection_refused'."""
        mock_urlopen.side_effect = urllib.error.URLError(ConnectionRefusedError(10061, "Connection refused"))

        reach = self.manager.check_reachability()
        self.assertFalse(reach.is_reachable)
        self.assertEqual(reach.failure_category, HermesFailureCategory.CONNECTION_REFUSED.value)
        self.assertIn("hermes agent start", reach.recommended_action or "")

        health = self.manager.check_health()
        self.assertEqual(health.failure_category, HermesFailureCategory.CONNECTION_REFUSED.value)
        self.assertIn("hermes agent start", health.recommended_action or "")

    @patch("urllib.request.urlopen")
    def test_diagnostic_timeout(self, mock_urlopen: MagicMock) -> None:
        """When gateway endpoint times out, reports failure_category='timeout'."""
        mock_urlopen.side_effect = urllib.error.URLError(socket.timeout("The read operation timed out"))

        reach = self.manager.check_reachability()
        self.assertFalse(reach.is_reachable)
        self.assertEqual(reach.failure_category, HermesFailureCategory.TIMEOUT.value)
        self.assertIn("timed out", reach.recommended_action or "")

        health = self.manager.check_health()
        self.assertEqual(health.failure_category, HermesFailureCategory.TIMEOUT.value)
        self.assertIn("timed out", health.recommended_action or "")

    @patch("urllib.request.urlopen")
    def test_diagnostic_unsupported_endpoint(self, mock_urlopen: MagicMock) -> None:
        """When gateway health endpoint returns 404 or 501, reports failure_category='unsupported_endpoint'."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://127.0.0.1:8642/v1/health",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None,
        )

        reach = self.manager.check_reachability()
        self.assertFalse(reach.is_reachable)
        self.assertEqual(reach.failure_category, HermesFailureCategory.UNSUPPORTED_ENDPOINT.value)
        self.assertIn("404/501", reach.recommended_action or "")

        health = self.manager.check_health()
        self.assertEqual(health.failure_category, HermesFailureCategory.UNSUPPORTED_ENDPOINT.value)

    @patch("urllib.request.urlopen")
    def test_diagnostic_invalid_response(self, mock_urlopen: MagicMock) -> None:
        """When gateway endpoint returns 500 error or unexpected payload, reports failure_category='invalid_response'."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://127.0.0.1:8642/v1/health",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None,
        )

        reach = self.manager.check_reachability()
        self.assertFalse(reach.is_reachable)
        self.assertEqual(reach.failure_category, HermesFailureCategory.INVALID_RESPONSE.value)

        health = self.manager.check_health()
        self.assertEqual(health.failure_category, HermesFailureCategory.INVALID_RESPONSE.value)

    # -------------------------------------------------------------------------
    # 2. Stage-based Failure Categories: runtime_not_attached, capability_not_declared, auth_unknown, unauthenticated
    # -------------------------------------------------------------------------
    @patch("urllib.request.urlopen")
    def test_diagnostic_runtime_not_attached(self, mock_urlopen: MagicMock) -> None:
        """When gateway is detected (HTTP 200) but no runtime context is bound, reports 'runtime_not_attached'."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        reach = self.manager.check_reachability()
        self.assertTrue(reach.is_reachable)
        self.assertEqual(reach.mechanism, "gateway")
        self.assertFalse(reach.execution_capable)
        self.assertEqual(reach.failure_category, HermesFailureCategory.RUNTIME_NOT_ATTACHED.value)

        health = self.manager.check_health()
        self.assertEqual(health.connection_stage, HermesConnectionStage.GATEWAY_DETECTED)
        self.assertTrue(health.gateway_reachable)
        self.assertFalse(health.runtime_attached)
        self.assertEqual(health.failure_category, HermesFailureCategory.RUNTIME_NOT_ATTACHED.value)
        self.assertIn("in-process runtime is attached", health.recommended_action or "")

    def test_diagnostic_capability_not_declared(self) -> None:
        """When runtime context is attached but missing required capability tool, reports 'capability_not_declared'."""
        mock_context = MagicMock()
        mock_context.available_tools = ["fs_read"]  # Missing gmail_search, etc.
        mock_context.auth_status = {"gmail": "authenticated"}

        self.bridge.bind_context(mock_context)
        health = self.manager.check_health()

        gmail_cap = health.capabilities.get("gmail", {})
        self.assertEqual(gmail_cap.get("availability"), CapabilityAvailability.UNAVAILABLE.value)
        self.assertEqual(gmail_cap.get("failure_category"), HermesFailureCategory.CAPABILITY_NOT_DECLARED.value)
        self.assertEqual(health.failure_category, HermesFailureCategory.CAPABILITY_NOT_DECLARED.value)
        self.assertIn("not declared in Hermes available tools", health.recommended_action or "")

    def test_diagnostic_auth_unknown(self) -> None:
        """When runtime context is attached with tool but auth probe returns UNKNOWN, reports 'auth_unknown'."""
        class UnknownAuthCtx:
            available_tools = ["gmail_search", "calendar_list_events"]
            def is_capability_authenticated(self, cap: str) -> None:
                return None  # UNKNOWN
            def execute_tool(self, tool_name: str, args: dict) -> dict:
                return {"status": "success"}

        self.bridge.bind_context(UnknownAuthCtx())
        health = self.manager.check_health()

        self.assertEqual(health.connection_stage, HermesConnectionStage.CAPABILITIES_DISCOVERED)
        self.assertEqual(health.gmail_auth_status, "unknown")
        self.assertEqual(health.failure_category, HermesFailureCategory.AUTH_UNKNOWN.value)
        self.assertIn("unverified authentication status", health.recommended_action or "")

    def test_diagnostic_unauthenticated(self) -> None:
        """When runtime context is attached with tool but explicitly unauthenticated, reports 'unauthenticated'."""
        mock_context = MagicMock()
        mock_context.available_tools = ["gmail_search", "calendar_list_events"]
        mock_context.auth_status = {"gmail": "unauthenticated"}

        self.bridge.bind_context(mock_context)
        health = self.manager.check_health()

        self.assertEqual(health.connection_stage, HermesConnectionStage.CAPABILITIES_DISCOVERED)
        self.assertEqual(health.gmail_auth_status, "unauthenticated")
        self.assertEqual(health.failure_category, HermesFailureCategory.UNAUTHENTICATED.value)
        self.assertIn("Open Hermes and connect/configure its capability credentials", health.recommended_action or "")

    # -------------------------------------------------------------------------
    # 3. Privacy & Sanitization: Zero Stack Traces / Credentials / Private Tokens
    # -------------------------------------------------------------------------
    def test_zero_leakage_in_diagnostics(self) -> None:
        """Verifies health report safe_diagnostics contains zero private credentials or tracebacks."""
        health = self.manager.check_health()
        serialized = json.dumps(health.safe_diagnostics, default=str).lower()

        forbidden = [
            "password", "secret", "token", "refresh_token", "access_token",
            "bearer", "traceback", "stacktrace", "file \"c:", "line ",
        ]
        for term in forbidden:
            self.assertNotIn(term, serialized, f"Forbidden sensitive diagnostic leakage found: {term}")


if __name__ == "__main__":
    unittest.main()
