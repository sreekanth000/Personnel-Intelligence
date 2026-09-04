"""
Unit & Integration Tests for Source-Backed Generic Observation Contract.

Verifies:
1. Observation with arbitrary source is accepted.
2. Provenance survives persistence.
3. Source reference survives persistence.
4. Timestamps remain distinct (occurred_at vs observed_at).
5. Confidence is preserved.
6. Duplicate observations are idempotent.
7. Malformed observations are rejected safely.
8. Unknown source types do not break ingestion.
9. PI does not call external APIs.
10. Interpretation does not overwrite observation.
11. Source evidence can be traced from a recommendation back to its originating observation.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_intelligence.core.events.exceptions import (
    DuplicateEventError,
    EventValidationError,
)
from personal_intelligence.core.events.models import (
    Event,
    Observation,
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.events.observation import record_observation
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.world.model import EpistemicRecord, PersonalWorldModel
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore


class TestSourceBackedObservationContract(unittest.TestCase):
    """Test suite proving the source-backed generic observation contract."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_obs_contract.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.local_store = LocalStateStore(db_manager=self.db_manager)
        self.event_store = self.local_store.event_store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_1_observation_with_arbitrary_source_is_accepted(self) -> None:
        """Proves PI accepts arbitrary external sources (WhatsApp, Whoop, Slack, Jira, etc.) without whitelisting."""
        now = datetime.now(timezone.utc)
        sources_to_test = ["whatsapp", "whoop", "slack", "jira", "hevy", "linear", "bank_account", "healthkit"]

        for src in sources_to_test:
            obs = record_observation(
                source=src,
                source_id=f"{src}-ref-12345",
                timestamp=now - timedelta(minutes=10),
                observation_type="generic_activity",
                summary=f"Activity observed from {src}",
                evidence={"metric": 42, "status": "active"},
                provenance={"tool": f"{src}_connector", "ref": f"{src}://item/12345"},
                event_store=self.event_store,
            )
            self.assertIsNotNone(obs)
            self.assertEqual(obs.source, src)
            self.assertEqual(obs.source_reference, f"{src}-ref-12345")

    def test_2_provenance_survives_persistence(self) -> None:
        """Proves full provenance coordinates survive database storage and retrieval."""
        now = datetime.now(timezone.utc)
        prov_dict = {
            "tool": "whatsapp_messages",
            "chat_id": "group-987",
            "message_id": "msg-554433",
            "query": "urgent meeting",
            "extractor": "hermes_v1",
        }

        obs = record_observation(
            source="whatsapp",
            source_id="msg-554433",
            timestamp=now,
            observation_type="possible_commitment",
            summary="Client requested updated project timeline",
            evidence={"sender": "Alex", "deadline_mentioned": "Friday 5 PM"},
            provenance=prov_dict,
            event_store=self.event_store,
        )

        # Retrieve raw from SQLite
        persisted = self.event_store.get(obs.id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.provenance["tool"], "whatsapp_messages")
        self.assertEqual(persisted.provenance["chat_id"], "group-987")
        self.assertEqual(persisted.provenance["message_id"], "msg-554433")
        self.assertEqual(persisted.provenance["extractor"], "hermes_v1")

    def test_3_source_reference_survives_persistence(self) -> None:
        """Proves external system source references are preserved accurately."""
        now = datetime.now(timezone.utc)
        obs = record_observation(
            source="jira",
            source_id="PROJ-8942",
            timestamp=now,
            observation_type="task_updated",
            summary="Bug ticket PROJ-8942 transitioned to In Review",
            evidence={"assignee": "sarah@company.com", "priority": "high"},
            provenance={"tool": "jira_get_issue", "issue_key": "PROJ-8942"},
            event_store=self.event_store,
        )

        persisted = self.event_store.get(obs.id)
        self.assertEqual(persisted.source_reference, "PROJ-8942")
        self.assertEqual(persisted.source_id, "PROJ-8942")

        # Also verify lookup by source_id works
        found = self.event_store.get_by_source_id("jira", "PROJ-8942")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, obs.id)

    def test_4_timestamps_remain_distinct(self) -> None:
        """Proves occurred_at (event_time) and observed_at (ingested_at) remain strictly distinct."""
        occurred = datetime(2026, 8, 15, 9, 30, tzinfo=timezone.utc)
        observed = datetime(2026, 8, 15, 14, 45, tzinfo=timezone.utc)

        obs = Event(
            id="evt-time-distinct",
            source="slack",
            source_id="slack-msg-1",
            observation_type="message_received",
            occurred_at=occurred,
            observed_at=observed,
            payload={"summary": "Async discussion"},
            provenance={"tool": "slack_history"},
        )
        self.event_store.append(obs)

        persisted = self.event_store.get("evt-time-distinct")
        self.assertEqual(persisted.occurred_at, occurred)
        self.assertEqual(persisted.observed_at, observed)
        self.assertNotEqual(persisted.occurred_at, persisted.observed_at)
        self.assertEqual((persisted.observed_at - persisted.occurred_at).total_seconds(), 5.25 * 3600)

    def test_5_confidence_is_preserved(self) -> None:
        """Proves floating point confidence scores in [0.0, 1.0] are stored and preserved."""
        obs = record_observation(
            source="whoop",
            source_id="rec-20260815",
            timestamp=datetime.now(timezone.utc),
            observation_type="activity_logged",
            summary="Recovery score 78%",
            evidence={"recovery_score": 78, "hrv": 65},
            provenance={"tool": "whoop_recovery"},
            confidence=0.88,
            event_store=self.event_store,
        )

        persisted = self.event_store.get(obs.id)
        self.assertAlmostEqual(persisted.confidence, 0.88, places=2)
        self.assertEqual(persisted.confidence_category, "moderate")

    def test_6_duplicate_observations_are_idempotent(self) -> None:
        """Proves identical observations produce deterministic hashes and enforce idempotency."""
        ts = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
        obs1 = record_observation(
            source="slack",
            source_id="msg-100",
            timestamp=ts,
            observation_type="email_received",
            summary="Quarterly planning note",
            evidence={"title": "Quarterly planning note"},
            provenance={"tool": "slack_sync"},
            event_store=self.event_store,
        )

        # Re-recording identical observation returns existing or same hash without crashing
        obs2 = record_observation(
            source="slack",
            source_id="msg-100",
            timestamp=ts,
            observation_type="email_received",
            summary="Quarterly planning note",
            evidence={"title": "Quarterly planning note"},
            provenance={"tool": "slack_sync"},
            event_store=self.event_store,
        )

        self.assertEqual(obs1.event_hash, obs2.event_hash)
        self.assertEqual(self.event_store.count(), 1)

    def test_7_malformed_observations_are_rejected_safely(self) -> None:
        """Proves invalid observation fields raise EventValidationError safely."""
        now = datetime.now(timezone.utc)

        # Missing source
        with self.assertRaises(EventValidationError):
            record_observation(
                source="",
                source_id="123",
                timestamp=now,
                observation_type="test",
                summary="test",
                provenance={"tool": "test"},
                event_store=self.event_store,
            )

        # Invalid source characters
        with self.assertRaises(EventValidationError):
            record_observation(
                source="invalid source with spaces!!!",
                source_id="123",
                timestamp=now,
                observation_type="test",
                summary="test",
                provenance={"tool": "test"},
                event_store=self.event_store,
            )

        # Missing provenance
        with self.assertRaises(EventValidationError):
            record_observation(
                source="slack",
                source_id="123",
                timestamp=now,
                observation_type="test",
                summary="test",
                provenance={},
                event_store=self.event_store,
            )

        # Out-of-bounds confidence (>1.0)
        with self.assertRaises(EventValidationError):
            record_observation(
                source="slack",
                source_id="123",
                timestamp=now,
                observation_type="test",
                summary="test",
                confidence=1.5,
                provenance={"tool": "test"},
                event_store=self.event_store,
            )

    def test_8_unknown_source_types_do_not_break_ingestion(self) -> None:
        """Proves completely novel/unseen external source names ingest without schema failure."""
        novel_source = "smart_thermostat_iot"
        obs = record_observation(
            source=novel_source,
            source_id="device-sensor-88",
            timestamp=datetime.now(timezone.utc),
            observation_type="telemetry_alert",
            summary="Living room ambient temperature drop",
            evidence={"temp_c": 16.5, "humidity": 45},
            provenance={"tool": "iot_sensor_reader", "mac": "00:1B:44:11:3A:B7"},
            source_type="iot_sensor",
            event_store=self.event_store,
        )
        self.assertEqual(obs.source, novel_source)
        self.assertEqual(obs.source_type, "iot_sensor")

    def test_9_pi_does_not_call_external_apis(self) -> None:
        """Proves PI functions purely locally in SQLite with zero network calls."""
        with patch("urllib.request.urlopen") as mock_url, patch("http.client.HTTPConnection") as mock_http:
            obs = record_observation(
                source="healthkit",
                source_id="hk-sample-999",
                timestamp=datetime.now(timezone.utc),
                observation_type="heart_rate_spike",
                summary="Elevated resting heart rate during sleep",
                evidence={"resting_hr": 84, "baseline": 62},
                provenance={"tool": "apple_health_export", "file": "/data/export.xml"},
                event_store=self.event_store,
            )
            self.assertEqual(mock_url.call_count, 0)
            self.assertEqual(mock_http.call_count, 0)

    def test_10_interpretation_does_not_overwrite_observation(self) -> None:
        """Proves PI interpretations (epistemic facts / situations) do not overwrite the raw observation."""
        now = datetime.now(timezone.utc)
        wm = PersonalWorldModel(db_manager=self.db_manager)

        # 1. Store Source Observation
        obs = record_observation(
            source="calendar",
            source_id="cal-ev-400",
            timestamp=now,
            observation_type="calendar_event",
            summary="Client Workshop at 4 PM",
            evidence={"title": "Client Workshop", "start_time": "16:00"},
            provenance={"tool": "calendar_list"},
            event_store=self.event_store,
        )

        original_summary = obs.summary
        original_hash = obs.event_hash

        # 2. PI derives an inference (e.g. conflict with commute)
        fact = wm.record_epistemic_fact(
            subject="Client Workshop",
            predicate="conflicts_with",
            object="Airport Commute",
            epistemic_type="inferred",
            source="personal_intelligence_reasoning",
            origin_event_id=obs.id,
            supporting_observation_ids=[obs.id],
            provenance={"rule": "temporal_commute_overlap"},
        )

        # 3. Verify Observation in event_log is untouched
        fetched_obs = self.event_store.get(obs.id)
        self.assertEqual(fetched_obs.summary, original_summary)
        self.assertEqual(fetched_obs.event_hash, original_hash)
        self.assertEqual(fetched_obs.observation_type, "calendar_event")

        # 4. Verify Inference is stored separately in epistemic_records with lineage
        self.assertEqual(fact.epistemic_type, "inferred")
        self.assertEqual(fact.origin_event_id, obs.id)
        self.assertIn(obs.id, fact.supporting_observation_ids)

    def test_11_source_evidence_can_be_traced_from_recommendation_back_to_observation(self) -> None:
        """Proves full traceability from a situation / recommendation back to originating observation."""
        now = datetime.now(timezone.utc)
        sit_store = SituationStore(db_manager=self.db_manager)

        # 1. Originating observation
        obs = record_observation(
            source="whatsapp",
            source_id="wa-msg-888",
            timestamp=now,
            observation_type="possible_commitment",
            summary="Contract sign-off needed by 5 PM",
            evidence={"contract_id": "CT-2026-99", "deadline": "17:00"},
            provenance={"tool": "whatsapp_connector", "chat": "Legal Counsel"},
            event_store=self.event_store,
        )

        # 2. Situation created referencing observation
        sit = Situation(
            id="sit-contract-deadline",
            type="contract_deadline_pressure",
            status=SituationStatus.OPEN.value,
            priority=SituationPriority.HIGH.value,
            context={"summary": "Pending contract signature required today"},
            evidence=[obs.id],
            created_at=now,
            updated_at=now,
        )
        sit_store.create(sit)

        # 3. Trace back from situation evidence
        loaded_sit = sit_store.get("sit-contract-deadline")
        self.assertIn(obs.id, loaded_sit.evidence)

        # Fetch underlying source evidence
        underlying_obs = self.event_store.get(loaded_sit.evidence[0])
        self.assertEqual(underlying_obs.source, "whatsapp")
        self.assertEqual(underlying_obs.source_reference, "wa-msg-888")
        self.assertEqual(underlying_obs.provenance["tool"], "whatsapp_connector")


if __name__ == "__main__":
    unittest.main()
