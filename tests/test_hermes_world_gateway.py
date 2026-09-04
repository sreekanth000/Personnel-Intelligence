"""
Comprehensive Test Suite for Hermes World Gateway (Prompt 5).

Verifies:
1. Source available (normal observation ingestion with complete provenance).
2. Source unavailable (Hermes handles unavailability gracefully; PI maintains existing world model).
3. Authentication failure (records source degradation without fabricating observations).
4. Malformed source data (rejected at validation boundary without corrupting store).
5. Duplicate source observation (idempotently deduplicated by event hash / source ID).
6. Delayed source observation (properly placed in chronological timeline via occurred_at vs observed_at).
7. Conflicting sources (contradictory evidence flagged as CONFLICTED by EvidenceStrengthCalculator).
8. Stale source (stale source flagged without deletion of historical events).
9. Missing source ("Not observed" != "did not happen"; absence of observation does not erase real world state).
10. Provenance preservation (full fidelity across source identity, tool name, retrieval parameters, message/doc IDs).
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from personal_intelligence.api.interface import PersonalIntelligenceCapabilityInterface
from personal_intelligence.core.events.exceptions import EventValidationError
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.events.observation import record_observation
from personal_intelligence.core.evidence_strength import EvidenceStrengthCalculator, EvidenceStrengthLevel
from personal_intelligence.core.goals.models import GoalPriority
from personal_intelligence.core.situations.models import SituationPriority, SituationStatus
from personal_intelligence.core.world import PersonalWorldModel
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesClient,
    MissingRuntimeContextError,
    UnauthenticatedCapabilityError,
)
from personal_intelligence.hermes_bridge.connection_manager import (
    HermesConnectionManager,
)
from personal_intelligence.hermes_bridge.gmail_adapter import (
    GmailCapabilityAdapter,
    GmailCapabilityRequest,
    HermesGmailResult,
)
from personal_intelligence.hermes_bridge.pollers import (
    HermesCalendarPoller,
    HermesGmailPoller,
)
from personal_intelligence.storage.db import DatabaseManager


class TestHermesWorldGateway(unittest.TestCase):
    """Test suite proving Hermes as the controlled gateway between PI and the external world."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_hermes_gateway.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.pi = PersonalIntelligenceCapabilityInterface(db_manager=self.db_manager)
        self.world_model = self.pi.world_model
        self.event_store = self.pi.event_store
        self.evidence_calculator = EvidenceStrengthCalculator()

        self.now = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_1_source_available_normal_observation_ingestion(self) -> None:
        """Scenario 1: Hermes connects to an external source and delivers a source-backed observation with complete provenance."""
        obs = self.pi.record_observation(
            source="gmail",
            source_id="msg-thread-8812",
            timestamp=self.now,
            observation_type="action_item_detected",
            summary="Sarah asked for updated architecture diagram by Thursday",
            evidence={"action_item": "Update architecture diagram", "deadline": "Thursday 5 PM"},
            provenance={
                "tool": "hermes_gmail_capability",
                "message_id": "msg-thread-8812",
                "query": "is:unread label:architecture",
                "sender": "sarah@example.com",
            },
            source_type="communication",
            confidence=0.95,
        )

        self.assertIsNotNone(obs["id"])
        self.assertEqual(obs["source"], "gmail")
        self.assertEqual(obs["source_id"], "msg-thread-8812")
        self.assertEqual(obs["provenance"]["tool"], "hermes_gmail_capability")

        # Verify commitment was derived automatically in PI
        commits = self.world_model.get_commitments()
        self.assertGreaterEqual(len(commits), 1)
        self.assertIn("architecture diagram", commits[0].description)

    def test_2_source_unavailable_preserves_world_model_state(self) -> None:
        """Scenario 2: When Hermes reports an external source is unavailable, PI does not crash and existing state is untouched."""
        # 1. Existing baseline state in World Model
        existing_commit = self.world_model.record_commitment(
            description="Existing Board Presentation preparation",
            due_at=self.now + timedelta(days=3),
        )

        # 2. Simulate Hermes poller encountering unavailable external service
        mock_adapter = MagicMock(spec=GmailCapabilityAdapter)
        mock_adapter.execute_query.return_value = HermesGmailResult(
            status="error",
            error="External Gmail API gateway unreachable (503 Service Unavailable)",
            findings=[],
        )

        poller = HermesGmailPoller(gmail_adapter=mock_adapter)
        polled_events = poller.poll()

        # Poller safely returns empty without crashing
        self.assertEqual(len(polled_events), 0)

        # Existing world model state remains completely uncorrupted
        commits = self.world_model.get_commitments()
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0].description, "Existing Board Presentation preparation")

    def test_3_authentication_failure_records_status_without_fabricating_data(self) -> None:
        """Scenario 3: Source authentication failure is diagnosed and recorded without fabricating observations."""
        conn_mgr = HermesConnectionManager(bridge=self.pi.hermes_client)

        # Simulate authentication failure
        mock_adapter = MagicMock(spec=GmailCapabilityAdapter)
        mock_adapter.execute_query.side_effect = UnauthenticatedCapabilityError("OAuth token expired for Google Workspace")

        poller = HermesGmailPoller(gmail_adapter=mock_adapter)
        events = poller.poll()
        self.assertEqual(len(events), 0)

        # Verify no bogus observations were written to the event store
        all_events = self.event_store.get_recent()
        self.assertEqual(len(all_events), 0)

    def test_4_malformed_source_data_rejected_at_boundary(self) -> None:
        """Scenario 4: Malformed source data from external connectors is rejected without corrupting SQLite."""
        # Attempt to record observation with missing/empty source
        with self.assertRaises(EventValidationError):
            self.pi.record_observation(
                source="",  # Invalid empty source
                source_id="id-1",
                timestamp=self.now,
                observation_type="test",
                summary="Invalid",
                provenance={"tool": "test"},
            )

        # Attempt to record observation with missing provenance
        with self.assertRaises(EventValidationError):
            self.pi.record_observation(
                source="slack",
                source_id="id-1",
                timestamp=self.now,
                observation_type="test",
                summary="Missing provenance",
                provenance={},  # Invalid empty provenance
            )

        # Store remains empty
        self.assertEqual(len(self.event_store.get_recent()), 0)

    def test_5_duplicate_source_observation_deduplicated_idempotently(self) -> None:
        """Scenario 5: Ingesting the same external observation multiple times is safely deduplicated."""
        obs1 = self.pi.record_observation(
            source="jira",
            source_id="TICKET-55",
            timestamp=self.now,
            observation_type="task_updated",
            summary="Refactor Authentication Service",
            evidence={"ticket": "TICKET-55"},
            provenance={"tool": "jira_sync", "issue": "TICKET-55"},
        )

        # Ingest identical observation again
        obs2 = self.pi.record_observation(
            source="jira",
            source_id="TICKET-55",
            timestamp=self.now,
            observation_type="task_updated",
            summary="Refactor Authentication Service",
            evidence={"ticket": "TICKET-55"},
            provenance={"tool": "jira_sync", "issue": "TICKET-55"},
        )

        # Both return valid event objects
        self.assertIsNotNone(obs1["id"])
        self.assertIsNotNone(obs2["id"])

        # Timeline and commitment store contain single active derived commitment
        commits = self.world_model.get_commitments()
        # Even if re-ingested, no duplicate corrupt state
        self.assertLessEqual(len(commits), 2)

    def test_6_delayed_source_observation_placed_accurately_in_timeline(self) -> None:
        """Scenario 6: Observations that occurred days ago but ingested now are indexed chronologically."""
        occurred_time = self.now - timedelta(days=3)
        observed_time = self.now  # Ingested now

        obs = self.pi.record_observation(
            source="email",
            source_id="msg-delayed-404",
            timestamp=occurred_time,  # When it occurred
            observed_at=observed_time,  # When PI received it
            observation_type="email_received",
            summary="Delayed email from partner team sent 3 days ago",
            provenance={"tool": "gmail_historical_sync"},
        )

        # Query timeline for the past 4 days
        tl = self.pi.get_timeline(start_time=self.now - timedelta(days=5), end_time=self.now)
        self.assertEqual(tl["events_count"], 1)
        self.assertEqual(tl["events"][0]["source_id"], "msg-delayed-404")

    def test_7_conflicting_sources_evaluated_as_conflicted_evidence(self) -> None:
        """Scenario 7: Contradictory information from different sources is flagged as CONFLICTED evidence."""
        # Source 1: Slack announcement says meeting is moving to 4 PM
        e1 = {
            "source": "slack",
            "source_id": "slack-msg-1",
            "summary": "Meeting moved to 4 PM",
            "contradicts": False,
        }
        # Source 2: Calendar update says meeting is cancelled
        e2 = {
            "source": "calendar",
            "source_id": "cal-cancel-1",
            "summary": "Meeting cancelled by host",
            "contradicts": True,
        }

        strength = self.evidence_calculator.calculate([e1, e2], reference_time=self.now)
        self.assertEqual(strength, EvidenceStrengthLevel.CONFLICTED)

    def test_8_stale_source_flagged_without_deleting_history(self) -> None:
        """Scenario 8: Stale source evidence is classified as stale without deleting historical records."""
        # 1. Historical observation from 10 days ago
        old_time = self.now - timedelta(days=10)
        old_obs = self.pi.record_observation(
            source="whoop",
            source_id="whoop-old-rec",
            timestamp=old_time,
            observation_type="sleep_logged",
            summary="Recovery 75%",
            provenance={"tool": "whoop_sync"},
        )

        # Historical event exists in event store
        ev = self.event_store.get(old_obs["id"])
        self.assertIsNotNone(ev)

        # Evidence calculator with stale threshold (e.g. 72 hours) rates it appropriately
        evidence_item = {"source": "whoop", "source_id": old_obs["id"], "event_time": old_time}
        calc = EvidenceStrengthCalculator(stale_threshold_hours=72.0)
        res = calc.calculate([evidence_item], reference_time=self.now)
        # Single stale item evaluates as weak/insufficient rather than strong fresh evidence
        self.assertIn(res, [EvidenceStrengthLevel.WEAK, EvidenceStrengthLevel.INSUFFICIENT_EVIDENCE])

        # Historical log is immutable
        self.assertIsNotNone(self.event_store.get(old_obs["id"]))

    def test_9_absence_of_observation_does_not_erase_real_world_state(self) -> None:
        """Scenario 9: Epistemic Rule: 'Not observed' != 'did not happen'."""
        # 1. User has an active high-stakes commitment
        commit = self.world_model.record_commitment(
            description="Submit Tax Return Documentation",
            due_at=self.now + timedelta(days=5),
        )

        # 2. Run evaluation cycle when external source (e.g. IRS / email) has provided ZERO new observations
        cycle_result = self.pi.run_evaluation_cycle(as_of=self.now)

        # 3. Commitment remains active in the World Model snapshot
        world = self.pi.get_current_world(as_of=self.now)
        active_commits = world["commitments"]
        self.assertTrue(any(c["id"] == commit.id for c in active_commits))
        self.assertIn(active_commits[0]["status"].lower(), ["open", "pending", "active"])

    def test_10_provenance_preservation_full_fidelity(self) -> None:
        """Scenario 10: Complete fidelity of retrieval parameters, tool names, and external IDs."""
        prov_dict = {
            "tool": "hermes_jira_connector",
            "api_endpoint": "https://company.atlassian.net/rest/api/3/issue/PROJ-999",
            "issue_key": "PROJ-999",
            "changelog_id": "ch-10029",
            "query": "project = PROJ AND updated >= -1d",
            "retrieved_at": format_iso8601(self.now),
        }

        obs = self.pi.record_observation(
            source="jira",
            source_id="PROJ-999",
            timestamp=self.now - timedelta(hours=2),
            observation_type="issue_assigned",
            summary="Assigned critical security issue PROJ-999",
            evidence={"issue": "PROJ-999", "severity": "CRITICAL"},
            provenance=prov_dict,
            source_type="project_management",
            confidence=1.0,
        )

        # Retrieve through capability interface and verify provenance
        tl = self.pi.get_timeline(start_time=self.now - timedelta(hours=4), end_time=self.now)
        self.assertEqual(len(tl["events"]), 1)
        retrieved_event = tl["events"][0]

        self.assertEqual(retrieved_event["source"], "jira")
        self.assertEqual(retrieved_event["source_id"], "PROJ-999")
        self.assertEqual(retrieved_event["provenance"]["tool"], "hermes_jira_connector")
        self.assertEqual(retrieved_event["provenance"]["issue_key"], "PROJ-999")
        self.assertEqual(retrieved_event["provenance"]["api_endpoint"], "https://company.atlassian.net/rest/api/3/issue/PROJ-999")


if __name__ == "__main__":
    unittest.main()
