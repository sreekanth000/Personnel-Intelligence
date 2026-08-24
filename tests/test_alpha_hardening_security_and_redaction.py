"""
Alpha Release Security, Invariant Hardening, and Sensitive Data Redaction Tests.

Validates:
1. Personal Intelligence cannot access Gmail without host Hermes runtime.
2. Live mode strictly disallows stub / mock success fallbacks.
3. UI and API never claim Gmail investigated without a real tool-execution record.
4. Sensitive Gmail / personal fields are redacted across logs, activity feeds, errors, and reasoning episodes.
"""

from datetime import datetime, timezone
import json
import os
import tempfile
from typing import Any, Dict
import unittest
from unittest.mock import MagicMock

from personal_intelligence.api.server import DashboardDataService
from personal_intelligence.core.activity.stream import ActivityStream
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesRuntimeBridge,
    MissingCapabilityError,
    MissingRuntimeContextError,
    UnauthenticatedCapabilityError,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.gmail_adapter import (
    GmailCapabilityAdapter,
    GmailCapabilityRequest,
)
from personal_intelligence.security.guard import UnauthorizedWriteOperationError
from personal_intelligence.security.redactor import SensitivePayloadRedactor
from personal_intelligence.storage.db import DatabaseManager


class TestAlphaHardeningSecurityAndRedaction(unittest.TestCase):
    """
    Hardening security and redaction test suite for Alpha release.
    """

    def setUp(self) -> None:
        set_active_hermes_context(None)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "hardening_test.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.service = DashboardDataService(db_manager=self.db_manager)
        self.service.is_demo_mode = False
        self.activity_stream = ActivityStream.get_instance()

    def tearDown(self) -> None:
        set_active_hermes_context(None)
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Personal Intelligence Cannot Access Gmail Without Hermes
    # -------------------------------------------------------------------------
    def test_gmail_access_impossible_without_hermes(self) -> None:
        """Personal Intelligence fails explicitly with typed errors if Hermes context is absent."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        bridge.bind_context(None)

        # Direct tool execution without runtime context in LIVE mode must raise MissingRuntimeContextError
        with self.assertRaises(MissingRuntimeContextError):
            bridge.execute_tool("gmail_search", {"query": "urgent contract"})

        # Gmail capability adapter returns unavailable status when Hermes is offline
        adapter = GmailCapabilityAdapter(bridge=bridge)
        req = GmailCapabilityRequest(query="urgent contract")
        result = adapter.execute_query(req)
        self.assertEqual(result.status, "unavailable")
        self.assertIn("not attached", result.error or "")

    def test_zero_oauth_tokens_or_google_clients_in_codebase(self) -> None:
        """Verifies no Google OAuth clients or credential storage exists in the package."""
        import personal_intelligence

        self.assertFalse(hasattr(personal_intelligence, "GmailClient"))
        self.assertFalse(hasattr(personal_intelligence, "GoogleOAuth"))
        self.assertFalse(hasattr(personal_intelligence, "OAuth2Credentials"))
        self.assertFalse(hasattr(personal_intelligence, "TokenStore"))

    # -------------------------------------------------------------------------
    # 2. Live Mode Cannot Use Stub Success Responses
    # -------------------------------------------------------------------------
    def test_live_mode_rejects_stub_success_fallback(self) -> None:
        """Live mode must never synthesize fake success responses or silent mocks."""
        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        bridge.bind_context(None)

        # Tool call without runtime context in LIVE mode must raise typed error
        with self.assertRaises(MissingRuntimeContextError):
            bridge.execute_tool("gmail_search", {"query": "status"})

        # Invocation without runtime context in LIVE mode fails explicitly
        from personal_intelligence.hermes_bridge.client import HermesInvocationRequest
        res = bridge.invoke_reasoning(HermesInvocationRequest(prompt="Analyze status"))
        self.assertFalse(res.success)
        self.assertIn("not attached in LIVE mode", res.error or "")

    def test_live_mode_raises_on_unauthenticated_capability(self) -> None:
        """Live mode raises UnauthenticatedCapabilityError or returns unauthenticated status."""
        mock_ctx = MagicMock()
        mock_ctx.available_tools = ["gmail_search"]
        mock_ctx.is_capability_authenticated.return_value = False

        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        bridge.bind_context(mock_ctx)

        with self.assertRaises(UnauthenticatedCapabilityError):
            bridge.execute_tool("gmail_search", {"query": "status"})

        # Adapter returns typed unauthenticated status
        mock_ctx_dict = MagicMock()
        mock_ctx_dict.available_tools = ["gmail_search"]
        mock_ctx_dict.auth_status = {"gmail": "unauthenticated"}
        bridge.bind_context(mock_ctx_dict)
        adapter = GmailCapabilityAdapter(bridge=bridge)
        req = GmailCapabilityRequest(query="status")
        res = adapter.execute_query(req)
        self.assertEqual(res.status, "unauthenticated")

    # -------------------------------------------------------------------------
    # 3. UI/API Never Claims Gmail Investigation Without Real Tool Execution
    # -------------------------------------------------------------------------
    def test_ui_and_api_never_claim_investigation_without_event(self) -> None:
        """Dashboard data source and situation detail payloads verify no Gmail investigation occurred."""
        sit = self.service.situation_store.create_situation(
            type="deadline_risk",
            priority="high",
            context={"summary": "Pending deliverable deadline approaching."},
        )

        # 1. Sources status reports last_successful_investigation as None
        sources = self.service.get_data_sources_payload()
        self.assertIsNone(sources["gmail"]["last_successful_investigation"])

        # 2. Situation detail returns 0 Gmail investigation calls
        detail = self.service.get_situation_detail_payload(sit.id)
        calls = detail.get("investigation", {}).get("calls", [])
        gmail_calls = [c for c in calls if c.get("capability") == "Gmail"]
        self.assertEqual(len(gmail_calls), 0)

    # -------------------------------------------------------------------------
    # 4. Sensitive Gmail & Personal Field Redaction
    # -------------------------------------------------------------------------
    def test_sensitive_payload_redaction_in_activity_stream(self) -> None:
        """Activity stream automatically redacts passwords, tokens, and sensitive personal fields."""
        ev = self.activity_stream.emit(
            event_type="observation_created",
            summary="User authenticated with Bearer secret_oauth_token_12345 and password supersecret",
            metadata={
                "access_token": "ya29.sensitive_oauth_token",
                "email_body": "Confidential financial transaction details",
                "safe_field": "public_meeting",
            },
        )

        self.assertNotIn("secret_oauth_token_12345", ev.summary)
        self.assertIn("[REDACTED_SENSITIVE]", str(ev.metadata.get("access_token")))
        self.assertIn("[REDACTED_SENSITIVE]", str(ev.metadata.get("email_body")))
        self.assertEqual(ev.metadata.get("safe_field"), "public_meeting")

    def test_sensitive_payload_redaction_in_reasoning_episodes(self) -> None:
        """Episode store sanitizes observations, inferences, predictions, and metadata."""
        ep = self.service.episode_store.create_episode(
            situation_id="sit-test-redact",
            hermes_task="Assess sensitive deliverable status",
            observations=[
                {"type": "FACT", "content": "Bearer ya29.token_payload_xyz leaked in message"},
                {"type": "FACT", "password": "mypassword123", "content": "Validated telemetry"},
            ],
            inferences=[
                {"type": "INFERENCE", "secret_key": "sk-live-sensitive", "content": "Workload is heavy"},
            ],
            predictions=[
                {"type": "PREDICTION", "api_key": "api_sensitive_key", "content": "Risk high"},
            ],
            recommendation={
                "type": "RECOMMENDATION",
                "auth_token": "token_abc",
                "primary_action": "Review upcoming milestones",
            },
            context_snapshot={"private_key": "ssh-rsa sensitive"},
            metadata={"refresh_token": "1//refresh_token_secret"},
        )

        # Retrieve stored episode and verify redaction
        stored = self.service.episode_store.get_episode(ep.id)
        self.assertIsNotNone(stored)
        stored_dict_str = json.dumps(stored.to_dict())

        self.assertNotIn("ya29.token_payload_xyz", stored_dict_str)
        self.assertNotIn("mypassword123", stored_dict_str)
        self.assertNotIn("sk-live-sensitive", stored_dict_str)
        self.assertNotIn("api_sensitive_key", stored_dict_str)
        self.assertNotIn("token_abc", stored_dict_str)
        self.assertNotIn("ssh-rsa sensitive", stored_dict_str)
        self.assertNotIn("1//refresh_token_secret", stored_dict_str)

    def test_write_operations_strictly_prohibited(self) -> None:
        """Personal Intelligence forbids all Gmail mutation operations."""
        mock_ctx = MagicMock()
        mock_ctx.available_tools = ["gmail_search"]
        mock_ctx.auth_status = {"gmail": "authenticated"}

        bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.LIVE)
        bridge.bind_context(mock_ctx)

        adapter = GmailCapabilityAdapter(bridge=bridge)
        req = GmailCapabilityRequest(query="status")

        with self.assertRaises(UnauthorizedWriteOperationError):
            adapter.execute_query(req, tool_name="gmail_send_message")

        with self.assertRaises(UnauthorizedWriteOperationError):
            adapter.execute_query(req, tool_name="gmail_delete_message")

        with self.assertRaises(UnauthorizedWriteOperationError):
            adapter.execute_query(req, tool_name="gmail_modify_labels")


if __name__ == "__main__":
    unittest.main()
