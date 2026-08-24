"""
Test suite validating Data Layer Hardening, Encryption at Rest, Key Management,
Deletion APIs, State Rebuilding, Retention Policies, Access Auditing,
Context Minimization, and Sensitive Payload Redaction.
"""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.context.builder import ContextBuilder
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.situations.models import Situation, SituationPriority
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.security.audit import ContextAccessAuditor
from personal_intelligence.security.redactor import SensitivePayloadRedactor
from personal_intelligence.storage.crypto import DatabaseEncryptor, KeyManager
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.retention import RetentionManager, RetentionPolicy


class TestDataLayerHardening(unittest.TestCase):
    """Test suite covering data layer security, encryption, deletions, and privacy governance."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "hardened.db")
        self.key_dir = os.path.join(self.temp_dir.name, "keys")
        self.key_manager = KeyManager(key_dir=self.key_dir)

        self.db_manager = DatabaseManager(
            db_path=self.db_path,
            key_manager=self.key_manager,
        )
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.state_engine = StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.auditor = ContextAccessAuditor(db_manager=self.db_manager)
        self.context_builder = ContextBuilder(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            auditor=self.auditor,
        )

        self.base_time = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # =========================================================================
    # 1. Encryption at Rest & External Key Management
    # =========================================================================

    def test_encryption_at_rest_and_external_key_storage(self) -> None:
        """
        Verify:
        1. Encryption key is stored in external key file outside the database.
        2. DatabaseEncryptor encrypts and decrypts with authenticated integrity.
        3. Encrypted database file at rest cannot be read as plaintext SQLite.
        """
        # Master key is generated outside database
        master_key = self.key_manager.get_or_create_master_key()
        self.assertEqual(len(master_key), 32)
        key_file = Path(self.key_dir) / KeyManager.DEFAULT_KEY_FILENAME
        self.assertTrue(key_file.exists())
        self.assertNotEqual(str(key_file), self.db_path)

        # Ingest an event into the database
        ev = Event(
            id="evt-secret-001",
            event_type="private_observation",
            source="secure_sensor",
            event_time=self.base_time,
            payload={"private_token": "top_secret_token_value", "heart_rate": 65},
        )
        self.event_store.append(ev)
        self.assertEqual(self.event_store.count(), 1)

        # Seal/encrypt database at rest
        sealed_path = self.db_manager.seal_encrypted_database()
        self.assertTrue(os.path.exists(sealed_path))
        encryptor = DatabaseEncryptor(key=master_key)
        self.assertTrue(encryptor.is_encrypted_file(sealed_path))

        # Direct raw file read shows no plaintext strings
        with open(sealed_path, "rb") as f:
            raw_bytes = f.read()
        self.assertNotIn(b"top_secret_token_value", raw_bytes)
        self.assertNotIn(b"evt-secret-001", raw_bytes)
        self.assertTrue(raw_bytes.startswith(DatabaseEncryptor.MAGIC_HEADER))

        # Tampering with ciphertext triggers MAC authentication failure
        tampered_bytes = bytearray(raw_bytes)
        tampered_bytes[30] ^= 0xFF  # Flip a bit in ciphertext
        with self.assertRaises(ValueError):
            encryptor.decrypt_bytes(bytes(tampered_bytes))

        # Unseal and verify data restoration
        unsealed_path = self.db_manager.unseal_database()
        self.assertTrue(os.path.exists(unsealed_path))
        restored_store = EventStore(db_manager=self.db_manager)
        restored_ev = restored_store.get_by_id("evt-secret-001")
        self.assertIsNotNone(restored_ev)
        self.assertEqual(restored_ev.payload["private_token"], "top_secret_token_value")

    # =========================================================================
    # 2. Deleting Individual Events & Source Deletions
    # =========================================================================

    def test_event_deletion_individual_and_by_source(self) -> None:
        """
        Verify:
        1. Individual event deletion removes target event and returns True.
        2. Source deletion removes all events for a given source and returns deleted count.
        3. Deleting non-existent events returns False / 0.
        """
        events = [
            Event(id="evt-oura-01", event_type="sleep_session", source="oura_ring", event_time=self.base_time - timedelta(days=2), payload={"duration": 480}),
            Event(id="evt-oura-02", event_type="sleep_session", source="oura_ring", event_time=self.base_time - timedelta(days=1), payload={"duration": 450}),
            Event(id="evt-gps-01", event_type="location_update", source="gps_telemetry", event_time=self.base_time - timedelta(hours=5), payload={"lat": 40.71, "lon": -74.0}),
            Event(id="evt-gps-02", event_type="location_update", source="gps_telemetry", event_time=self.base_time - timedelta(hours=2), payload={"lat": 40.72, "lon": -74.01}),
            Event(id="evt-gcal-01", event_type="calendar_event", source="google_calendar", event_time=self.base_time, payload={"title": "Team Sync"}),
        ]
        self.event_store.append_batch(type("Batch", (), {"events": events})())
        self.assertEqual(self.event_store.count(), 5)

        # 1. Delete single event
        del_res = self.event_store.delete_event("evt-gcal-01")
        self.assertTrue(del_res)
        self.assertIsNone(self.event_store.get_by_id("evt-gcal-01"))
        self.assertEqual(self.event_store.count(), 4)

        # Delete non-existent event
        self.assertFalse(self.event_store.delete_event("non-existent-id"))

        # 2. Delete all events from a source
        deleted_count = self.event_store.delete_by_source("gps_telemetry")
        self.assertEqual(deleted_count, 2)
        self.assertEqual(self.event_store.count(event_type="location_update"), 0)
        self.assertEqual(self.event_store.count(), 2)

        # Remaining events are only oura_ring
        remaining_events = self.event_store.recent(limit=10)
        self.assertEqual(len(remaining_events), 2)
        self.assertTrue(all(e.source == "oura_ring" for e in remaining_events))

    # =========================================================================
    # 3. Deterministic State Rebuild After Deletion
    # =========================================================================

    def test_state_rebuild_after_event_and_source_deletion(self) -> None:
        """
        Verify that after deleting events or sources, derived state is recalculated cleanly
        from remaining timeline events without stale residue.
        """
        # Ingest prolonged activity and context signals
        events = [
            Event(
                id="evt-work-01",
                event_type="activity_observed",
                source="productivity_obs",
                event_time=self.base_time - timedelta(minutes=150),
                payload={"activity": "software_development", "duration_minutes": 150},
            ),
            Event(
                id="evt-work-02",
                event_type="activity_observed",
                source="productivity_obs",
                event_time=self.base_time - timedelta(minutes=10),
                payload={"activity": "software_development", "duration_minutes": 150},
            ),
            Event(
                id="evt-ctx-01",
                event_type="signal_observed",
                source="context_telemetry",
                event_time=self.base_time - timedelta(minutes=20),
                payload={"context": "temporary_coffee_shop", "topic": "offsite_work"},
            ),
        ]
        self.event_store.append_batch(type("Batch", (), {"events": events})())

        # Compute initial state
        state_before = self.state_engine.compute_current_state(reference_time=self.base_time)
        self.assertIsNotNone(state_before.get_feature("recent_context_signal"))
        ctx_feat_before = state_before.get_feature("recent_context_signal").value
        self.assertEqual(ctx_feat_before, "temporary_coffee_shop")

        # User purges all context telemetry data
        self.event_store.delete_by_source("context_telemetry")

        # Deterministically rebuild state
        state_after = self.state_engine.rebuild_state(as_of=self.base_time)

        # Context signal feature is recalculated without the deleted event
        ctx_feat_after = state_after.get_feature("recent_context_signal").value
        self.assertNotEqual(ctx_feat_after, "temporary_coffee_shop")
        self.assertEqual(ctx_feat_after, "unknown")

    # =========================================================================
    # 4. Configurable Retention Policies
    # =========================================================================

    def test_configurable_retention_policy_pruning(self) -> None:
        """
        Verify retention manager prunes events older than configured horizons:
        - location_update: 14 days
        - ambient_environment: 7 days
        - sleep_session: 90 days
        """
        policy = RetentionPolicy(
            rules_by_event_type={
                "location_update": 14,
                "ambient_environment": 7,
                "sleep_session": 90,
            },
            default_days=30,
        )
        retention_mgr = RetentionManager(
            event_store=self.event_store,
            db_manager=self.db_manager,
            policy=policy,
        )

        # Ingest events across varying historical dates
        events = [
            # Expired location (> 14d)
            Event(id="evt-loc-old", event_type="location_update", source="gps", event_time=self.base_time - timedelta(days=20), payload={"lat": 1.0, "lon": 1.0}),
            # Fresh location (< 14d)
            Event(id="evt-loc-fresh", event_type="location_update", source="gps", event_time=self.base_time - timedelta(days=5), payload={"lat": 2.0, "lon": 2.0}),
            # Expired ambient (> 7d)
            Event(id="evt-amb-old", event_type="ambient_environment", source="mic", event_time=self.base_time - timedelta(days=10), payload={"ambient": "cafe"}),
            # Fresh sleep (< 90d)
            Event(id="evt-sleep-fresh", event_type="sleep_session", source="oura", event_time=self.base_time - timedelta(days=40), payload={"duration": 480}),
        ]
        self.event_store.append_batch(type("Batch", (), {"events": events})())
        self.assertEqual(self.event_store.count(), 4)

        # Dry run check
        dry_summary = retention_mgr.enforce_retention(as_of=self.base_time, dry_run=True)
        self.assertEqual(dry_summary.total_pruned, 2)
        self.assertEqual(self.event_store.count(), 4)  # Nothing actually deleted in dry run

        # Live retention pruning
        summary = retention_mgr.enforce_retention(as_of=self.base_time, dry_run=False)
        self.assertEqual(summary.total_pruned, 2)
        self.assertEqual(summary.pruned_by_type.get("location_update"), 1)
        self.assertEqual(summary.pruned_by_type.get("ambient_environment"), 1)

        # Verify only fresh events remain in EventStore
        self.assertEqual(self.event_store.count(), 2)
        self.assertIsNone(self.event_store.get_by_id("evt-loc-old"))
        self.assertIsNone(self.event_store.get_by_id("evt-amb-old"))
        self.assertIsNotNone(self.event_store.get_by_id("evt-loc-fresh"))
        self.assertIsNotNone(self.event_store.get_by_id("evt-sleep-fresh"))

    # =========================================================================
    # 5. Sensitive Payload Redaction & Logging Safety
    # =========================================================================

    def test_sensitive_payload_redaction_and_safe_logging(self) -> None:
        """
        Verify SensitivePayloadRedactor sanitizes sensitive keys and auth tokens.
        """
        redactor = SensitivePayloadRedactor()

        raw_payload = {
            "user_id": "usr-123",
            "device_model": "Pixel 9",
            "password": "super_secret_password_123",
            "api_key": "sk-live-secret-key-9999",
            "access_token": "bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "location": {
                "latitude": 37.7749,
                "longitude": -122.4194,
                "city": "San Francisco",
            },
            "raw_audio": b"binary_audio_data",
            "notes": "Private medical discussion about blood pressure.",
            "metrics": {
                "step_count": 8500,
                "blood_pressure": "120/80",
            },
        }

        sanitized = redactor.sanitize(raw_payload)

        # Public non-sensitive fields preserved
        self.assertEqual(sanitized["user_id"], "usr-123")
        self.assertEqual(sanitized["device_model"], "Pixel 9")
        self.assertEqual(sanitized["metrics"]["step_count"], 8500)
        self.assertEqual(sanitized["location"]["city"], "San Francisco")

        # Sensitive keys redacted
        self.assertEqual(sanitized["password"], "[REDACTED_SENSITIVE]")
        self.assertEqual(sanitized["api_key"], "[REDACTED_SENSITIVE]")
        self.assertEqual(sanitized["access_token"], "[REDACTED_SENSITIVE]")
        self.assertEqual(sanitized["location"]["latitude"], 0.0)
        self.assertEqual(sanitized["location"]["longitude"], 0.0)
        self.assertEqual(sanitized["raw_audio"], "[REDACTED_SENSITIVE]")
        self.assertEqual(sanitized["notes"], "[REDACTED_SENSITIVE]")
        self.assertEqual(sanitized["metrics"]["blood_pressure"], "[REDACTED_SENSITIVE]")

    # =========================================================================
    # 6. Sensitive Context Access Auditing
    # =========================================================================

    def test_sensitive_context_access_auditing(self) -> None:
        """
        Verify that building bounded context records structured audit records.
        """
        sit = self.situation_store.create(
            type="schedule_conflict",
            priority=SituationPriority.HIGH.value,
            novelty=0.75,
            context={"summary": "Overlapping critical meetings"},
            evidence=["event:evt-101"],
        )
        curr_state = self.state_engine.compute_current_state(reference_time=self.base_time)

        # Build bounded context
        bounded_ctx = self.context_builder.build_bounded_context(
            situation=sit,
            current_state=curr_state,
            objective="Evaluate meeting conflict resolution",
        )
        self.assertIsNotNone(bounded_ctx)

        # Check audit log in SQLite
        records = self.auditor.list_access_records(situation_id=sit.id)
        self.assertGreaterEqual(len(records), 1)
        audit_entry = records[0]
        self.assertEqual(audit_entry.situation_id, sit.id)
        self.assertEqual(audit_entry.accessor, "hermes_reasoning")
        self.assertEqual(audit_entry.purpose, "Evaluate meeting conflict resolution")
        self.assertIn("time_of_day", audit_entry.features_accessed)

    # =========================================================================
    # 7. Context Minimization: Hermes Never Receives Complete History
    # =========================================================================

    def test_strict_context_minimization_guarantee(self) -> None:
        """
        Verify that out of 200+ stored events, ContextBuilder strictly filters and bounds
        the context, never leaking full event history into the Hermes context.
        """
        # Ingest 150 generic noise events + 2 target situation events
        bulk_events = []
        for i in range(150):
            t = self.base_time - timedelta(days=20, minutes=i*10)
            bulk_events.append(
                Event(
                    id=f"evt-bulk-{i:03d}",
                    event_type="app_focus",
                    source="os_window",
                    event_time=t,
                    payload={"app": "Chrome", "tab": f"page_{i}"},
                )
            )

        # 2 Target events
        target_1 = Event(
            id="evt-target-01",
            event_type="calendar_event",
            source="gcal",
            event_time=self.base_time + timedelta(hours=1),
            payload={"title": "Urgent Architecture Review", "cognitive_workload": "high"},
        )
        target_2 = Event(
            id="evt-target-02",
            event_type="sleep_session",
            source="oura",
            event_time=self.base_time - timedelta(hours=6),
            payload={"duration_minutes": 220, "restfulness": "poor"},
        )
        bulk_events.extend([target_1, target_2])
        self.event_store.append_batch(type("Batch", (), {"events": bulk_events})())
        self.assertEqual(self.event_store.count(), 152)

        timeline = self.timeline_engine.get_time_range(
            start_time=self.base_time - timedelta(days=30),
            end_time=self.base_time + timedelta(hours=2),
        )
        self.assertEqual(len(timeline.events), 152)

        situation = self.situation_store.create(
            type="cognitive_physical_strain_risk",
            priority=SituationPriority.HIGH.value,
            novelty=0.85,
            context={"summary": "Short sleep precedes architecture review"},
            evidence=["event:evt-target-01", "event:evt-target-02"],
        )
        current_state = self.state_engine.compute_current_state(reference_time=self.base_time)

        # Build bounded context
        bounded_context = self.context_builder.build_bounded_context(
            situation=situation,
            current_state=current_state,
            timeline=timeline,
        )

        # CONTEXT MINIMIZATION ASSERTIONS:
        # 1. Hermes receives <= max_recent_events (15) + max_historical_events (10)
        recent_count = len(bounded_context.relevant_recent_timeline)
        historical_count = len(bounded_context.relevant_historical_events)
        total_hermes_events = recent_count + historical_count

        self.assertLessEqual(total_hermes_events, 25)
        self.assertLess(total_hermes_events, 152)  # Far less than 152 total stored events

        # 2. Context dictionary contains only bounded arrays, not the 152 raw events
        context_dict = bounded_context.to_dict()
        self.assertLessEqual(len(context_dict["relevant_recent_timeline"]), 15)
        self.assertLessEqual(len(context_dict["relevant_historical_events"]), 10)


if __name__ == "__main__":
    unittest.main()
