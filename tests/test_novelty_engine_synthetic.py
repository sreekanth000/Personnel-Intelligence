"""
Deterministic Synthetic Test Suite for NoveltyEngine.

Tests:
1. z-score deviation
2. baseline comparison
3. event frequency (categorical rarity)
4. event velocity
5. event silence
6. historical state similarity
7. cross-domain combination rarity
8. Categorical outputs contract (NORMAL, UNUSUAL, HIGHLY_UNUSUAL, NOVEL_COMBINATION)
9. NOVEL_COMBINATION creates a candidate novel_situation in SituationEngine
10. Hermes permitted to conclude 'insufficient evidence' on cold start / sparse history
"""

from datetime import datetime, timedelta, timezone
import unittest

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.novelty.detector import NoveltyEngine
from personal_intelligence.core.novelty.models import (
    FeatureNoveltyResult,
    NoveltyClassification,
    NoveltyResult,
    OverallNoveltyLevel,
)
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.models import (
    SituationPriority,
    StandardSituationCategory,
)
from personal_intelligence.core.state.models import StateFeature, StateRepresentation


class TestNoveltyEngineSynthetic(unittest.TestCase):
    """Deterministic synthetic test suite for NoveltyEngine."""

    def setUp(self) -> None:
        self.engine = NoveltyEngine(min_history_samples=3)
        self.base_time = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)

    # -------------------------------------------------------------------------
    # 1. z-score Deviation & Baseline Comparison
    # -------------------------------------------------------------------------

    def test_z_score_deviation_and_baseline_comparison(self) -> None:
        """
        Verify deterministic z-score computation and baseline distribution comparison.
        Normal: |z| < 1.5 -> NORMAL
        Unusual: 1.5 <= |z| < 2.5 -> UNUSUAL
        Highly Unusual: |z| >= 2.5 -> HIGHLY_UNUSUAL
        """
        # Baseline sleep duration: 10 snapshots with mean=480, std=20
        history: list[StateRepresentation] = []
        for i in range(10, 0, -1):
            t = self.base_time - timedelta(days=i)
            val = 480.0 + (20.0 if i % 2 == 0 else -20.0)  # alternating 500, 460
            rep = StateRepresentation(timestamp=t)
            rep.set_feature("sleep_duration_mins", val, source="sleep_tracker")
            history.append(rep)

        # Case A: Normal (480 mins -> z = 0.0)
        curr_normal = StateRepresentation(timestamp=self.base_time)
        curr_normal.set_feature("sleep_duration_mins", 480.0, source="sleep_tracker")
        res_normal = self.engine.detect(curr_normal, history)
        self.assertEqual(res_normal.overall_level, OverallNoveltyLevel.NORMAL.value)
        feat_res_norm = res_normal.feature_results[0]
        self.assertEqual(feat_res_norm.classification, NoveltyClassification.NORMAL.value)
        self.assertEqual(feat_res_norm.baseline["mean"], 480.0)
        self.assertEqual(feat_res_norm.baseline["std"], 20.0)

        # Case B: Moderate Unusual (444 mins -> z = -1.8)
        curr_unusual = StateRepresentation(timestamp=self.base_time)
        curr_unusual.set_feature("sleep_duration_mins", 444.0, source="sleep_tracker")
        res_unusual = self.engine.detect(curr_unusual, history)
        self.assertEqual(res_unusual.overall_level, OverallNoveltyLevel.UNUSUAL.value)
        feat_res_unusual = res_unusual.feature_results[0]
        self.assertEqual(feat_res_unusual.classification, NoveltyClassification.UNUSUAL.value)
        self.assertAlmostEqual(feat_res_unusual.deviation, 1.8, places=1)

        # Case C: Highly Unusual (225 mins -> z = -12.75)
        curr_high = StateRepresentation(timestamp=self.base_time)
        curr_high.set_feature("sleep_duration_mins", 225.0, source="sleep_tracker")
        res_high = self.engine.detect(curr_high, history)
        self.assertEqual(res_high.overall_level, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)
        feat_res_high = res_high.feature_results[0]
        self.assertEqual(feat_res_high.classification, NoveltyClassification.HIGHLY_UNUSUAL.value)

    # -------------------------------------------------------------------------
    # 2. Event Frequency & Categorical Rarity
    # -------------------------------------------------------------------------

    def test_event_frequency_and_categorical_rarity(self) -> None:
        """
        Verify empirical categorical event frequency tracking.
        Common value (>10%) -> NORMAL
        Rare value (<10%) -> UNUSUAL
        Unseen value (0%) -> HIGHLY_UNUSUAL
        """
        # History with 10 snapshots: 8 'home', 2 'office'
        history: list[StateRepresentation] = []
        for i in range(10, 0, -1):
            t = self.base_time - timedelta(days=i)
            loc = "home" if i > 2 else "office"
            rep = StateRepresentation(timestamp=t)
            rep.set_feature("location_context", loc, source="location_tracker")
            history.append(rep)

        # Common value ('home' -> 80%)
        curr_common = StateRepresentation(timestamp=self.base_time)
        curr_common.set_feature("location_context", "home", source="location_tracker")
        res_common = self.engine.detect(curr_common, history)
        self.assertEqual(res_common.overall_level, OverallNoveltyLevel.NORMAL.value)

        # Unseen categorical value ('airport' -> 0%)
        curr_unseen = StateRepresentation(timestamp=self.base_time)
        curr_unseen.set_feature("location_context", "airport", source="location_tracker")
        res_unseen = self.engine.detect(curr_unseen, history)
        self.assertEqual(res_unseen.overall_level, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)
        feat_res = res_unseen.feature_results[0]
        self.assertEqual(feat_res.classification, NoveltyClassification.HIGHLY_UNUSUAL.value)
        self.assertIn("never been observed", feat_res.explanation)

    # -------------------------------------------------------------------------
    # 3. Event Velocity & Silence
    # -------------------------------------------------------------------------

    def test_event_velocity_deviation(self) -> None:
        """Verify event velocity rate divergence vs historical velocity distribution."""
        history: list[StateRepresentation] = []
        for i in range(10, 0, -1):
            t = self.base_time - timedelta(hours=i)
            rep = StateRepresentation(timestamp=t)
            rep.set_feature("event_velocity", 0.2 + (0.02 if i % 2 == 0 else -0.02), source="timeline")
            history.append(rep)

        # Velocity surge: 2.5 events/min (z > 50)
        curr_surge = StateRepresentation(timestamp=self.base_time)
        curr_surge.set_feature("event_velocity", 2.5, source="timeline")
        res_surge = self.engine.detect(curr_surge, history)
        self.assertEqual(res_surge.overall_level, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)
        feat_res = res_surge.feature_results[0]
        self.assertIn("velocity surge", feat_res.explanation.lower())

    def test_event_silence_deviation(self) -> None:
        """Verify abnormal inactivity gap detection vs historical inter-arrival intervals."""
        history: list[StateRepresentation] = []
        for i in range(10, 0, -1):
            t = self.base_time - timedelta(days=i)
            rep = StateRepresentation(timestamp=t)
            rep.set_feature("inactivity_silence_gap", 2.0 + (0.2 if i % 2 == 0 else -0.2), source="timeline")
            history.append(rep)

        # Long silence gap: 14.0 hours
        curr_silence = StateRepresentation(timestamp=self.base_time)
        curr_silence.set_feature("inactivity_silence_gap", 14.0, source="timeline")
        res_silence = self.engine.detect(curr_silence, history)
        self.assertEqual(res_silence.overall_level, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)
        feat_res = res_silence.feature_results[0]
        self.assertIn("inactivity/silence", feat_res.explanation.lower())

    # -------------------------------------------------------------------------
    # 4. Historical State Similarity & Cross-Domain Combination Rarity
    # -------------------------------------------------------------------------

    def test_historical_state_similarity_and_novel_combination(self) -> None:
        """
        Verify multivariate distance calculation detecting NOVEL_COMBINATION
        when individual features are individually possible but their combination is novel.
        """
        # Baseline: (Home, Coding, Low density) OR (Office, Meeting, High density)
        history: list[StateRepresentation] = []
        for i in range(10, 0, -1):
            t = self.base_time - timedelta(days=i)
            rep = StateRepresentation(timestamp=t)
            if i % 2 == 0:
                rep.set_feature("location", "home", source="loc")
                rep.set_feature("activity", "coding", source="act")
                rep.set_feature("density", 0.1, source="net")
            else:
                rep.set_feature("location", "office", source="loc")
                rep.set_feature("activity", "meeting", source="act")
                rep.set_feature("density", 0.9, source="net")
            history.append(rep)

        # Novel combination: (Airport, Coding, High density)
        curr_comb = StateRepresentation(timestamp=self.base_time)
        curr_comb.set_feature("location", "airport", source="loc")
        curr_comb.set_feature("activity", "coding", source="act")
        curr_comb.set_feature("density", 0.9, source="net")

        res = self.engine.detect(curr_comb, history)
        self.assertEqual(res.overall_level, OverallNoveltyLevel.NOVEL_COMBINATION.value)
        self.assertTrue(res.metadata["is_novel_combination"])

    def test_cross_domain_combination_rarity(self) -> None:
        """Verify cross-domain combination rarity detection across 2+ distinct domains."""
        # 10 historical snapshots where sleep is always normal (480m) and meeting count is low (1)
        history: list[StateRepresentation] = []
        for i in range(10, 0, -1):
            t = self.base_time - timedelta(days=i)
            rep = StateRepresentation(timestamp=t)
            rep.set_feature("sleep_mins", 480.0, source="biometrics")
            rep.set_feature("calendar_meetings", 1.0, source="schedule")
            history.append(rep)

        # Current state: severe sleep restriction (200m) + extreme meeting overload (8)
        curr_rare = StateRepresentation(timestamp=self.base_time)
        curr_rare.set_feature("sleep_mins", 200.0, source="biometrics")
        curr_rare.set_feature("calendar_meetings", 8.0, source="schedule")

        res = self.engine.detect(curr_rare, history)
        self.assertEqual(res.overall_level, OverallNoveltyLevel.NOVEL_COMBINATION.value)
        self.assertTrue(res.metadata["is_novel_combination"])

    # -------------------------------------------------------------------------
    # 5. SituationEngine Integration & Hermes Insufficient Evidence Contract
    # -------------------------------------------------------------------------

    def test_novel_combination_creates_candidate_novel_situation(self) -> None:
        """Verify that NOVEL_COMBINATION creates a candidate novel_situation in SituationEngine."""
        novelty_result = NoveltyResult(
            overall_level=OverallNoveltyLevel.NOVEL_COMBINATION,
        )
        sit_engine = SituationEngine()
        current_state = StateRepresentation(timestamp=self.base_time)

        eval_res = sit_engine.evaluate(
            current_state=current_state,
            novelty_result=novelty_result,
            reference_time=self.base_time,
        )

        novel_sits = [s for s in eval_res.candidate_situations if s.type == "novel_situation"]
        self.assertGreaterEqual(len(novel_sits), 1)
        self.assertEqual(novel_sits[0].type, StandardSituationCategory.NOVEL_SITUATION.value)
        self.assertTrue(novel_sits[0].information_required)

    def test_hermes_insufficient_evidence_conclusion(self) -> None:
        """
        Verify that when history is sparse / cold start (< min_history_samples),
        NoveltyEngine returns NORMAL with insufficient_history metadata,
        enabling Hermes to conclude 'insufficient evidence' without forcing interpretation.
        """
        # Sparse history with only 1 sample
        sparse_history = [
            StateRepresentation(
                timestamp=self.base_time - timedelta(days=1),
                features={"metric_x": StateFeature(name="metric_x", value=10.0, source="sensor")},
            )
        ]

        curr = StateRepresentation(
            timestamp=self.base_time,
            features={"metric_x": StateFeature(name="metric_x", value=999.0, source="sensor")},
        )

        res = self.engine.detect(curr, sparse_history)
        self.assertEqual(res.overall_level, OverallNoveltyLevel.NORMAL.value)
        self.assertTrue(res.metadata["cold_start"])
        self.assertEqual(res.metadata["reasoning_instruction"], "insufficient_evidence")
        self.assertIn("Insufficient history", res.feature_results[0].explanation)


if __name__ == "__main__":
    unittest.main()
