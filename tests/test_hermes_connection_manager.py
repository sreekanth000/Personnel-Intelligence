"""
Comprehensive Integration & Unit Tests for HermesConnectionManager:
- Connected state with dynamic capability discovery.
- Unavailable state with actionable local launch instructions.
- Unauthenticated state with official Hermes setup instructions ('hermes auth google').
- Zero-OAuth & strict read-only safety guarantees.
- API endpoint integration (/api/pi/hermes/status, /api/pi/hermes/connect, /api/pi/hermes/setup_gmail).
"""

from datetime import datetime, timezone
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from personal_intelligence.api.server import create_dashboard_server
from personal_intelligence.hermes_bridge.capabilities import (
    CapabilityAuthStatus,
    CapabilityAvailability,
    HermesConnectionStage,
    HermesConnectionStatus,
    REQUIRED_CAPABILITIES,
)
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesRuntimeBridge,
    get_active_hermes_context,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.connection_manager import (
    HermesConnectionManager,
    HermesHealthReport,
    HermesInstallationInfo,
    HermesReachabilityInfo,
)
from personal_intelligence.storage.db import DatabaseManager


class TestHermesConnectionManager(unittest.TestCase):
    """
    Test suite verifying HermesConnectionManager across all lifecycle states.
    """

    def setUp(self) -> None:
        set_active_hermes_context(None)
        self.bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        self.manager = HermesConnectionManager(bridge=self.bridge)

    def tearDown(self) -> None:
        set_active_hermes_context(None)

    # -------------------------------------------------------------------------
    # 1. Connected State
    # -------------------------------------------------------------------------
    def test_connected_state_dynamic_capability_discovery(self) -> None:
        """Verifies connected state with active Hermes context and dynamic capability discovery."""
        mock_context = MagicMock()
        mock_context.available_tools = [
            "gmail_search",
            "calendar_list_events",
            "drive_get_document",
            "meet_list_recent_meetings",
            "fs_read",
            "web_search",
            "llm_reasoning",
        ]
        mock_context.auth_status = {
            "gmail": "authenticated",
            "calendar": "authenticated",
            "drive": "authenticated",
            "meet": "authenticated",
            "filesystem": "not_required",
            "web": "authenticated",
            "reasoning": "not_required",
        }

        report = self.manager.connect(runtime_context=mock_context)
        self.assertEqual(report.connection_status, HermesConnectionStatus.CONNECTED)
        self.assertEqual(report.runtime_mode, "attached_hermes")

        # Discover all 7 capabilities
        self.assertEqual(len(report.capabilities), 7)
        for cap_name in REQUIRED_CAPABILITIES:
            self.assertIn(cap_name, report.capabilities)
            cap = report.capabilities[cap_name]
            self.assertEqual(cap.availability, CapabilityAvailability.AVAILABLE)
            self.assertTrue(cap.read_only)

        # Health report verification
        health = self.manager.check_health()
        self.assertTrue(health.is_reachable)
        self.assertEqual(health.reachability_mechanism, "in_process")
        self.assertEqual(health.gmail_auth_status, "authenticated")

    # -------------------------------------------------------------------------
    # 2. Unavailable / Disconnected State & Actionable Instructions
    # -------------------------------------------------------------------------
    def test_unavailable_state_provides_launch_instructions(self) -> None:
        """Verifies disconnected state provides clear, actionable local launch instructions."""
        self.manager.disconnect()

        with patch("shutil.which", return_value=None), patch("os.path.exists", return_value=False):
            inst_info = self.manager.detect_installation()
            self.assertFalse(inst_info.is_installed)

            reach_info = self.manager.check_reachability(gateway_url="http://127.0.0.1:9999")
            self.assertFalse(reach_info.is_reachable)

            health = self.manager.check_health()
            self.assertEqual(health.connection_status, HermesConnectionStatus.DISCONNECTED)
            self.assertIsNotNone(health.actionable_instructions)
            self.assertIn("hermes agent start", health.actionable_instructions)
            self.assertIn("pip install hermes-agent", health.actionable_instructions)

    def test_installed_but_unreachable_launch_instructions(self) -> None:
        """Verifies installed binary provides exact command to start Hermes."""
        with patch("shutil.which", return_value="/usr/local/bin/hermes"):
            instructions = self.manager.get_launch_instructions()
            self.assertIn("/usr/local/bin/hermes agent start", instructions)
            self.assertIn("Connect Hermes", instructions)

    # -------------------------------------------------------------------------
    # 3. Unauthenticated State & Official Setup Guide
    # -------------------------------------------------------------------------
    def test_unauthenticated_state_provides_official_hermes_setup_instructions(self) -> None:
        """Verifies unauthenticated Gmail provides official Hermes auth instructions."""
        mock_context = MagicMock()
        mock_context.available_tools = ["gmail_search", "calendar_list_events", "fs_read"]
        mock_context.auth_status = {
            "gmail": "unauthenticated",
            "calendar": "unauthenticated",
        }

        self.manager.connect(runtime_context=mock_context)
        health = self.manager.check_health()

        self.assertEqual(health.connection_status, HermesConnectionStatus.CONNECTED)
        self.assertEqual(health.connection_stage, HermesConnectionStage.CAPABILITIES_DISCOVERED)
        self.assertFalse(health.gmail_authenticated)
        self.assertEqual(health.gmail_auth_status, "unauthenticated")

        setup_info = self.manager.get_gmail_setup_instructions()
        self.assertEqual(setup_info["command"], "hermes auth google")
        self.assertEqual(setup_info["command_source"], "example_fallback")
        self.assertFalse(setup_info["is_official_command"])
        self.assertEqual(setup_info["command_label"], "example / environment-specific command")
        self.assertIn("Open Hermes and connect/configure its Gmail capability", setup_info["instruction"])
        self.assertTrue(setup_info["zero_oauth_guarantee"])
        self.assertTrue(setup_info["read_only_enforced"])

    # -------------------------------------------------------------------------
    # 4. Zero-OAuth & Read-Only Safety Assertions
    # -------------------------------------------------------------------------
    def test_zero_oauth_tokens_stored_or_exposed(self) -> None:
        """Guarantees no OAuth tokens or client secrets are created or stored."""
        health = self.manager.check_health()
        health_dict = health.__dict__
        serialized_str = json.dumps(health_dict, default=str).lower()

        forbidden_terms = ["client_secret", "refresh_token", "access_token", "api_key", "password"]
        for term in forbidden_terms:
            self.assertNotIn(term, serialized_str, f"Forbidden credential term found in health report: {term}")

        self.assertTrue(health.safe_diagnostics.get("zero_oauth_stored"))
        self.assertTrue(health.safe_diagnostics.get("read_only_enforced"))

    # -------------------------------------------------------------------------
    # 5. REST API Integration Endpoints
    # -------------------------------------------------------------------------
    def test_api_hermes_endpoints(self) -> None:
        """Tests /api/pi/hermes/status, /api/pi/hermes/connect, and /api/pi/hermes/setup_gmail."""
        import urllib.request
        import threading

        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "hermes_api_test.db")
        db_mgr = DatabaseManager(db_path=db_path)
        db_mgr.initialize_schema()

        server = create_dashboard_server(port=0, host="127.0.0.1", db_manager=db_mgr)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        base_url = f"http://127.0.0.1:{port}"

        try:
            # 1. GET /api/pi/hermes/status
            req = urllib.request.Request(f"{base_url}/api/pi/hermes/status")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["status"], "success")
                self.assertIn("health", data)
                self.assertIn("connection_status", data["health"])

            # 2. POST /api/pi/hermes/connect
            req = urllib.request.Request(
                f"{base_url}/api/pi/hermes/connect",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["status"], "success")
                self.assertIn("connection_status", data)

            # 3. GET /api/pi/hermes/setup_gmail
            req = urllib.request.Request(f"{base_url}/api/pi/hermes/setup_gmail")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["status"], "success")
                self.assertEqual(data["setup"]["command"], "hermes auth google")
                self.assertTrue(data["setup"]["zero_oauth_guarantee"])
        finally:
            server.shutdown()
            server.server_close()
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
