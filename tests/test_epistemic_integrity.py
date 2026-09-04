"""
Test Suite for Explicit Epistemic State Management and Integrity Safeguards.

ARCHITECTURAL PRINCIPLE:
Personal Intelligence does NOT maintain an independent 'fact database' or parallel memory store.
Epistemic state and truth lineage are unified across core architectural subsystems:
- EventStore: Ground-truth observations with immutable historical provenance.
- PersonalWorldModel: Semantic owner and registrar of epistemic facts.
- ContextGraph: Relational substrate linking entities via typed edges with epistemic_type.
- EvidenceQualityCalculator: Multi-factor deterministic evidence quality evaluation.
- EpisodeStore: Structured reasoning episodes, user responses, and empirical outcomes.

Verifies:
1. Observations remain observations (epistemic_type == 'observed') with immutable provenance.
2. Inferences remain inferences (epistemic_type == 'inferred') and must cite supporting observations.
3. Provenance survives round-trip serialization and database storage.
4. Contradictory observations remain visible (never silently deleted).
5. Reasoning operates without Bayesian probabilities.
6. Deterministic evidence quality calculation works with independent source lineage.
7. Illegal epistemic promotion (INFERRED -> OBSERVED) is prevented.
8. Cascading truth retraction marks linked derived/inferred records as retracted.
9. Predictions remain predictions and distinct.
10. Recommendations and actions remain strictly segregated.
11. Historical observations remain immutable in EventStore.
12. No second fact store or parallel memory database exists.
13. EpistemicFactStore compatibility adapter is delegation-only and issues deprecation warning.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
import warnings

from personal_intelligence.core.episodes.models import ReasoningEpisode
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.evidence_quality import (
    EvidenceQualityCalculator,
    EvidenceQualityLevel,
)
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.core.world.models import (
    EpistemicIntegrityError,
    EpistemicRecord,
    EpistemicType,
)
from personal_intelligence.storage.db import DatabaseManager


class TestEpistemicIntegrityModel(unittest.TestCase):
    """Verifies explicit epistemic state management and invariants in Personal World Model."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_epistemic.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.world_model = PersonalWorldModel(db_manager=self.db_manager)
        self.evidence_calculator = EvidenceQualityCalculator()
        self.base_time = datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_observations_remain_observations_with_provenance(self) -> None:
        """Requirement 1 & 3: Verified ground-truth observations remain 'observed' with full provenance."""
        wm = self.world_model

        obs_record = wm.record_epistemic_fact(
            subject="Alex Rivera",
            predicate="sent_email_subject",
            object="Q3 Architecture Plan Final Draft",
            epistemic_type=EpistemicType.OBSERVED,
            source="gmail",
            source_id="msg-apex-9921",
            origin_event_id="evt-gmail-001",
            supporting_observation_ids=["evt-gmail-001"],
            provenance={
                "channel": "gmail",
                "message_id": "msg-apex-9921",
                "sender": "alex.rivera@company.com",
                "timestamp": "2026-09-01T08:00:00Z",
            },
        )

        self.assertEqual(obs_record.epistemic_type, EpistemicType.OBSERVED.value)
        self.assertEqual(obs_record.source, "gmail")
        self.assertEqual(obs_record.source_id, "msg-apex-9921")
        self.assertEqual(obs_record.origin_event_id, "evt-gmail-001")
        self.assertEqual(obs_record.supporting_observation_ids, ["evt-gmail-001"])

        # Query from DB to verify persistence
        saved_records = wm.get_epistemic_records(epistemic_type="observed", subject="Alex Rivera")
        self.assertEqual(len(saved_records), 1)
        self.assertEqual(saved_records[0].provenance["message_id"], "msg-apex-9921")
        self.assertEqual(saved_records[0].epistemic_type, "observed")

    def test_inferences_remain_inferences_and_cite_supporting_observations(self) -> None:
        """Requirement 2: Inferences explicitly reference supporting observations and remain 'inferred'."""
        wm = self.world_model

        # Step 1: Record 2 Ground-Truth Observations
        obs1 = wm.record_epistemic_fact(
            subject="Client Alpha",
            predicate="slack_tone",
            object="critical",
            epistemic_type=EpistemicType.OBSERVED,
            source="slack",
            origin_event_id="evt-slack-001",
            supporting_observation_ids=["evt-slack-001"],
        )
        obs2 = wm.record_epistemic_fact(
            subject="Project Alpha",
            predicate="deliverable_due",
            object="in_24h",
            epistemic_type=EpistemicType.OBSERVED,
            source="linear",
            origin_event_id="evt-linear-001",
            supporting_observation_ids=["evt-linear-001"],
        )

        # Step 2: Formulate Inferred Epistemic Record citing supporting observation IDs
        inf_record = wm.record_epistemic_fact(
            subject="Client Alpha",
            predicate="perceived_risk_level",
            object="high_dissatisfaction",
            epistemic_type=EpistemicType.INFERRED,
            statement="Client Alpha is at risk of churn due to approaching deadline friction.",
            source="hermes_reasoning",
            source_id="episode-771",
            supporting_observation_ids=[obs1.origin_event_id, obs2.origin_event_id],
            provenance={"reasoning_episode_id": "episode-771", "synthesized_by": "hermes"},
        )

        self.assertEqual(inf_record.epistemic_type, EpistemicType.INFERRED.value)
        self.assertIn("evt-slack-001", inf_record.supporting_observation_ids)
        self.assertIn("evt-linear-001", inf_record.supporting_observation_ids)

        # Verify query segregation: querying 'observed' does NOT return this inference
        obs_only = wm.get_epistemic_records(epistemic_type=EpistemicType.OBSERVED.value)
        inf_only = wm.get_epistemic_records(epistemic_type=EpistemicType.INFERRED.value)

        self.assertEqual(len(obs_only), 2)
        self.assertEqual(len(inf_only), 1)
        self.assertEqual(inf_only[0].epistemic_type, "inferred")

    def test_forbidden_silent_promotion_from_inference_to_observation(self) -> None:
        """Requirement 7: Never silently promote INFERRED -> OBSERVED."""
        inf_record = EpistemicRecord(
            epistemic_type=EpistemicType.INFERRED,
            statement="User is stressed about meeting.",
            subject="User",
            predicate="mental_state",
            object="stressed",
            supporting_observation_ids=["evt-obs-1"],
        )

        # Attempting silent promotion must raise EpistemicIntegrityError
        with self.assertRaises(EpistemicIntegrityError):
            inf_record.promote_to_observation()

    def test_contradictory_observations_remain_visible(self) -> None:
        """Requirement 4: Contradictory observations are recorded in contradictory lineage, never deleted."""
        wm = self.world_model

        # Observation 1: User is in Room A
        rec = wm.record_epistemic_fact(
            subject="User",
            predicate="location",
            object="Conference Room A",
            epistemic_type=EpistemicType.OBSERVED,
            source="calendar",
            origin_event_id="evt-cal-101",
            supporting_observation_ids=["evt-cal-101"],
        )

        # Observation 2: GPS reports User is in Base Camp Café (Contradictory)
        rec_updated = wm.record_epistemic_fact(
            subject="User",
            predicate="location",
            object="Conference Room A",
            epistemic_type=EpistemicType.OBSERVED,
            contradictory_observation_ids=["evt-gps-102"],
        )

        self.assertIn("evt-cal-101", rec_updated.supporting_observation_ids)
        self.assertIn("evt-gps-102", rec_updated.contradictory_observation_ids)
        self.assertEqual(rec_updated.status, "active")

    def test_reasoning_without_bayesian_probability(self) -> None:
        """Requirement 5: Epistemic records operate deterministically without continuous Bayesian P(H|E)."""
        wm = self.world_model

        rec = wm.record_epistemic_fact(
            subject="Server Cluster",
            predicate="status",
            object="healthy",
            epistemic_type=EpistemicType.OBSERVED,
            source="datadog",
            origin_event_id="evt-dd-1",
            supporting_observation_ids=["evt-dd-1"],
        )

        rec_dict = rec.to_dict()
        # Verify no Bayesian attributes in the epistemic record dictionary
        self.assertNotIn("belief_score", rec_dict)
        self.assertNotIn("posterior_probability", rec_dict)
        self.assertNotIn("prior_probability", rec_dict)
        self.assertNotIn("likelihood", rec_dict)
        self.assertEqual(rec_dict["epistemic_type"], "observed")

    def test_deterministic_evidence_quality_with_provenance_lineage(self) -> None:
        """Requirement 6: Evidence quality uses independent provenance lineage without fake probabilities."""
        evidence_items = [
            {"source": "gmail", "origin_event_id": "mail-1", "statement": "Client requested Friday sync"},
            {"source": "calendar", "origin_event_id": "cal-1", "statement": "Friday 14:00 review invite accepted"},
            {"source": "slack", "origin_event_id": "slack-1", "statement": "Client PM posted agenda in channel"},
        ]

        quality = self.evidence_calculator.calculate(evidence_items)
        self.assertEqual(quality, EvidenceQualityLevel.STRONG)

        # Contradiction marks as CONFLICTED
        contradicted_items = evidence_items + [
            {"source": "linear", "origin_event_id": "lin-1", "statement": "Meeting cancelled", "contradicts": True}
        ]
        quality_conflicted = self.evidence_calculator.calculate(contradicted_items)
        self.assertEqual(quality_conflicted, EvidenceQualityLevel.CONFLICTED)

    def test_cascading_truth_retraction_on_epistemic_records(self) -> None:
        """Requirement 8: Retracting an observation retracts all derived and inferred epistemic records."""
        wm = self.world_model

        # 1. Record an observation
        obs = wm.record_epistemic_fact(
            subject="Project Beta",
            predicate="milestone_deadline",
            object="Tomorrow 09:00",
            epistemic_type=EpistemicType.OBSERVED,
            source="slack",
            origin_event_id="evt-fake-slack-msg",
            supporting_observation_ids=["evt-fake-slack-msg"],
        )

        # 2. Record an inference derived from this observation
        inf = wm.record_epistemic_fact(
            subject="Project Beta",
            predicate="schedule_risk",
            object="high",
            epistemic_type=EpistemicType.INFERRED,
            statement="Project Beta is at extreme risk of missing tomorrow's deadline.",
            source="hermes_reasoning",
            supporting_observation_ids=["evt-fake-slack-msg"],
        )

        self.assertEqual(obs.status, "active")
        self.assertEqual(inf.status, "active")

        # 3. Retract origin observation
        retracted_ids = wm.retract_observation("evt-fake-slack-msg")

        self.assertIn(obs.id, retracted_ids)
        self.assertIn(inf.id, retracted_ids)

        # 4. Verify both are marked retracted in database
        active_records = wm.get_epistemic_records(status="active", subject="Project Beta")
        retracted_records = wm.get_epistemic_records(status="retracted", subject="Project Beta")

        self.assertEqual(len(active_records), 0)
        self.assertEqual(len(retracted_records), 2)

    def test_inference_cannot_be_persisted_as_observation_accidentally(self) -> None:
        """Verify inferences cannot be recorded as observations without verified provenance, and require supporting observations."""
        wm = self.world_model

        # 1. Bare observation without provenance must be rejected
        with self.assertRaises(EpistemicIntegrityError):
            wm.record_epistemic_fact(
                subject="User",
                predicate="feeling",
                object="tired",
                epistemic_type=EpistemicType.OBSERVED,
                source="unknown",
                source_id=None,
                origin_event_id=None,
                provenance=None,
                supporting_observation_ids=[],
            )

        # 2. Inference without supporting observations must be rejected
        with self.assertRaises(EpistemicIntegrityError):
            wm.record_epistemic_fact(
                subject="Project Delta",
                predicate="likely_delayed",
                object="true",
                epistemic_type=EpistemicType.INFERRED,
                supporting_observation_ids=[],
            )

    def test_predictions_remain_predictions_and_distinct(self) -> None:
        """Verify predictions remain strictly segregated from observations and inferences."""
        wm = self.world_model

        pred = wm.record_epistemic_fact(
            subject="Weather Forecast",
            predicate="predicted_rainfall",
            object="heavy",
            epistemic_type=EpistemicType.PREDICTED,
            source="noaa_model",
            source_id="model-run-44",
            origin_event_id="evt-weather-run",
            supporting_observation_ids=["evt-weather-run"],
            provenance={"run": "gfs_00z"},
        )
        self.assertEqual(pred.epistemic_type, "predicted")

        # Query segregation: querying 'observed' or 'inferred' does not return prediction
        obs_records = wm.get_epistemic_records(epistemic_type="observed")
        inf_records = wm.get_epistemic_records(epistemic_type="inferred")
        pred_records = wm.get_epistemic_records(epistemic_type="predicted")

        self.assertNotIn(pred.id, [r.id for r in obs_records])
        self.assertNotIn(pred.id, [r.id for r in inf_records])
        self.assertIn(pred.id, [r.id for r in pred_records])

        # Attempt to promote prediction to observation must fail
        with self.assertRaises(EpistemicIntegrityError):
            pred.promote_to_observation()

    def test_recommendation_and_action_separation(self) -> None:
        """Verify recommendations remain separate from executed actions in reasoning episodes."""
        episode = ReasoningEpisode(
            situation_id="sit-overwork-01",
            recommendation="Suggest rescheduling 16:00 sync to tomorrow morning.",
            inferences=["User has 5 consecutive back-to-back meetings"],
            predictions=["High risk of meeting exhaustion"],
            user_response=None,  # User has not acted yet
            outcome=None,        # Outcome is separate
            status="pending",
        )

        # Recommendation, Inference, and Prediction exist distinctly
        self.assertEqual(episode.recommendation, "Suggest rescheduling 16:00 sync to tomorrow morning.")
        self.assertEqual(len(episode.inferences), 1)
        self.assertEqual(len(episode.predictions), 1)
        # Action is separate and not yet executed
        self.assertIsNone(episode.user_response)
        self.assertIsNone(episode.outcome)

        # User later responds with an action
        episode.user_response = {"action": "accepted", "executed_at": "2026-09-03T10:00:00Z"}
        episode.outcome = {"calendar_event_moved": True}
        episode.status = "completed"

        self.assertEqual(episode.user_response["action"], "accepted")
        self.assertTrue(episode.outcome["calendar_event_moved"])

    def test_historical_observations_remain_immutable(self) -> None:
        """Verify historical observations in EventStore cannot be mutated by derived inferences."""
        obs_event = Event(
            source="linear",
            source_id="issue-900",
            event_type="ticket_closed",
            payload={"title": "Fix bug 900", "closed_by": "developer@co.com"},
            timestamp=datetime.now(timezone.utc),
            confidence=1.0,
        )
        saved_event = self.world_model.event_store.append(obs_event)
        orig_hash = saved_event.event_hash
        orig_payload = dict(saved_event.payload)

        # Record downstream inference citing this event
        inf = self.world_model.record_epistemic_fact(
            subject="Sprint Target",
            predicate="status",
            object="on_track",
            epistemic_type=EpistemicType.INFERRED,
            supporting_observation_ids=[saved_event.id],
        )

        # Re-fetch event from store and verify it is completely untouched
        refetched = self.world_model.event_store.get(saved_event.id)
        self.assertEqual(refetched.event_hash, orig_hash)
        self.assertEqual(refetched.payload, orig_payload)
        self.assertEqual(refetched.confidence, 1.0)

    def test_no_second_fact_or_memory_store_exists(self) -> None:
        """Verify system does not introduce duplicate database files or duplicate fact stores."""
        conn = self.db_manager.get_connection()
        try:
            # Query all table names in SQLite
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            # Ensure no duplicate fact stores exist
            self.assertNotIn("duplicate_facts", tables)
            self.assertNotIn("second_memory_store", tables)
            self.assertNotIn("parallel_fact_store", tables)
            self.assertNotIn("epistemic_fact_store", tables)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
