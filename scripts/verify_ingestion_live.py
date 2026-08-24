"""
Live verification script demonstrating the complete Event Ingestion API lifecycle.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error

# Ensure workspace root is in sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from personal_intelligence.api.server import EventAPIServer
from personal_intelligence.api.ingestion import EventIngestionService
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.storage.db import DatabaseManager


def main():
    print("=== Personal Intelligence Event Ingestion Live Verification ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/live_verify.db"
        db_mgr = DatabaseManager(db_path=db_path)
        store = EventStore(db_manager=db_mgr)
        service = EventIngestionService(event_store=store)

        server = EventAPIServer(host="127.0.0.1", port=0, service=service)
        port = server.port
        base_url = f"http://127.0.0.1:{port}"
        print(f"1. Started local Event API server on {base_url}")

        server_thread = threading.Thread(target=server.start, daemon=True)
        server_thread.start()
        time.sleep(0.1)

        def make_req(endpoint, method="GET", data=None):
            url = f"{base_url}{endpoint}"
            body_bytes = json.dumps(data).encode("utf-8") if data else None
            headers = {"Content-Type": "application/json"} if data else {}
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req) as resp:
                    return resp.getcode(), json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode("utf-8"))

        # Step 1: Health Check
        code, health = make_req("/health")
        print(f"2. GET /health -> HTTP {code}: {json.dumps(health)}")
        assert code == 200 and health["status"] == "ok"

        # Step 2: Post Event 1 (Valid)
        event_1 = {
            "event_id": "evt-live-100",
            "timestamp": "2026-08-21T20:45:00Z",
            "type": "ambient_noise_level",
            "source": "microphone_sensor",
            "subject": "office_room_1",
            "payload": {"decibels": 45.2, "frequency_band": "mid"},
            "confidence": 0.97,
        }
        code, resp1 = make_req("/events", method="POST", data=event_1)
        print(f"3. POST /events (Valid Event) -> HTTP {code}: {json.dumps(resp1)}")
        assert code == 201 and resp1["status"] == "accepted"

        # Step 3: Post Duplicate Event
        code, resp2 = make_req("/events", method="POST", data=event_1)
        print(f"4. POST /events (Duplicate Event) -> HTTP {code}: {json.dumps(resp2)}")
        assert code == 200 and resp2["status"] == "duplicate"

        # Step 4: Post Malformed Event (Missing required field 'type')
        bad_event = {
            "timestamp": "2026-08-21T20:45:00Z",
            "source": "sensor",
            "payload": {"val": 1},
        }
        code, resp3 = make_req("/events", method="POST", data=bad_event)
        print(f"5. POST /events (Malformed Event) -> HTTP {code}: {json.dumps(resp3)}")
        assert code == 400 and resp3["status"] == "rejected"

        # Step 5: Query Recent Events
        code, recent = make_req("/events/recent?limit=5")
        print(f"6. GET /events/recent -> HTTP {code}: Found {recent['count']} event(s)")
        assert code == 200 and recent["count"] == 1
        print(f"   Stored Event ID: {recent['events'][0]['id']}")
        print(f"   Stored Event Type: {recent['events'][0]['event_type']}")
        print(f"   Stored Event Hash: {recent['events'][0]['event_hash']}")

        server.shutdown()
        print("7. Server shut down cleanly. All live checks PASSED!")


if __name__ == "__main__":
    main()
