"""
Tests for Hermes Capability-Connection Contract, Status Reporting, and Zero-OAuth Boundaries.
"""

from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock

from personal_intelligence.hermes_bridge.capabilities import (
    CAPABILITY_TOOL_MAPPINGS,
    REQUIRED_CAPABILITIES,
    CapabilityAuthStatus,
    CapabilityAvailability,
    CapabilityStatus,
    HermesCapabilityInspector,
    HermesConnectionStage,
    HermesConnectionStatus,
    HermesRuntimeStatusReport,
)
from personal_intelligence.hermes_bridge.client import (
    HermesClient,
    HermesRuntimeBridge,
    get_active_hermes_context,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
from personal_intelligence.storage.db import DatabaseManager


class TestHermesCapabilityContract(unittest.TestCase):
    """
    Validates the strict Hermes capability-connection contract models, enums,
    inspector probing, and zero-OAuth boundary guarantees.
    """

    def setUp(self) -> None:
        self.inspector = HermesCapabilityInspector()
        set_active_hermes_context(None)

    def tearDown(self) -> None:
        set_active_hermes_context(None)

    # -------------------------------------------------------------------------
    # 1. HermesConnectionStatus Enums & Values
    # -------------------------------------------------------------------------
    def test_connection_status_enum_values(self) -> None:
        """Verifies exact requirement: disconnected, connecting, connected, unavailable, unauthenticated, error, demo."""
        required_states = [
            "disconnected",
            "connecting",
            "connected",
            "unavailable",
            "unauthenticated",
            "error",
            "demo",
        ]
        enum_values = [s.value for s in HermesConnectionStatus]
        for state in required_states:
            self.assertIn(state, enum_values, f"Missing required connection status: {state}")
            self.assertEqual(HermesConnectionStatus(state).value, state)

    # -------------------------------------------------------------------------
    # 2. Required 7 Capabilities & Tool Mappings
    # -------------------------------------------------------------------------
    def test_required_capabilities_list(self) -> None:
        """Verifies Gmail, Calendar, Drive, Meet, filesystem, web, reasoning are present."""
        expected = ["gmail", "calendar", "drive", "meet", "filesystem", "web", "reasoning"]
        for cap in expected:
            self.assertIn(cap, REQUIRED_CAPABILITIES)
            self.assertIn(cap, CAPABILITY_TOOL_MAPPINGS)

    # -------------------------------------------------------------------------
    # 3. CapabilityStatus Schema & Read-Only Enforcement
    # -------------------------------------------------------------------------
    def test_capability_status_fields_and_read_only_default(self) -> None:
        """Verifies capability status fields, read_only=True, and serialization."""
        now = datetime.now(timezone.utc)
        status = CapabilityStatus(
            capability_name="gmail",
            availability=CapabilityAvailability.AVAILABLE,
            authenticated_status=CapabilityAuthStatus.AUTHENTICATED,
            read_only=True,
            tool_name="gmail_search",
            last_checked_at=now,
            error_message=None,
            safe_diagnostics={"probe_type": "unit_test"},
        )

        d = status.to_dict()
        self.assertEqual(d["capability_name"], "gmail")
        self.assertEqual(d["availability"], "available")
        self.assertEqual(d["authenticated_status"], "authenticated")
        self.assertTrue(d["read_only"])
        self.assertEqual(d["tool_name"], "gmail_search")
        self.assertIn("T", d["last_checked_at"])
        self.assertIsNone(d["error_message"])
        self.assertEqual(d["safe_diagnostics"]["probe_type"], "unit_test")

    # -------------------------------------------------------------------------
    # 4. Probing in Standalone / Unattached Mode
    # -------------------------------------------------------------------------
    def test_probe_all_standalone_unattached(self) -> None:
        """Verifies report when no host Hermes runtime context is attached."""
        report = self.inspector.probe_all(runtime_context=None, is_demo=False)

        self.assertEqual(report.connection_status, HermesConnectionStatus.DISCONNECTED)
        self.assertEqual(report.runtime_mode, "standalone_local")
        self.assertEqual(len(report.capabilities), 7)

        # External Google Workspace capabilities must report UNAVAILABLE & UNAUTHENTICATED
        for cap in ["gmail", "calendar", "drive", "meet", "web"]:
            cap_stat = report.capabilities[cap]
            self.assertEqual(cap_stat.availability, CapabilityAvailability.UNAVAILABLE)
            self.assertEqual(cap_stat.authenticated_status, CapabilityAuthStatus.UNAUTHENTICATED)
            self.assertTrue(cap_stat.read_only)
            self.assertIsNotNone(cap_stat.error_message)

        # Local capabilities (filesystem, reasoning) remain locally available
        self.assertEqual(report.capabilities["filesystem"].availability, CapabilityAvailability.AVAILABLE)
        self.assertEqual(report.capabilities["reasoning"].availability, CapabilityAvailability.AVAILABLE)

    # -------------------------------------------------------------------------
    # 5. Probing in Demo Mode
    # -------------------------------------------------------------------------
    def test_probe_all_demo_mode(self) -> None:
        """Verifies report when operating in deterministic DEMO MODE."""
        report = self.inspector.probe_all(runtime_context=None, is_demo=True)

        self.assertEqual(report.connection_status, HermesConnectionStatus.DEMO)
        self.assertEqual(report.runtime_mode, "demo")

        for cap in REQUIRED_CAPABILITIES:
            cap_stat = report.capabilities[cap]
            self.assertEqual(cap_stat.availability, CapabilityAvailability.DEMO)
            self.assertEqual(cap_stat.authenticated_status, CapabilityAuthStatus.NOT_REQUIRED)
            self.assertTrue(cap_stat.read_only)
            self.assertTrue(cap_stat.safe_diagnostics.get("synthetic_observations_active"))

    # -------------------------------------------------------------------------
    # 6. Probing with Mock Attached Hermes Context
    # -------------------------------------------------------------------------
    def test_probe_all_attached_hermes_context_authenticated(self) -> None:
        """Verifies report when attached to a live Hermes context declaring all tools."""
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
        mock_context.auth_status = {c: "authenticated" for c in REQUIRED_CAPABILITIES}

        report = self.inspector.probe_all(runtime_context=mock_context, is_demo=False)

        self.assertEqual(report.connection_status, HermesConnectionStatus.CONNECTED)
        self.assertEqual(report.runtime_mode, "attached_hermes")

        for cap in REQUIRED_CAPABILITIES:
            cap_stat = report.capabilities[cap]
            self.assertEqual(cap_stat.availability, CapabilityAvailability.AVAILABLE)
            self.assertEqual(cap_stat.authenticated_status, CapabilityAuthStatus.AUTHENTICATED)
            self.assertTrue(cap_stat.read_only)

    def test_probe_all_attached_hermes_context_unauthenticated_source(self) -> None:
        """Verifies report when Hermes context is attached but an external source is unauthenticated."""
        mock_context = MagicMock()
        mock_context.available_tools = ["gmail_search", "calendar_list_events", "fs_read", "llm_reasoning"]
        mock_context.auth_status = {
            "gmail": "unauthenticated",
            "calendar": "authenticated",
            "drive": "unauthenticated",
            "meet": "unauthenticated",
            "filesystem": "authenticated",
            "web": "authenticated",
            "reasoning": "authenticated",
        }

        report = self.inspector.probe_all(runtime_context=mock_context, is_demo=False)

        # Hermes runtime IS connected and usable
        self.assertEqual(report.connection_status, HermesConnectionStatus.CONNECTED)
        self.assertEqual(report.connection_stage, HermesConnectionStage.CAPABILITIES_DISCOVERED)
        self.assertFalse(report.gmail_authenticated)

        # Gmail capability independently reports unauthenticated
        self.assertEqual(report.capabilities["gmail"].authenticated_status, CapabilityAuthStatus.UNAUTHENTICATED)
        self.assertEqual(report.capabilities["calendar"].authenticated_status, CapabilityAuthStatus.AUTHENTICATED)

    # -------------------------------------------------------------------------
    # 7. Zero OAuth / Token / Credential Code Guarantee
    # -------------------------------------------------------------------------
    def test_zero_oauth_tokens_or_credentials_stored(self) -> None:
        """Asserts that capability models and reports contain zero credentials or tokens."""
        report = self.inspector.probe_all(runtime_context=None, is_demo=False)
        d = report.to_dict()

        serialized_str = str(d).lower()
        forbidden_terms = ["access_token", "refresh_token", "client_secret", "oauth_token", "api_key", "password"]
        for term in forbidden_terms:
            self.assertNotIn(term, serialized_str, f"Forbidden credential term found in capability report: {term}")

        self.assertFalse(d["safe_diagnostics"].get("external_credentials_stored", True))
        self.assertTrue(d["safe_diagnostics"].get("read_only_enforced", False))

    # -------------------------------------------------------------------------
    # 8. Command Handler & /pi test_sources Integration
    # -------------------------------------------------------------------------
    def test_command_handler_test_sources_includes_all_7_capabilities(self) -> None:
        """Verifies /pi test_sources includes Gmail, Calendar, Drive, Meet, Filesystem, Web, Reasoning."""
        db = DatabaseManager(db_path=":memory:")
        bridge = HermesRuntimeBridge()
        handler = PersonalIntelligenceCommandHandler(db_manager=db, hermes_client=bridge)

        sources = handler.get_test_sources_payload()
        self.assertEqual(len(sources), 7)

        caps = [s["capability"] for s in sources]
        for expected_cap in REQUIRED_CAPABILITIES:
            self.assertIn(expected_cap, caps)

        formatted_md = handler.handle_test_sources()
        self.assertIn("Gmail", formatted_md)
        self.assertIn("Google Calendar", formatted_md)
        self.assertIn("Google Drive", formatted_md)
        self.assertIn("Google Meet", formatted_md)
        self.assertIn("Filesystem", formatted_md)
        self.assertIn("Web Search", formatted_md)
        self.assertIn("Hermes Reasoning", formatted_md)


if __name__ == "__main__":
    unittest.main()
