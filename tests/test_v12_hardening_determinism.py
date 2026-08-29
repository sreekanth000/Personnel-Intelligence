"""
Unit and Integration Tests for V1.2 Determinism & Data-Model Hardening.

Verifies:
  1. Deterministic Evidence Strength & Independent Sources (lineage grouping)
  2. Commitment Data Model as Graph Entities (entities.entity_type='commitment')
  3. Investigation Exhaustion State (INVESTIGATION_INCOMPLETE outcome & policy handling)
  4. Deterministic Pattern Lifecycle Transitions & Non-Causal Semantics
  5. Deterministic Situation Deduplication & Situation Freshness
  6. Deterministic Intervention Decision Table (decide_intervention pure function)
"""

from datetime import datetime, timedelta, timezone
import unittest
import uuid

from personal_intelligence.core.evidence_strength import (
    EvidenceStrengthCalculator,
    EvidenceStrengthLevel,
    extract_evidence_group_key,
)
from personal_intelligence.core.patterns.engine import PatternEngine
from personal_intelligence.core.patterns.models import (
    Pattern,
    PatternStatus,
    PatternType,
)
from personal_intelligence.core.policy.engine import (
    InterventionPolicyEngine,
    decide_intervention,
)
from personal_intelligence.core.policy.models import (
    InvestigationStatus,
    PolicyAction,
    SituationFreshness,
    UserContext,
)
from personal_intelligence.core.situations.lifecycle import SituationLifecycleManager
from personal_intelligence.core.situations.models import (
    Situation,
    SituationPriority,
    SituationStatus,
    compute_deterministic_situation_identity,
)
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.world.graph import EntityGraphStore, EntityNode
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.core.world.models import (
    Commitment,
    CommitmentStatus,
    FactProvenance,
)
from personal_intelligence.hermes_bridge.situation_investigation import (
    CrossSourceEvidenceBundle,
    InvestigationOutcome,
    InvestigationPlan,
    InvestigationTerminationReason,
)
from personal_intelligence.storage.db import DatabaseManager


class TestV12HardeningDeterminism(unittest.TestCase):
    """Comprehensive test suite for V1.2 determinism and data-model hardening."""

    def setUp(self) -> None:
        self.db_manager = DatabaseManager(db_path=":memory:")
        self.db_manager.initialize_schema()
        self.now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)
        self.evidence_calc = EvidenceStrengthCalculator()

    # -------------------------------------------------------------------------
    # 1. EVIDENCE INDEPENDENCE & PROVENANCE LINEAGE TESTS
    # -------------------------------------------------------------------------

    def test_same_gmail_thread_counted_once(self) -> None:
        """Two observations from the same Gmail thread/source belong to 1 evidence group -> WEAK."""
        obs1 = {
            "source": "gmail",
            "source_id": "msg_001",
            "thread_id": "thread_abc",
            "content": "Meeting moved to 3pm",
        }
        obs2 = {
            "source": "gmail",
            "source_id": "msg_002",
            "thread_id": "thread_abc",
            "content": "Follow up on 3pm meeting",
        }
        strength = self.evidence_calc.calculate([obs1, obs2], reference_time=self.now)
        self.assertEqual(strength, EvidenceStrengthLevel.WEAK)

    def test_gmail_and_calendar_same_origin_counted_once(self) -> None:
        """A Calendar event auto-generated from a Gmail message shares origin -> 1 group -> WEAK."""
        obs_gmail = {
            "source": "gmail",
            "source_id": "msg_001",
            "origin_event_id": "msg_001",
            "content": "Flight confirmation UA123",
        }
        obs_cal = {
            "source": "calendar",
            "source_id": "cal_evt_999",
            "origin_event_id": "msg_001",  # Same origin event
            "content": "Flight UA123 automatically added",
        }
        strength = self.evidence_calc.calculate([obs_gmail, obs_cal], reference_time=self.now)
        self.assertEqual(strength, EvidenceStrengthLevel.WEAK)

    def test_independent_gmail_and_calendar_counted_twice(self) -> None:
        """Independent Gmail and Calendar observations form 2 groups -> MODERATE."""
        obs_gmail = {
            "source": "gmail",
            "source_id": "msg_001",
            "content": "Client email requesting status call",
        }
        obs_cal = {
            "source": "calendar",
            "source_id": "cal_evt_101",
            "content": "Independently scheduled status call",
        }
        strength = self.evidence_calc.calculate([obs_gmail, obs_cal], reference_time=self.now)
        self.assertEqual(strength, EvidenceStrengthLevel.MODERATE)

    def test_three_independent_sources_produce_strong(self) -> None:
        """Three distinct independent channels (Gmail + Calendar + Drive) -> STRONG."""
        obs1 = {"source": "gmail", "source_id": "msg_1", "content": "Proposal submission note"}
        obs2 = {"source": "calendar", "source_id": "cal_1", "content": "Deadline block on calendar"}
        obs3 = {"source": "drive", "source_id": "doc_1", "content": "Proposal v2.pdf modified timestamp"}

        strength = self.evidence_calc.calculate([obs1, obs2, obs3], reference_time=self.now)
        self.assertEqual(strength, EvidenceStrengthLevel.STRONG)

    def test_contradictory_sources_produce_conflicted(self) -> None:
        """Materially contradictory observations -> CONFLICTED."""
        obs_supporting = {"source": "calendar", "source_id": "cal_1", "content": "Meeting confirmed"}
        obs_contradicting = {"source": "gmail", "source_id": "msg_1", "content": "Meeting cancelled", "contradicts": True}

        strength = self.evidence_calc.calculate([obs_supporting, obs_contradicting], reference_time=self.now)
        self.assertEqual(strength, EvidenceStrengthLevel.CONFLICTED)

    # -------------------------------------------------------------------------
    # 2. COMMITMENT DATA MODEL TESTS
    # -------------------------------------------------------------------------

    def test_commitment_entity_creation_and_graph_relationships(self) -> None:
        """Commitment is created as entity (entity_type='commitment') and queried via graph without separate table."""
        world_model = PersonalWorldModel(db_manager=self.db_manager)
        due_date = self.now + timedelta(days=2)

        commitment = world_model.record_commitment(
            description="Deliver architecture hardening specification",
            due_at=due_date,
            status=CommitmentStatus.OPEN.value,
            metadata={"goal_id": "goal_arch_v1", "priority": "high"},
            provenance=FactProvenance(origin_source="gmail", source_id="msg_task_01"),
        )

        self.assertIsInstance(commitment, Commitment)
        self.assertEqual(commitment.entity_type, "commitment")
        self.assertEqual(commitment.status, CommitmentStatus.OPEN.value)

        # Query commitments from graph store
        graph_store = EntityGraphStore(db_manager=self.db_manager)
        commitments = graph_store.get_commitments(status=CommitmentStatus.OPEN.value)
        self.assertEqual(len(commitments), 1)
        self.assertEqual(commitments[0]["name"], "Deliver architecture hardening specification")

        # Verify graph edges: USER -> owns -> COMMITMENT and COMMITMENT -> supports -> GOAL
        user_node = graph_store.get_node("user_primary")
        self.assertIsNotNone(user_node)
        neighbors = graph_store.get_neighbors("user_primary", depth=1)
        self.assertTrue(any(rel == "owns" and target.entity_type == "commitment" for _, rel, target in neighbors))

    def test_commitment_status_transitions(self) -> None:
        """Commitment transitions OPEN -> IN_PROGRESS -> COMPLETED without silent LLM mutation."""
        world_model = PersonalWorldModel(db_manager=self.db_manager)
        commit = world_model.record_commitment(description="Submit quarterly report")

        # Transition to COMPLETED
        updated = world_model.resolve_commitment(commit.id, status=CommitmentStatus.COMPLETED.value)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, CommitmentStatus.COMPLETED.value)

        # Verify in graph store
        graph_store = EntityGraphStore(db_manager=self.db_manager)
        completed_commits = graph_store.get_commitments(status=CommitmentStatus.COMPLETED.value)
        self.assertEqual(len(completed_commits), 1)

    # -------------------------------------------------------------------------
    # 3. INVESTIGATION EXHAUSTION TESTS
    # -------------------------------------------------------------------------

    def test_investigation_exhaustion_outcome_and_policy(self) -> None:
        """Investigation reaching budget exhaustion produces INCOMPLETE and defers consequential situations."""
        plan = InvestigationPlan(
            situation_id="sit_001",
            situation_type="unresolved_commitment",
            investigation_target="Check client reply status",
            unknowns=["Has client confirmed acceptance?"],
        )
        bundle = CrossSourceEvidenceBundle(
            situation_id="sit_001",
            situation_type="unresolved_commitment",
            situation_summary="Client proposal reply pending",
            remaining_unknowns=["Has client confirmed acceptance?"],
        )
        sit = Situation(type="unresolved_commitment", id="sit_001")

        outcome = InvestigationOutcome(
            situation=sit,
            plan=plan,
            investigation_result=None,
            evidence_bundle=bundle,
            evidence_observations_recorded=[],
            episode=None,
            investigation_succeeded=True,
            gap_resolved=False,
            remaining_unknowns=["Has client confirmed acceptance?"],
            rounds_executed=3,
            total_tool_calls=5,
            termination_reason=InvestigationTerminationReason.BUDGET_EXHAUSTED.value,
            investigation_status="INCOMPLETE",
        )

        self.assertEqual(outcome.investigation_status, "INCOMPLETE")
        self.assertIn("Has client confirmed acceptance?", outcome.remaining_unknowns)

        # Policy: Consequential situation with INCOMPLETE investigation -> DEFER
        policy_res = decide_intervention(
            urgency="high",
            actionability="high",
            evidence_strength="weak",
            attention_state="available",
            investigation_status=outcome.investigation_status,
        )
        self.assertEqual(policy_res.action, PolicyAction.DEFER.value)

        # Policy: Low consequence with INCOMPLETE investigation -> SUPPRESS or BRIEFING
        policy_low = decide_intervention(
            urgency="low",
            actionability="low",
            evidence_strength="weak",
            attention_state="available",
            investigation_status=outcome.investigation_status,
        )
        self.assertEqual(policy_low.action, PolicyAction.SUPPRESS.value)

    # -------------------------------------------------------------------------
    # 4. DETERMINISTIC PATTERN LIFECYCLE TESTS
    # -------------------------------------------------------------------------

    def test_pattern_lifecycle_transitions(self) -> None:
        """Tests complete deterministic 7-stage lifecycle transitions and thresholds."""
        engine = PatternEngine()

        # 1. OBSERVED -> HYPOTHESIS on initial observation
        p = Pattern(
            id="pat_01",
            pattern_type=PatternType.BEHAVIORAL_PATTERN.value,
            description="User appears to review PRs in morning",
            first_seen=self.now,
            last_seen=self.now,
            support_count=1,
            contradiction_count=0,
            status=PatternStatus.OBSERVED.value,
        )
        st, _ = engine.evaluate_progression(p, as_of=self.now)
        self.assertEqual(st, PatternStatus.HYPOTHESIS)

        # 2. HYPOTHESIS -> EMERGING (support >= 3, span >= 7d, contra < 50%)
        p.support_count = 3
        p.first_seen = self.now - timedelta(days=8)
        p.last_seen = self.now
        st, _ = engine.evaluate_progression(p, as_of=self.now)
        self.assertEqual(st, PatternStatus.EMERGING)

        # 3. EMERGING -> SUPPORTED (support >= 6, span >= 21d, contra < 20%)
        p.support_count = 6
        p.contradiction_count = 1
        p.first_seen = self.now - timedelta(days=22)
        p.last_seen = self.now
        st, _ = engine.evaluate_progression(p, as_of=self.now)
        self.assertEqual(st, PatternStatus.SUPPORTED)

        # 4. SUPPORTED -> ACTIVE (support >= 10, span >= 45d, contra < 20%, recent evidence <= 14d)
        #    time_span = last_seen - first_seen, so need span >= 45d
        p.support_count = 10
        p.contradiction_count = 1
        p.first_seen = self.now - timedelta(days=48)
        p.last_seen = self.now - timedelta(days=2)
        st, _ = engine.evaluate_progression(p, as_of=self.now)
        self.assertEqual(st, PatternStatus.ACTIVE)

        # 5. ACTIVE -> DECAYING (no evidence for >= 60d)
        p.last_seen = self.now - timedelta(days=65)
        p.status = PatternStatus.ACTIVE.value
        st, _ = engine.evaluate_progression(p, as_of=self.now)
        self.assertEqual(st, PatternStatus.DECAYING)

        # 6. DECAYING -> INACTIVE (no evidence for >= 120d)
        p.last_seen = self.now - timedelta(days=125)
        p.status = PatternStatus.DECAYING.value
        st, _ = engine.evaluate_progression(p, as_of=self.now)
        self.assertEqual(st, PatternStatus.INACTIVE)

        # 7. DECAYING -> ACTIVE (recovery on fresh support)
        p.last_seen = self.now - timedelta(days=1)
        p.status = PatternStatus.DECAYING.value
        st, _ = engine.evaluate_progression(p, as_of=self.now)
        self.assertEqual(st, PatternStatus.ACTIVE)

    # -------------------------------------------------------------------------
    # 5. SITUATION DEDUPLICATION & FRESHNESS TESTS
    # -------------------------------------------------------------------------

    def test_deterministic_situation_identity_and_deduplication(self) -> None:
        """Deterministic identity prevents duplicate situation creation and updates existing on material change."""
        sit_store = SituationStore(db_manager=self.db_manager)
        lifecycle = SituationLifecycleManager(situation_store=sit_store, db_manager=self.db_manager)

        id1 = compute_deterministic_situation_identity(
            situation_type="unresolved_commitment",
            primary_entity_ids=["proj_a", "client_bob"],
            goal_ids=["goal_launch"],
            trigger_origin_ids=["msg_001"],
        )
        id2 = compute_deterministic_situation_identity(
            situation_type="unresolved_commitment",
            primary_entity_ids=["client_bob", "proj_a"],  # Order permutation
            goal_ids=["goal_launch"],
            trigger_origin_ids=["msg_001"],
        )
        self.assertEqual(id1, id2)  # Invariant: Sorted order guarantees identical SHA256

        # Register situation
        sit_candidate = Situation(
            type="unresolved_commitment",
            priority=SituationPriority.HIGH.value,
            context={"primary_entity_ids": ["proj_a"], "trigger_origin_ids": ["msg_001"]},
            evidence=["msg_001"],
            related_goals=["goal_launch"],
        )
        sit_reg, is_new = lifecycle.register_or_update(sit_candidate)
        self.assertTrue(is_new)

        # Re-register exact duplicate -> Returns existing without duplicate creation
        sit_dup, is_new_dup = lifecycle.register_or_update(sit_candidate)
        self.assertFalse(is_new_dup)
        self.assertEqual(sit_reg.id, sit_dup.id)

        # Same situation with material new evidence -> Updates existing situation
        sit_updated_candidate = Situation(
            type="unresolved_commitment",
            priority=SituationPriority.CRITICAL.value,
            context={"primary_entity_ids": ["proj_a"], "trigger_origin_ids": ["msg_001"]},
            evidence=["msg_001", "msg_002_deadline_changed"],
            related_goals=["goal_launch"],
        )
        sit_merged, is_new_merged = lifecycle.register_or_update(sit_updated_candidate)
        self.assertFalse(is_new_merged)
        self.assertEqual(sit_merged.id, sit_reg.id)
        self.assertIn("msg_002_deadline_changed", sit_merged.evidence)

    def test_situation_freshness_computation(self) -> None:
        """Calculates FRESH (<=24h), AGING (24h-7d), and STALE (>7d)."""
        sit = Situation(type="unresolved_commitment")

        # FRESH (updated just now)
        sit.updated_at = self.now - timedelta(hours=5)
        self.assertEqual(sit.compute_freshness(as_of=self.now), SituationFreshness.FRESH)

        # AGING (updated 3 days ago)
        sit.updated_at = self.now - timedelta(days=3)
        self.assertEqual(sit.compute_freshness(as_of=self.now), SituationFreshness.AGING)

        # STALE (updated 10 days ago)
        sit.updated_at = self.now - timedelta(days=10)
        self.assertEqual(sit.compute_freshness(as_of=self.now), SituationFreshness.STALE)

    # -------------------------------------------------------------------------
    # 6. DETERMINISTIC INTERVENTION DECISION FUNCTION TESTS
    # -------------------------------------------------------------------------

    def test_decide_intervention_full_matrix(self) -> None:
        """Tests pure deterministic decide_intervention across all precedence rules."""
        # 1. Situation resolved -> DISCARD
        res = decide_intervention(urgency="critical", situation_status="resolved")
        self.assertEqual(res.action, PolicyAction.DISCARD.value)

        # 2. Duplicate / already notified -> DISCARD
        res = decide_intervention(urgency="high", recently_notified=True)
        self.assertEqual(res.action, PolicyAction.DISCARD.value)

        # 3. Evidence conflicted on consequential situation -> DEFER
        res = decide_intervention(urgency="high", evidence_strength="conflicted")
        self.assertEqual(res.action, PolicyAction.DEFER.value)

        # 3b. Evidence conflicted on low urgency situation -> SUPPRESS
        res = decide_intervention(urgency="low", evidence_strength="conflicted")
        self.assertEqual(res.action, PolicyAction.SUPPRESS.value)

        # 4. Critical urgency + Available -> INTERRUPT
        res = decide_intervention(urgency="critical", attention_state="available", evidence_strength="strong")
        self.assertEqual(res.action, PolicyAction.INTERRUPT.value)

        # 4b. Critical urgency + Deep Work (without bypass) -> DEFER
        res = decide_intervention(urgency="critical", attention_state="deep_work", critical_bypass_dnd=False)
        self.assertEqual(res.action, PolicyAction.DEFER.value)

        # 4c. Critical urgency + Deep Work (with bypass) -> INTERRUPT
        res = decide_intervention(urgency="critical", attention_state="deep_work", critical_bypass_dnd=True)
        self.assertEqual(res.action, PolicyAction.INTERRUPT.value)

        # 5. High urgency + Actionable + Strong evidence + Available -> INTERRUPT
        res = decide_intervention(urgency="high", actionability="high", evidence_strength="strong", attention_state="available")
        self.assertEqual(res.action, PolicyAction.INTERRUPT.value)

        # 5b. High urgency + Meeting -> DEFER
        res = decide_intervention(urgency="high", actionability="high", evidence_strength="strong", attention_state="meeting")
        self.assertEqual(res.action, PolicyAction.DEFER.value)

        # 6. Medium urgency + Available -> BRIEFING
        res = decide_intervention(urgency="medium", actionability="high", attention_state="available")
        self.assertEqual(res.action, PolicyAction.BRIEFING.value)

        # 6b. Medium urgency + Deep Work -> DEFER
        res = decide_intervention(urgency="medium", actionability="high", attention_state="deep_work")
        self.assertEqual(res.action, PolicyAction.DEFER.value)

        # 7. Low urgency + Actionable + Fresh -> BRIEFING
        res = decide_intervention(urgency="low", actionability="high", freshness="fresh", attention_state="available")
        self.assertEqual(res.action, PolicyAction.BRIEFING.value)

        # 8. Stale situation -> DISCARD
        res = decide_intervention(urgency="medium", freshness="stale")
        self.assertEqual(res.action, PolicyAction.DISCARD.value)

        # 9. Recently dismissed -> SUPPRESS
        res = decide_intervention(urgency="high", recently_dismissed=True)
        self.assertEqual(res.action, PolicyAction.SUPPRESS.value)


if __name__ == "__main__":
    unittest.main()
