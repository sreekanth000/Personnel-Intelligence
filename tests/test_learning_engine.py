"""
Unit tests for the Personal Learning Engine.
Verifies discovery of recurring personal associations, non-causal representation,
evidence accumulation, contradiction tracking, recency-aware temporal decay, and recovery:
OBSERVED -> HYPOTHESIS -> EMERGING -> SUPPORTED -> ACTIVE -> DECAYING -> INACTIVE -> RECOVERY.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    ReasoningEpisode,
)
from personal_intelligence.core.patterns import (
    EvidenceObservationType,
    LearningEngine,
    Pattern,
    PatternEvidence,
    PatternStatus,
    PatternStore,
)
from personal_intelligence.storage.db import DatabaseManager


class TestPersonalLearningEngine(unittest.TestCase):
    """Test suite for Personal Learning Engine, non-causal discovery, decay, and recovery."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_learning_decay.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.engine = LearningEngine(
            pattern_store=self.pattern_store,
            decay_after_days=14,
            inactivate_after_days=45,
        )
        self.base_time = datetime(2026, 8, 1, 8, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- 1. Non-Causal Semantics Test ---

    def test_non_causal_representation_sanitization(self) -> None:
        """
        Verify that patterns are stored strictly as empirical associations,
        and causal claims ('causes', 'leads to', 'results in') are sanitized to association wording.
        """
        pat1 = self.engine.register_candidate_pattern(
            description="Low sleep causes shorter workouts.",
            first_seen=self.base_time,
        )
        self.assertEqual(pat1.description, "Low sleep appears associated with shorter workouts.")
        self.assertNotIn("causes", pat1.description)

        pat2 = self.engine.register_candidate_pattern(
            description="Afternoon coffee leads to delayed sleep onset.",
            first_seen=self.base_time,
        )
        self.assertEqual(pat2.description, "Afternoon coffee appears correlated with delayed sleep onset.")
        self.assertNotIn("leads to", pat2.description)

    # --- 2. Evidence Accumulation & Promotion ---

    def test_lifecycle_progression_from_observed_to_active(self) -> None:
        """
        Verify progressive promotion through stages as supporting evidence accumulates:
        OBSERVED -> HYPOTHESIS -> EMERGING -> SUPPORTED -> ACTIVE.
        """
        pat = self.engine.register_candidate_pattern(
            description="Deep work sessions over 3 hours appear associated with afternoon fatigue.",
            first_seen=self.base_time,
            initial_status=PatternStatus.OBSERVED,
        )
        self.assertEqual(pat.status, PatternStatus.OBSERVED.value)
        self.assertEqual(pat.support_count, 1)

        # Observation 2 -> HYPOTHESIS
        pat, _ = self.engine.record_evidence(
            pattern_id=pat.id,
            observation_type=EvidenceObservationType.SUPPORT,
            observed_at=self.base_time + timedelta(days=1),
        )
        self.assertEqual(pat.status, PatternStatus.HYPOTHESIS.value)

        # Observations 3-4 -> EMERGING
        for i in range(2):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=2 + i),
            )
        self.assertEqual(pat.status, PatternStatus.EMERGING.value)

        # Observations 5-7 -> SUPPORTED
        for i in range(3):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=5 + i),
            )
        self.assertEqual(pat.status, PatternStatus.SUPPORTED.value)

        # Observations 8-10 -> ACTIVE
        for i in range(3):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=9 + i),
            )
        self.assertEqual(pat.status, PatternStatus.ACTIVE.value)
        self.assertEqual(pat.evidence_strength, "strong")

    # --- 3. Stable Pattern Remains Active ---

    def test_stable_pattern_remains_active(self) -> None:
        """Verify that a pattern with regular reinforcement stays ACTIVE."""
        # Create ACTIVE pattern
        pat = self.engine.register_candidate_pattern(
            description="Regular schedule appears associated with consistent productivity.",
            first_seen=self.base_time,
        )
        for i in range(10):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=i),
            )
        self.assertEqual(pat.status, PatternStatus.ACTIVE.value)

        # Apply recency decay sweep as of day 12 (within 14-day decay window)
        as_of_time = self.base_time + timedelta(days=12)
        decayed = self.engine.apply_recency_decay(as_of=as_of_time)
        
        # Should not be decayed
        refreshed = self.pattern_store.get_pattern(pat.id)
        self.assertEqual(refreshed.status, PatternStatus.ACTIVE.value)
        self.assertEqual(len(decayed), 0)

    # --- 4. Old Pattern Decays Due to Inactivity ---

    def test_old_pattern_decays_due_to_inactivity(self) -> None:
        """
        Verify recency-aware decay:
        1. Pattern unobserved for 16 days (>= 14d) -> DECAYING
        2. Pattern unobserved for 50 days (>= 45d) -> INACTIVE
        """
        pat = self.engine.register_candidate_pattern(
            description="Late night snack appears associated with delayed wakeup.",
            first_seen=self.base_time,
        )
        for i in range(10):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=i),
            )
        self.assertEqual(pat.status, PatternStatus.ACTIVE.value)
        last_obs = self.base_time + timedelta(days=9)

        # Step 1: 16 days after last observation -> DECAYING
        time_16d_later = last_obs + timedelta(days=16)
        decayed_1 = self.engine.apply_recency_decay(as_of=time_16d_later)
        self.assertEqual(len(decayed_1), 1)
        self.assertEqual(decayed_1[0].status, PatternStatus.DECAYING.value)

        # Step 2: 50 days after last observation -> INACTIVE
        time_50d_later = last_obs + timedelta(days=50)
        decayed_2 = self.engine.apply_recency_decay(as_of=time_50d_later)
        self.assertEqual(len(decayed_2), 1)
        self.assertEqual(decayed_2[0].status, PatternStatus.INACTIVE.value)

    # --- 5. Contradictory Evidence Accelerates Decay ---

    def test_contradictory_evidence_accelerates_decay(self) -> None:
        """Verify contradictory evidence immediately accelerates demotion to DECAYING and INACTIVE."""
        pat = self.engine.register_candidate_pattern(
            description="Desk work appears associated with eye strain.",
            first_seen=self.base_time,
        )
        for i in range(7):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=i),
            )
        self.assertEqual(pat.status, PatternStatus.SUPPORTED.value)

        # 3 rapid contradictions -> drops ratio below 65% -> DECAYING immediately
        for i in range(3):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.CONTRADICTION,
                observed_at=self.base_time + timedelta(days=8 + i),
            )
        self.assertEqual(pat.status, PatternStatus.DECAYING.value)

        # Additional contradictions where contra > support -> INACTIVE
        for i in range(5):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.CONTRADICTION,
                observed_at=self.base_time + timedelta(days=12 + i),
            )
        self.assertEqual(pat.status, PatternStatus.INACTIVE.value)

    # --- 6. Pattern Recovery from Inactive / Decaying ---

    def test_pattern_recovers_with_fresh_support(self) -> None:
        """
        Verify that an INACTIVE or DECAYING pattern can recover when fresh supporting evidence reappears.
        """
        # Create a pattern that decayed to INACTIVE
        pat = self.engine.register_candidate_pattern(
            description="Audiobooks during commute appear associated with relaxed arrival state.",
            first_seen=self.base_time,
        )
        for i in range(10):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=i),
            )
        self.assertEqual(pat.status, PatternStatus.ACTIVE.value)

        # Force decay to INACTIVE via long time gap (60 days)
        dormant_time = self.base_time + timedelta(days=70)
        self.engine.apply_recency_decay(as_of=dormant_time)
        inactive_pat = self.pattern_store.get_pattern(pat.id)
        self.assertEqual(inactive_pat.status, PatternStatus.INACTIVE.value)

        # Fresh supporting evidence reappears at day 71 -> Recovers to SUPPORTED / ACTIVE
        recovered_pat, _ = self.engine.record_evidence(
            pattern_id=pat.id,
            observation_type=EvidenceObservationType.SUPPORT,
            observed_at=dormant_time + timedelta(days=1),
        )
        self.assertIn(recovered_pat.status, [PatternStatus.SUPPORTED.value, PatternStatus.ACTIVE.value, PatternStatus.EMERGING.value])
        self.assertNotEqual(recovered_pat.status, PatternStatus.INACTIVE.value)

    # --- 7. Historical Evidence Permanently Preserved ---

    def test_historical_evidence_never_deleted(self) -> None:
        """Verify that decaying and inactiving patterns preserves all pattern_evidence records in SQLite."""
        pat = self.engine.register_candidate_pattern(
            description="Evening walks appear associated with deeper sleep.",
            first_seen=self.base_time,
        )
        for i in range(5):
            self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=i),
                episode_id=f"ep-support-{i}",
            )
        self.engine.record_evidence(
            pattern_id=pat.id,
            observation_type=EvidenceObservationType.CONTRADICTION,
            observed_at=self.base_time + timedelta(days=6),
            episode_id="ep-contra-1",
        )

        # Force decay to INACTIVE
        self.engine.apply_recency_decay(as_of=self.base_time + timedelta(days=100))

        # Check that all 6 evidence instances remain in SQLite
        evidence_list = self.pattern_store.list_evidence_for_pattern(pat.id)
        self.assertEqual(len(evidence_list), 6)
        support_items = [e for e in evidence_list if e.observation_type == "SUPPORT"]
        contra_items = [e for e in evidence_list if e.observation_type == "CONTRADICTION"]
        self.assertEqual(len(support_items), 5)
        self.assertEqual(len(contra_items), 1)


    # --- 8. Intervention Preference Learning Tests ---

    def test_learn_preference_specific_vs_generic_recommendations(self) -> None:
        """
        Verify that longitudinal reasoning episodes with accepted specific recommendations
        and dismissed generic reminders generate a specificity preference hypothesis.
        """
        episodes = [
            # 3 Specific recommendations (Accepted)
            ReasoningEpisode(
                id="ep-spec-1",
                hermes_task="Assess workout fatigue",
                recommendation={"content": "Hydrate with 500ml water and rest 15 minutes before the next set.", "specificity": "specific"},
                user_response={"response": "ACCEPTED"},
                created_at=self.base_time,
            ),
            ReasoningEpisode(
                id="ep-spec-2",
                hermes_task="Assess workout fatigue",
                recommendation={"content": "Switch to low-impact stretching routine for 10 minutes to prevent hamstring strain.", "specificity": "specific"},
                user_response={"response": "ACCEPTED"},
                created_at=self.base_time + timedelta(days=1),
            ),
            ReasoningEpisode(
                id="ep-spec-3",
                hermes_task="Assess schedule conflict",
                recommendation={"content": "Move 2:00 PM sync to 3:30 PM to avoid overlap with client presentation.", "specificity": "specific"},
                user_response={"response": "ACCEPTED"},
                created_at=self.base_time + timedelta(days=2),
            ),
            # 2 Generic reminders (Dismissed)
            ReasoningEpisode(
                id="ep-gen-1",
                hermes_task="Check schedule",
                recommendation={"content": "Check schedule.", "specificity": "generic"},
                user_response={"response": "DISMISSED"},
                created_at=self.base_time + timedelta(days=3),
            ),
            ReasoningEpisode(
                id="ep-gen-2",
                hermes_task="Reminder",
                recommendation={"content": "Take a break.", "specificity": "generic"},
                user_response={"response": "DISMISSED"},
                created_at=self.base_time + timedelta(days=4),
            ),
        ]

        patterns = self.engine.scan_intervention_preferences(episodes)
        self.assertGreaterEqual(len(patterns), 1)

        spec_pat = next((p for p in patterns if "specific contextual recommendations" in p.description), None)
        self.assertIsNotNone(spec_pat)
        self.assertEqual(spec_pat.description, "User appears more responsive to specific contextual recommendations than generic reminders.")
        self.assertEqual(spec_pat.metadata["dimension"], "recommendation_specificity")
        self.assertEqual(spec_pat.metadata["specific_acceptance_rate"], 1.0)
        self.assertEqual(spec_pat.metadata["generic_acceptance_rate"], 0.0)

        # Check episode provenance
        evidence_records = self.pattern_store.list_evidence_for_pattern(spec_pat.id)
        ev_episode_ids = {e.episode_id for e in evidence_records}
        self.assertIn("ep-spec-1", ev_episode_ids)
        self.assertIn("ep-spec-2", ev_episode_ids)
        self.assertIn("ep-gen-1", ev_episode_ids)

    def test_learn_preference_timing_and_urgency(self) -> None:
        """
        Verify discovery of timing preferences (morning responsiveness)
        and urgency preferences (high urgency responsiveness).
        """
        morning_dt = datetime(2026, 8, 1, 9, 0, 0, tzinfo=timezone.utc)
        evening_dt = datetime(2026, 8, 1, 20, 0, 0, tzinfo=timezone.utc)

        episodes = [
            # Morning episodes with positive responses
            ReasoningEpisode(
                id="ep-morn-1",
                hermes_task="Morning briefing",
                urgency="high",
                recommendation={"content": "Review 3 priority tasks for today before 10 AM."},
                user_response={"response": "ACCEPTED"},
                created_at=morning_dt,
            ),
            ReasoningEpisode(
                id="ep-morn-2",
                hermes_task="Morning briefing",
                urgency="high",
                recommendation={"content": "Take morning walk to prepare for deep work session."},
                user_response={"response": "COMPLETED"},
                created_at=morning_dt + timedelta(days=1),
            ),
            # Evening episodes with dismissed responses
            ReasoningEpisode(
                id="ep-eve-1",
                hermes_task="Evening summary",
                urgency="low",
                recommendation={"content": "Log end-of-day reflections."},
                user_response={"response": "DISMISSED"},
                created_at=evening_dt,
            ),
            ReasoningEpisode(
                id="ep-eve-2",
                hermes_task="Evening summary",
                urgency="medium",
                recommendation={"content": "Review tomorrow's calendar."},
                user_response={"response": "IGNORED"},
                created_at=evening_dt + timedelta(days=1),
            ),
        ]

        patterns = self.engine.scan_intervention_preferences(episodes)
        self.assertGreaterEqual(len(patterns), 1)

        # Check for timing pattern
        timing_pat = next((p for p in patterns if "morning hours" in p.description), None)
        self.assertIsNotNone(timing_pat)
        self.assertIn("appears more responsive", timing_pat.description)

        # Check for urgency pattern
        urg_pat = next((p for p in patterns if "high urgency" in p.description), None)
        self.assertIsNotNone(urg_pat)
        self.assertIn("appear associated with higher acceptance rates", urg_pat.description)

    def test_learn_preference_busy_context_dismissal(self) -> None:
        """
        Verify discovery of contextual preference where recommendations during busy context are dismissed.
        """
        episodes = [
            ReasoningEpisode(
                id="ep-busy-1",
                hermes_task="Task reminder",
                intervention_decision={"user_context": "busy"},
                recommendation={"content": "Check updated notes."},
                user_response={"response": "DISMISSED"},
                created_at=self.base_time,
            ),
            ReasoningEpisode(
                id="ep-busy-2",
                hermes_task="Task reminder",
                intervention_decision={"user_context": "busy"},
                recommendation={"content": "Update status report."},
                user_response={"response": "IGNORED"},
                created_at=self.base_time + timedelta(days=1),
            ),
        ]

        patterns = self.engine.scan_intervention_preferences(episodes)
        self.assertGreaterEqual(len(patterns), 1)

        busy_pat = next((p for p in patterns if "busy context" in p.description), None)
        self.assertIsNotNone(busy_pat)
        self.assertEqual(busy_pat.description, "Recommendations delivered during busy context appear associated with higher dismissal rates.")
        self.assertEqual(busy_pat.metadata["dimension"], "context")


if __name__ == "__main__":
    unittest.main()
