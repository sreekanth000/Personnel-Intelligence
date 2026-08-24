"""
Empirical PatternEngine Test Suite.

Tests:
1. Multi-source empirical evidence (observations, state transitions, situations, user responses, recommendations, outcomes, episodes)
2. Supporting evidence accumulation
3. Contradicting evidence tracking
4. Insufficient evidence handling
5. Pattern activation (ACTIVE)
6. Decay (DECAYING) from silence or contradictions
7. Recovery from decay
8. Inactive patterns (INACTIVE)
9. Non-causal empirical association phrasing contract
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest
from typing import Any, Dict, List, Optional

from personal_intelligence.core.episodes.models import (
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.patterns import (
    EvidenceObservationType,
    Pattern,
    PatternEngine,
    PatternEvidence,
    PatternStatus,
    PatternStore,
    PatternType,
)
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.storage.db import DatabaseManager


class TestPatternEngineEmpirical(unittest.TestCase):
    """Test suite for empirical PatternEngine pipeline and 7-stage lifecycle."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_pattern_empirical.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.engine = PatternEngine(pattern_store=self.pattern_store, decay_after_days=14, inactivate_after_days=45)
        self.base_time = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Multi-Source Empirical Evidence & Candidate Associations
    # -------------------------------------------------------------------------

    def test_multi_source_empirical_evidence(self) -> None:
        """
        Verify pattern discovery is derived from empirical Personal Intelligence evidence:
        observations, state transitions, situations, user responses, recommendations, outcomes.
        """
        # 1. State transitions: high workload -> reduced activity
        s1 = StateRepresentation(timestamp=self.base_time)
        s1.set_feature("workload_index", 3.0, source="calendar")
        s2 = StateRepresentation(timestamp=self.base_time + timedelta(hours=3))
        s2.set_feature("recent_activity_duration", 15.0, source="timeline")

        s3 = StateRepresentation(timestamp=self.base_time + timedelta(days=1))
        s3.set_feature("workload_index", 2.8, source="calendar")
        s4 = StateRepresentation(timestamp=self.base_time + timedelta(days=1, hours=3))
        s4.set_feature("recent_activity_duration", 10.0, source="timeline")

        transition_patterns = self.engine.discover_state_transition_patterns([s1, s2, s3, s4])
        self.assertGreaterEqual(len(transition_patterns), 1)
        pat = transition_patterns[0]
        self.assertIn("Lower activity duration has occurred more frequently", pat.description)
        self.assertEqual(pat.status, PatternStatus.HYPOTHESIS.value)

        # 2. Observations & Outcomes from Episodes
        ep1 = self.episode_store.create_episode(
            trigger_type="reasoning_cycle",
            created_at=self.base_time,
            metadata={
                "recommendation": {"content": "Take a 15-min walk", "specificity": "specific"},
                "user_response": {"response": "ACCEPTED"},
                "outcome": {"status": "COMPLETED", "success": True},
            },
        )
        ep2 = self.episode_store.create_episode(
            trigger_type="reasoning_cycle",
            created_at=self.base_time + timedelta(days=1),
            metadata={
                "recommendation": {"content": "Hydrate and stretch", "specificity": "specific"},
                "user_response": {"response": "ACCEPTED"},
                "outcome": {"status": "COMPLETED", "success": True},
            },
        )
        ep_generic = self.episode_store.create_episode(
            trigger_type="reasoning_cycle",
            created_at=self.base_time + timedelta(days=2),
            metadata={
                "recommendation": {"content": "stay on track", "specificity": "generic"},
                "user_response": {"response": "DISMISSED"},
                "outcome": {"status": "DISMISSED"},
            },
        )

        interaction_patterns = self.engine.discover_interaction_patterns([ep1, ep2, ep_generic])
        self.assertGreaterEqual(len(interaction_patterns), 1)
        int_pat = interaction_patterns[0]
        self.assertIn("specific contextual recommendations", int_pat.description)
        self.assertIn(ep1.id, int_pat.supporting_episodes)
        self.assertIn(ep_generic.id, int_pat.supporting_episodes)

    # -------------------------------------------------------------------------
    # 2. Supporting Evidence Accumulation & Pattern Metadata
    # -------------------------------------------------------------------------

    def test_supporting_evidence_accumulation(self) -> None:
        """
        Verify accumulating supporting evidence increments support_count, updates last_observed,
        maintains source_observations, and preserves provenance.
        """
        pat = self.engine.register_candidate_pattern(
            description="Lower productivity has occurred more frequently after days containing late meetings.",
            first_seen=self.base_time,
            initial_status=PatternStatus.OBSERVED,
        )

        self.assertEqual(pat.support_count, 1)
        self.assertEqual(pat.contradiction_count, 0)
        self.assertEqual(pat.first_observed, self.base_time)
        self.assertEqual(pat.last_observed, self.base_time)

        # Record 3 supporting observation events
        t1 = self.base_time + timedelta(days=1)
        t2 = self.base_time + timedelta(days=2)
        t3 = self.base_time + timedelta(days=3)

        self.engine.record_supporting_evidence(pat.id, observation_id="obs-001", observed_at=t1)
        self.engine.record_supporting_evidence(pat.id, observation_id="obs-002", observed_at=t2)
        updated_pat, ev = self.engine.record_supporting_evidence(pat.id, observation_id="obs-003", observed_at=t3)

        self.assertEqual(updated_pat.support_count, 4)
        self.assertEqual(updated_pat.contradiction_count, 0)
        self.assertEqual(updated_pat.last_observed, t3)
        self.assertEqual(updated_pat.status, PatternStatus.EMERGING.value)
        self.assertIn("obs-001", updated_pat.supporting_evidence)
        self.assertIn("obs-003", updated_pat.supporting_evidence)

    # -------------------------------------------------------------------------
    # 3. Contradicting Evidence Tracking
    # -------------------------------------------------------------------------

    def test_contradicting_evidence_tracking(self) -> None:
        """
        Verify recording contradictory evidence increments contradiction_count,
        updates contradicting_evidence list, and adjusts empirical confidence ratio.
        """
        pat = self.engine.register_candidate_pattern(
            description="Tuesday afternoons are frequently observed with high calendar density.",
            first_seen=self.base_time,
            initial_status=PatternStatus.SUPPORTED,
        )
        # Seed 7 supports
        for i in range(1, 8):
            self.engine.record_supporting_evidence(pat.id, observation_id=f"obs-supp-{i}", observed_at=self.base_time + timedelta(days=i))

        # Record 2 contradictions (e.g. quiet Tuesday afternoon observed)
        t_contra_1 = self.base_time + timedelta(days=9)
        t_contra_2 = self.base_time + timedelta(days=10)

        self.engine.record_contradicting_evidence(pat.id, observation_id="obs-contra-1", observed_at=t_contra_1)
        updated_pat, ev = self.engine.record_contradicting_evidence(pat.id, observation_id="obs-contra-2", observed_at=t_contra_2)

        self.assertEqual(updated_pat.support_count, 8)
        self.assertEqual(updated_pat.contradiction_count, 2)
        self.assertAlmostEqual(updated_pat.confidence, 0.8, places=2)
        self.assertIn("obs-contra-1", updated_pat.contradicting_evidence)
        self.assertIn("obs-contra-2", updated_pat.contradicting_evidence)

    # -------------------------------------------------------------------------
    # 4. Insufficient Evidence
    # -------------------------------------------------------------------------

    def test_insufficient_evidence_lifecycle(self) -> None:
        """
        Verify that a single or sparse observation is categorized as OBSERVED / HYPOTHESIS
        and does not prematurely graduate to ACTIVE or SUPPORTED.
        """
        pat = self.engine.register_candidate_pattern(
            description="Morning deep work sessions coincide with higher task completion.",
            first_seen=self.base_time,
            initial_status=PatternStatus.OBSERVED,
        )

        self.assertEqual(pat.status, PatternStatus.OBSERVED.value)
        self.assertEqual(pat.evidence_strength, "weak")
        self.assertEqual(pat.support_count, 1)

        # 1 additional observation -> HYPOTHESIS, not ACTIVE
        updated, _ = self.engine.record_supporting_evidence(pat.id, observation_id="obs-morning-2", observed_at=self.base_time + timedelta(hours=2))
        self.assertEqual(updated.status, PatternStatus.HYPOTHESIS.value)
        self.assertEqual(updated.evidence_strength, "weak")

    # -------------------------------------------------------------------------
    # 5. Pattern Activation
    # -------------------------------------------------------------------------

    def test_pattern_activation(self) -> None:
        """
        Verify that accumulating strong supporting evidence (>= 10 observations, >= 85% ratio, recent)
        progressively advances pattern to ACTIVE status.
        """
        pat = self.engine.register_candidate_pattern(
            description="User appears more responsive to morning recommendations than evening.",
            first_seen=self.base_time,
            initial_status=PatternStatus.OBSERVED,
        )

        for i in range(1, 11):
            t = self.base_time + timedelta(days=i)
            updated, _ = self.engine.record_supporting_evidence(pat.id, episode_id=f"ep-morn-{i}", observed_at=t)

        self.assertEqual(updated.support_count, 11)
        self.assertEqual(updated.contradiction_count, 0)
        self.assertEqual(updated.status, PatternStatus.ACTIVE.value)
        self.assertEqual(updated.evidence_strength, "strong")
        self.assertEqual(updated.decay_state, "active")

    # -------------------------------------------------------------------------
    # 6. Recency and Contradiction Decay
    # -------------------------------------------------------------------------

    def test_pattern_decay(self) -> None:
        """
        Verify that silence for >= 14 days or multiple contradictions triggers DECAYING state.
        """
        pat = self.engine.register_candidate_pattern(
            description="Friday afternoons coincide with low code review activity.",
            first_seen=self.base_time,
            initial_status=PatternStatus.ACTIVE,
        )
        for i in range(1, 10):
            self.engine.record_supporting_evidence(pat.id, observation_id=f"obs-{i}", observed_at=self.base_time + timedelta(days=i))

        # Advance time by 20 days without new observations (decay_after_days = 14)
        sweep_time = self.base_time + timedelta(days=30)
        decayed_patterns = self.engine.apply_recency_decay(as_of=sweep_time)

        fetched = self.pattern_store.get_pattern(pat.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.status, PatternStatus.DECAYING.value)
        self.assertEqual(fetched.decay_state, "decaying")

    # -------------------------------------------------------------------------
    # 7. Recovery From Decay
    # -------------------------------------------------------------------------

    def test_recovery_from_decay(self) -> None:
        """
        Verify that fresh supporting observations restore a DECAYING pattern back to ACTIVE.
        """
        pat = self.engine.register_candidate_pattern(
            description="Friday afternoons coincide with low code review activity.",
            first_seen=self.base_time,
            initial_status=PatternStatus.ACTIVE,
        )
        for i in range(1, 10):
            self.engine.record_supporting_evidence(pat.id, observation_id=f"obs-{i}", observed_at=self.base_time + timedelta(days=i))

        # Put in decaying state
        sweep_time = self.base_time + timedelta(days=30)
        self.engine.apply_recency_decay(as_of=sweep_time)
        self.assertEqual(self.pattern_store.get_pattern(pat.id).status, PatternStatus.DECAYING.value)

        # Fresh observation arrives
        fresh_time = sweep_time + timedelta(hours=2)
        recovered, _ = self.engine.record_supporting_evidence(pat.id, observation_id="obs-fresh", observed_at=fresh_time)

        self.assertEqual(recovered.status, PatternStatus.ACTIVE.value)
        self.assertEqual(recovered.decay_state, "active")

    # -------------------------------------------------------------------------
    # 8. Inactive Patterns
    # -------------------------------------------------------------------------

    def test_inactive_patterns(self) -> None:
        """
        Verify that overwhelming contradictions (ratio <= 50% with contra >= 3)
        or prolonged silence (>= 45 days) marks pattern as INACTIVE.
        """
        pat = self.engine.register_candidate_pattern(
            description="Exercise is frequently followed by elevated late-night screen time.",
            first_seen=self.base_time,
            initial_status=PatternStatus.EMERGING,
        )
        # Record 4 supporting and 5 contradictions
        for i in range(1, 4):
            self.engine.record_supporting_evidence(pat.id, observation_id=f"obs-supp-{i}", observed_at=self.base_time + timedelta(days=i))
        for j in range(1, 6):
            self.engine.record_contradicting_evidence(pat.id, observation_id=f"obs-contra-{j}", observed_at=self.base_time + timedelta(days=4+j))

        fetched = self.pattern_store.get_pattern(pat.id)
        self.assertEqual(fetched.status, PatternStatus.INACTIVE.value)
        self.assertEqual(fetched.decay_state, "inactive")

    # -------------------------------------------------------------------------
    # 9. Strictly Non-Causal Phrasing Contract
    # -------------------------------------------------------------------------

    def test_strictly_non_causal_phrasing_contract(self) -> None:
        """
        Verify causal claims ('causes', 'leads to', 'results in') are automatically sanitized
        to empirical associations.
        """
        # BAD input: "Late meetings cause poor productivity."
        pat = self.engine.register_candidate_pattern(
            description="Late meetings cause poor productivity.",
            first_seen=self.base_time,
        )
        # GOOD output: empirical association
        self.assertNotIn(" cause ", pat.description)
        self.assertIn(" appear associated with ", pat.description)


if __name__ == "__main__":
    unittest.main()
