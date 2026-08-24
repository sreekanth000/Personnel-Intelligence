"""
Integration test suite validating synthetic longitudinal pattern learning.
Verifies discovery of interaction patterns over 120+ reasoning episodes,
evidence accumulation, contradiction tracking, lifecycle progression,
recency decay, recovery, and complete episode provenance chains.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest

from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.patterns.engine import LearningEngine
from personal_intelligence.core.patterns.models import (
    EvidenceObservationType,
    PatternStatus,
)
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.storage.db import DatabaseManager
from scripts.evaluate_longitudinal_learning import (
    generate_longitudinal_episodes,
    run_longitudinal_evaluation,
)


class TestSyntheticLongitudinalLearningEvaluation(unittest.TestCase):
    """
    Formal longitudinal evaluation test suite.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_longitudinal.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.learning_engine = LearningEngine(
            pattern_store=self.pattern_store,
            db_manager=self.db_manager,
            decay_after_days=14,
            inactivate_after_days=45,
        )

        self.base_time = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_longitudinal_pattern_discovery_and_lifecycle(self) -> None:
        """
        Verify end-to-end longitudinal evaluation:
        - 120 synthetic episodes across 60 days
        - Discovery of specificity preference without hardcoded rules
        - Non-causal association semantics
        - Supporting evidence accumulation with provenance
        - Contradiction tracking
        - Progression from HYPOTHESIS to ACTIVE
        - Recency decay after 20 days silence
        - Recovery upon fresh supporting observation
        """
        # 1. Ingest 120 longitudinal episodes
        episodes = generate_longitudinal_episodes(base_time=self.base_time, total_episodes=120)
        self.assertGreaterEqual(len(episodes), 100)

        for ep in episodes:
            self.episode_store.create_episode(
                situation_id=ep.situation_id,
                hermes_task=ep.hermes_task,
                urgency=ep.urgency,
                actionability=ep.actionability,
                evidence_strength=ep.evidence_strength,
                recommendation=ep.recommendation,
                intervention_decision=ep.intervention_decision,
                user_response=ep.user_response,
                outcome=ep.outcome,
                created_at=ep.created_at,
                episode_id=ep.id,
            )

        # 2. Learning Engine scan
        patterns = self.learning_engine.scan_intervention_preferences(episodes)
        self.assertGreaterEqual(len(patterns), 1)

        specificity_pattern = next(
            (p for p in patterns if "specific" in p.description.lower()),
            None,
        )
        self.assertIsNotNone(specificity_pattern, "Must discover specificity preference pattern.")

        # 3. Non-causal association check
        desc_lower = specificity_pattern.description.lower()
        self.assertNotIn("causes", desc_lower)
        self.assertNotIn("leads to", desc_lower)
        self.assertNotIn("results in", desc_lower)
        self.assertIn("appears more responsive to", desc_lower)

        # 4. Evidence Accumulation
        self.assertGreaterEqual(specificity_pattern.support_count, 50)
        self.assertEqual(specificity_pattern.contradiction_count, 0)
        self.assertGreaterEqual(specificity_pattern.metadata.get("specific_acceptance_rate", 0), 0.65)
        self.assertLessEqual(specificity_pattern.metadata.get("generic_acceptance_rate", 1.0), 0.40)

        # 5. Provenance audit
        evidence_chain = self.pattern_store.list_evidence_for_pattern(specificity_pattern.id, limit=200)
        self.assertGreaterEqual(len(evidence_chain), 50)
        for ev in evidence_chain[:10]:
            self.assertIsNotNone(ev.episode_id)
            persisted_ep = self.episode_store.get_episode(ev.episode_id)
            self.assertIsNotNone(persisted_ep, f"Evidence {ev.evidence_id} must link to existing episode.")

        # 6. Progression to ACTIVE
        status, strength = self.learning_engine.evaluate_progression(specificity_pattern, as_of=self.base_time)
        self.assertEqual(status, PatternStatus.ACTIVE)
        self.assertEqual(strength, "strong")

        specificity_pattern.status = status.value
        specificity_pattern.evidence_strength = strength
        self.pattern_store.update_pattern(specificity_pattern)

        # 7. Contradiction Tracking
        contra_time = self.base_time + timedelta(hours=1)
        contra_ep = self.episode_store.create_episode(
            situation_id="sit-contra-test",
            hermes_task="Contradiction test",
            urgency="medium",
            actionability="high",
            evidence_strength="strong",
            created_at=contra_time,
        )
        updated_pat, contra_ev = self.learning_engine.record_evidence(
            pattern_id=specificity_pattern.id,
            observation_type=EvidenceObservationType.CONTRADICTION,
            observed_at=contra_time,
            episode_id=contra_ep.id,
            details={"reason": "User dismissed specific recommendation during meeting."},
        )
        self.assertEqual(updated_pat.contradiction_count, 1)
        self.assertEqual(contra_ev.observation_type, EvidenceObservationType.CONTRADICTION.value)

        # 8. Recency Decay Simulation (20 days silence)
        decay_time = self.base_time + timedelta(days=20)
        decay_status, decay_strength = self.learning_engine.evaluate_progression(updated_pat, as_of=decay_time)
        self.assertEqual(decay_status, PatternStatus.DECAYING)

        updated_pat.status = decay_status.value
        updated_pat.evidence_strength = decay_strength
        self.pattern_store.update_pattern(updated_pat)

        # 9. Recovery from Decay
        recovery_time = decay_time + timedelta(days=1)
        rec_ep = self.episode_store.create_episode(
            situation_id="sit-recovery-test",
            hermes_task="Recovery test",
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            created_at=recovery_time,
        )
        recovered_pat, _ = self.learning_engine.record_evidence(
            pattern_id=updated_pat.id,
            observation_type=EvidenceObservationType.SUPPORT,
            observed_at=recovery_time,
            episode_id=rec_ep.id,
            details={"reason": "User completed specific recommendation."},
        )
        self.assertIn(recovered_pat.status, (PatternStatus.ACTIVE.value, PatternStatus.SUPPORTED.value))
        self.assertEqual(recovered_pat.evidence_strength, "strong")

        # Confirm all evidence remained intact through decay & recovery
        all_evidence = self.pattern_store.list_evidence_for_pattern(recovered_pat.id, limit=300)
        self.assertGreaterEqual(len(all_evidence), 52)

    def test_run_longitudinal_evaluation_script(self) -> None:
        """Verify the evaluation script executes without errors."""
        run_longitudinal_evaluation()


if __name__ == "__main__":
    unittest.main()
