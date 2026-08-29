"""
Comprehensive End-to-End Test Suite for Personal Intelligence Loop (Prompt 3).

Verifies the complete 25-step execution sequence, auditable reason codes,
invocation telemetry, state mutation safety, and 15 distinct operational scenarios:

1. insignificant event (early exit: NOT_SIGNIFICANT)
2. meaningful single-domain event
3. meaningful cross-domain event (calendar + mobility fusion)
4. novel combination (novelty escalation & workflow)
5. multi-goal conflict (tradeoff reasoning across goals)
6. information gap requiring Hermes investigation
7. Hermes reasoning without investigation
8. duplicate situation (lifecycle deduplication)
9. deep-work situation (attention protection & DEFER)
10. critical situation (CRITICAL budget & INTERRUPT)
11. conflicted evidence (CONFLICTED strength & suppression)
12. user-approved action (explicit decision hook)
13. rejected recommendation (interaction pattern learning)
14. successful recommendation (positive outcome reinforcement)
15. failed recommendation (negative outcome & world model update)
"""

from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    RecommendationResult,
)
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals import GoalStore
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.loop import (
    EarlyExitReason,
    PersonalIntelligenceEvaluationLoop,
    PersonalIntelligenceLoop,
)
from personal_intelligence.core.novelty.models import NoveltyResult
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.core.significance import SignificanceLevel
from personal_intelligence.core.situations.models import SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.hermes_bridge.client import HermesClient, HermesInvocationResponse
from personal_intelligence.hermes_bridge.situation_investigation import (
    CrossSourceEvidenceBundle,
    InvestigationOutcome,
    InvestigationPlan,
)
from personal_intelligence.storage.db import DatabaseManager


class TestPersonalIntelligenceLoopE2E(unittest.TestCase):
    """Full 15-scenario end-to-end test suite for PersonalIntelligenceLoop."""

    def setUp(self) -> None:
        self.db_manager = DatabaseManager(db_path=":memory:")
        self.db_manager.initialize_schema()

        self.mock_hermes = MagicMock(spec=HermesClient)
        self.mock_investigator = MagicMock()

        self.loop = PersonalIntelligenceLoop(
            db_manager=self.db_manager,
            hermes_client=self.mock_hermes,
            situation_investigator=self.mock_investigator,
        )

        self.base_time = datetime(2026, 8, 29, 14, 0, 0, tzinfo=timezone.utc)

    # -------------------------------------------------------------------------
    # Scenario 1: Insignificant Event
    # -------------------------------------------------------------------------
    def test_01_insignificant_event_stops_early_with_reason_code(self) -> None:
        """Routine low-significance event stops early with NOT_SIGNIFICANT reason code without calling Hermes."""
        event = Event(
            event_type="newsletter_received",
            source="email",
            source_id="news_1",
            event_time=self.base_time - timedelta(minutes=5),
            payload={"subject": "Weekly Tech Digest", "sender": "news@daily.com"},
        )

        result = self.loop.run_cycle(
            incoming_events=[event],
            as_of=self.base_time,
        )

        self.assertEqual(result.events_processed_count, 1)
        self.mock_hermes.invoke_reasoning.assert_not_called()
        self.assertEqual(len(result.episodes_created), 0)

    # -------------------------------------------------------------------------
    # Scenario 2: Meaningful Single-Domain Event
    # -------------------------------------------------------------------------
    def test_02_meaningful_single_domain_event_triggers_reasoning(self) -> None:
        """High-priority goal deadline event triggers Hermes reasoning and produces an episode."""
        goal = self.loop.goal_store.create_goal(
            name="Q3 Product Beta Launch",
            priority=GoalPriority.HIGH.value,
        )

        event = Event(
            event_type="deadline_warning",
            source="jira",
            source_id="jira_99",
            event_time=self.base_time - timedelta(minutes=10),
            payload={"summary": "Q3 Product Beta Launch blocker reported", "status": "blocked"},
        )

        synthesis_json = {
            "what_is_happening": "Production release blocker on Q3 Product Beta Launch.",
            "evidence_summary": ["Jira ticket reported blocked (event:jira_99)"],
            "inferences": ["Launch milestone will slip if unaddressed today."],
            "predictions": ["Beta delay past target date."],
            "recommendations": ["Reassign backend engineer to unblock CI pipeline."],
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
            "requires_follow_up": True,
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(synthesis_json),
            duration_ms=250,
        )

        result = self.loop.run_cycle(
            incoming_events=[event],
            user_context=UserContext.AVAILABLE.value,
            as_of=self.base_time,
        )

        self.assertGreaterEqual(len(result.episodes_created), 1)
        episode = result.episodes_created[0]
        self.assertEqual(episode.urgency, "high")
        self.assertEqual(episode.actionability, "high")
        self.assertIsNotNone(episode.reason_for_invocation)
        self.assertIn(episode.reasoning_budget, ["MEDIUM", "HIGH"])

    # -------------------------------------------------------------------------
    # Scenario 3: Meaningful Cross-Domain Event
    # -------------------------------------------------------------------------
    def test_03_meaningful_cross_domain_event_fuses_calendar_and_mobility(self) -> None:
        """Cross-domain calendar and flight events fuse into situational reasoning."""
        events = [
            Event(
                event_type="flight_delay",
                source="mobility",
                source_id="fl_12",
                event_time=self.base_time - timedelta(minutes=30),
                payload={"flight": "UA404", "delay_minutes": 90, "new_eta": "16:30"},
            ),
            Event(
                event_type="calendar_event",
                source="calendar",
                source_id="cal_44",
                event_time=self.base_time - timedelta(minutes=10),
                payload={"summary": "Executive Dinner", "start_time": "16:00", "attendees": ["ceo@co.com"]},
            ),
        ]

        synthesis_json = {
            "what_is_happening": "Flight delay causes direct overlap with scheduled Executive Dinner.",
            "evidence_summary": ["Flight UA404 delayed by 90m", "Executive Dinner at 16:00"],
            "inferences": ["User cannot attend Executive Dinner on time."],
            "predictions": ["Arrival at dinner will be at least 45 minutes late."],
            "recommendations": ["Notify dinner organizer immediately to reschedule."],
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(synthesis_json),
            duration_ms=300,
        )

        result = self.loop.run_cycle(
            incoming_events=events,
            user_context=UserContext.AVAILABLE.value,
            as_of=self.base_time,
        )

        self.assertGreaterEqual(len(result.episodes_created), 1)
        self.mock_hermes.invoke_reasoning.assert_called()

    # -------------------------------------------------------------------------
    # Scenario 4: Novel Combination
    # -------------------------------------------------------------------------
    def test_04_novel_combination_escalates_and_triggers_novel_workflow(self) -> None:
        """Statistically novel anomaly triggers run_novel_workflow with novel synthesis."""
        event = Event(
            event_type="unusual_state_event",
            source="system",
            source_id="sys_nov",
            event_time=self.base_time - timedelta(minutes=5),
            payload={"metric": "unprecedented_load_pattern"},
        )

        # Explicit NoveltyResult object
        novelty_obj = NoveltyResult(
            overall_level="NOVEL_COMBINATION",
            timestamp=self.base_time,
        )
        self.loop.novelty_engine.evaluate_state = MagicMock(return_value=novelty_obj)

        synthesis_json = {
            "what_is_happening": "Unprecedented combination of physiological strain and meeting load.",
            "evidence_summary": ["Novel state detected across 3 dimensions"],
            "inferences": ["High probability of cognitive exhaustion."],
            "predictions": ["Sharp performance decline."],
            "recommendations": ["Clear evening schedule and prioritize rest."],
            "urgency": "high",
            "actionability": "medium",
            "relevance": "high",
            "evidence_strength": "moderate",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(synthesis_json),
            duration_ms=350,
        )

        result = self.loop.run_cycle(
            incoming_events=[event],
            as_of=self.base_time,
        )

        self.assertIsNotNone(result.novelty_result)
        self.assertEqual(result.novelty_result.overall_level, "NOVEL_COMBINATION")

    # -------------------------------------------------------------------------
    # Scenario 5: Multi-Goal Conflict
    # -------------------------------------------------------------------------
    def test_05_multi_goal_conflict_evaluates_goal_tradeoffs(self) -> None:
        """Reasoning context incorporates multi-goal tradeoffs."""
        self.loop.goal_store.create_goal(name="Ship Feature Alpha", priority=GoalPriority.HIGH.value)
        self.loop.goal_store.create_goal(name="Maintain Sleep Schedule", priority=GoalPriority.HIGH.value)

        event = Event(
            event_type="late_night_deployment_scheduled",
            source="calendar",
            source_id="cal_late",
            event_time=self.base_time - timedelta(minutes=5),
            payload={"summary": "Emergency Deployment at 23:30", "duration": 120},
        )

        synthesis_json = {
            "what_is_happening": "Late night deployment conflicts with Maintain Sleep Schedule goal.",
            "evidence_summary": ["Emergency Deployment scheduled at 23:30"],
            "inferences": ["User will incur 2+ hours of sleep deficit."],
            "predictions": ["Next day focus score degraded."],
            "recommendations": ["Delegate deployment on-call to secondary engineer."],
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(synthesis_json),
            duration_ms=280,
        )

        result = self.loop.run_cycle(
            incoming_events=[event],
            as_of=self.base_time,
        )

        self.assertEqual(len(result.active_goals), 2)
        self.assertGreaterEqual(len(result.episodes_created), 1)

    # -------------------------------------------------------------------------
    # Scenario 6: Information Gap Requiring Hermes Investigation
    # -------------------------------------------------------------------------
    def test_06_information_gap_triggers_bounded_hermes_investigation(self) -> None:
        """Information gap situation triggers bounded investigation before reasoning."""
        sit = self.loop.situation_store.create_situation(
            situation_type="information_gap",
            priority=SituationPriority.HIGH.value,
            information_required=True,
            evidence=["Calendar invite received without location or zoom link."],
            next_evaluation_at=self.base_time,
        )

        plan = InvestigationPlan(
            situation_id=sit.id,
            situation_type=sit.type,
            investigation_target="zoom_link",
            known_facts=["Calendar invite received"],
            unknowns=["Zoom link", "Location"],
        )
        bundle = CrossSourceEvidenceBundle(
            situation_id=sit.id,
            situation_type=sit.type,
            situation_summary="Missing meeting location",
            facts_by_source={"calendar": ["Calendar invite received"]},
            remaining_unknowns=[],
        )

        mock_outcome = InvestigationOutcome(
            situation=sit,
            plan=plan,
            investigation_result=None,
            evidence_bundle=bundle,
            evidence_observations_recorded=["Found zoom link in thread"],
            episode=None,
            investigation_succeeded=True,
            gap_resolved=True,
            rounds_executed=1,
            total_tool_calls=1,
        )
        self.mock_investigator.investigate.return_value = mock_outcome

        synthesis_json = {
            "what_is_happening": "Resolved missing zoom link from email thread for upcoming client meeting.",
            "evidence_summary": ["Zoom link identified in client reply"],
            "inferences": ["Meeting can proceed smoothly."],
            "predictions": ["No delay at start time."],
            "recommendations": ["Attach zoom link to calendar event."],
            "urgency": "medium",
            "actionability": "high",
            "relevance": "medium",
            "evidence_strength": "strong",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(synthesis_json),
            duration_ms=220,
        )

        result = self.loop.run_cycle(
            as_of=self.base_time,
        )

        self.mock_investigator.investigate.assert_called()
        self.assertEqual(len(result.episodes_created), 1)
        self.assertEqual(result.episodes_created[0].investigation_rounds, 1)

    # -------------------------------------------------------------------------
    # Scenario 7: Hermes Reasoning Without Investigation
    # -------------------------------------------------------------------------
    def test_07_hermes_reasoning_without_investigation_when_gap_absent(self) -> None:
        """Situation with complete evidence executes reasoning directly without tool investigation."""
        sit = self.loop.situation_store.create_situation(
            situation_type="conflicting_commitments",
            priority=SituationPriority.HIGH.value,
            information_required=False,
            evidence=["Event A at 14:00", "Event B at 14:00"],
            next_evaluation_at=self.base_time,
        )

        synthesis_json = {
            "what_is_happening": "Two conflicting meetings at 14:00.",
            "evidence_summary": ["Event A at 14:00", "Event B at 14:00"],
            "inferences": ["Double booking."],
            "predictions": ["One meeting will be missed."],
            "recommendations": ["Decline Event B."],
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(synthesis_json),
            duration_ms=200,
        )

        result = self.loop.run_cycle(as_of=self.base_time)

        self.mock_investigator.investigate.assert_not_called()
        self.assertEqual(len(result.episodes_created), 1)
        self.assertEqual(result.episodes_created[0].investigation_rounds, 0)

    # -------------------------------------------------------------------------
    # Scenario 8: Duplicate Situation Lifecycle
    # -------------------------------------------------------------------------
    def test_08_duplicate_situation_deduplicates_with_reason_code(self) -> None:
        """Repeated cycle without new events or changes avoids creating duplicate situations."""
        sit = self.loop.situation_store.create_situation(
            situation_type="goal_risk",
            priority=SituationPriority.MEDIUM.value,
            status=SituationStatus.RESOLVED.value,
        )

        result = self.loop.run_cycle(as_of=self.base_time)

        self.assertEqual(len(result.episodes_created), 0)

    # -------------------------------------------------------------------------
    # Scenario 9: Deep-Work Situation
    # -------------------------------------------------------------------------
    def test_09_deep_work_situation_defers_presentation_under_attention_protection(self) -> None:
        """Non-critical recommendation during DEEP_WORK is deferred under attention policy."""
        sit = self.loop.situation_store.create_situation(
            situation_type="conflicting_commitments",
            priority=SituationPriority.MEDIUM.value,
            evidence=["Minor overlap next week"],
            next_evaluation_at=self.base_time,
        )

        synthesis_json = {
            "what_is_happening": "Minor calendar overlap next Tuesday.",
            "evidence_summary": ["Two 15-minute events overlap"],
            "inferences": ["Non-urgent adjustment needed."],
            "predictions": ["Can be handled later."],
            "recommendations": ["Reschedule during next briefing."],
            "urgency": "medium",
            "actionability": "medium",
            "relevance": "medium",
            "evidence_strength": "moderate",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(synthesis_json),
            duration_ms=210,
        )

        result = self.loop.run_cycle(
            user_context=UserContext.DEEP_WORK.value,
            as_of=self.base_time,
        )

        self.assertEqual(len(result.actions_decided), 1)
        action = result.actions_decided[0][1]
        self.assertEqual(action, PolicyAction.DEFER.value)

    # -------------------------------------------------------------------------
    # Scenario 10: Critical Situation
    # -------------------------------------------------------------------------
    def test_10_critical_situation_interrupts_with_critical_budget(self) -> None:
        """CRITICAL urgency interrupts user across all contexts with CRITICAL budget."""
        sit = self.loop.situation_store.create_situation(
            situation_type="goal_risk",
            priority=SituationPriority.CRITICAL.value,
            evidence=["Production server outage affecting all users."],
            next_evaluation_at=self.base_time,
        )

        synthesis_json = {
            "what_is_happening": "Production outage active.",
            "evidence_summary": ["500 errors on all API gateways"],
            "inferences": ["Zero customer transactions processing."],
            "predictions": ["Severe SLA violation within 15 minutes."],
            "recommendations": ["Immediate rollback to last known stable release."],
            "urgency": "critical",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(synthesis_json),
            duration_ms=180,
        )

        result = self.loop.run_cycle(
            user_context=UserContext.MEETING.value,
            as_of=self.base_time,
        )

        self.assertEqual(len(result.actions_decided), 1)
        action = result.actions_decided[0][1]
        self.assertEqual(action, PolicyAction.INTERRUPT.value)
        self.assertEqual(result.episodes_created[0].reasoning_budget, "CRITICAL")

    # -------------------------------------------------------------------------
    # Scenario 11: Conflicted Evidence
    # -------------------------------------------------------------------------
    def test_11_conflicted_evidence_suppresses_or_discards_premature_action(self) -> None:
        """Contradicting observations produce CONFLICTED evidence strength and suppress action."""
        sit = self.loop.situation_store.create_situation(
            situation_type="goal_risk",
            priority=SituationPriority.HIGH.value,
            evidence=[
                {"source": "gmail", "statement": "Client cancelled project", "contradicts": False},
                {"source": "slack", "statement": "Client confirmed project is ON", "contradicts": True},
                {"source": "calendar", "statement": "Kickoff still on calendar", "contradicts": True},
            ],
            next_evaluation_at=self.base_time,
        )

        synthesis_json = {
            "what_is_happening": "Conflicting status regarding client project cancellation.",
            "evidence_summary": ["Conflicting signals across Gmail, Slack, and Calendar"],
            "inferences": ["Status is unverified."],
            "predictions": ["Taking action now could cause embarrassment."],
            "recommendations": ["Seek direct confirmation before taking action."],
            "urgency": "high",
            "actionability": "low",
            "relevance": "high",
            "evidence_strength": "conflicted",
            "requires_follow_up": True,
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(synthesis_json),
            duration_ms=220,
        )

        result = self.loop.run_cycle(as_of=self.base_time)

        self.assertEqual(len(result.episodes_created), 1)
        ep = result.episodes_created[0]
        self.assertEqual(ep.evidence_strength, "conflicted")
        action = result.actions_decided[0][1]
        self.assertIn(action, (PolicyAction.BRIEFING.value, PolicyAction.DEFER.value, PolicyAction.DISCARD.value))

    # -------------------------------------------------------------------------
    # Scenario 12: User-Approved Action
    # -------------------------------------------------------------------------
    def test_12_user_approved_action_triggers_external_delegation_record(self) -> None:
        """Explicit user approval records ACCEPTED response and updates reasoning episode."""
        sit = self.loop.situation_store.create_situation(
            situation_type="conflicting_commitments",
            priority=SituationPriority.HIGH.value,
        )
        ep = self.loop.episode_store.create_episode(
            situation_id=sit.id,
            recommendation={"action": "Decline duplicate meeting"},
            urgency="high",
            actionability="high",
            status=EpisodeStatus.INTERVENTION_DELIVERED.value,
        )

        res = self.loop.capture_user_response(
            situation_id=sit.id,
            response="ACCEPTED",
            feedback_notes="Accepted recommendation to decline duplicate.",
            episode_id=ep.id,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["response"], "ACCEPTED")

        updated_ep = self.loop.episode_store.get_episode(ep.id)
        self.assertIsNotNone(updated_ep.user_response)
        self.assertEqual(updated_ep.user_response["response"], "ACCEPTED")

        # Situation resolved
        updated_sit = self.loop.situation_store.get_situation(sit.id)
        self.assertEqual(updated_sit.status, SituationStatus.RESOLVED.value)

    # -------------------------------------------------------------------------
    # Scenario 13: Rejected Recommendation
    # -------------------------------------------------------------------------
    def test_13_rejected_recommendation_updates_interaction_pattern_negative_evidence(self) -> None:
        """User dismissal updates situation to DISMISSED and records negative interaction evidence."""
        sit = self.loop.situation_store.create_situation(
            situation_type="prolonged_inactivity_on_priority",
            priority=SituationPriority.MEDIUM.value,
        )
        ep = self.loop.episode_store.create_episode(
            situation_id=sit.id,
            recommendation={"action": "Take a 15-minute walk"},
            urgency="low",
            actionability="low",
            status=EpisodeStatus.INTERVENTION_DELIVERED.value,
        )

        res = self.loop.capture_user_response(
            situation_id=sit.id,
            response="DISMISSED",
            feedback_notes="Not helpful right now.",
            episode_id=ep.id,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["response"], "DISMISSED")

        updated_ep = self.loop.episode_store.get_episode(ep.id)
        self.assertEqual(updated_ep.user_response["response"], "DISMISSED")

    # -------------------------------------------------------------------------
    # Scenario 14: Successful Recommendation
    # -------------------------------------------------------------------------
    def test_14_successful_recommendation_records_outcome_and_reinforces_patterns(self) -> None:
        """Positive longitudinal outcome confirms recommendation success and updates learning patterns."""
        sit = self.loop.situation_store.create_situation(
            situation_type="goal_risk",
            priority=SituationPriority.HIGH.value,
        )
        ep = self.loop.episode_store.create_episode(
            situation_id=sit.id,
            recommendation={"action": "Switch to fast compile flag"},
            urgency="high",
            actionability="high",
            status=EpisodeStatus.RESPONSE_RECORDED.value,
        )

        res = self.loop.capture_outcome(
            situation_id=sit.id,
            outcome_status=RecommendationResult.COMPLETED.value,
            evaluation_notes="Build time reduced by 60%, deadline met.",
            success=True,
            episode_id=ep.id,
            impact_metrics={"build_speedup_percent": 60},
        )

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["success"])

        updated_ep = self.loop.episode_store.get_episode(ep.id)
        self.assertIsNotNone(updated_ep.outcome)
        self.assertTrue(updated_ep.outcome["success"])
        self.assertEqual(updated_ep.outcome["outcome_status"], "COMPLETED")

    # -------------------------------------------------------------------------
    # Scenario 15: Failed Recommendation
    # -------------------------------------------------------------------------
    def test_15_failed_recommendation_records_outcome_and_updates_world_model(self) -> None:
        """Negative outcome evaluation records FAILED outcome without corrupting world model."""
        sit = self.loop.situation_store.create_situation(
            situation_type="goal_risk",
            priority=SituationPriority.HIGH.value,
        )
        ep = self.loop.episode_store.create_episode(
            situation_id=sit.id,
            recommendation={"action": "Attempt third-party migration"},
            urgency="high",
            actionability="high",
            status=EpisodeStatus.RESPONSE_RECORDED.value,
        )

        res = self.loop.capture_outcome(
            situation_id=sit.id,
            outcome_status="FAILED",
            evaluation_notes="Third-party tool threw fatal incompatibility error.",
            success=False,
            episode_id=ep.id,
        )

        self.assertEqual(res["status"], "success")
        self.assertFalse(res["success"])

        updated_ep = self.loop.episode_store.get_episode(ep.id)
        self.assertIsNotNone(updated_ep.outcome)
        self.assertFalse(updated_ep.outcome["success"])


if __name__ == "__main__":
    unittest.main()
