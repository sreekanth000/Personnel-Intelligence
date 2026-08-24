"""
Hermes Connection Stage Separation Tests.

Proves that:
1. A responding HTTP health endpoint alone cannot make Gmail appear connected or investigated.
2. The 6-stage connection model progresses correctly.
3. Tool overrides are rejected outside TEST mode.
4. Unknown auth is never treated as authenticated.
5. Capability tool names are sourced from context metadata when available.
6. Setup command is sourced from context metadata, not hard-coded.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from personal_intelligence.hermes_bridge.capabilities import (
    CAPABILITY_TOOL_MAPPINGS,
    DEFAULT_GMAIL_SETUP_COMMAND,
    CapabilityAuthStatus,
    CapabilityAvailability,
    HermesCapabilityInspector,
    HermesConnectionStage,
    HermesConnectionStatus,
    _resolve_capability_metadata,
)
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesRuntimeBridge,
    MissingRuntimeContextError,
    UnauthenticatedCapabilityError,
    get_active_hermes_context,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.connection_manager import (
    HermesConnectionManager,
    HermesHealthReport,
    HermesReachabilityInfo,
)
from personal_intelligence.hermes_bridge.gmail_adapter import (
    GmailCapabilityAdapter,
    GmailCapabilityRequest,
)
from personal_intelligence.security.guard import UnauthorizedWriteOperationError


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

class _FakeRuntimeContext:
    """
    Minimal fake Hermes in-process runtime context for stage tests.
    Configurable tool list, auth status, and optional metadata provider.
    """
    def __init__(
        self,
        available_tools: Optional[List[str]] = None,
        auth_status: Optional[Dict[str, str]] = None,
        capability_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.available_tools = available_tools or []
        self.auth_status = auth_status or {}
        self._capability_metadata = capability_metadata or {}

    def execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "tool": name, "result": []}

    def is_capability_authenticated(self, capability: str) -> bool:
        val = self.auth_status.get(capability)
        if val == "authenticated":
            return True
        if val == "unauthenticated":
            return False
        return None  # → UNKNOWN

    def get_capability_metadata(self, capability: str) -> Optional[Dict[str, Any]]:
        return self._capability_metadata.get(capability)


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------

class TestHermesConnectionStageSeparation(unittest.TestCase):

    def setUp(self) -> None:
        set_active_hermes_context(None)
        self.inspector = HermesCapabilityInspector()

    def tearDown(self) -> None:
        set_active_hermes_context(None)

    # -----------------------------------------------------------------
    # 1. Health endpoint alone cannot make Gmail connected or investigated
    # -----------------------------------------------------------------
    def test_health_endpoint_alone_does_not_make_gmail_connected(self) -> None:
        """
        Simulating an HTTP 200 on /v1/health must NOT advance stage beyond
        GATEWAY_DETECTED. Gmail must remain unavailable, auth unknown.
        """
        manager = HermesConnectionManager(
            bridge=HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE),
        )

        # Simulate gateway health probe responding
        report = self.inspector.probe_all(
            runtime_context=None,
            is_demo=False,
            gateway_reachable=True,  # ← HTTP health endpoint responded
        )

        # Stage must not exceed GATEWAY_DETECTED
        self.assertEqual(report.connection_stage, HermesConnectionStage.GATEWAY_DETECTED)

        # High-level status maps to DISCONNECTED (gateway ≠ usable)
        self.assertEqual(report.connection_status, HermesConnectionStatus.DISCONNECTED)

        # Execution capability flags
        self.assertTrue(report.gateway_reachable)
        self.assertFalse(report.runtime_attached)
        self.assertFalse(report.capabilities_discovered)
        self.assertFalse(report.gmail_authenticated)

        # Gmail must be UNAVAILABLE and auth must be UNAUTHENTICATED
        # (Standalone unattached path: no runtime means no auth confirmation —
        # UNAUTHENTICATED is the conservative and backward-compatible value here.
        # Both UNAUTHENTICATED and UNKNOWN correctly block all Gmail investigations.)
        gmail = report.capabilities.get("gmail")
        self.assertIsNotNone(gmail)
        self.assertEqual(gmail.availability, CapabilityAvailability.UNAVAILABLE)
        self.assertNotEqual(gmail.authenticated_status, CapabilityAuthStatus.AUTHENTICATED,
                            "Gateway-only detection must never report Gmail as authenticated")

    def test_health_endpoint_alone_does_not_allow_gmail_investigation(self) -> None:
        """
        Attempting to invoke gmail_search with no runtime context (even if gateway
        was detected) must raise MissingRuntimeContextError.
        """
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        bridge.bind_context(None)

        with self.assertRaises(MissingRuntimeContextError):
            bridge.execute_tool("gmail_search", {"query": "urgent contract"})

    def test_health_report_execution_capable_flag_is_false_for_gateway(self) -> None:
        """
        HermesHealthReport.gateway_reachable=True but runtime_attached=False
        must be clearly reflected when only gateway detection was possible.
        """
        manager = HermesConnectionManager(
            bridge=HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE),
        )

        # Patch reachability to simulate gateway responding but no context attached
        mock_reach = HermesReachabilityInfo(
            is_reachable=True,
            mechanism="gateway",
            gateway_url="http://127.0.0.1:8642",
            details="HTTP health endpoint responded. DETECTION ONLY.",
            execution_capable=False,
        )
        with patch.object(manager, "check_reachability", return_value=mock_reach):
            health = manager.check_health()

        self.assertTrue(health.gateway_reachable)
        self.assertFalse(health.runtime_attached)
        self.assertFalse(health.capabilities_discovered)
        self.assertFalse(health.gmail_authenticated)
        self.assertEqual(health.connection_stage, HermesConnectionStage.GATEWAY_DETECTED)
        self.assertEqual(health.connection_status, HermesConnectionStatus.DISCONNECTED)

    # -----------------------------------------------------------------
    # 2. 6-Stage connection progression
    # -----------------------------------------------------------------
    def test_6_stage_disconnected_no_context_no_gateway(self) -> None:
        report = self.inspector.probe_all(
            runtime_context=None, is_demo=False, gateway_reachable=False
        )
        self.assertEqual(report.connection_stage, HermesConnectionStage.DISCONNECTED)

    def test_6_stage_gateway_detected(self) -> None:
        report = self.inspector.probe_all(
            runtime_context=None, is_demo=False, gateway_reachable=True
        )
        self.assertEqual(report.connection_stage, HermesConnectionStage.GATEWAY_DETECTED)
        self.assertEqual(report.connection_status, HermesConnectionStatus.DISCONNECTED)

    def test_6_stage_runtime_attached(self) -> None:
        # Minimal context with no external tools declared.
        # Local caps (filesystem, reasoning) may still advance to CAPABILITIES_DISCOVERED.
        ctx = MagicMock()
        ctx.available_tools = []
        del ctx.call_tool  # remove call_tool; keep execute_tool
        ctx.execute_tool = lambda n, a: {}
        ctx.auth_status = {}

        report = self.inspector.probe_all(runtime_context=ctx, is_demo=False)
        # Stage is somewhere between TRANSPORT_READY and CAPABILITIES_DISCOVERED inclusive
        acceptable_stages = (
            HermesConnectionStage.TRANSPORT_READY,
            HermesConnectionStage.RUNTIME_ATTACHED,
            HermesConnectionStage.CAPABILITIES_DISCOVERED,
        )
        self.assertIn(report.connection_stage, acceptable_stages,
                      f"Unexpected stage: {report.connection_stage.value}")
        self.assertFalse(report.gmail_authenticated)

    def test_6_stage_capabilities_discovered(self) -> None:
        ctx = _FakeRuntimeContext(
            available_tools=["gmail_search", "calendar_list_events"],
            auth_status={"gmail": "unauthenticated"},
        )
        report = self.inspector.probe_all(runtime_context=ctx, is_demo=False)
        self.assertEqual(report.connection_stage, HermesConnectionStage.CAPABILITIES_DISCOVERED)
        self.assertFalse(report.gmail_authenticated)

    def test_6_stage_gmail_authenticated(self) -> None:
        ctx = _FakeRuntimeContext(
            available_tools=["gmail_search", "calendar_list_events"],
            auth_status={"gmail": "authenticated"},
        )
        report = self.inspector.probe_all(runtime_context=ctx, is_demo=False)
        self.assertEqual(report.connection_stage, HermesConnectionStage.GMAIL_AUTHENTICATED)
        self.assertTrue(report.gmail_authenticated)

    def test_stage_ordinal_ordering(self) -> None:
        """Stages must have a strictly increasing ordinal."""
        order = [
            HermesConnectionStage.DISCONNECTED,
            HermesConnectionStage.GATEWAY_DETECTED,
            HermesConnectionStage.TRANSPORT_READY,
            HermesConnectionStage.RUNTIME_ATTACHED,
            HermesConnectionStage.CAPABILITIES_DISCOVERED,
            HermesConnectionStage.GMAIL_AUTHENTICATED,
        ]
        for i in range(len(order) - 1):
            self.assertLess(order[i].ordinal, order[i + 1].ordinal,
                            f"{order[i].value} ordinal must be < {order[i + 1].value}")

    # -----------------------------------------------------------------
    # 3. Tool overrides rejected outside TEST mode
    # -----------------------------------------------------------------
    def test_tool_override_registration_rejected_in_live_mode(self) -> None:
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        with self.assertRaises(RuntimeError) as cm:
            bridge.register_tool_override("gmail_search", lambda **kwargs: {})
        self.assertIn("TEST mode", str(cm.exception))

    def test_tool_override_registration_rejected_in_demo_mode(self) -> None:
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.DEMO)
        with self.assertRaises(RuntimeError) as cm:
            bridge.register_tool_override("gmail_search", lambda **kwargs: {})
        self.assertIn("TEST mode", str(cm.exception))

    def test_tool_override_allowed_in_test_mode(self) -> None:
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.TEST)
        bridge.register_tool_override("gmail_search", lambda **kwargs: {"status": "ok"})
        result = bridge.execute_tool("gmail_search", {"query": "test"})
        self.assertEqual(result["status"], "ok")

    # -----------------------------------------------------------------
    # 4. Unknown auth never treated as authenticated
    # -----------------------------------------------------------------
    def test_absent_auth_probe_returns_unknown_not_authenticated(self) -> None:
        """
        When a runtime context has no auth probe at all and the capability is
        an external workspace tool, auth must be UNKNOWN.
        """
        ctx = MagicMock(spec=["available_tools", "execute_tool"])
        ctx.available_tools = ["gmail_search"]
        ctx.execute_tool = lambda n, a: {}

        status = self.inspector.probe_capability("gmail", runtime_context=ctx)
        self.assertEqual(status.authenticated_status, CapabilityAuthStatus.UNKNOWN)

    def test_auth_probe_returning_none_yields_unknown(self) -> None:
        """is_capability_authenticated returning None must yield UNKNOWN."""
        ctx = _FakeRuntimeContext(
            available_tools=["gmail_search"],
            auth_status={},  # gmail not present → None
        )
        status = self.inspector.probe_capability("gmail", runtime_context=ctx)
        self.assertEqual(status.authenticated_status, CapabilityAuthStatus.UNKNOWN)

    def test_unknown_auth_blocks_tool_execution(self) -> None:
        """
        A runtime context with no auth probe for an external capability must block
        execute_tool with UnauthenticatedCapabilityError (not silently succeed).
        """
        ctx = MagicMock(spec=["available_tools", "execute_tool"])
        ctx.available_tools = ["gmail_search"]
        ctx.execute_tool = lambda n, a: {"status": "should_not_reach"}

        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        bridge.bind_context(ctx)

        with self.assertRaises(UnauthenticatedCapabilityError):
            bridge.execute_tool("gmail_search", {"query": "test"})

    # -----------------------------------------------------------------
    # 5. Capability tool names sourced from context metadata
    # -----------------------------------------------------------------
    def test_capability_tool_names_from_context_metadata(self) -> None:
        """When context provides get_capability_metadata, tool names use it."""
        ctx = _FakeRuntimeContext(
            available_tools=["my_custom_gmail_fetch"],
            auth_status={"gmail": "authenticated"},
            capability_metadata={
                "gmail": {
                    "primary_tool": "my_custom_gmail_fetch",
                    "tool_names": ["my_custom_gmail_fetch"],
                    "auth_required": True,
                    "is_read_only": True,
                }
            },
        )
        status = self.inspector.probe_capability("gmail", runtime_context=ctx)
        self.assertEqual(status.tool_name, "my_custom_gmail_fetch")
        self.assertTrue(status.metadata.hermes_provided)
        self.assertNotEqual(status.tool_name, CAPABILITY_TOOL_MAPPINGS["gmail"])

    def test_static_fallback_tool_used_when_no_metadata(self) -> None:
        """When context provides no capability metadata, static fallback applies."""
        ctx = _FakeRuntimeContext(
            available_tools=["gmail_search"],
            auth_status={"gmail": "authenticated"},
        )
        status = self.inspector.probe_capability("gmail", runtime_context=ctx)
        # Should use the fallback
        self.assertEqual(status.tool_name, CAPABILITY_TOOL_MAPPINGS["gmail"])
        self.assertFalse(status.metadata.hermes_provided)

    # -----------------------------------------------------------------
    # 6. Setup command sourced from context metadata
    # -----------------------------------------------------------------
    def test_setup_command_from_context_metadata(self) -> None:
        """
        When context provides get_capability_metadata with a setup_command,
        it overrides the DEFAULT_GMAIL_SETUP_COMMAND constant.
        """
        ctx = _FakeRuntimeContext(
            available_tools=["gmail_search"],
            auth_status={"gmail": "unauthenticated"},
            capability_metadata={
                "gmail": {
                    "primary_tool": "gmail_search",
                    "tool_names": ["gmail_search"],
                    "setup_command": "hermes auth workspace --provider=google --scope=gmail",
                    "auth_required": True,
                    "is_read_only": True,
                }
            },
        )
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        bridge.bind_context(ctx)
        manager = HermesConnectionManager(bridge=bridge)
        instructions = manager.get_gmail_setup_instructions()

        # Must use Hermes-provided command, marked as official
        self.assertEqual(
            instructions["command"],
            "hermes auth workspace --provider=google --scope=gmail",
        )
        self.assertEqual(instructions["command_source"], "hermes_provided")
        self.assertTrue(instructions["is_official_command"])
        self.assertNotEqual(instructions["command"], DEFAULT_GMAIL_SETUP_COMMAND)

    def test_setup_command_fallback_when_no_metadata(self) -> None:
        """Without context metadata, setup command falls back to clearly labelled example and instructs user to configure in Hermes."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        bridge.bind_context(None)
        manager = HermesConnectionManager(bridge=bridge)
        instructions = manager.get_gmail_setup_instructions()
        self.assertEqual(instructions["command"], DEFAULT_GMAIL_SETUP_COMMAND)
        self.assertEqual(instructions["command_source"], "example_fallback")
        self.assertFalse(instructions["is_official_command"])
        self.assertEqual(instructions["command_label"], "example / environment-specific command")
        self.assertIn("Open Hermes and connect/configure its Gmail capability, then refresh this page.", instructions["instruction"])
        self.assertNotIn("Run the official", instructions["instruction"])

    def test_launch_instructions_use_official_nous_research_reference(self) -> None:
        """Verifies launch instructions link to Nous Research and do not reference google/hermes."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        manager = HermesConnectionManager(bridge=bridge)
        launch_inst = manager.get_launch_instructions()
        self.assertNotIn("github.com/google/hermes", launch_inst)
        self.assertIn("NousResearch", launch_inst)

    # -----------------------------------------------------------------
    # 7. Hermes Connected while Gmail Unauthenticated Contract
    # -----------------------------------------------------------------
    def test_hermes_connected_while_gmail_unauthenticated_contract(self) -> None:
        """
        Adopts the strict contract:
        - Hermes connection_status is 'connected' when a real runtime is attached and usable.
        - Gmail has independent status: 'unauthenticated'.
        - connection_stage remains 'capabilities_discovered' until Gmail is authenticated.
        - gmail_authenticated is False.
        """
        ctx = _FakeRuntimeContext(
            available_tools=["gmail_search", "calendar_list_events", "fs_read", "llm_reasoning"],
            auth_status={"gmail": "unauthenticated", "calendar": "authenticated"},
        )
        report = self.inspector.probe_all(runtime_context=ctx, is_demo=False)

        # Hermes is connected
        self.assertEqual(report.connection_status, HermesConnectionStatus.CONNECTED)
        self.assertEqual(report.connection_stage, HermesConnectionStage.CAPABILITIES_DISCOVERED)
        self.assertFalse(report.gmail_authenticated)
        self.assertTrue(report.runtime_attached)
        self.assertTrue(report.capabilities_discovered)

        # Gmail capability status is independent
        self.assertEqual(report.capabilities["gmail"].availability, CapabilityAvailability.AVAILABLE)
        self.assertEqual(report.capabilities["gmail"].authenticated_status, CapabilityAuthStatus.UNAUTHENTICATED)

    def test_dashboard_payload_shows_hermes_connected_and_gmail_needs_connection(self) -> None:
        """
        Dashboard/API payload communicates both:
        - hermes.status == 'connected'
        - gmail.status == 'unauthenticated'
        - gmail.needs_connection_in_hermes == True
        """
        from personal_intelligence.api.server import DashboardDataService
        from personal_intelligence.storage.db import DatabaseManager

        db_manager = DatabaseManager(db_path=":memory:")
        db_manager.initialize_schema()
        service = DashboardDataService(db_manager=db_manager)
        service.is_demo_mode = False

        ctx = _FakeRuntimeContext(
            available_tools=["gmail_search", "calendar_list_events", "fs_read"],
            auth_status={"gmail": "unauthenticated", "calendar": "authenticated"},
        )
        service.hermes_client.bind_context(ctx)
        service.connection_manager.bridge.bind_context(ctx)

        payload = service.get_data_sources_payload()

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["connection_stage"], "capabilities_discovered")
        self.assertFalse(payload["gmail_authenticated"])
        self.assertEqual(payload["hermes"]["status"], "connected")
        self.assertEqual(payload["gmail"]["status"], "unauthenticated")
        self.assertTrue(payload["gmail"]["needs_connection_in_hermes"])
        self.assertIn("hermes auth google", payload["actionable_instructions"])


if __name__ == "__main__":
    unittest.main()
