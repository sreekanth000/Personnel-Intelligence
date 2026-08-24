"""
Tests for NoveltyEngine Deterministic V1 Architecture Refactoring.

Verifies:
1. Numerical feature deviation (z-score across configurable baseline windows)
2. Categorical rarity (empirical frequency tracking)
3. Event velocity deviation (event rate vs historical velocity distribution)
4. Event silence/deviation (inactivity gap vs historical inter-arrival distribution)
5. Historical state similarity and NOVEL_COMBINATION detection
6. NOVEL_COMBINATION creates a NOVEL_SITUATION candidate
7. Hermes reasoning can conclude 'insufficient evidence' without forced interpretations
"""

from datetime import datetime, timedelta, timezone
import json
import unittest

from personal_intelligence.core.events.models import Event, Observation
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.novelty.detector import (
    NoveltyEngine,
    StatisticalNoveltyDetector,
)
from personal_intelligence.core.novelty.models import (
    FeatureNoveltyResult,
    NoveltyClassification,
    NoveltyResult,
    OverallNoveltyLevel,
)
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.models import (
    Situation,
    SituationPriority,
    StandardSituationCategory,
)
from personal_intelligence.core.state.models import StateFeature, StateRepresentation


class TestNoveltyEngineRefactor(unittest.TestCase):
    """Test suite for deterministic V1 NoveltyEngine capabilities."""

    def setUp(self) -> None:
        self.engine = NoveltyEngine()
        self.base_time = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

    # -------------------------------------------------------------------------
    # 1. Numerical feature deviation & baseline windows
    # -------------------------------------------------------------------------

    def test_numerical_feature_z_score_and_windows(self) -> None:
        """Verifies exact z-score computation and baseline window filtering."""
        # 14 days of historical sleep: mean = 480 mins, std = 20 mins
        history: list[StateRepresentation] = []
        for i in range(14, 0, -1):
            t = self.base_time - timedelta(days=i)
            # alternating 460, 480, 500 -> mean 480, std ~16.3
            val = 480.0 + ((i % 3) - 1) * 20.0
            history.append(
                StateRepresentation(
                    timestamp=t,
                    features={
                        "sleep_duration_mins": StateFeature(
                            name="sleep_duration_mins",
                            value=val,
                            source="sleep_tracker",
                            timestamp=t,
                        )
                    },
                )
            )

        # Case A: Normal value (485 mins, z < 1.0) -> NORMAL
        normal_state = StateRepresentation(
            timestamp=self.base_time,
            features={
                "sleep_duration_mins": StateFeature(
                    name="sleep_duration_mins",
                    value=485.0,
                    source="sleep_tracker",
                    timestamp=self.base_time,
                )
            },
        )
        res_normal = self.engine.detect(normal_state, history)
        self.assertEqual(res_normal.overall_level, OverallNoveltyLevel.NORMAL.value)
        feat_res = res_normal.feature_results[0]
        self.assertLess(feat_res.deviation, 1.0)
        self.assertEqual(feat_res.classification, NoveltyClassification.NORMAL.value)

        # Case B: Severe deviation (225 mins, z > 10.0) -> HIGHLY_UNUSUAL
        deviated_state = StateRepresentation(
            timestamp=self.base_time,
            features={
                "sleep_duration_mins": StateFeature(
                    name="sleep_duration_mins",
                    value=225.0,
                    source="sleep_tracker",
                    timestamp=self.base_time,
                )
            },
        )
        res_deviated = self.engine.detect(deviated_state, history)
        self.assertEqual(res_deviated.overall_level, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)
        feat_res_dev = res_deviated.feature_results[0]
        self.assertGreater(feat_res_dev.deviation, 2.5)
        self.assertEqual(feat_res_dev.classification, NoveltyClassification.HIGHLY_UNUSUAL.value)

        # Case C: Baseline window filtering (limit to last 5 days)
        windowed_engine = NoveltyEngine(baseline_window_days=5)
        res_windowed = windowed_engine.detect(deviated_state, history)
        self.assertEqual(res_windowed.metadata["history_count"], 5)

    # -------------------------------------------------------------------------
    # 2. Categorical rarity
    # -------------------------------------------------------------------------

    def test_categorical_rarity_detection(self) -> None:
        """Verifies empirical frequency tracking for common vs rare vs unseen categories."""
        # 10 historical snapshots: 8 "office", 2 "home", 0 "airport"
        history: list[StateRepresentation] = []
        for i in range(10, 0, -1):
            t = self.base_time - timedelta(days=i)
            loc = "home" if i in (1, 2) else "office"
            history.append(
                StateRepresentation(
                    timestamp=t,
                    features={
                        "primary_work_location": StateFeature(
                            name="primary_work_location",
                            value=loc,
                            source="location_manager",
                            timestamp=t,
                        )
                    },
                )
            )

        # Common value "office" (80%) -> NORMAL
        res_common = self.engine.detect(
            StateRepresentation(
                timestamp=self.base_time,
                features={"primary_work_location": StateFeature(name="primary_work_location", value="office", source="location", timestamp=self.base_time)},
            ),
            history,
        )
        self.assertEqual(res_common.feature_results[0].classification, NoveltyClassification.NORMAL.value)

        # Rare value "home" (20% <= rare threshold of 20% or unseen) -> NORMAL or UNUSUAL
        engine_rare = NoveltyEngine(categorical_rare_threshold=0.25)
        res_rare = engine_rare.detect(
            StateRepresentation(
                timestamp=self.base_time,
                features={"primary_work_location": StateFeature(name="primary_work_location", value="home", source="location", timestamp=self.base_time)},
            ),
            history,
        )
        self.assertEqual(res_rare.feature_results[0].classification, NoveltyClassification.UNUSUAL.value)

        # Unseen value "airport" (0%) -> HIGHLY_UNUSUAL
        res_unseen = self.engine.detect(
            StateRepresentation(
                timestamp=self.base_time,
                features={"primary_work_location": StateFeature(name="primary_work_location", value="airport", source="location", timestamp=self.base_time)},
            ),
            history,
        )
        self.assertEqual(res_unseen.feature_results[0].classification, NoveltyClassification.HIGHLY_UNUSUAL.value)
        self.assertIn("never been observed", res_unseen.feature_results[0].explanation)

    # -------------------------------------------------------------------------
    # 3. Event velocity deviation
    # -------------------------------------------------------------------------

    def test_event_velocity_deviation(self) -> None:
        """Verifies rate surge detection against historical velocity distribution."""
        # 10 historical snapshots: message velocity mean = 5.0 msgs/hr, std = 1.0
        history: list[StateRepresentation] = []
        for i in range(10, 0, -1):
            t = self.base_time - timedelta(hours=i)
            history.append(
                StateRepresentation(
                    timestamp=t,
                    features={
                        "message_velocity_hourly": StateFeature(
                            name="message_velocity_hourly",
                            value=5.0 + ((i % 3) - 1) * 1.0,
                            source="communication_stream",
                            timestamp=t,
                        )
                    },
                )
            )

        # Velocity surge (35.0 msgs/hr, ~30 sigma)
        surge_state = StateRepresentation(
            timestamp=self.base_time,
            features={
                "message_velocity_hourly": StateFeature(
                    name="message_velocity_hourly",
                    value=35.0,
                    source="communication_stream",
                    timestamp=self.base_time,
                )
            },
        )
        res_surge = self.engine.detect(surge_state, history)
        self.assertEqual(res_surge.overall_level, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)
        feat_res = res_surge.feature_results[0]
        self.assertEqual(feat_res.classification, NoveltyClassification.HIGHLY_UNUSUAL.value)
        self.assertIn("velocity surge", feat_res.explanation.lower())

    # -------------------------------------------------------------------------
    # 4. Event silence/inactivity deviation
    # -------------------------------------------------------------------------

    def test_event_silence_deviation(self) -> None:
        """Verifies abnormal inactivity/silence gap detection."""
        # 10 historical snapshots: silence gap between updates mean = 2.0 hrs, std = 0.5 hrs
        history: list[StateRepresentation] = []
        for i in range(10, 0, -1):
            t = self.base_time - timedelta(days=i)
            history.append(
                StateRepresentation(
                    timestamp=t,
                    features={
                        "silence_duration_hours": StateFeature(
                            name="silence_duration_hours",
                            value=2.0 + ((i % 3) - 1) * 0.4,
                            source="activity_tracker",
                            timestamp=t,
                        )
                    },
                )
            )

        # Abnormal silence (18.0 hours without update, > 25 sigma)
        silence_state = StateRepresentation(
            timestamp=self.base_time,
            features={
                "silence_duration_hours": StateFeature(
                    name="silence_duration_hours",
                    value=18.0,
                    source="activity_tracker",
                    timestamp=self.base_time,
                )
            },
        )
        res_silence = self.engine.detect(silence_state, history)
        self.assertEqual(res_silence.overall_level, OverallNoveltyLevel.HIGHLY_UNUSUAL.value)
        feat_res = res_silence.feature_results[0]
        self.assertEqual(feat_res.classification, NoveltyClassification.HIGHLY_UNUSUAL.value)
        self.assertIn("abnormal inactivity/silence", feat_res.explanation.lower())

    # -------------------------------------------------------------------------
    # 5. Historical state similarity & NOVEL_COMBINATION
    # -------------------------------------------------------------------------

    def test_historical_state_similarity_and_novel_combination(self) -> None:
        """
        Verifies that when individual features may not be completely unseen,
        an unobserved joint combination across multiple dimensions produces NOVEL_COMBINATION.
        """
        # Baseline history has 2 canonical modes:
        # Mode A: (location: "office", workload: "high" (8.0), meeting_count: 5.0)
        # Mode B: (location: "home", workload: "low" (2.0), meeting_count: 0.0)
        history: list[StateRepresentation] = []
        for i in range(10):
            t = self.base_time - timedelta(days=i + 1)
            is_office = i % 2 == 0
            history.append(
                StateRepresentation(
                    timestamp=t,
                    features={
                        "location": StateFeature(name="location", value="office" if is_office else "home", source="loc", timestamp=t),
                        "workload_score": StateFeature(name="workload_score", value=8.0 if is_office else 2.0, source="work", timestamp=t),
                        "meeting_count": StateFeature(name="meeting_count", value=5.0 if is_office else 0.0, source="cal", timestamp=t),
                    },
                )
            )

        # Novel combination: (location: "home", workload: 14.0, meeting_count: 12.0)
        # High workload + high meeting count at home is an unfamiliar combination never observed together
        novel_state = StateRepresentation(
            timestamp=self.base_time,
            features={
                "location": StateFeature(name="location", value="home", source="loc", timestamp=self.base_time),
                "workload_score": StateFeature(name="workload_score", value=14.0, source="work", timestamp=self.base_time),
                "meeting_count": StateFeature(name="meeting_count", value=12.0, source="cal", timestamp=self.base_time),
            },
        )

        res_comb = self.engine.detect(novel_state, history)
        self.assertEqual(res_comb.overall_level, OverallNoveltyLevel.NOVEL_COMBINATION.value)
        self.assertTrue(res_comb.metadata["is_novel_combination"])
        self.assertEqual(res_comb.metadata["similar_state_count"], 0)

    # -------------------------------------------------------------------------
    # 6. NOVEL_COMBINATION creates a NOVEL_SITUATION candidate
    # -------------------------------------------------------------------------

    def test_novel_combination_creates_novel_situation_candidate(self) -> None:
        """
        Verifies that when NoveltyResult produces NOVEL_COMBINATION,
        SituationEngine generates a NOVEL_SITUATION candidate.
        """
        sit_engine = SituationEngine()
        novel_state = StateRepresentation(
            timestamp=self.base_time,
            features={
                "domain_alpha_metric": StateFeature(name="domain_alpha_metric", value=9.5, source="sys_a", timestamp=self.base_time),
                "domain_beta_metric": StateFeature(name="domain_beta_metric", value=18.2, source="sys_b", timestamp=self.base_time),
            },
        )

        novelty_result = NoveltyResult(
            overall_level=OverallNoveltyLevel.NOVEL_COMBINATION,
            metadata={"min_state_distance": 0.85, "is_novel_combination": True},
        )

        eval_result = sit_engine.evaluate(
            current_state=novel_state,
            novelty_result=novelty_result,
            reference_time=self.base_time,
        )

        types = [s.type for s in eval_result.candidate_situations]
        self.assertIn("novel_situation", types)
        novel_sit = next(s for s in eval_result.candidate_situations if s.type == "novel_situation")
        self.assertEqual(novel_sit.priority, SituationPriority.HIGH.value)
        self.assertTrue(novel_sit.information_required)
        self.assertIn("novel_situation", novel_sit.context.get("category", ""))

    # -------------------------------------------------------------------------
    # 7. Hermes reasoning can conclude 'insufficient evidence'
    # -------------------------------------------------------------------------

    def test_hermes_insufficient_evidence_preservation(self) -> None:
        """
        Verifies that Hermes is permitted to conclude 'insufficient evidence' on novel states
        without forcing an ungrounded interpretation.
        """
        from personal_intelligence.hermes_bridge.reasoning import (
            ActionabilityLevel,
            EvidenceStrength,
            StructuredReasoningSynthesis,
            UrgencyLevel,
        )

        synthesis = StructuredReasoningSynthesis(
            what_is_happening="An anomalous multi-domain state was observed, but external context is insufficient to determine cause.",
            evidence_summary=["Telemetry reading recorded (telemetry:node-7)"],
            inferences=["Insufficient evidence to confirm whether this represents a scheduled maintenance or an issue."],
            predictions=["No immediate disruption predicted pending clarification."],
            recommendations=["Observe for next 2 hours without user interruption."],
            uncertainties=["Underlying operational intent is unknown."],
            urgency=UrgencyLevel.LOW.value,
            actionability=ActionabilityLevel.LOW.value,
            evidence_strength=EvidenceStrength.INSUFFICIENT_EVIDENCE.value,
        )

        self.assertEqual(synthesis.evidence_strength, "insufficient_evidence")
        self.assertIn("insufficient evidence", synthesis.inferences[0].lower())
        self.assertEqual(synthesis.urgency, "low")
        self.assertEqual(synthesis.actionability, "low")

        self.assertIn("insufficient evidence", synthesis.inferences[0].lower())
        self.assertEqual(synthesis.urgency, "low")


if __name__ == "__main__":
    unittest.main()
