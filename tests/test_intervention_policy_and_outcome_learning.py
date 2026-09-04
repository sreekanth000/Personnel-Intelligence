"""
Unit & Integration Tests for Intervention Policy and Outcome Learning Cleanup (Prompt 7).

Verifies:
1. Policy cannot be bypassed: External callers/Hermes cannot force an action or bypass policy.
2. Critical Hermes output cannot force interruption: Urgency 'critical' does not automatically interrupt
   when user context is in meeting, driving, transit, deep work, or when actionability is low.
3. ACCEPT / DISMISS / IGNORE / DEFER are recorded in EpisodeStore.
4. Observations remain immutable: Interventions, responses, and learning do not mutate EventStore.
5. Response and outcome remain separate: ACCEPT does not automatically mean success/completed.
6. Outcome requires evidence: Does not manufacture outcomes; unbacked outcomes are UNKNOWN or rejected.
7. Learning does not rewrite historical observations: Pattern discovery leaves EventStore and episodes unmutated.
8. Repeated patterns can be reused safely: Recurrent situations update pattern support without causal claims.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.episodes.models import (
    EpisodeStatus,
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.patterns.engine import LearningEngine
from personal_intelligence.core.patterns.models import PatternStatus, PatternType
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.policy.engine import InterventionPolicyEngine, decide_intervention
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.storage.db import DatabaseManager


class TestInterventionPolicyAndOutcomeLearning(unittest.TestCase):
    """Test suite for Prompt 7 Intervention Policy and Outcome Learning Cleanup."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_prompt7.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.policy_engine = InterventionPolicyEngine()
        self.learning_engine = LearningEngine(pattern_store=self.pattern_store)

        self.now = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Policy Cannot Be Bypassed
    # -------------------------------------------------------------------------
    def test_policy_cannot_be_bypassed(self) -> None:
        """
        Verify that Hermes or external LLM outputs cannot bypass Intervention Policy.
        Even if Hermes explicitly dictates 'action: INTERRUPT' or 'bypass_policy: True',
        PI policy executes its own independent deterministic evaluation.
        """
        hermes_recommendation = {
            "title": "Unverified Server Warning",
            "action": "INTERRUPT",  # Hermes attempts to dictate presentation action
            "bypass_policy": True,   # Hermes attempts to bypass policy
            "urgency": "medium",
            "actionability": "low",
        }

        # User is in deep work
        decision = self.policy_engine.evaluate_recommendation(
            recommendation=hermes_recommendation,
            user_context="deep_work",
            evidence_strength="weak",
        )

        # Policy MUST NOT output INTERRUPT
        self.assertNotEqual(decision.action, PolicyAction.INTERRUPT.value)
        self.assertIn(decision.action, (PolicyAction.DEFER.value, PolicyAction.SUPPRESS.value, PolicyAction.DISCARD.value, PolicyAction.BRIEFING.value))

    # -------------------------------------------------------------------------
    # 2. Critical Hermes Output Cannot Force Interruption
    # -------------------------------------------------------------------------
    def test_critical_hermes_output_cannot_force_interruption(self) -> None:
        """
        Verify that a Hermes output marked 'critical' does NOT automatically force an interruption.
        Only PI policy determines the actual intervention level.
        """
        # Scenario A: User is in deep work focus mode -> DEFER
        res_deep_work = self.policy_engine.evaluate(
            urgency="critical",
            actionability="high",
            evidence_strength="strong",
            user_context="deep_work",
        )
        self.assertEqual(res_deep_work.action, PolicyAction.DEFER.value)

        # Scenario B: User is in DND or sleeping -> DEFER
        res_dnd = self.policy_engine.evaluate(
            urgency="critical",
            actionability="high",
            evidence_strength="strong",
            user_context="do_not_disturb",
        )
        self.assertEqual(res_dnd.action, PolicyAction.DEFER.value)

        # Scenario C: Critical urgency but evidence is weak -> DEFER
        res_weak = self.policy_engine.evaluate(
            urgency="critical",
            actionability="high",
            evidence_strength="weak",
            user_context="available",
        )
        self.assertEqual(res_weak.action, PolicyAction.DEFER.value)

        # Scenario D: Critical urgency but evidence is conflicted -> DEFER
        res_conf = self.policy_engine.evaluate(
            urgency="critical",
            actionability="high",
            evidence_strength="conflicted",
            user_context="available",
        )
        self.assertEqual(res_conf.action, PolicyAction.DEFER.value)

        # Scenario E: Critical urgency but actionability is low/none -> BRIEFING
        res_low_act = self.policy_engine.evaluate(
            urgency="critical",
            actionability="low",
            evidence_strength="strong",
            user_context="available",
        )
        self.assertEqual(res_low_act.action, PolicyAction.BRIEFING.value)

        # Scenario F: Critical urgency but situation is already resolved -> DISCARD
        res_resolved = self.policy_engine.evaluate(
            urgency="critical",
            actionability="high",
            evidence_strength="strong",
            user_context="available",
            situation_resolved=True,
        )
        self.assertEqual(res_resolved.action, PolicyAction.DISCARD.value)

        # Scenario G: Critical urgency but recently dismissed -> SUPPRESS
        res_dismissed = self.policy_engine.evaluate(
            urgency="critical",
            actionability="high",
            evidence_strength="strong",
            user_context="available",
            recently_dismissed=True,
        )
        self.assertEqual(res_dismissed.action, PolicyAction.SUPPRESS.value)

    # -------------------------------------------------------------------------
    # 3. ACCEPT / DISMISS / IGNORE / DEFER are recorded
    # -------------------------------------------------------------------------
    def test_user_responses_recorded(self) -> None:
        """
        Verify that EpisodeStore records ACCEPT, DISMISS, IGNORE, and DEFER user responses.
        """
        for resp in [RecommendationResult.ACCEPT, RecommendationResult.DISMISS, RecommendationResult.IGNORE, RecommendationResult.DEFER]:
            ep = self.episode_store.create_episode(
                situation_id="sit-user-resp-test",
                hermes_task=f"Task for {resp.value}",
                recommendation={"summary": "Recommended schedule adjustment"},
            )

            updated = self.episode_store.record_user_response(
                episode_id=ep.id,
                response=resp,
                feedback_notes=f"User responded with {resp.value}",
                timestamp=self.now,
            )

            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, EpisodeStatus.RESPONSE_RECORDED.value)
            user_rec = updated.get_user_response_record()
            self.assertIsNotNone(user_rec)
            self.assertEqual(user_rec.response, resp.value)

    # -------------------------------------------------------------------------
    # 4. Observations Remain Immutable
    # -------------------------------------------------------------------------
    def test_observations_remain_immutable(self) -> None:
        """
        Verify that recording policy decisions, user responses, outcomes,
        and learning patterns NEVER mutates historical EventStore observations.
        """
        # Ingest original observation
        event = Event(
            id="evt-obs-orig-1",
            source="google_calendar",
            event_type="meeting_ended",
            event_time=self.now - timedelta(hours=2),
            payload={"summary": "Quarterly Strategy Review", "attendees": ["alice@corp.com"]},
        )
        self.event_store.record_event(event)

        # Snapshot of event state
        before_event = self.event_store.get("evt-obs-orig-1")
        self.assertIsNotNone(before_event)
        before_dict = before_event.to_dict()

        # Execute reasoning episode lifecycle
        ep = self.episode_store.create_episode(
            situation_id="sit-strategy",
            observations=["evt-obs-orig-1"],
            recommendation={"summary": "Send follow-up notes"},
        )
        self.episode_store.record_user_response(ep.id, RecommendationResult.ACCEPT)
        self.episode_store.record_evidence_backed_outcome(ep.id, evidence_event_ids=["evt-obs-orig-1"])

        # Execute learning sweep
        self.learning_engine.learn_patterns(events=[event], episodes=[ep], as_of=self.now)

        # Verify historical observation in EventStore is 100% identical and unmutated
        after_event = self.event_store.get("evt-obs-orig-1")
        self.assertIsNotNone(after_event)
        self.assertEqual(before_dict, after_event.to_dict())

    # -------------------------------------------------------------------------
    # 5. Response and Outcome Remain Separate
    # -------------------------------------------------------------------------
    def test_response_and_outcome_remain_separate(self) -> None:
        """
        Verify that USER RESPONSE and OUTCOME are strictly separate.
        An accepted recommendation does NOT automatically mean it succeeded.
        """
        ep = self.episode_store.create_episode(
            situation_id="sit-proposal-sep",
            recommendation={"summary": "Draft and send sales proposal"},
        )

        # User accepts the recommendation
        updated = self.episode_store.record_user_response(
            episode_id=ep.id,
            response=RecommendationResult.ACCEPT,
            feedback_notes="Will do this now",
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, EpisodeStatus.RESPONSE_RECORDED.value)

        # Outcome MUST NOT be automatically marked or manufactured as completed
        self.assertIsNone(updated.outcome)
        out_rec = updated.get_outcome_record()
        self.assertIsNone(out_rec)

    # -------------------------------------------------------------------------
    # 6. Outcome Requires Evidence
    # -------------------------------------------------------------------------
    def test_outcome_requires_evidence(self) -> None:
        """
        Verify that outcomes must be based on observed evidence where possible.
        Outcomes without evidence are not manufactured as successes.
        """
        ep = self.episode_store.create_episode(
            situation_id="sit-evidence-need",
            recommendation={"summary": "Take a break after prolonged coding session"},
        )

        # Case A: Outcome without evidence defaults to UNKNOWN via record_evidence_backed_outcome
        backed_unknown = self.episode_store.record_evidence_backed_outcome(
            episode_id=ep.id,
            evidence_event_ids=[],  # No evidence provided
            outcome_status=RecommendationResult.COMPLETED,
        )
        self.assertIsNotNone(backed_unknown)
        out_rec = backed_unknown.get_outcome_record()
        self.assertIsNotNone(out_rec)
        self.assertEqual(out_rec.outcome_status, RecommendationResult.UNKNOWN.value)
        self.assertIsNone(out_rec.success)

        # Case B: Strict validation raises ValueError if require_evidence=True and no evidence is passed
        with self.assertRaises(ValueError) as ctx:
            self.episode_store.record_outcome(
                episode_id=ep.id,
                outcome_status=RecommendationResult.COMPLETED,
                evidence_event_ids=[],
                require_evidence=True,
            )
        self.assertIn("requires supporting observed evidence", str(ctx.exception))

        # Case C: Valid evidence event ID records COMPLETED successfully
        backed_completed = self.episode_store.record_evidence_backed_outcome(
            episode_id=ep.id,
            evidence_event_ids=["evt-break-detected-01"],
            outcome_status=RecommendationResult.COMPLETED,
        )
        self.assertIsNotNone(backed_completed)
        self.assertEqual(backed_completed.get_outcome_record().outcome_status, RecommendationResult.COMPLETED.value)
        self.assertTrue(backed_completed.get_outcome_record().success)

    # -------------------------------------------------------------------------
    # 7. Learning Does Not Rewrite Historical Observations
    # -------------------------------------------------------------------------
    def test_learning_does_not_rewrite_historical_observations(self) -> None:
        """
        Verify that empirical learning discovers patterns without modifying historical observations.
        """
        obs_1 = Event(
            id="evt-learn-1",
            source="device_telemetry",
            event_type="app_focus",
            event_time=self.now - timedelta(days=5),
            payload={"app": "IDE", "duration_minutes": 180},
        )
        obs_2 = Event(
            id="evt-learn-2",
            source="device_telemetry",
            event_type="app_focus",
            event_time=self.now - timedelta(days=4),
            payload={"app": "IDE", "duration_minutes": 200},
        )
        self.event_store.record_event(obs_1)
        self.event_store.record_event(obs_2)

        ep = self.episode_store.create_episode(
            situation_id="sit-coding-fatigue",
            observations=["evt-learn-1", "evt-learn-2"],
            recommendation={"summary": "Stretch break recommended"},
        )
        self.episode_store.record_user_response(ep.id, RecommendationResult.ACCEPT)

        # Run learning
        results = self.learning_engine.learn_patterns(
            events=[obs_1, obs_2],
            episodes=[ep],
            as_of=self.now,
        )

        # Observations in EventStore remain unchanged
        retrieved_1 = self.event_store.get("evt-learn-1")
        retrieved_2 = self.event_store.get("evt-learn-2")
        self.assertEqual(retrieved_1.payload["duration_minutes"], 180)
        self.assertEqual(retrieved_2.payload["duration_minutes"], 200)

        # Episode context snapshot remains unchanged
        retrieved_ep = self.episode_store.get_episode(ep.id)
        self.assertEqual(retrieved_ep.observations, ["evt-learn-1", "evt-learn-2"])

    # -------------------------------------------------------------------------
    # 8. Repeated Patterns Can Be Reused Safely
    # -------------------------------------------------------------------------
    def test_repeated_patterns_can_be_reused_safely(self) -> None:
        """
        Verify that repeated situations can be learned and reused safely
        without explosive duplication or non-causal claims.
        """
        episodes = [
            self.episode_store.create_episode(
                situation_id="sit-conflict-1",
                hermes_task="resolve_schedule_conflict",
                context_snapshot={"category": "schedule_conflict"},
                created_at=self.now - timedelta(days=3),
            ),
            self.episode_store.create_episode(
                situation_id="sit-conflict-2",
                hermes_task="resolve_schedule_conflict",
                context_snapshot={"category": "schedule_conflict"},
                created_at=self.now - timedelta(days=1),
            ),
        ]

        # First recurrence discovery
        patterns = self.learning_engine.discover_situation_recurrence_patterns(episodes)
        self.assertEqual(len(patterns), 1)
        initial_pat = patterns[0]
        self.assertIn("schedule_conflict", initial_pat.description)
        # Non-causal phrasing
        self.assertNotIn("causes", initial_pat.description.lower())
        self.assertNotIn("because of", initial_pat.description.lower())

        # Second sweep with fresh occurrence reuses and updates the existing pattern
        third_ep = self.episode_store.create_episode(
            situation_id="sit-conflict-3",
            hermes_task="resolve_schedule_conflict",
            context_snapshot={"category": "schedule_conflict"},
            created_at=self.now,
        )
        updated_patterns = self.learning_engine.discover_situation_recurrence_patterns(episodes + [third_ep])
        self.assertEqual(len(updated_patterns), 1)
        self.assertEqual(updated_patterns[0].id, initial_pat.id)
        self.assertGreaterEqual(updated_patterns[0].support_count, 3)


if __name__ == "__main__":
    unittest.main()
