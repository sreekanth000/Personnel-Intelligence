"""
Tests for SituationEngine Architecture Refactoring.

Proves:
A. Known candidate categories are detected (goal_risk, conflicting_commitments, information_gap, etc.)
B. Multiple categories can coexist simultaneously in a single SituationEvaluation
C. Completely unfamiliar multi-domain combinations produce NOVEL_SITUATION
D. The system does not require a hard-coded rule for the exact novel scenario
"""

from datetime import datetime, timedelta, timezone
import unittest
import uuid

from personal_intelligence.core.events.models import Event, Observation
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.novelty.models import (
    FeatureNoveltyResult,
    NoveltyClassification,
    NoveltyResult,
    OverallNoveltyLevel,
)
from personal_intelligence.core.patterns.models import Pattern

from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.models import (
    Situation,
    SituationEvaluation,
    SituationPriority,
    SituationStatus,
    StandardSituationCategory,
)
from personal_intelligence.core.state.models import StateFeature, StateRepresentation
from personal_intelligence.core.world.models import (
    Commitment,
    CommitmentStatus,
    CurrentState,
    IssueSeverity,
    IssueStatus,
    OpenIssue,
    UpcomingEvent,
)


class TestSituationEngineRefactor(unittest.TestCase):
    """Test suite verifying candidate generator architecture and dynamic novel situation discovery."""

    def setUp(self) -> None:
        self.engine = SituationEngine()
        self.base_time = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

    # -------------------------------------------------------------------------
    # A. Known category is detected
    # -------------------------------------------------------------------------

    def test_known_category_detected_goal_risk(self) -> None:
        """Verifies goal_risk candidate generator detects risk factors for high priority goals."""
        goal = Goal(
            id="goal-ml-deploy",
            name="Deploy Model Pipeline",
            description="Deploy production inference pipeline by end of sprint",
            priority=GoalPriority.CRITICAL.value,
            status=GoalStatus.ACTIVE.value,
        )
        issue = OpenIssue(
            id="issue-gpu-quota",
            description="GPU cluster quota exceeded; builds failing",
            severity=IssueSeverity.CRITICAL.value,
            status=IssueStatus.OPEN.value,
            created_at=self.base_time - timedelta(hours=2),
            updated_at=self.base_time,
        )
        current_state = CurrentState(
            open_issues=[issue],
            timestamp=self.base_time,
        )

        eval_result = self.engine.evaluate(
            current_state=current_state,
            goals=[goal],
            reference_time=self.base_time,
        )

        categories = [s.type for s in eval_result.candidate_situations]
        self.assertIn("goal_risk", categories)
        goal_risk_sit = next(s for s in eval_result.candidate_situations if s.type == "goal_risk")
        self.assertEqual(goal_risk_sit.priority, SituationPriority.HIGH.value)
        self.assertIn("goal-ml-deploy", goal_risk_sit.related_goals)
        self.assertIn("issue-gpu-quota", goal_risk_sit.evidence)

    def test_known_category_detected_information_gap(self) -> None:
        """Verifies information_gap candidate generator detects missing referenced documents."""
        obs = Observation(
            id="obs-doc-ref",
            observation_type="email_received",
            source="gmail",
            source_id="msg-101",
            summary="Client emailed requesting review of attached 'SecurityAuditReport_v2.docx'.",
            structured_data={
                "summary": "Client emailed requesting review of attached 'SecurityAuditReport_v2.docx'.",
                "evidence": {
                    "referenced_document": "SecurityAuditReport_v2.docx",
                    "missing_context": True,
                },
            },
            timestamp=self.base_time - timedelta(minutes=30),
        )

        current_state = CurrentState(timestamp=self.base_time)
        eval_result = self.engine.evaluate(
            current_state=current_state,
            recent_observations=[obs],
            reference_time=self.base_time,
        )

        categories = [s.type for s in eval_result.candidate_situations]
        self.assertIn("information_gap", categories)
        gap_sit = next(s for s in eval_result.candidate_situations if s.type == "information_gap")
        self.assertTrue(gap_sit.information_required)
        self.assertIn("SecurityAuditReport_v2.docx", gap_sit.investigation_target)

    # -------------------------------------------------------------------------
    # B. Multiple categories can coexist
    # -------------------------------------------------------------------------

    def test_multiple_categories_coexist(self) -> None:
        """Verifies that multiple candidate generators can produce situations simultaneously."""
        # 1. Goal + Issue -> Goal Risk
        goal = Goal(
            id="goal-q3-launch",
            name="Q3 Product Launch",
            priority=GoalPriority.HIGH.value,
            status=GoalStatus.ACTIVE.value,
        )
        issue = OpenIssue(
            id="issue-api-latency",
            description="Blocked by third party API latency spike",
            severity=IssueSeverity.HIGH.value,
            status=IssueStatus.OPEN.value,
            created_at=self.base_time - timedelta(hours=1),
            updated_at=self.base_time,
        )

        # 2. Overdue Commitment -> Forgotten Commitment / Action Item
        commit = Commitment(
            id="commit-slides",
            description="Send keynote slide deck to event organizers",
            due_at=self.base_time - timedelta(hours=4),
            status=CommitmentStatus.PENDING.value,
            created_at=self.base_time - timedelta(days=2),
        )

        # 3. Information Gap Observation
        obs = Observation(
            id="obs-missing-spec",
            observation_type="document_changed",
            source="drive",
            summary="Spec updated with missing context",
            structured_data={
                "summary": "Spec updated with missing context",
                "evidence": {"referenced_document": "Database_Schema_v3.pdf"},
            },
            timestamp=self.base_time - timedelta(minutes=15),
        )

        current_state = CurrentState(
            current_commitments=[commit],
            open_issues=[issue],
            timestamp=self.base_time,
        )

        eval_result = self.engine.evaluate(
            current_state=current_state,
            goals=[goal],
            recent_observations=[obs],
            reference_time=self.base_time,
        )

        detected_types = {s.type for s in eval_result.candidate_situations}
        # Verify coexistence of at least 3 distinct situation categories
        self.assertIn("goal_risk", detected_types)
        self.assertTrue(
            "possible_forgotten_commitment" in detected_types
            or "unresolved_action_item_before_milestone" in detected_types
        )
        self.assertIn("information_gap", detected_types)
        self.assertIn("external_dependency_risk", detected_types)
        self.assertGreaterEqual(len(eval_result.candidate_situations), 3)

    # -------------------------------------------------------------------------
    # C. Completely unfamiliar combinations produce novel situations
    # -------------------------------------------------------------------------

    def test_unfamiliar_combinations_produce_novel_situations(self) -> None:
        """
        Verifies that an unclassified multi-domain signal collision with high novelty
        produces NOVEL_SITUATION.
        """
        # Multi-domain features: severe biometric deviation + environmental anomaly
        current_state = StateRepresentation(
            timestamp=self.base_time,
            features={
                "biometric_strain_index": StateFeature(
                    name="biometric_strain_index",
                    value=3.4,  # +3.4 sigma deviation
                    source="wearable",
                    timestamp=self.base_time,
                ),
                "ambient_temperature_fluctuation": StateFeature(
                    name="ambient_temperature_fluctuation",
                    value=2.8,  # +2.8 sigma deviation
                    source="smart_home",
                    timestamp=self.base_time,
                ),
            },
        )

        # Unclassified anomalous observation from unexpected source
        unfamiliar_obs = Observation(
            id="obs-sensor-anomaly-001",
            observation_type="anomaly_detected",
            source="environment",
            source_id="sensor-mesh-88",
            summary="Rapid ambient shift coincides with unexpected physiological response.",
            structured_data={
                "raw_values": {"sensor": "ir_mesh", "state": "irregular"},
                "confidence": 0.9,
            },
            timestamp=self.base_time,
        )

        novelty_res = NoveltyResult(
            overall_level=OverallNoveltyLevel.HIGHLY_UNUSUAL,
            feature_results=[
                FeatureNoveltyResult(
                    feature="biometric_strain_index",
                    current_value=3.4,
                    baseline={"mean": 0.0, "std": 1.0},
                    deviation=3.4,
                    classification=NoveltyClassification.HIGHLY_UNUSUAL,
                    explanation="Significant elevation in strain",
                )
            ],
            metadata={"deviated_features": {"biometric_strain_index": 3.4}},
        )


        eval_result = self.engine.evaluate(
            current_state=current_state,
            recent_observations=[unfamiliar_obs],
            novelty_result=novelty_res,
            reference_time=self.base_time,
        )

        novel_sits = [s for s in eval_result.candidate_situations if s.type == "novel_situation"]
        self.assertGreaterEqual(len(novel_sits), 1)

        novel_sit = novel_sits[0]
        self.assertEqual(novel_sit.type, "novel_situation")
        self.assertEqual(novel_sit.priority, SituationPriority.HIGH.value)
        self.assertGreaterEqual(novel_sit.novelty, 0.70)
        self.assertTrue(novel_sit.information_required)
        self.assertIn("obs-sensor-anomaly-001", novel_sit.evidence)
        self.assertIn("cross_domain_factors", novel_sit.context)

    # -------------------------------------------------------------------------
    # D. Does not require a hardcoded rule for the exact novel scenario
    # -------------------------------------------------------------------------

    def test_dynamic_novel_discovery_without_hardcoded_rules(self) -> None:
        """
        Synthesizes an entirely synthetic, un-modeled scenario:
        e.g., 'telemetry_frequency_shift' across device domain + 'transit_delay_metric'
        interacting simultaneously without any explicit code rule matching these field names.
        """
        current_state = StateRepresentation(
            timestamp=self.base_time,
            features={
                "custom_quantum_telemetry_rate": StateFeature(
                    name="custom_quantum_telemetry_rate",
                    value=4.2,
                    source="experimental_lab",
                    timestamp=self.base_time,
                ),
                "hyper_transit_congestion_sigma": StateFeature(
                    name="hyper_transit_congestion_sigma",
                    value=3.1,
                    source="orbital_transit",
                    timestamp=self.base_time,
                ),
            },
        )

        novel_obs = Observation(
            id="obs-synthetic-novel-42",
            observation_type="unusual_state_collision",
            source="experimental_lab",
            summary="Synthesized non-standard cross-domain state collision.",
            structured_data={"synthetic_field_alpha": 1234, "synthetic_field_beta": "unseen_value"},
            timestamp=self.base_time,
        )

        eval_result = self.engine.evaluate(
            current_state=current_state,
            recent_observations=[novel_obs],
            reference_time=self.base_time,
        )

        # Confirm NOVEL_SITUATION is generated dynamically from the multi-domain feature deviations
        novel_sits = [s for s in eval_result.candidate_situations if s.type == "novel_situation"]
        self.assertTrue(len(novel_sits) >= 1)
        sit = novel_sits[0]
        self.assertEqual(sit.type, "novel_situation")
        self.assertIn("obs-synthetic-novel-42", sit.evidence)
        self.assertIn("contributing_features", sit.context)
        self.assertIn("custom_quantum_telemetry_rate", sit.context["contributing_features"])


if __name__ == "__main__":
    unittest.main()
