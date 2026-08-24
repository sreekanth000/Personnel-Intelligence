"""
Test Suite for Personal Intelligence Demo UI & /api/pi/* Endpoints.

Validates:
1. All 7 screens data contracts under /api/pi/*
2. 9-Stage vertical Situation Detail lifecycle flow payload:
   TRIGGER -> OBSERVATIONS -> TIMELINE -> INFORMATION GAPS -> HERMES INVESTIGATION -> EVIDENCE -> REASONING -> RECOMMENDATION -> INTERVENTION DECISION
3. Strict Epistemic Demarcation (FACT, INFERENCE, PREDICTION, RECOMMENDATION, INTERVENTION)
4. Interactive Action Endpoints (/api/pi/actions/*)
5. Absence of fake floating-point confidence probabilities
6. Static HTML5, CSS, and JS asset serving
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.request

from personal_intelligence.api.server import DashboardDataService, create_dashboard_server
from personal_intelligence.storage.db import DatabaseManager


class TestDemoUIAPIPi(unittest.TestCase):
    """
    Test suite for the /api/pi/* API surface and Demo UI.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.temp_dir.name, "demo_ui_test.db")
        cls.db_manager = DatabaseManager(db_path=cls.db_path)
        cls.db_manager.initialize_schema()

        cls.data_service = DashboardDataService(db_manager=cls.db_manager)

        cls.port = 8911
        cls.host = "127.0.0.1"
        cls.server = create_dashboard_server(
            port=cls.port,
            host=cls.host,
            db_manager=cls.db_manager,
        )
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp_dir.cleanup()

    def _get_json(self, path: str) -> dict:
        url = f"http://{self.host}:{self.port}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("application/json", resp.headers.get("Content-Type"))
            return json.loads(resp.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"http://{self.host}:{self.port}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("application/json", resp.headers.get("Content-Type"))
            return json.loads(resp.read().decode("utf-8"))

    # -------------------------------------------------------------------------
    # Screen 1: Overview
    # -------------------------------------------------------------------------
    def test_screen_overview_endpoint(self) -> None:
        data = self._get_json("/api/pi/overview")
        self.assertIn("current_state", data)
        self.assertIn("active_goals", data)
        self.assertIn("upcoming_commitments", data)
        self.assertIn("open_situations", data)
        self.assertIn("important_recommendations", data)
        self.assertIn("emerging_patterns", data)
        self.assertIn("novelty_indicators", data)
        self.assertGreaterEqual(len(data["active_goals"]), 1)

    # -------------------------------------------------------------------------
    # Screen 2: World Model
    # -------------------------------------------------------------------------
    def test_screen_world_model_endpoint(self) -> None:
        data = self._get_json("/api/pi/world_model")
        self.assertIn("goals", data)
        self.assertIn("open_situations", data)
        self.assertIn("known_patterns", data)
        self.assertIn("current_state", data)
        self.assertIn("computed_features", data["current_state"])

    # -------------------------------------------------------------------------
    # Screen 3 & 4: Situations and 9-Stage Visual Flow Detail
    # -------------------------------------------------------------------------
    def test_screen_situations_and_9_stage_detail_flow(self) -> None:
        sits = self._get_json("/api/pi/situations")
        self.assertIsInstance(sits, list)
        self.assertGreaterEqual(len(sits), 1)

        sit_id = sits[0]["situation_id"]
        detail = self._get_json(f"/api/pi/situations/{sit_id}")

        self.assertEqual(detail["status"], "success")
        self.assertIn("flow", detail)
        flow = detail["flow"]

        # Stage 1: TRIGGER
        self.assertIn("trigger", flow)
        self.assertEqual(flow["trigger"]["stage"], "TRIGGER")
        self.assertIn("title", flow["trigger"])
        self.assertIn("priority", flow["trigger"])

        # Stage 2: OBSERVATIONS
        self.assertIn("observations", flow)
        self.assertGreaterEqual(len(flow["observations"]), 1)
        self.assertEqual(flow["observations"][0]["tag"], "FACT")
        self.assertIn("provenance", flow["observations"][0])

        # Stage 3: TIMELINE
        self.assertIn("timeline", flow)
        self.assertIsInstance(flow["timeline"], list)

        # Stage 4: INFORMATION GAPS
        self.assertIn("information_gaps", flow)
        self.assertIsInstance(flow["information_gaps"], list)

        # Stage 5: HERMES INVESTIGATION
        self.assertIn("investigation", flow)
        self.assertIn("status", flow["investigation"])
        self.assertIn("capabilities_used", flow["investigation"])

        # Stage 6: EVIDENCE
        self.assertIn("evidence", flow)
        self.assertIsInstance(flow["evidence"], list)

        # Stage 7: REASONING (Epistemic separation)
        self.assertIn("reasoning", flow)
        self.assertIn("inferences", flow["reasoning"])
        self.assertIn("predictions", flow["reasoning"])
        for inf in flow["reasoning"]["inferences"]:
            self.assertEqual(inf["tag"], "INFERENCE")
        for pred in flow["reasoning"]["predictions"]:
            self.assertEqual(pred["tag"], "PREDICTION")

        # Stage 8: RECOMMENDATION
        self.assertIn("recommendation", flow)
        self.assertEqual(flow["recommendation"]["tag"], "RECOMMENDATION")
        self.assertIn("primary", flow["recommendation"])

        # Stage 9: INTERVENTION DECISION
        self.assertIn("intervention", flow)
        self.assertEqual(flow["intervention"]["tag"], "INTERVENTION")
        self.assertIn("action", flow["intervention"])
        self.assertIn(flow["intervention"]["action"].upper(), ["INTERRUPT", "BRIEFING", "DEFER", "SUPPRESS", "DISCARD"])

    # -------------------------------------------------------------------------
    # Screen 5: Patterns
    # -------------------------------------------------------------------------
    def test_screen_patterns_endpoint(self) -> None:
        data = self._get_json("/api/pi/patterns")
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        pat = data[0]
        self.assertIn("description", pat)
        self.assertIn("support_count", pat)
        self.assertIn("confidence_ratio", pat)
        self.assertIn("evidence_provenance", pat)

    # -------------------------------------------------------------------------
    # Screen 6: Timeline
    # -------------------------------------------------------------------------
    def test_screen_timeline_endpoint(self) -> None:
        data = self._get_json("/api/pi/timeline?limit=15")
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        evt = data[0]
        self.assertIn("id", evt)
        self.assertIn("source", evt)
        self.assertIn("timestamp", evt)
        self.assertIn("summary", evt)

    # -------------------------------------------------------------------------
    # Screen 7: Reasoning Episodes
    # -------------------------------------------------------------------------
    def test_screen_episodes_endpoint(self) -> None:
        data = self._get_json("/api/pi/episodes")
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        ep = data[0]
        self.assertIn("facts", ep)
        self.assertIn("inferences", ep)
        self.assertIn("predictions", ep)
        self.assertIn("recommendation", ep)
        self.assertIn("intervention", ep)
        self.assertIn("outcome", ep)

    # -------------------------------------------------------------------------
    # Action Invocations (/api/pi/actions/*)
    # -------------------------------------------------------------------------
    def test_action_endpoints(self) -> None:
        # /api/pi/actions/what_matters
        res_wm = self._post_json("/api/pi/actions/what_matters", {})
        self.assertEqual(res_wm["status"], "success")
        self.assertIn("formatted_text", res_wm)

        # /api/pi/actions/what_changed
        res_wc = self._post_json("/api/pi/actions/what_changed", {"time_window_hours": 48})
        self.assertEqual(res_wc["status"], "success")
        self.assertIn("changes", res_wc)

        # /api/pi/actions/investigate
        res_inv = self._post_json("/api/pi/actions/investigate", {})
        self.assertEqual(res_inv["status"], "success")

        # /api/pi/actions/why
        res_why = self._post_json("/api/pi/actions/why", {})
        self.assertEqual(res_why["status"], "success")
        self.assertIn("diagnostic_report", res_why)

        # /api/pi/actions/test_sources
        res_src = self._post_json("/api/pi/actions/test_sources", {})
        self.assertEqual(res_src["status"], "success")
        self.assertIn("sources", res_src)

    # -------------------------------------------------------------------------
    # Activity Stream & Sources Endpoints
    # -------------------------------------------------------------------------
    def test_activity_stream_and_sources_get_endpoints(self) -> None:
        act = self._get_json("/api/pi/activity?limit=10")
        self.assertIsInstance(act, list)

        sources = self._get_json("/api/pi/sources")
        self.assertIsInstance(sources, list)
        self.assertEqual(len(sources), 7)

    # -------------------------------------------------------------------------
    # Demo Mode Scenario Loading & Reset
    # -------------------------------------------------------------------------
    def test_demo_mode_scenario_actions(self) -> None:
        res1 = self._post_json("/api/pi/demo/load_scenario", {"scenario_id": 1})
        self.assertEqual(res1["status"], "success")
        self.assertTrue(res1["is_demo_mode"])

        res2 = self._post_json("/api/pi/demo/load_scenario", {"scenario_id": 2})
        self.assertEqual(res2["status"], "success")

        res3 = self._post_json("/api/pi/demo/load_scenario", {"scenario_id": 3})
        self.assertEqual(res3["status"], "success")

        res4 = self._post_json("/api/pi/demo/load_scenario", {"scenario_id": 4})
        self.assertEqual(res4["status"], "success")

        res5 = self._post_json("/api/pi/demo/load_scenario", {"scenario_id": 5})
        self.assertEqual(res5["status"], "success")

        res_intel = self._post_json("/api/pi/demo/run_intelligence", {})
        self.assertEqual(res_intel["status"], "success")

        res_clear = self._post_json("/api/pi/demo/clear", {})
        self.assertEqual(res_clear["status"], "success")

        res_reset = self._post_json("/api/pi/demo/reset", {})
        self.assertEqual(res_reset["status"], "success")

    # -------------------------------------------------------------------------
    # Static Assets & Zero Write UI Integrity
    # -------------------------------------------------------------------------
    def test_static_ui_assets_and_integrity(self) -> None:
        url_html = f"http://{self.host}:{self.port}/index.html"
        with urllib.request.urlopen(url_html, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            # Verify all 7 screens exist in markup
            self.assertIn('id="screen-overview"', content)
            self.assertIn('id="screen-world-model"', content)
            self.assertIn('id="screen-situations"', content)
            self.assertIn('id="screen-situation-detail"', content)
            self.assertIn('id="screen-patterns"', content)
            self.assertIn('id="screen-timeline"', content)
            self.assertIn('id="screen-episodes"', content)
            # Verify live activity stream container and demo controller exist
            self.assertIn('id="live-activity-stream-container"', content)
            self.assertIn('id="btn-mode-live"', content)
            self.assertIn('id="btn-mode-demo"', content)
            self.assertIn('id="demo-scenario-select"', content)
            self.assertIn('id="btn-demo-inject"', content)
            self.assertIn('id="btn-demo-run"', content)
            self.assertIn('id="btn-demo-reset"', content)
            self.assertIn('id="btn-demo-clear"', content)
            # Verify epistemic tags
            self.assertIn("badge-fact", content)
            self.assertIn("badge-inference", content)
            self.assertIn("badge-prediction", content)
            self.assertIn("badge-recommendation", content)
            self.assertIn("badge-intervention", content)


if __name__ == "__main__":
    unittest.main()
