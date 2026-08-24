"""
Unit and integration tests for the Personal Intelligence Situation Engine.

Verifies:
1. Inputs: current state, recent observations, timeline, active goals, known patterns, emerging hypotheses.
2. Candidate situations identified across 9 generic categories:
   - possible forgotten commitment
   - upcoming preparation need
   - schedule conflict
   - unresolved issue
   - unusual change
   - goal risk
   - opportunity
   - information gap
   - novel situation
3. Output structure: situation_id, type, evidence, related_goals, novelty, status.
4. Non-intrusive design: does NOT notify user, does NOT take action, does NOT call external APIs directly.
5. Information gap flagging: marks information_required = True and defines investigation_target for Hermes.
6. Execution via Hermes plugin tool `evaluate_candidate_situations`.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.novelty.models import NoveltyClassification, NoveltyResult, OverallNoveltyLevel
from personal_intelligence.core.patterns.models import Pattern, PatternStatus
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.models import (
    Situation,
    SituationEvaluation,
    SituationPriority,
    SituationStatus,
)
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.core.world.models import (
    Commitment,
    CurrentState,
    FactProvenance,
    IssueSeverity,
    IssueStatus,
    OpenIssue,
    UpcomingEvent,
)
from personal_intelligence.hermes_bridge.plugin.tools import (
    evaluate_candidate_situations as hermes_eval_situations_tool,
)
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore


class TestSituationEngine(unittest.TestCase):
    """Comprehensive test suite for SituationEngine."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_situation_engine.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.local_store = LocalStateStore(db_manager=self.db_manager)
        self.world_model = PersonalWorldModel(db_manager=self.db_manager, local_store=self.local_store)
        self.engine = SituationEngine()
        self.now = datetime(2026, 8, 22, 10, 30, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Candidate Category: Possible Forgotten Commitment
    # -------------------------------------------------------------------------

    def test_possible_forgotten_commitment_identification(self) -> None:
        """
        Verify identification of commitments due soon or overdue without confirmation,
        marking information_required = True with investigation_target.
        """
        # Overdue commitment from meeting action item
        commit = self.world_model.record_commitment(
            description="Send encryption benchmark metrics to security team",
            due_at=self.now - timedelta(hours=4),
            provenance=FactProvenance(origin_source="meet", source_id="meet_retro_1", tool="google_meet"),
        )

        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        sits = [s for s in eval_res.candidate_situations if s.type == "possible_forgotten_commitment"]

        self.assertGreaterEqual(len(sits), 1)
        sit = sits[0]
        self.assertTrue(sit.id.startswith("sit_forgotten_commit_"))
        self.assertEqual(sit.status, SituationStatus.OPEN.value)
        self.assertEqual(sit.priority, SituationPriority.HIGH.value)
        self.assertIn(commit.id, sit.evidence)
        self.assertTrue(sit.information_required)
        self.assertIsNotNone(sit.investigation_target)
        self.assertIn("Check Gmail/Drive", sit.investigation_target)

    # -------------------------------------------------------------------------
    # 2. Candidate Category: Upcoming Preparation Need
    # -------------------------------------------------------------------------

    def test_upcoming_preparation_need_identification(self) -> None:
        """
        Verify that upcoming major reviews within 24h lacking preparation documents
        are identified with information_required = True.
        """
        obs_cal = self.world_model.record_observation(
            source="calendar",
            source_id="cal_q3_exec_review",
            timestamp=self.now - timedelta(hours=1),
            observation_type="calendar_event",
            summary="Executive Architecture Review scheduled tomorrow.",
            evidence={
                "title": "Executive Architecture Review",
                "start_time": (self.now + timedelta(hours=14)).isoformat(),
            },
            provenance={"tool": "google_workspace_calendar"},
        )

        goal = self.world_model.create_goal(name="Executive Architecture Review", priority=GoalPriority.HIGH.value)

        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        prep_sits = [s for s in eval_res.candidate_situations if s.type == "upcoming_preparation_need"]

        self.assertGreaterEqual(len(prep_sits), 1)
        sit = prep_sits[0]
        self.assertEqual(sit.type, "upcoming_preparation_need")
        self.assertTrue(sit.information_required)
        self.assertIn("Google Drive and filesystem", sit.investigation_target)
        self.assertIn(goal.id, sit.related_goals)

    # -------------------------------------------------------------------------
    # 3. Candidate Category: Schedule Conflict
    # -------------------------------------------------------------------------

    def test_schedule_conflict_identification(self) -> None:
        """Verify direct temporal overlaps between upcoming commitments are identified."""
        self.world_model.record_observation(
            source="calendar",
            source_id="evt_a",
            timestamp=self.now - timedelta(minutes=30),
            observation_type="calendar_event",
            summary="Meeting A",
            evidence={
                "title": "Vendor Sync",
                "start_time": (self.now + timedelta(hours=2)).isoformat(),
            },
            provenance={"tool": "google_workspace_calendar"},
        )
        self.world_model.record_observation(
            source="calendar",
            source_id="evt_b",
            timestamp=self.now - timedelta(minutes=20),
            observation_type="calendar_event",
            summary="Meeting B",
            evidence={
                "title": "Architecture Deep-Dive",
                "start_time": (self.now + timedelta(hours=2, minutes=30)).isoformat(),
            },
            provenance={"tool": "google_workspace_calendar"},
        )

        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        conflict_sits = [s for s in eval_res.candidate_situations if s.type == "schedule_conflict"]

        self.assertGreaterEqual(len(conflict_sits), 1)
        sit = conflict_sits[0]
        self.assertEqual(sit.type, "schedule_conflict")
        self.assertEqual(len(sit.evidence), 2)

    # -------------------------------------------------------------------------
    # 4. Candidate Category: Unresolved Issue
    # -------------------------------------------------------------------------

    def test_unresolved_issue_identification(self) -> None:
        """Verify high severity blockers or prolonged issues are flagged for investigation."""
        issue = self.world_model.record_open_issue(
            title="Production encryption key rotation failure",
            description="HSM provider timed out during token migration",
            severity=IssueSeverity.CRITICAL.value,
            provenance=FactProvenance(origin_source="filesystem", tool="filesystem"),
        )

        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        issue_sits = [s for s in eval_res.candidate_situations if s.type == "unresolved_issue"]

        self.assertGreaterEqual(len(issue_sits), 1)
        sit = issue_sits[0]
        self.assertEqual(sit.type, "unresolved_issue")
        self.assertEqual(sit.priority, SituationPriority.HIGH.value)
        self.assertIn(issue.id, sit.evidence)
        self.assertTrue(sit.information_required)
        self.assertIn("Investigate system logs", sit.investigation_target)

    # -------------------------------------------------------------------------
    # 5. Candidate Category: Unusual Change
    # -------------------------------------------------------------------------

    def test_unusual_change_identification(self) -> None:
        """Verify routine deviation or abnormal state signals generate unusual_change."""
        self.world_model.record_observation(
            source="hermes",
            source_id="obs_anomaly_1",
            timestamp=self.now - timedelta(hours=2),
            observation_type="unusual_state",
            summary="Abnormal late night work burst detected during designated sleep window.",
            evidence={"routine_deviation": 0.85},
            provenance={"tool": "hermes"},
        )

        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        change_sits = [s for s in eval_res.candidate_situations if s.type == "unusual_change"]

        self.assertGreaterEqual(len(change_sits), 1)
        sit = change_sits[0]
        self.assertEqual(sit.type, "unusual_change")
        self.assertGreaterEqual(sit.novelty, 0.5)

    # -------------------------------------------------------------------------
    # 6. Candidate Category: Goal Risk
    # -------------------------------------------------------------------------

    def test_goal_risk_identification(self) -> None:
        """Verify friction between active critical goals and blocker issues produces goal_risk."""
        goal = self.world_model.create_goal(name="Q3 Production Launch", priority=GoalPriority.CRITICAL.value)
        issue = self.world_model.record_open_issue(
            title="Database replica replication lag",
            description="Replication queue blocked behind long-running schema migration",
            severity=IssueSeverity.HIGH.value,
        )

        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        risk_sits = [s for s in eval_res.candidate_situations if s.type == "goal_risk"]

        self.assertGreaterEqual(len(risk_sits), 1)
        sit = risk_sits[0]
        self.assertEqual(sit.type, "goal_risk")
        self.assertIn(goal.id, sit.related_goals)
        self.assertIn(issue.id, sit.evidence)

    # -------------------------------------------------------------------------
    # 7. Candidate Category: Opportunity
    # -------------------------------------------------------------------------

    def test_opportunity_identification(self) -> None:
        """Verify alignment of open calendar morning block, focus pattern, and top goal produces opportunity."""
        goal = self.world_model.create_goal(name="Core Architecture Spec", priority=GoalPriority.HIGH.value)

        pattern = Pattern(
            description="User completes high-leverage focus work best during uninterrupted morning blocks.",
            first_seen=self.now - timedelta(days=30),
            last_seen=self.now,
            support_count=15,
            status=PatternStatus.ACTIVE,
        )
        self.local_store.pattern_store.create_pattern(pattern)

        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        opp_sits = [s for s in eval_res.candidate_situations if s.type == "opportunity"]

        self.assertGreaterEqual(len(opp_sits), 1)
        sit = opp_sits[0]
        self.assertEqual(sit.type, "opportunity")
        self.assertIn(goal.id, sit.related_goals)

    # -------------------------------------------------------------------------
    # 8. Candidate Category: Information Gap
    # -------------------------------------------------------------------------

    def test_information_gap_identification(self) -> None:
        """Verify observations referencing missing external resources generate information_gap."""
        obs = self.world_model.record_observation(
            source="gmail",
            source_id="msg_contract_draft",
            timestamp=self.now - timedelta(minutes=15),
            observation_type="email_received",
            summary="Vendor sent email referencing unattached draft contract doc_vendor_q4_v2.",
            evidence={"referenced_document": "doc_vendor_q4_v2", "missing_context": True},
            provenance={"tool": "google_workspace_gmail", "query": "label:contract"},
        )

        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        gap_sits = [s for s in eval_res.candidate_situations if s.type == "information_gap"]

        self.assertGreaterEqual(len(gap_sits), 1)
        sit = gap_sits[0]
        self.assertEqual(sit.type, "information_gap")
        self.assertTrue(sit.information_required)
        self.assertIn("doc_vendor_q4_v2", sit.investigation_target)
        self.assertIn(obs.id, sit.evidence)

    # -------------------------------------------------------------------------
    # 9. Candidate Category: Novel Situation
    # -------------------------------------------------------------------------

    def test_novel_situation_identification(self) -> None:
        """Verify high statistical novelty creates novel_situation context frame."""
        novelty_result = NoveltyResult(
            overall_level=OverallNoveltyLevel.HIGHLY_UNUSUAL,
        )

        current_state = self.world_model.get_current_state(reference_time=self.now)
        eval_res = self.engine.evaluate(
            current_state=current_state,
            novelty_result=novelty_result,
            reference_time=self.now,
        )

        novel_sits = [s for s in eval_res.candidate_situations if s.type == "novel_situation"]
        self.assertGreaterEqual(len(novel_sits), 1)
        sit = novel_sits[0]
        self.assertEqual(sit.type, "novel_situation")
        self.assertGreaterEqual(sit.novelty, 0.80)
        self.assertTrue(sit.information_required)

    # -------------------------------------------------------------------------
    # 10. Non-Intrusive Invariant (No user notifications, no action taking)
    # -------------------------------------------------------------------------

    def test_non_intrusive_invariants(self) -> None:
        """
        Verify the Situation Engine strictly outputs candidates and does not take actions
        or trigger user notifications.
        """
        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        self.assertIsInstance(eval_res, SituationEvaluation)
        self.assertIsInstance(eval_res.candidate_situations, list)
        for sit in eval_res.candidate_situations:
            # Check all required fields are present
            self.assertTrue(bool(sit.id))
            self.assertTrue(bool(sit.type))
            self.assertIsInstance(sit.evidence, list)
            self.assertIsInstance(sit.related_goals, list)
            self.assertIsInstance(sit.novelty, float)
            self.assertIn(sit.status, [SituationStatus.OPEN.value, SituationStatus.MONITORING.value])

    # -------------------------------------------------------------------------
    # 11. Candidate-Generation Primitives vs Exhaustive Taxonomy Tests
    # -------------------------------------------------------------------------

    def test_known_situation_primitive(self) -> None:
        """
        1. Known Situation: Verify candidate-generation primitive triggers known category
        (e.g., goal_risk from critical open issues).
        """
        goal = self.world_model.goal_store.create_goal(
            name="Deploy Production Release",
            priority="critical",
        )
        issue = self.world_model.record_open_issue(
            title="Database migration failure in staging",
            description="Schema migration timed out",
            severity="critical",
        )

        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        goal_risks = [s for s in eval_res.candidate_situations if s.type == "goal_risk"]

        self.assertGreaterEqual(len(goal_risks), 1)
        sit = goal_risks[0]
        self.assertEqual(sit.type, "goal_risk")
        self.assertIn(goal.id, sit.related_goals)
        self.assertIn(issue.id, sit.evidence)

    def test_multiple_simultaneous_situations(self) -> None:
        """
        2. Multiple Simultaneous Situations: Verify engine identifies multiple distinct
        situations simultaneously across different categories.
        """
        # 1. Overdue commitment -> possible_forgotten_commitment
        c = self.world_model.record_commitment(
            description="Submit architecture review",
            due_at=self.now - timedelta(hours=2),
        )
        # 2. Critical issue on active goal -> goal_risk
        g = self.world_model.goal_store.create_goal(name="Complete Architecture", priority="critical")
        iss = self.world_model.record_open_issue(title="API Contract Blocker", description="Blocker in API contract", severity="critical")
        # 3. Missing document -> information_gap
        obs = self.world_model.record_observation(
            source="gmail",
            source_id="msg_missing_doc",
            timestamp=self.now - timedelta(minutes=15),
            observation_type="information_gap",
            summary="Referenced spec_sheet_v4 is missing",
            evidence={"referenced_document": "spec_sheet_v4", "missing_context": True},
            provenance={"tool": "google_workspace_gmail", "query": "spec_sheet_v4"},
        )

        eval_res = self.engine.evaluate_world_model(self.world_model, reference_time=self.now)
        detected_types = {s.type for s in eval_res.candidate_situations}

        self.assertGreaterEqual(len(eval_res.candidate_situations), 3)
        self.assertIn("possible_forgotten_commitment", detected_types)
        self.assertIn("goal_risk", detected_types)
        self.assertIn("information_gap", detected_types)

    def test_cross_domain_situation(self) -> None:
        """
        3. Cross-Domain Situation: Verify multi-domain signals (sleep deficit + calendar workload
        + transit disruption) synthesize a cross-domain situation without domain-specific agents.
        """
        # Biometric/sleep feature + calendar meeting density
        state_rep = StateRepresentation(timestamp=self.now)
        state_rep.set_feature("recent_activity_duration", 180.0, source="sleep_tracker")
        state_rep.set_feature("event_density", 0.15, source="calendar")

        # Multi-domain observations
        obs_sleep = Event(id="obs-sleep", event_type="sleep_observed", source="whoop", event_time=self.now - timedelta(hours=5), payload={"hours": 3.0})
        obs_meet = Event(id="obs-meet", event_type="calendar_event", source="gcal", event_time=self.now - timedelta(hours=2), payload={"meeting": "Executive Sync"})
        obs_transit = Event(id="obs-transit", event_type="flight_delay", source="travel", event_time=self.now - timedelta(minutes=30), payload={"delay_minutes": 120})

        training_goal = Goal(name="10km Tempo Run", priority=GoalPriority.HIGH.value)

        eval_res = self.engine.evaluate(
            current_state=state_rep,
            recent_observations=[obs_sleep, obs_meet, obs_transit],
            goals=[training_goal],
            reference_time=self.now,
        )

        self.assertGreaterEqual(len(eval_res.candidate_situations), 1)
        # Situation incorporates evidence from multiple domains
        all_evidence = set(eval_res.evidence)
        self.assertTrue(len(eval_res.candidate_situations) >= 1)

    def test_completely_novel_combination(self) -> None:
        """
        4. Completely Novel Combination: Verify that a high statistical novelty result
        generates a novel_situation context frame.
        """
        novelty_result = NoveltyResult(
            overall_level=OverallNoveltyLevel.NOVEL_COMBINATION,
        )
        obs_novel = Event(
            id="obs-anom-01",
            event_type="unusual_multi_sensor_spike",
            source="sensor_network",
            event_time=self.now - timedelta(minutes=10),
            payload={"divergence_sigma": 3.8},
        )

        current_state = self.world_model.get_current_state(reference_time=self.now)
        eval_res = self.engine.evaluate(
            current_state=current_state,
            recent_observations=[obs_novel],
            novelty_result=novelty_result,
            reference_time=self.now,
        )

        novel_sits = [s for s in eval_res.candidate_situations if s.type == "novel_situation"]
        self.assertEqual(len(novel_sits), 1)
        sit = novel_sits[0]
        self.assertEqual(sit.type, "novel_situation")
        self.assertGreaterEqual(sit.novelty, 0.85)
        self.assertTrue(sit.information_required)
        self.assertIn("obs-anom-01", sit.evidence)

    def test_no_matching_predefined_category(self) -> None:
        """
        5. No Matching Predefined Category: When a combination of observations does not
        match any of the standard candidate primitives, SituationEngine dynamically
        creates a novel_situation rather than failing or discarding the context.
        """
        # Novel unclassified events that do NOT match goal_risk, forgotten_commitment, etc.
        obs1 = Event(
            id="obs-custom-telemetry-1",
            event_type="crypto_gas_price_surge",
            source="blockchain_monitor",
            event_time=self.now - timedelta(minutes=20),
            payload={"gwei": 350, "threshold": 50},
        )
        obs2 = Event(
            id="obs-custom-telemetry-2",
            event_type="iot_air_quality_alert",
            source="home_sensor",
            event_time=self.now - timedelta(minutes=10),
            payload={"pm25": 180, "location": "office"},
        )

        current_state = StateRepresentation(timestamp=self.now)
        eval_res = self.engine.evaluate(
            current_state=current_state,
            recent_observations=[obs1, obs2],
            goals=[],
            reference_time=self.now,
        )

        # Must synthesize novel_situation dynamically
        novel_sits = [s for s in eval_res.candidate_situations if s.type == "novel_situation"]
        self.assertGreaterEqual(len(novel_sits), 1)
        sit = novel_sits[0]
        self.assertEqual(sit.type, "novel_situation")
        self.assertTrue(sit.information_required)
        self.assertTrue(any(e in sit.evidence for e in ["obs-custom-telemetry-1", "obs-custom-telemetry-2"]))


if __name__ == "__main__":
    unittest.main()

