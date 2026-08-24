"""
Unit tests for V1 Statistical Novelty Detection.
Tests normal state, single anomaly, multiple anomalies, missing history,
zero variance, and categorical novelty.
"""

from datetime import datetime, timedelta, timezone
import unittest

from personal_intelligence.core.novelty import (
    FeatureNoveltyResult,
    NoveltyClassification,
    NoveltyResult,
    OverallNoveltyLevel,
    StatisticalNoveltyDetector,
)
from personal_intelligence.core.state import StateFeature, StateRepresentation


class TestStatisticalNoveltyDetector(unittest.TestCase):
    """Test suite for V1 StatisticalNoveltyDetector."""

    def setUp(self) -> None:
        self.detector = StatisticalNoveltyDetector(min_history_samples=3)
        self.base_time = datetime(2026, 8, 21, 14, 0, 0, tzinfo=timezone.utc)

    def _create_state_snapshot(
        self,
        dt: datetime,
        location: str = "office",
        activity: str = "coding",
        event_density: float = 0.5,
        activity_duration: float = 45.0,
        goal_pressure: float = 2.0,
    ) -> StateRepresentation:
        """Helper to construct realistic synthetic historical StateRepresentation snapshots."""
        rep = StateRepresentation(timestamp=dt)
        rep.set_feature("current_location", location, source="test_loc")
        rep.set_feature("current_activity", activity, source="test_act")
        rep.set_feature("event_density", event_density, source="test_density")
        rep.set_feature("recent_activity_duration", activity_duration, source="test_dur")
        rep.set_feature("goal_pressure", {"pressure_score": goal_pressure}, source="test_goal")
        return rep

    # --- 1. Normal State Test ---

    def test_normal_state(self) -> None:
        """Verify normal state evaluation when current values align with historical baselines."""
        # 10 historical snapshots with density ~0.5 (std ~0.05), duration ~45, location='office'
        history = [
            self._create_state_snapshot(
                self.base_time - timedelta(days=i),
                location="office",
                activity="coding",
                event_density=0.5 + (0.02 if i % 2 == 0 else -0.02),
                activity_duration=45.0 + (2.0 if i % 2 == 0 else -2.0),
                goal_pressure=2.0,
            )
            for i in range(1, 11)
        ]

        current = self._create_state_snapshot(
            self.base_time,
            location="office",
            activity="coding",
            event_density=0.51,
            activity_duration=46.0,
            goal_pressure=2.0,
        )

        res = self.detector.detect(current, history)

        self.assertEqual(res.overall_level, OverallNoveltyLevel.NORMAL.value)
        self.assertEqual(len(res.get_anomalous_features()), 0)
        for feat_res in res.feature_results:
            self.assertEqual(feat_res.classification, NoveltyClassification.NORMAL.value)

    # --- 2. One Anomalous Feature Test ---

    def test_one_anomalous_feature(self) -> None:
        """Verify detection when exactly one numerical feature diverges significantly (|z| >= 2.0)."""
        # Baseline density: mean=0.5, std ~ 0.05
        history = [
            self._create_state_snapshot(
                self.base_time - timedelta(hours=i),
                location="office",
                activity="coding",
                event_density=0.5 + (0.05 if i % 2 == 0 else -0.05),
                activity_duration=30.0,
            )
            for i in range(1, 11)
        ]

        # Current state has an extreme event density spike (3.5 events/min, |z| > 50)
        current = self._create_state_snapshot(
            self.base_time,
            location="office",
            activity="coding",
            event_density=3.5,  # Extreme spike
            activity_duration=30.0,
        )

        res = self.detector.detect(current, history)

        self.assertEqual(res.overall_level, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)
        anomalies = res.get_anomalous_features()
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0].feature, "event_density")
        self.assertEqual(anomalies[0].classification, NoveltyClassification.HIGHLY_UNUSUAL.value)
        self.assertGreaterEqual(anomalies[0].deviation, 2.0)

    # --- 3. Multiple Anomalous Features Test ---

    def test_multiple_anomalous_features(self) -> None:
        """Verify detection when multiple features deviate simultaneously."""
        history = [
            self._create_state_snapshot(
                self.base_time - timedelta(hours=i),
                location="home",
                activity="resting",
                event_density=0.2 + (0.02 if i % 2 == 0 else -0.02),
                activity_duration=20.0 + (1.0 if i % 2 == 0 else -1.0),
                goal_pressure=1.0,
            )
            for i in range(1, 11)
        ]

        # Deviations in density, duration, and goal pressure
        current = self._create_state_snapshot(
            self.base_time,
            location="home",
            activity="resting",
            event_density=1.2,  # Large spike
            activity_duration=180.0,  # Prolonged duration
            goal_pressure=10.0,  # Goal pressure surge
        )

        res = self.detector.detect(current, history)

        self.assertIn(res.overall_level, (OverallNoveltyLevel.HIGHLY_UNUSUAL.value, OverallNoveltyLevel.NOVEL_COMBINATION.value))

        anomalous_names = {f.feature for f in res.get_anomalous_features()}
        self.assertIn("event_density", anomalous_names)
        self.assertIn("recent_activity_duration", anomalous_names)
        self.assertIn("goal_pressure", anomalous_names)

    # --- 4. Missing History / Cold-Start Test ---

    def test_missing_history_cold_start(self) -> None:
        """Verify safe handling when history is empty or smaller than min_history_samples."""
        current = self._create_state_snapshot(self.base_time, event_density=99.0)

        # Empty history
        res_empty = self.detector.detect(current, history=[])
        self.assertEqual(res_empty.overall_level, OverallNoveltyLevel.NORMAL.value)
        self.assertTrue(res_empty.metadata["cold_start"])
        self.assertEqual(len(res_empty.get_anomalous_features()), 0)

        # 1 historical item (< min_history_samples of 3)
        h1 = [self._create_state_snapshot(self.base_time - timedelta(hours=1))]
        res_one = self.detector.detect(current, history=h1)
        self.assertEqual(res_one.overall_level, OverallNoveltyLevel.NORMAL.value)
        self.assertTrue(res_one.metadata["cold_start"])

    # --- 5. Zero Variance Test ---

    def test_zero_variance_handling(self) -> None:
        """Verify zero variance handling: constant values are normal, changes are highly unusual."""
        # 5 identical historical snapshots with exactly 0.5 density (std = 0.0)
        history = [
            self._create_state_snapshot(
                self.base_time - timedelta(hours=i),
                event_density=0.5,
            )
            for i in range(1, 6)
        ]

        # Case A: Current value matches exact zero-variance constant
        curr_match = self._create_state_snapshot(self.base_time, event_density=0.5)
        res_match = self.detector.detect(curr_match, history)
        feat_match = [f for f in res_match.feature_results if f.feature == "event_density"][0]
        self.assertEqual(feat_match.classification, NoveltyClassification.NORMAL.value)
        self.assertEqual(feat_match.deviation, 0.0)

        # Case B: Current value differs from zero-variance constant
        curr_diff = self._create_state_snapshot(self.base_time, event_density=0.6)
        res_diff = self.detector.detect(curr_diff, history)
        feat_diff = [f for f in res_diff.feature_results if f.feature == "event_density"][0]
        self.assertEqual(feat_diff.classification, NoveltyClassification.HIGHLY_UNUSUAL.value)
        self.assertEqual(res_diff.overall_level, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)

    # --- 6. Categorical Novelty Test ---

    def test_categorical_novelty(self) -> None:
        """Verify detection of unseen or rare categorical state dimensions."""
        # History exclusively at 'home' and 'office'
        history = [
            self._create_state_snapshot(
                self.base_time - timedelta(days=i),
                location="office" if i % 2 == 0 else "home",
                activity="coding",
            )
            for i in range(1, 11)
        ]

        # Current location is an unseen airport lounge
        current = self._create_state_snapshot(
            self.base_time,
            location="airport_terminal_3",
            activity="coding",
        )

        res = self.detector.detect(current, history)

        self.assertEqual(res.overall_level, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)
        loc_res = [f for f in res.feature_results if f.feature == "current_location"][0]
        self.assertEqual(loc_res.classification, NoveltyClassification.HIGHLY_UNUSUAL.value)
        self.assertEqual(loc_res.deviation, 1.0)  # 100% rarity

    def test_summary_and_serialization(self) -> None:
        """Verify to_dict and to_compact_summary representations."""
        history = [
            self._create_state_snapshot(self.base_time - timedelta(hours=i), event_density=0.5)
            for i in range(1, 6)
        ]
        current = self._create_state_snapshot(self.base_time, event_density=2.5)

        res = self.detector.detect(current, history)
        d = res.to_dict()
        self.assertIn("overall_level", d)
        self.assertIn("feature_results", d)
        self.assertEqual(d["overall_level"], "HIGHLY_UNUSUAL")

        summary = res.to_compact_summary()
        self.assertIn("HIGHLY_UNUSUAL", summary)
        self.assertIn("event_density", summary)


if __name__ == "__main__":
    unittest.main()
