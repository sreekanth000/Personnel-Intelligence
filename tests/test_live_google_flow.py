"""
Unit tests for Real Google Live Demo Flow.

Validates the complete canonical sequence:
LIVE MODE
    ↓
Hermes Google authentication
    ↓
/pi what_matters
    ↓
Personal World Model
    ↓
Situation Detection
    ↓
Hermes Gmail/Drive/Calendar/Meet
    ↓
Reasoning
    ↓
UI
"""

from datetime import datetime, timezone
import json
import threading
import time
import unittest
import urllib.request

from unittest.mock import MagicMock

from personal_intelligence.api.server import (
    DashboardDataService,
    create_dashboard_server,
)
from personal_intelligence.hermes_bridge.client import set_active_hermes_context
from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
from personal_intelligence.storage.db import DatabaseManager


def _create_mock_context() -> MagicMock:
    mock_ctx = MagicMock()
    mock_ctx.available_tools = [
        "gmail_search", "calendar_list_events", "drive_get_document",
        "meet_list_recent_meetings", "fs_read", "web_search", "llm_reasoning"
    ]
    mock_ctx.auth_status = {
        "gmail": "authenticated", "google": "authenticated",
        "calendar": "authenticated", "drive": "authenticated",
        "meet": "authenticated", "web": "authenticated",
        "filesystem": "authenticated", "reasoning": "authenticated",
    }
    mock_ctx.execute_tool.return_value = {"status": "success", "messages": []}
    return mock_ctx


class TestLiveGoogleFlow(unittest.TestCase):
    """
    Test suite for Real Google Live Flow execution.
    """

    def setUp(self) -> None:
        self.mock_ctx = _create_mock_context()
        set_active_hermes_context(self.mock_ctx)
        self.db = DatabaseManager(db_path=":memory:")
        self.db.initialize_schema()
        self.service = DashboardDataService(db_manager=self.db)
        self.service.connection_manager.bridge.bind_context(self.mock_ctx)
        self.service.investigator.hermes_client.bind_context(self.mock_ctx)
        self.handler = PersonalIntelligenceCommandHandler(db_manager=self.db)

    def tearDown(self) -> None:
        set_active_hermes_context(None)

    def test_live_flow_command_execution(self) -> None:
        out = self.handler.execute("/pi live_flow")
        self.assertIn("Real Google Workspace Live Flow", out)
        self.assertIn("LIVE MODE", out)
        self.assertIn("Hermes Google Workspace Capabilities", out)
        self.assertIn("Personal World Model", out)
        self.assertIn("Situation Detection", out)
        self.assertIn("Multi-Source Reasoning", out)

    def test_live_flow_service_execution(self) -> None:
        res = self.service.execute_live_google_flow()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["flow"], "REAL_GOOGLE_LIVE_DEMO_FLOW")
        self.assertEqual(res["mode"], "LIVE_MODE")
        self.assertFalse(self.service.is_demo_mode)
        self.assertEqual(len(res["stages"]), 8)

        stage_names = [s["name"] for s in res["stages"]]
        self.assertIn("LIVE MODE", stage_names)
        self.assertIn("Hermes Google Authentication", stage_names)
        self.assertIn("/pi what_matters", stage_names)
        self.assertIn("Personal World Model", stage_names)
        self.assertIn("Situation Detection", stage_names)
        self.assertIn("Hermes Gmail/Drive/Calendar/Meet", stage_names)
        self.assertIn("Reasoning & Policy", stage_names)
        self.assertIn("UI Presentation", stage_names)

        self.assertIn("what_matters_text", res)
        self.assertIsInstance(res["recommendations"], list)


class TestLiveGoogleFlowHttp(unittest.TestCase):
    """
    HTTP endpoint tests for POST /api/pi/live/run_flow.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.mock_ctx = _create_mock_context()
        set_active_hermes_context(cls.mock_ctx)
        cls.db = DatabaseManager(db_path=":memory:")
        cls.db.initialize_schema()
        cls.port = 18899
        cls.server = create_dashboard_server(
            host="127.0.0.1",
            port=cls.port,
            db_manager=cls.db,
            ui_dir="ui",
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        set_active_hermes_context(None)
        cls.server.shutdown()
        cls.server.server_close()

    def test_post_live_run_flow(self) -> None:
        url = f"http://127.0.0.1:{self.port}/api/pi/live/run_flow"
        req = urllib.request.Request(
            url,
            data=json.dumps({}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["flow"], "REAL_GOOGLE_LIVE_DEMO_FLOW")
            self.assertEqual(data["mode"], "LIVE_MODE")
            self.assertEqual(len(data["stages"]), 8)


if __name__ == "__main__":
    unittest.main()
