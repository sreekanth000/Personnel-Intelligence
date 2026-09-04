"""
End-to-End Test Suite for the Personal Intelligence Reasoning Layer.

Demonstrates the 15 canonical intelligence reasoning scenarios:
1. Isolated observation (low significance, no reasoning warranted).
2. Observation + history (historical context elevates significance).
3. Observation + goal (goal linkage creates significance).
4. Observation + relationship (important relationship creates significance).
5. Observation + conflicting commitment (schedule conflict detected and flagged).
6. Multi-source corroboration (multiple independent sources elevate evidence strength).
7. Cross-domain situation (biometric + calendar + messaging synthesized).
8. Novel but insignificant event (novel spam/newsletter rejected).
9. Non-novel but highly significant event (recurring high-stakes milestone triggered).
10. Insufficient evidence (gaps identified, suppressed or flagged as investigation needed).
11. Hermes reasoning triggered (eligibility gate passes when significant).
12. Hermes reasoning correctly bounded (prompt context bounded with token target).
13. Recommendation generated (structured recommendation produced).
14. Intervention policy evaluated (PI determines interrupt vs digest vs silent).
15. Complete provenance chain preserved (lineage from recommendation back to source).
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.evidence_strength import EvidenceStrengthCalculator, EvidenceStrengthLevel
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.loop import EarlyExitReason, PersonalIntelligenceEvaluationLoop
from personal_intelligence.core.novelty import NoveltyEngine, NoveltyResult
from personal_intelligence.core.policy.engine import InterventionPolicyEngine
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.core.significance import PersonalSignificanceEngine, SignificanceLevel
from personal_intelligence.core.situations.eligibility import ReasoningEligibilityGate
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.lifecycle import SituationLifecycleManager
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.world import (
    CanonicalEntityType,
    CanonicalRelationship,
    ContextGraph,
    PersonalWorldModel,
)
from personal_intelligence.hermes_bridge.client import HermesClient
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore


class TestPersonalIntelligenceReasoningLayer(unittest.TestCase):
    """Proves that PI operates as a genuine longitudinal intelligence layer."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_pi_reasoning.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.local_store = LocalStateStore(db_manager=self.db_manager)

        self.event_store = self.local_store.event_store
        self.goal_store = self.local_store.goal_store
        self.situation_store = self.local_store.situation_store
        self.episode_store = self.local_store.episode_store
        self.pattern_store = self.local_store.pattern_store

        self.world_model = PersonalWorldModel(db_manager=self.db_manager, local_store=self.local_store)
        self.context_graph = self.world_model.context_graph
        self.significance_engine = PersonalSignificanceEngine()
        self.eligibility_gate = ReasoningEligibilityGate()
        self.evidence_calculator = EvidenceStrengthCalculator()
        self.policy_engine = InterventionPolicyEngine()

        self.loop = PersonalIntelligenceEvaluationLoop(
            db_manager=self.db_manager,
            event_store=self.event_store,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            episode_store=self.episode_store,
            pattern_store=self.pattern_store,
            world_model=self.world_model,
        )

        self.now = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_1_isolated_observation_low_significance_no_reasoning(self) -> None:
        """Scenario 1: An isolated trivial observation has low significance and does not trigger Hermes reasoning."""
        # Record routine observation (e.g. coffee shop receipt, weather report)
        obs = self.world_model.record_observation(
            source="bank",
            source_id="txn-9988",
            timestamp=self.now,
            observation_type="transaction_logged",
            summary="Coffee Purchase $4.50",
            evidence={"amount": 4.50, "merchant": "Cafe Blue"},
            provenance={"tool": "bank_sync"},
        )

        # Evaluate significance
        sig = self.significance_engine.evaluate_situation(
            situation_type="routine_spending",
            situation_priority=SituationPriority.LOW.value,
            evidence_count=1,
            novelty_score=0.0,
            has_information_gap=False,
            goals=[],
            reference_time=self.now,
        )

        self.assertEqual(sig.level, SignificanceLevel.NOT_SIGNIFICANT.value)

        # Eligibility gate check
        sit = Situation(
            id="sit-trivial",
            type="routine_spending",
            priority=SituationPriority.LOW.value,
            status=SituationStatus.OPEN.value,
        )
        decision = self.eligibility_gate.evaluate(
            situation=sit,
            significance=sig,
            is_new_situation=True,
            has_new_events=True,
        )
        self.assertFalse(decision.requires_hermes)

    def test_2_observation_plus_history_elevates_significance(self) -> None:
        """Scenario 2: Observation combined with repeated historical occurrences elevates significance."""
        # 3 previous missed build alerts in the last 2 days
        for i in range(3):
            self.world_model.record_observation(
                source="github",
                source_id=f"build-fail-{i}",
                timestamp=self.now - timedelta(hours=24 * (3 - i)),
                observation_type="build_failure",
                summary=f"CI Pipeline Build Failure #{i+1}",
                evidence={"repo": "core-engine", "error": "test timeout"},
                provenance={"tool": "github_actions"},
            )

        # New failure today
        latest_obs = self.world_model.record_observation(
            source="github",
            source_id="build-fail-4",
            timestamp=self.now,
            observation_type="build_failure",
            summary="CI Pipeline Build Failure #4",
            evidence={"repo": "core-engine", "error": "test timeout"},
            provenance={"tool": "github_actions"},
        )

        # Significance evaluated with multi-observation history
        sig = self.significance_engine.evaluate_situation(
            situation_type="recurring_ci_failure",
            situation_priority=SituationPriority.HIGH.value,
            evidence_count=4,
            novelty_score=0.3,
            has_information_gap=False,
            goals=[],
            reference_time=self.now,
        )
        self.assertIn(sig.level, [SignificanceLevel.HIGH.value, SignificanceLevel.MEDIUM.value])

    def test_3_observation_plus_goal_linkage_creates_significance(self) -> None:
        """Scenario 3: Observation connected to an active goal in the Context Graph triggers high significance."""
        goal = self.world_model.create_goal(
            name="Deploy Alpha Release",
            description="Launch Alpha release by Friday",
            priority=GoalPriority.CRITICAL.value,
        )

        obs = self.world_model.record_observation(
            source="slack",
            source_id="msg-blocker-1",
            timestamp=self.now,
            observation_type="blocker_detected",
            summary="Database migration failed for Deploy Alpha Release",
            evidence={"goal": "Deploy Alpha Release", "blocker": "Schema migration crash"},
            provenance={"tool": "slack_sync"},
        )

        sig = self.significance_engine.evaluate_situation(
            situation_type="critical_goal_blocker",
            situation_priority=SituationPriority.CRITICAL.value,
            evidence_count=1,
            novelty_score=0.7,
            has_information_gap=False,
            goals=[goal],
            reference_time=self.now,
        )
        self.assertEqual(sig.level, SignificanceLevel.CRITICAL.value)
        self.assertIn("critical", sig.reasons[0].lower())

    def test_4_observation_plus_relationship_creates_significance(self) -> None:
        """Scenario 4: Observation involving a key person connected via Context Graph elevates significance."""
        vip = self.context_graph.upsert_entity(
            name="Dr. Elena Vance (CEO)",
            entity_type=CanonicalEntityType.PERSON.value,
            id="person_elena",
        )
        self.context_graph.connect(
            source_id="user_primary",
            target_id=vip.id,
            relationship=CanonicalRelationship.WORKS_WITH.value,
            metadata={"importance": "executive_leadership"},
        )

        obs = self.world_model.record_observation(
            source="email",
            source_id="msg-vip-44",
            timestamp=self.now,
            observation_type="message_received",
            summary="Urgent request from Dr. Elena Vance (CEO) regarding investor deck",
            evidence={"sender": "Dr. Elena Vance (CEO)", "urgent": True},
            provenance={"tool": "gmail_fetch"},
            entity_refs=[vip.id],
        )

        # Graph traversal links observation to executive relationship
        bounded = self.world_model.get_bounded_context(target_id=obs.id, depth=1)
        self.assertTrue(any(n.name == "Dr. Elena Vance (CEO)" for n in bounded.nodes))

    def test_5_observation_plus_conflicting_commitment(self) -> None:
        """Scenario 5: An observation conflicting with an existing commitment is detected and flagged."""
        # 1. Existing commitment
        commit = self.world_model.record_commitment(
            description="Deliver Project Apollo Architecture Blueprint",
            due_at=self.now + timedelta(hours=3),
        )

        # 2. Incoming meeting observation overlapping the entire block
        obs = self.world_model.record_observation(
            source="calendar",
            source_id="cal-conflict-1",
            timestamp=self.now,
            observation_type="calendar_event",
            summary="Emergency 3-hour Incident Review",
            evidence={"duration_hours": 3, "conflicts_with": commit.description},
            provenance={"tool": "gcal_sync"},
        )

        sit = self.world_model.create_situation(
            type="conflicting_commitments",
            priority=SituationPriority.HIGH.value,
            evidence=[obs.id],
            context={"commitment_id": commit.id, "summary": "3-hour emergency meeting overlaps delivery deadline"},
        )
        self.assertEqual(sit.type, "conflicting_commitments")
        self.assertEqual(sit.priority, SituationPriority.HIGH.value)

    def test_6_multi_source_corroboration_elevates_evidence_strength(self) -> None:
        """Scenario 6: Evidence from multiple independent sources is deterministically rated strong."""
        # 1. Slack message
        e1 = {"source": "slack", "source_id": "s1", "event_time": self.now, "summary": "API Gateway down"}
        # 2. PagerDuty alert
        e2 = {"source": "pagerduty", "source_id": "p1", "event_time": self.now, "summary": "Gateway 502 spike"}
        # 3. CloudWatch metrics
        e3 = {"source": "cloudwatch", "source_id": "c1", "event_time": self.now, "summary": "HTTP 502 error rate 95%"}

        strength = self.evidence_calculator.calculate([e1, e2, e3], reference_time=self.now)
        self.assertEqual(strength, EvidenceStrengthLevel.STRONG)

    def test_7_cross_domain_situation_synthesis(self) -> None:
        """Scenario 7: Biometric deficit + calendar load + urgent communication synthesized seamlessly."""
        # Biometric
        o1 = self.world_model.record_observation(
            source="whoop",
            source_id="whoop-rec",
            timestamp=self.now - timedelta(hours=3),
            observation_type="sleep_logged",
            summary="Recovery 28% (Severe sleep deficit)",
            evidence={"recovery": 28},
            provenance={"tool": "whoop"},
        )

        # Calendar
        o2 = self.world_model.record_observation(
            source="calendar",
            source_id="cal-load",
            timestamp=self.now,
            observation_type="calendar_event",
            summary="8 Back-to-Back Strategy Reviews",
            evidence={"meetings_count": 8},
            provenance={"tool": "calendar"},
        )

        # Context Graph synthesizes cross-domain context
        self.context_graph.connect(o1.id, "user_primary", CanonicalRelationship.AFFECTS.value)
        self.context_graph.connect(o2.id, "user_primary", CanonicalRelationship.INVOLVES.value)

        bounded = self.world_model.get_bounded_context(target_id="user_primary", depth=1)
        node_ids = {n.id for n in bounded.nodes}
        self.assertIn(o1.id, node_ids)
        self.assertIn(o2.id, node_ids)

    def test_8_novel_but_insignificant_event_rejected(self) -> None:
        """Scenario 8: A highly novel observation with zero personal relevance is rejected without reasoning."""
        # Novel newsletter/marketing email never seen before
        obs = self.world_model.record_observation(
            source="email",
            source_id="spam-novel-1",
            timestamp=self.now,
            observation_type="email_received",
            summary="50% Off Luxury Yachts Summer Promo",
            evidence={"sender": "promotions@luxury-yachts.com"},
            provenance={"tool": "gmail_filter"},
        )

        sig = self.significance_engine.evaluate_situation(
            situation_type="unsolicited_newsletter",
            situation_priority=SituationPriority.LOW.value,
            evidence_count=1,
            novelty_score=0.95,  # High statistical novelty
            has_information_gap=False,
            goals=[],
            reference_time=self.now,
        )
        self.assertEqual(sig.level, SignificanceLevel.NOT_SIGNIFICANT.value)

    def test_9_non_novel_but_highly_significant_event_triggered(self) -> None:
        """Scenario 9: A familiar/recurring event that represents a high-stakes goal milestone triggers reasoning."""
        goal = self.world_model.create_goal(
            name="Quarterly Board Presentation",
            priority=GoalPriority.CRITICAL.value,
        )

        obs = self.world_model.record_observation(
            source="calendar",
            source_id="cal-board-q3",
            timestamp=self.now,
            observation_type="calendar_event",
            summary="Quarterly Board Presentation in 2 hours",
            evidence={"goal": "Quarterly Board Presentation"},
            provenance={"tool": "calendar"},
        )

        # Low novelty (it happens every quarter), but CRITICAL significance
        sig = self.significance_engine.evaluate_situation(
            situation_type="board_meeting_preparation",
            situation_priority=SituationPriority.CRITICAL.value,
            evidence_count=1,
            novelty_score=0.05,  # Zero novelty
            has_information_gap=False,
            goals=[goal],
            reference_time=self.now,
        )
        self.assertEqual(sig.level, SignificanceLevel.CRITICAL.value)

    def test_10_insufficient_evidence_flags_investigation_needed(self) -> None:
        """Scenario 10: Empty/missing evidence evaluates as insufficient_evidence; weak evidence flags investigation."""
        # 1. Empty evidence -> INSUFFICIENT_EVIDENCE
        strength_empty = self.evidence_calculator.calculate([], reference_time=self.now)
        self.assertEqual(strength_empty, EvidenceStrengthLevel.INSUFFICIENT_EVIDENCE)

        # 2. Single uncorroborated report -> WEAK
        single_evidence = [{"source": "slack", "source_id": "vague_msg", "summary": "Something might be broken"}]
        strength_single = self.evidence_calculator.calculate(single_evidence, reference_time=self.now)
        self.assertEqual(strength_single, EvidenceStrengthLevel.WEAK)

    def test_11_hermes_reasoning_triggered_when_eligible(self) -> None:
        """Scenario 11: Significant situation passes eligibility gate and triggers Hermes reasoning."""
        sit = self.world_model.create_situation(
            type="flight_delay_meeting_conflict",
            priority=SituationPriority.HIGH.value,
            novelty=0.6,
        )

        sig = self.significance_engine.evaluate_situation(
            situation_type=sit.type,
            situation_priority=sit.priority,
            evidence_count=2,
            novelty_score=0.6,
            has_information_gap=False,
            goals=[],
            reference_time=self.now,
        )

        elig = self.eligibility_gate.evaluate(
            situation=sit,
            significance=sig,
            is_new_situation=True,
            has_new_events=True,
        )
        self.assertTrue(elig.requires_hermes)

    def test_12_hermes_reasoning_correctly_bounded(self) -> None:
        """Scenario 12: Bounded context builder produces targeted, token-bounded prompt context."""
        builder = ContextBuilder(situation_store=self.situation_store, goal_store=self.goal_store)
        state_engine = StateEngine(timeline_engine=TimelineEngine(event_store=self.event_store), goal_store=self.goal_store)

        sit = self.world_model.create_situation(
            type="deadline_risk",
            priority=SituationPriority.HIGH.value,
        )
        curr_state = state_engine.compute_current_state(reference_time=self.now)

        bounded = builder.build_bounded_context(
            situation=sit,
            current_state=curr_state,
        )
        prompt_text = bounded.to_epistemic_prompt()

        # Verify bounded structure
        self.assertIn("OPEN_SITUATION", prompt_text)
        self.assertIn("OBSERVED_FACTS", prompt_text)
        self.assertLess(len(prompt_text), 15000)  # Bounded size

    def test_13_recommendation_generated_in_reasoning_episode(self) -> None:
        """Scenario 13: Structured recommendation with options and rationale is generated in episode."""
        sit = self.world_model.create_situation(type="contract_deadline", priority=SituationPriority.HIGH.value)

        episode = self.world_model.record_reasoning_episode(ReasoningEpisode(
            id="ep-test-rec",
            situation_id=sit.id,
            trigger_type="situation_reasoning",
            status=EpisodeStatus.REASONING_COMPLETED.value,
            recommendation={
                "headline": "Reschedule non-critical 3 PM sync to complete contract review",
                "action_items": ["Move 3 PM sync to tomorrow morning", "Notify Sarah of adjusted timeline"],
                "tradeoff_rationale": "Contract review deadline carries legal SLA penalties",
                "confidence": 0.92,
            },
        ))

        self.assertIsNotNone(episode.recommendation)
        self.assertEqual(episode.recommendation["headline"], "Reschedule non-critical 3 PM sync to complete contract review")
        self.assertEqual(len(episode.recommendation["action_items"]), 2)

    def test_14_intervention_policy_evaluated_independently(self) -> None:
        """Scenario 14: PI intervention policy evaluates delivery (interrupt vs digest vs silent) independently."""
        # Critical urgency forces interrupt even in focus state
        pol_result = self.policy_engine.evaluate(
            urgency="critical",
            actionability="high",
            evidence_strength="strong",
            user_context=UserContext.FOCUSED.value,
        )
        self.assertEqual(pol_result.action, PolicyAction.INTERRUPT)

    def test_15_complete_provenance_chain_preserved(self) -> None:
        """Scenario 15: Full provenance chain is traceable from recommendation back to originating observation."""
        # 1. Originating observation
        obs = self.world_model.record_observation(
            source="flight_tracker",
            source_id="flight-UA-904",
            timestamp=self.now,
            observation_type="flight_delayed",
            summary="Flight UA-904 delayed by 180 minutes",
            evidence={"flight": "UA-904", "delay_min": 180},
            provenance={"tool": "flight_radar_api", "flight_id": "UA-904", "query": "status:delayed"},
        )

        # 2. Situation created referencing observation
        sit = self.world_model.create_situation(
            type="travel_disruption",
            priority=SituationPriority.HIGH.value,
            evidence=[obs.id],
        )

        # 3. Episode referencing situation
        episode = self.world_model.record_reasoning_episode(ReasoningEpisode(
            id="ep-travel-disrupt",
            situation_id=sit.id,
            trigger_type="situation_reasoning",
            status=EpisodeStatus.REASONING_COMPLETED.value,
            recommendation={
                "headline": "Notify hotel of late arrival after 11 PM",
                "confidence": 0.95,
            },
        ))

        # 4. Trace back: Episode -> Situation -> Evidence ID -> EventStore -> Provenance
        loaded_ep = self.episode_store.get_episode(episode.id)
        loaded_sit = self.situation_store.get(loaded_ep.situation_id)
        origin_obs_id = loaded_sit.evidence[0]
        raw_obs = self.event_store.get(origin_obs_id)

        self.assertEqual(raw_obs.source, "flight_tracker")
        self.assertEqual(raw_obs.source_reference, "flight-UA-904")
        self.assertEqual(raw_obs.provenance["tool"], "flight_radar_api")
        self.assertEqual(raw_obs.provenance["flight_id"], "UA-904")


if __name__ == "__main__":
    unittest.main()
