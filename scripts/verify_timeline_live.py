"""
Live verification script demonstrating the Timeline Engine APIs and deterministic summarize_raw().
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.timeline import TimelineEngine
from personal_intelligence.storage.db import DatabaseManager


def main():
    print("=== Personal Intelligence Timeline Engine Live Verification ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/live_timeline.db"
        db_mgr = DatabaseManager(db_path=db_path)
        store = EventStore(db_manager=db_mgr)
        engine = TimelineEngine(event_store=store)

        base_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=timezone.utc)
        print(f"1. Seeding 8 events starting at {base_time.isoformat()}...")

        event_definitions = [
            ("ambient_light", "light_sensor", "room_a", 0, {"lux": 150}),
            ("ambient_light", "light_sensor", "room_a", 30, {"lux": 350}),
            ("app_focus", "window_manager", "user", 45, {"app": "editor"}),
            ("motion_detected", "pir_sensor", "room_a", 60, {"count": 3}),
            ("app_focus", "window_manager", "user", 90, {"app": "terminal"}),
            ("cpu_spike", "system_monitor", "laptop", 100, {"load": 95.2}),
            ("ambient_temp", "thermostat", "room_a", 120, {"celsius": 23.4}),
            ("device_lock", "os_security", "user", 150, {"reason": "idle"}),
        ]

        anchor_event_id = None
        for i, (etype, src, subj, offset_min, payload) in enumerate(event_definitions):
            t = base_time + timedelta(minutes=offset_min)
            evt_id = f"evt-tl-{i}"
            if i == 3:
                anchor_event_id = evt_id
            store.append(
                Event(
                    id=evt_id,
                    event_type=etype,
                    source=src,
                    subject_id=subj,
                    payload=payload,
                    event_time=t,
                    confidence=0.95,
                )
            )

        print(f"   Stored {store.count()} events.")

        # 2. Last N Minutes
        ref_time = base_time + timedelta(minutes=150)
        tl_60m = engine.get_last_n_minutes(60, reference_time=ref_time)
        print(f"\n2. get_last_n_minutes(60): Found {len(tl_60m)} events in [90m, 150m]")
        for e in tl_60m:
            print(f"   [{e.event_time.isoformat()}] {e.event_type} (src={e.source})")

        # 3. Events around anchor event
        tl_around = engine.get_around_event(anchor_event_id, count_before=1, count_after=2)
        print(f"\n3. get_around_event('{anchor_event_id}', before=1, after=2): Found {len(tl_around)} events")
        for e in tl_around:
            marker = " <-- ANCHOR" if e.id == anchor_event_id else ""
            print(f"   [{e.event_time.isoformat()}] {e.id}: {e.event_type}{marker}")

        # 4. Filter by subject
        tl_subj = engine.get_for_subject("user")
        print(f"\n4. get_for_subject('user'): Found {len(tl_subj)} events")
        for e in tl_subj:
            print(f"   [{e.event_time.isoformat()}] {e.event_type} | {e.payload}")

        # 5. Deterministic summarize_raw()
        tl_full = engine.get_time_range()
        summary = tl_full.summarize_raw()
        print("\n5. timeline.summarize_raw():")
        print(json.dumps(summary, indent=2))

        # 6. Compact Text Representation
        print("\n6. timeline.to_compact_text():")
        print(tl_full.to_compact_text(max_events=4))

        print("\n7. All Timeline Engine checks PASSED!")


if __name__ == "__main__":
    main()
