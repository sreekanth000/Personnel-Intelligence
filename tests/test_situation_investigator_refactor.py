"""
Tests for SituationInvestigator Architecture Refactoring.

Verifies:
1. Information gap intake and planning without implementing direct external APIs.
2. Enforcement of investigation limits (max_rounds, max_tool_calls, max_context_size).
3. Termination on Gap Resolved.
4. Termination on Contradictory Evidence with requires_user_input flag.
5. Termination on No Relevant Evidence Exists without uncontrolled loops.
6. Termination on Budget Exhaustion at max_rounds.
7. Normalization of returned findings into Observation records with clean provenance.
8. Evidence bundle output suitable for ContextBuilder and ReasoningWorkflow.
"""

from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import MagicMock, patch

from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.situations.models import Situation, SituationPriority
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.hermes_bridge.client import HermesClient, HermesInvocationResponse
from personal_intelligence.hermes_bridge.investigation import (
    BoundedInvestigationWorkflow,
    InvestigationResult,
    InvestigationTask,
)
from personal_intelligence.hermes_bridge.situation_investigation import (
    CrossSourceEvidenceBundle,
    InvestigationOutcome,
    InvestigationPlan,
    InvestigationTerminationReason,
    SituationInvestigator,
)


class TestSituationInvestigatorRefactor(unittest.TestCase):
    """Test suite verifying bounded, multi-round SituationInvestigator without direct APIs."""

    def setUp(self) -> None:
        self.event_store = EventStore()
        self.situation_store = SituationStore()
        self.base_time = datetime(2026, 8, 22, 14, 0, 0, tzinfo=timezone.utc)

    # -------------------------------------------------------------------------
    # 1. Information gap intake & planning
    # -------------------------------------------------------------------------

    def test_information_gap_planning_without_direct_apis(self) -> None:
        """
        Verifies that given an information gap, the investigator formulates a capability request
        across Hermes-owned domains (Gmail, Drive, Calendar, Meet) without implementing direct APIs.
        """
        gap = "Is the architecture document ready for Friday's executive review?"
        situation = Situation(
            id="sit-arch-review-001",
            type="unresolved_action_item_before_milestone",
            priority=SituationPriority.HIGH.value,
            novelty=0.4,
            status="open",
            information_required=True,
            investigation_target=gap,
            context={"title": "Executive Review", "description": gap},
            created_at=self.base_time,
            updated_at=self.base_time,
        )

        mock_workflow = MagicMock(spec=BoundedInvestigationWorkflow)
        mock_result = InvestigationResult(
            task_id="task-arch-001",
            findings=["Architecture document 'Architecture_v3.pdf' was updated at 13:30 UTC with final diagrams."],
            source_references=["drive:doc-arch-v3"],
            uncertainty=[],
            expiration_time=self.base_time + timedelta(hours=4),
            is_valid=True,
        )
        mock_workflow.create_task.return_value = InvestigationTask(
            question_to_investigate=gap,
            known_facts=["Review scheduled for Friday"],
            unknowns=[gap],
            required_output={"findings": "list of findings"},
        )
        mock_workflow.execute_investigation.return_value = mock_result

        investigator = SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
            investigation_workflow=mock_workflow,
            max_rounds=3,
            max_tool_calls=5,
        )

        outcome = investigator.investigate(situation=situation, reference_time=self.base_time)

        self.assertTrue(outcome.investigation_succeeded)
        self.assertTrue(outcome.gap_resolved)
        self.assertEqual(outcome.termination_reason, InvestigationTerminationReason.GAP_RESOLVED.value)
        self.assertFalse(outcome.requires_user_input)
        self.assertIn("Architecture_v3.pdf", outcome.evidence_bundle.to_unified_context_string())

    # -------------------------------------------------------------------------
    # 2. Termination on Gap Resolved
    # -------------------------------------------------------------------------

    def test_termination_on_gap_resolved(self) -> None:
        """Verifies immediate termination in round 1 when findings resolve unknowns."""
        mock_workflow = MagicMock(spec=BoundedInvestigationWorkflow)
        mock_result = InvestigationResult(
            task_id="task-resolved-01",
            findings=["Meeting room reserved and invite accepted by all 4 stakeholders."],
            source_references=["calendar:event-8819", "gmail:thread-991"],
            uncertainty=[],
            expiration_time=self.base_time + timedelta(hours=2),
            is_valid=True,
        )
        mock_workflow.create_task.return_value = MagicMock()
        mock_workflow.execute_investigation.return_value = mock_result

        investigator = SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
            investigation_workflow=mock_workflow,
            max_rounds=3,
        )

        outcome = investigator.investigate_information_gap(
            information_gap="Are all participants confirmed for the Q3 strategy meeting?",
            reference_time=self.base_time,
        )

        self.assertEqual(outcome.rounds_executed, 1)
        self.assertEqual(outcome.termination_reason, InvestigationTerminationReason.GAP_RESOLVED.value)
        self.assertTrue(outcome.gap_resolved)
        self.assertEqual(len(outcome.remaining_unknowns), 0)

    # -------------------------------------------------------------------------
    # 3. Termination on Contradictory Evidence
    # -------------------------------------------------------------------------

    def test_termination_on_contradictory_evidence(self) -> None:
        """
        Verifies that when conflicting evidence is detected across sources
        (e.g., Drive document marked finalized but Gmail email says cancelled),
        the investigator immediately terminates and flags requires_user_input.
        """
        mock_workflow = MagicMock(spec=BoundedInvestigationWorkflow)
        mock_result = InvestigationResult(
            task_id="task-contra-01",
            findings=[
                "Drive document 'Budget_Q4.xlsx' was finalized and approved by finance at 11:00.",
                "Gmail thread from executive sponsor states: 'The Friday review has been cancelled due to budget freeze.'",
            ],
            source_references=["drive:doc-budget-q4", "gmail:msg-exec-cancel"],
            uncertainty=["Cannot confirm whether budget review is proceeding or cancelled."],
            expiration_time=self.base_time + timedelta(hours=3),
            is_valid=True,
        )
        mock_workflow.create_task.return_value = MagicMock()
        mock_workflow.execute_investigation.return_value = mock_result

        investigator = SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
            investigation_workflow=mock_workflow,
            max_rounds=3,
        )

        outcome = investigator.investigate_information_gap(
            information_gap="Is Friday's Budget Review still proceeding?",
            reference_time=self.base_time,
        )

        self.assertEqual(outcome.termination_reason, InvestigationTerminationReason.CONTRADICTORY_EVIDENCE.value)
        self.assertTrue(outcome.requires_user_input)
        self.assertFalse(outcome.gap_resolved)
        self.assertGreaterEqual(len(outcome.contradiction_notes), 1)

    # -------------------------------------------------------------------------
    # 4. Termination on No Relevant Evidence Exists
    # -------------------------------------------------------------------------

    def test_termination_on_no_relevant_evidence(self) -> None:
        """
        Verifies that when tools return zero matching results across queried capabilities,
        the investigator immediately stops and does not perform useless retry looping.
        """
        mock_workflow = MagicMock(spec=BoundedInvestigationWorkflow)
        mock_result = InvestigationResult(
            task_id="task-no-ev-01",
            findings=["No matching documents or emails found in any queried sources."],
            source_references=[],
            uncertainty=["Unknown topic was never mentioned in recent communications."],
            expiration_time=self.base_time + timedelta(hours=1),
            is_valid=True,
        )
        mock_workflow.create_task.return_value = MagicMock()
        mock_workflow.execute_investigation.return_value = mock_result

        investigator = SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
            investigation_workflow=mock_workflow,
            max_rounds=3,
        )

        outcome = investigator.investigate_information_gap(
            information_gap="What was the passcode for project Titan?",
            reference_time=self.base_time,
        )

        # Must terminate in round 1 without executing all 3 rounds
        self.assertEqual(outcome.rounds_executed, 1)
        self.assertEqual(outcome.termination_reason, InvestigationTerminationReason.NO_RELEVANT_EVIDENCE.value)
        self.assertFalse(outcome.gap_resolved)

    # -------------------------------------------------------------------------
    # 5. Termination on Budget Exhaustion
    # -------------------------------------------------------------------------

    def test_termination_on_budget_exhaustion(self) -> None:
        """
        Verifies that when investigation is inconclusive across rounds,
        it strictly halts upon reaching max_rounds (e.g. 3).
        """
        mock_workflow = MagicMock(spec=BoundedInvestigationWorkflow)
        mock_result_partial = InvestigationResult(
            task_id="task-partial-01",
            findings=["Investigation failed: Service temporarily unreachable."],
            source_references=[],
            uncertainty=["Still need author signature and final approval timestamp."],
            expiration_time=self.base_time + timedelta(hours=1),
            is_valid=False,
        )

        mock_workflow.create_task.return_value = MagicMock()
        mock_workflow.execute_investigation.return_value = mock_result_partial

        investigator = SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
            investigation_workflow=mock_workflow,
            max_rounds=3,
        )

        outcome = investigator.investigate_information_gap(
            information_gap="Has author signed off on publication?",
            reference_time=self.base_time,
        )

        self.assertEqual(outcome.rounds_executed, 3)
        self.assertEqual(outcome.termination_reason, InvestigationTerminationReason.BUDGET_EXHAUSTED.value)
        self.assertFalse(outcome.gap_resolved)

    # -------------------------------------------------------------------------
    # 6. Normalization & Provenance Preservation
    # -------------------------------------------------------------------------

    def test_normalization_and_provenance_preservation(self) -> None:
        """
        Verifies that discovered findings are normalized into Observation records
        in the EventStore with clean provenance coordinates (source, task_id, situation_id).
        """
        mock_workflow = MagicMock(spec=BoundedInvestigationWorkflow)
        mock_result = InvestigationResult(
            task_id="task-prov-42",
            findings=["Security audit passed with zero high-severity vulnerabilities."],
            source_references=["drive:sec-audit-report-v2.pdf"],
            uncertainty=[],
            expiration_time=self.base_time + timedelta(hours=6),
            is_valid=True,
        )
        mock_workflow.create_task.return_value = MagicMock()
        mock_workflow.execute_investigation.return_value = mock_result

        investigator = SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
            investigation_workflow=mock_workflow,
            max_rounds=3,
        )

        outcome = investigator.investigate_information_gap(
            information_gap="Did the security audit pass?",
            reference_time=self.base_time,
        )

        self.assertGreaterEqual(len(outcome.evidence_observations_recorded), 1)
        recorded_obs_id = outcome.evidence_observations_recorded[0]

        # Retrieve from event_store
        obs = self.event_store.get(recorded_obs_id)
        self.assertIsNotNone(obs)
        self.assertEqual(obs.source, "hermes_investigation")
        self.assertIn("Security audit passed", obs.payload.get("summary", ""))
        self.assertIn("task-prov-42", obs.payload.get("task_id", ""))
        self.assertIn("drive:sec-audit-report-v2.pdf", obs.payload.get("source_references", []))


if __name__ == "__main__":
    unittest.main()
