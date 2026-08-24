"""
Tests for Personal Intelligence Observation Model Refactoring.

Verifies:
1. Observation domain model with all required attributes:
   - id, timestamp, observation_type, source, source_id, summary, structured_data, provenance, confidence_category, created_at
2. Standard observation types:
   - possible_commitment, upcoming_milestone, meeting_decision, document_changed, unresolved_action, goal_signal, routine_change, novel_state
3. Strict non-mirroring semantic: stores only normalized observations relevant for longitudinal reasoning.
4. Preservation of retrieval provenance so Hermes can re-query sources on demand.
5. Complete backward compatibility with Event / EventStore code.
6. Schema initialization and database persistence.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.models import (
    Event,
    EventBatch,
    Observation,
    ObservationBatch,
    StandardObservationType,
    compute_observation_hash,
)
from personal_intelligence.core.events.observation import (
    ObservationResult,
    record_observation,
)
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.storage.db import DatabaseManager


class TestObservationModel(unittest.TestCase):
    """Test suite for the Observation domain entity."""

    def test_observation_instantiation_and_fields(self) -> None:
        """Verifies Observation contains all 10 canonical attributes."""
        now = datetime.now(timezone.utc)
        obs = Observation(
            id="obs-12345",
            timestamp=now,
            observation_type=StandardObservationType.POSSIBLE_COMMITMENT,
            source="gmail",
            source_id="msg-thread-98712",
            summary="User promised to deliver updated architecture document by Friday.",
            structured_data={
                "commitment": "updated architecture document",
                "deadline": "2026-08-28T17:00:00Z",
                "recipient": "sreekanth@team.org",
            },
            provenance={
                "tool": "gmail_search",
                "query": "from:me subject:architecture",
                "message_id": "msg-thread-98712",
            },
            confidence_category="high",
            created_at=now,
        )

        self.assertEqual(obs.id, "obs-12345")
        self.assertEqual(obs.timestamp, now)
        self.assertEqual(obs.observation_type, "possible_commitment")
        self.assertEqual(obs.source, "gmail")
        self.assertEqual(obs.source_id, "msg-thread-98712")
        self.assertEqual(obs.summary, "User promised to deliver updated architecture document by Friday.")
        self.assertEqual(obs.structured_data["commitment"], "updated architecture document")
        self.assertEqual(obs.provenance["tool"], "gmail_search")
        self.assertEqual(obs.confidence_category, "high")
        self.assertEqual(obs.created_at, now)

        # Verify property aliases for complete interoperability
        self.assertEqual(obs.event_time, obs.timestamp)
        self.assertEqual(obs.event_type, obs.observation_type)
        self.assertEqual(obs.payload, obs.structured_data)
        self.assertEqual(obs.ingested_at, obs.created_at)

    def test_standard_observation_types_coverage(self) -> None:
        """Verifies all required observation types are supported."""
        required_types = [
            StandardObservationType.POSSIBLE_COMMITMENT,
            StandardObservationType.UPCOMING_MILESTONE,
            StandardObservationType.MEETING_DECISION,
            StandardObservationType.DOCUMENT_CHANGED,
            StandardObservationType.UNRESOLVED_ACTION,
            StandardObservationType.GOAL_SIGNAL,
            StandardObservationType.ROUTINE_CHANGE,
            StandardObservationType.NOVEL_STATE,
        ]

        now = datetime.now(timezone.utc)
        for obs_type in required_types:
            obs = Observation(
                observation_type=obs_type,
                source="hermes",
                summary=f"Testing {obs_type}",
                structured_data={"type": obs_type},
                timestamp=now,
            )
            self.assertEqual(obs.observation_type, obs_type)
            self.assertIsNotNone(obs.event_hash)

    def test_observation_serialization_and_deserialization(self) -> None:
        """Verifies to_dict and from_dict roundtrip."""
        now = datetime.now(timezone.utc)
        obs = Observation(
            observation_type=StandardObservationType.MEETING_DECISION,
            source="meet",
            source_id="call-rec-4412",
            summary="Team agreed to migrate auth system to OAuth 2.1 in Q4.",
            structured_data={"decision": "OAuth 2.1 migration", "target_quarter": "Q4"},
            provenance={"tool": "meet_transcript_search", "meeting_id": "call-rec-4412"},
            confidence_category="confirmed",
            timestamp=now,
        )

        d = obs.to_dict()
        self.assertEqual(d["observation_type"], "meeting_decision")
        self.assertEqual(d["source_id"], "call-rec-4412")
        self.assertEqual(d["confidence_category"], "confirmed")

        reconstructed = Observation.from_dict(d)
        self.assertEqual(reconstructed.id, obs.id)
        self.assertEqual(reconstructed.observation_type, obs.observation_type)
        self.assertEqual(reconstructed.summary, obs.summary)
        self.assertEqual(reconstructed.source_id, obs.source_id)


class TestObservationStorePersistence(unittest.TestCase):
    """Verifies SQLite persistence and provenance retrieval without external data mirroring."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_obs_store.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.store = EventStore(db_manager=self.db_manager)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_record_observation_helper(self) -> None:
        """Verifies record_observation saves normalized item with provenance coordinates."""
        now = datetime.now(timezone.utc)
        obs = record_observation(
            source="drive",
            source_id="doc-arch-0091",
            timestamp=now,
            observation_type=StandardObservationType.DOCUMENT_CHANGED,
            summary="Architecture document v2.4 modified by team lead.",
            evidence={"file_name": "v2.4_final.pdf", "modification_time": "2026-08-22T14:30:00Z"},
            provenance={
                "tool": "drive_activity_search",
                "file_id": "doc-arch-0091",
                "path": "/Projects/Architecture/v2.4_final.pdf",
            },
            confidence=0.95,
            db_manager=self.db_manager,
        )

        self.assertIsNotNone(obs.id)
        self.assertEqual(obs.observation_type, "document_changed")
        self.assertEqual(obs.source, "drive")
        self.assertEqual(obs.source_id, "doc-arch-0091")
        self.assertEqual(obs.confidence_category, "high")
        self.assertIn("Architecture document v2.4", obs.summary)

        # Verify retrieval from store preserves provenance

        retrieved = self.store.get_by_id(obs.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.source_id, "doc-arch-0091")
        self.assertIsNotNone(retrieved.provenance)
        self.assertEqual(retrieved.provenance["file_id"], "doc-arch-0091")
        self.assertEqual(retrieved.provenance["tool"], "drive_activity_search")

    def test_observation_store_does_not_mirror_entire_external_stores(self) -> None:
        """Verifies store rejects multi-megabyte raw HTML / API dumps (data minimization)."""
        huge_evidence = {"raw_html_dump": "X" * 40000}  # > 32KB
        with self.assertRaises(Exception):
            record_observation(
                source="gmail",
                source_id="msg-bulk-001",
                timestamp=datetime.now(timezone.utc),
                observation_type="raw_email_mirror",
                summary="Email with huge body.",
                evidence=huge_evidence,
                provenance={"tool": "gmail_fetch"},
                db_manager=self.db_manager,
            )


if __name__ == "__main__":
    unittest.main()
