"""
Integration and unit tests for Personal Intelligence Event Ingestion API.
Tests HTTP endpoints (/events, /events/recent, /health) and EventIngestionService.
"""

from datetime import datetime, timezone
import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, Optional, Tuple
import unittest
import urllib.error
import urllib.request

from personal_intelligence.api.ingestion import (
    EventIngestionService,
    IngestionStatus,
)
from personal_intelligence.api.server import EventAPIServer
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.storage.db import DatabaseManager


class TestEventIngestionService(unittest.TestCase):
    """Unit tests for EventIngestionService parsing, validation, and contract handling."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_ingest.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.event_store = EventStore(db_manager=self.db_manager)
        self.service = EventIngestionService(event_store=self.event_store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ingest_valid_contract_event(self) -> None:
        """Verify ingestion of an event adhering to the required contract."""
        payload = {
            "event_id": "cust-event-123",
            "timestamp": "2026-08-21T15:30:00Z",
            "type": "custom_metric_logged",
            "source": "iot_agent",
            "subject": "device_main",
            "payload": {"voltage": 3.3, "status": "nominal"},
            "confidence": 0.95,
        }
        res = self.service.ingest_event(payload)
        self.assertEqual(res.status, IngestionStatus.ACCEPTED)
        self.assertEqual(res.event_id, "cust-event-123")
        self.assertIsNotNone(res.event_hash)

        # Verify stored in event store
        stored = self.event_store.get("cust-event-123")
        self.assertIsNotNone(stored)
        self.assertEqual(stored.event_type, "custom_metric_logged")
        self.assertEqual(stored.subject_id, "device_main")
        self.assertEqual(stored.confidence, 0.95)

    def test_ingest_default_subject(self) -> None:
        """Subject defaults to 'user' when omitted."""
        payload = {
            "timestamp": "2026-08-21T15:30:00+00:00",
            "type": "app_open",
            "source": "mobile_app",
            "payload": {"screen": "dashboard"},
        }
        res = self.service.ingest_event(payload)
        self.assertEqual(res.status, IngestionStatus.ACCEPTED)
        self.assertIsNotNone(res.event_id)

        stored = self.event_store.get(res.event_id)
        self.assertEqual(stored.subject_id, "user")

    def test_ingest_duplicate_event(self) -> None:
        """Duplicate event returns status DUPLICATE safely without failing."""
        payload = {
            "timestamp": "2026-08-21T15:30:00Z",
            "type": "heartbeat",
            "source": "daemon",
            "payload": {"counter": 10},
        }
        res1 = self.service.ingest_event(payload)
        self.assertEqual(res1.status, IngestionStatus.ACCEPTED)

        res2 = self.service.ingest_event(payload)
        self.assertEqual(res2.status, IngestionStatus.DUPLICATE)
        self.assertEqual(res2.event_hash, res1.event_hash)

    def test_ingest_rejected_malformed(self) -> None:
        """Malformed events return REJECTED status with error description."""
        # Missing type
        res1 = self.service.ingest_event({
            "timestamp": "2026-08-21T15:30:00Z",
            "source": "test",
            "payload": {},
        })
        self.assertEqual(res1.status, IngestionStatus.REJECTED)
        self.assertIn("type", res1.error)

        # Missing source
        res2 = self.service.ingest_event({
            "timestamp": "2026-08-21T15:30:00Z",
            "type": "test_type",
            "payload": {},
        })
        self.assertEqual(res2.status, IngestionStatus.REJECTED)
        self.assertIn("source", res2.error)

        # Naive timestamp lacking timezone
        res3 = self.service.ingest_event({
            "timestamp": "2026-08-21 15:30:00",
            "type": "test_type",
            "source": "test_src",
            "payload": {},
        })
        self.assertEqual(res3.status, IngestionStatus.REJECTED)

        # Non-dict payload
        res4 = self.service.ingest_event({
            "timestamp": "2026-08-21T15:30:00Z",
            "type": "test_type",
            "source": "test_src",
            "payload": "invalid_string_payload",
        })
        self.assertEqual(res4.status, IngestionStatus.REJECTED)


class TestEventAPIHTTPServer(unittest.TestCase):
    """Integration tests running live local EventAPIServer on ephemeral port."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.temp_dir.name, "test_api_server.db")
        cls.db_manager = DatabaseManager(db_path=cls.db_path)
        cls.event_store = EventStore(db_manager=cls.db_manager)
        cls.service = EventIngestionService(event_store=cls.event_store)

        # Start server on port 0 (OS allocates free port)
        cls.server = EventAPIServer(host="127.0.0.1", port=0, service=cls.service)
        cls.base_url = f"http://127.0.0.1:{cls.server.port}"

        cls.server_thread = threading.Thread(target=cls.server.start, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)  # Brief wait for socket to bind

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.temp_dir.cleanup()

    def _http_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict = None,
    ) -> Tuple[int, dict]:
        """Helper to send HTTP request and return (status_code, json_body)."""
        url = f"{self.base_url}{endpoint}"
        body_bytes = None
        headers = {}
        if data is not None:
            body_bytes = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                status_code = resp.getcode()
                response_data = json.loads(resp.read().decode("utf-8"))
                return status_code, response_data
        except urllib.error.HTTPError as e:
            status_code = e.code
            response_data = json.loads(e.read().decode("utf-8"))
            return status_code, response_data

    def test_get_health(self) -> None:
        """GET /health returns 200 OK and service status."""
        status_code, body = self._http_request("/health")
        self.assertEqual(status_code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "personal_intelligence_event_api")
        self.assertIn("total_events", body)

    def test_post_event_accepted(self) -> None:
        """POST /events with valid payload returns 201 Created and accepted status."""
        event_payload = {
            "event_id": "test-http-evt-1",
            "timestamp": "2026-08-21T18:00:00Z",
            "type": "button_pressed",
            "source": "dashboard_ui",
            "subject": "user",
            "payload": {"button_id": "refresh_data"},
            "confidence": 1.0,
        }
        status_code, body = self._http_request("/events", method="POST", data=event_payload)
        self.assertEqual(status_code, 201)
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(body["event_id"], "test-http-evt-1")
        self.assertIn("event_hash", body)

    def test_post_event_duplicate(self) -> None:
        """POST /events with duplicate payload returns 200 OK with duplicate status."""
        event_payload = {
            "event_id": "test-http-evt-2",
            "timestamp": "2026-08-21T18:05:00Z",
            "type": "temp_reading",
            "source": "sensor_b",
            "subject": "device_b",
            "payload": {"celsius": 24.1},
            "confidence": 0.99,
        }
        # First insertion
        status1, body1 = self._http_request("/events", method="POST", data=event_payload)
        self.assertEqual(status1, 201)
        self.assertEqual(body1["status"], "accepted")

        # Second identical insertion
        status2, body2 = self._http_request("/events", method="POST", data=event_payload)
        self.assertEqual(status2, 200)
        self.assertEqual(body2["status"], "duplicate")
        self.assertEqual(body2["event_hash"], body1["event_hash"])

    def test_post_event_rejected_malformed(self) -> None:
        """POST /events with invalid schema returns 400 Bad Request."""
        bad_payload = {
            "timestamp": "invalid_date_format",
            "type": "",
            "source": "ui",
            "payload": {},
        }
        status_code, body = self._http_request("/events", method="POST", data=bad_payload)
        self.assertEqual(status_code, 400)
        self.assertEqual(body["status"], "rejected")
        self.assertIn("error", body)

    def test_get_events_recent(self) -> None:
        """GET /events/recent returns recent ingested events."""
        # Ensure at least one event exists
        sample_event = {
            "timestamp": "2026-08-21T19:00:00Z",
            "type": "sample_recent_test",
            "source": "unit_test",
            "payload": {"status": "ok"},
        }
        self._http_request("/events", method="POST", data=sample_event)

        status_code, body = self._http_request("/events/recent?limit=10")
        self.assertEqual(status_code, 200)
        self.assertEqual(body["status"], "success")
        self.assertIsInstance(body["events"], list)
        self.assertGreaterEqual(body["count"], 1)

    def test_not_found_endpoint(self) -> None:
        """Querying undefined route returns 404."""
        status_code, body = self._http_request("/undefined_route")
        self.assertEqual(status_code, 404)
        self.assertEqual(body["status"], "error")


if __name__ == "__main__":
    unittest.main()
