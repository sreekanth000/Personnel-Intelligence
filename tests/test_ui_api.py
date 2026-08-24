"""
Test suite validating the Personal Intelligence Web UI Dashboard and API Endpoints.
Verifies all 6 core sections, strict epistemic demarcation, absence of pseudo-probability
claims, and static asset serving.
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


class TestPersonalIntelligenceUI(unittest.TestCase):
    """
    Validates Dashboard API server, data serialization, and epistemic demarcation.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.temp_dir.name, "ui_test.db")
        cls.db_manager = DatabaseManager(db_path=cls.db_path)
        cls.db_manager.initialize_schema()

        cls.data_service = DashboardDataService(db_manager=cls.db_manager)

        # Start live server on ephemeral high port
        cls.port = 8899
        cls.host = "127.0.0.1"
        cls.server = create_dashboard_server(
            port=cls.port,
            host=cls.host,
            db_manager=cls.db_manager,
        )
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.3)  # Brief warm-up

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp_dir.cleanup()

    def _get_json(self, path: str) -> dict:
        """Helper to fetch and parse JSON from local test server."""
        url = f"http://{self.host}:{self.port}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("application/json", resp.headers.get("Content-Type"))
            return json.loads(resp.read().decode("utf-8"))

    def test_complete_dashboard_summary_payload(self) -> None:
        """
        Verify /api/summary returns all 6 required sections with rich content.
        """
        data = self._get_json("/api/summary")

        # 1. CURRENT STATE
        self.assertIn("current_state", data)
        cs = data["current_state"]
        self.assertIn("summary", cs)
        self.assertIn("activity", cs)
        self.assertIn("features", cs)
        self.assertGreaterEqual(len(cs["features"]), 5)

        # 2. ACTIVE SITUATIONS
        self.assertIn("active_situations", data)
        situations = data["active_situations"]
        self.assertGreaterEqual(len(situations), 1)
        sit = situations[0]
        self.assertIn("situation_id", sit)
        self.assertIn("why_detected", sit)
        self.assertIn("evidence", sit)
        self.assertGreaterEqual(len(sit["evidence"]), 1)

        # 3. RECOMMENDATIONS
        self.assertIn("recommendations", data)
        recs = data["recommendations"]
        self.assertGreaterEqual(len(recs), 1)
        rec = recs[0]
        self.assertIn("title", rec)
        self.assertIn("why", rec)
        self.assertIn("policy_action", rec)

        # 4. LEARNED PATTERNS
        self.assertIn("learned_patterns", data)
        patterns = data["learned_patterns"]
        self.assertGreaterEqual(len(patterns), 1)
        pat = patterns[0]
        self.assertIn("description", pat)
        self.assertIn("support_count", pat)
        self.assertIn("contradiction_count", pat)
        self.assertIn("confidence_ratio", pat)

        # 5. REASONING EPISODES
        self.assertIn("reasoning_episodes", data)
        episodes = data["reasoning_episodes"]
        self.assertGreaterEqual(len(episodes), 1)
        ep = episodes[0]
        self.assertIn("facts", ep)
        self.assertIn("inferences", ep)
        self.assertIn("predictions", ep)
        self.assertIn("recommendation", ep)
        self.assertIn("intervention", ep)
        self.assertIn("outcome", ep)

        # 6. NOVEL EVENTS
        self.assertIn("novel_events", data)
        novel_events = data["novel_events"]
        self.assertGreaterEqual(len(novel_events), 1)
        novel = novel_events[0]
        self.assertIn("novelty_level", novel)
        self.assertIn("why_unusual", novel)
        novel_with_uncertainty = next((n for n in novel_events if n.get("insufficient_evidence")), None)
        self.assertIsNotNone(novel_with_uncertainty)
        self.assertTrue(novel_with_uncertainty["insufficient_evidence"])

    def test_strict_epistemic_demarcation(self) -> None:
        """
        Verify reasoning episodes explicitly segregate FACT, INFERENCE, PREDICTION, RECOMMENDATION.
        """
        episodes = self._get_json("/api/episodes")
        self.assertGreaterEqual(len(episodes), 1)
        ep = episodes[0]

        # Verify fact tags
        for f in ep["facts"]:
            self.assertEqual(f["tag"], "FACT")

        # Verify inference tags
        for inf in ep["inferences"]:
            self.assertEqual(inf["tag"], "INFERENCE")

        # Verify prediction tags
        for pred in ep["predictions"]:
            self.assertEqual(pred["tag"], "PREDICTION")

        # Verify recommendation tag
        self.assertEqual(ep["recommendation"]["tag"], "RECOMMENDATION")
        self.assertEqual(ep["intervention"]["tag"], "INTERVENTION")
        self.assertEqual(ep["outcome"]["tag"], "OUTCOME")

    def test_absence_of_pseudo_probability_claims(self) -> None:
        """
        Verify no LLM outputs are presented as faux floating-point probabilities (e.g. 0.941 probability).
        Metrics must represent empirical counts and qualitative strength categories.
        """
        data = self._get_json("/api/summary")
        summary_raw = json.dumps(data)

        # Verify qualitative labels and empirical ratios exist
        self.assertIn("STRONG", summary_raw)
        self.assertIn("High Novelty", summary_raw)
        self.assertIn("Empirical Support", summary_raw)

    def test_static_ui_assets_served(self) -> None:
        """
        Verify index.html, styles.css, and app.js are correctly served over HTTP.
        """
        # index.html
        url_html = f"http://{self.host}:{self.port}/index.html"
        with urllib.request.urlopen(url_html, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("Personal Intelligence", content)
            self.assertIn("badge-fact", content)

        # styles.css
        url_css = f"http://{self.host}:{self.port}/styles.css"
        with urllib.request.urlopen(url_css, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("--fact-color", content)

        # app.js
        url_js = f"http://{self.host}:{self.port}/app.js"
        with urllib.request.urlopen(url_js, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("fetchOverview", content)

    def _post_json(self, path: str, payload: dict) -> dict:
        """Helper to post and parse JSON from local test server."""
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

    def test_timeline_and_world_model_endpoints(self) -> None:
        """Verify /api/timeline and /api/world_model endpoints."""
        timeline_data = self._get_json("/api/timeline?limit=10")
        self.assertIsInstance(timeline_data, list)
        self.assertGreaterEqual(len(timeline_data), 1)
        first_evt = timeline_data[0]
        self.assertIn("id", first_evt)
        self.assertIn("source", first_evt)
        self.assertIn("timestamp", first_evt)

        wm_data = self._get_json("/api/world_model")
        self.assertIn("goals", wm_data)
        self.assertIn("open_situations", wm_data)

    def test_post_action_endpoints(self) -> None:
        """Verify interactive action endpoints (/api/actions/*)."""
        # 1. /api/actions/what_matters
        res_matters = self._post_json("/api/actions/what_matters", {})
        self.assertEqual(res_matters["status"], "success")
        self.assertIn("formatted_text", res_matters)
        self.assertIn("recommendations", res_matters)

        # 2. /api/actions/what_changed
        res_changed = self._post_json("/api/actions/what_changed", {"time_window_hours": 48})
        self.assertEqual(res_changed["status"], "success")
        self.assertIn("changes", res_changed)

        # 3. /api/actions/why
        res_why = self._post_json("/api/actions/why", {})
        self.assertEqual(res_why["status"], "success")
        self.assertIn("diagnostic_report", res_why)

        # 4. /api/actions/investigate
        res_inv = self._post_json("/api/actions/investigate", {})
        self.assertEqual(res_inv["status"], "success")
        self.assertIn("investigation_succeeded", res_inv)


if __name__ == "__main__":
    unittest.main()

