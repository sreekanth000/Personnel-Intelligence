"""
Integration tests for the Complete Personal Intelligence Evaluation Loop.
Verifies full 16-step execution, strict idempotency over identical state,
intervention policy decisions, and scheduled follow-up re-evaluations.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.episodes import EpisodeStatus, EpisodeStore
from personal_intelligence.core.events.buffer import EventBuffer
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.loop import PersonalIntelligenceEvaluationLoop
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.core.situations.models import SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.hermes_bridge.client import (
    HermesClient,
    HermesInvocationResponse,
)
from personal_intelligence.storage.db import DatabaseManager


class TestPersonalIntelligenceEvaluationLoop(unittest.TestCase):
    """Integration test suite for the complete Personal Intelligence Evaluation Loop."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_eval_loop.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.event_buffer = EventBuffer()
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.mock_hermes = MagicMock(spec=HermesClient)

        self.loop = PersonalIntelligenceEvaluationLoop(
            db_manager=self.db_manager,
            event_store=self.event_store,
            event_buffer=self.event_buffer,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            episode_store=self.episode_store,
            hermes_client=self.mock_hermes,
        )

        self.base_time = datetime(2026, 8, 22, 14, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_complete_16_step_evaluation_loop_execution(self) -> None:
        """
        Verify the complete 16-step pipeline from event ingestion to intervention policy
        and follow-up scheduling.
        """
        # 1. Active Goal
        goal = self.goal_store.create_goal(
            name="Deep Focus Block",
            description="Maintain uninterrupted coding focus before afternoon review",
            priority=GoalPriority.HIGH.value,
        )

        # 2. Incoming events simulating prolonged intense activity
        t_start = self.base_time - timedelta(minutes=150)
        events = [
            Event(
                id="evt-focus-start",
                event_type="app_focus",
                source="macos_window",
                event_time=t_start,
                payload={"app": "VSCode", "title": "personal_intelligence/core/loop.py", "duration_minutes": 150},
            ),
            Event(
                id="evt-meeting-upcoming",
                event_type="calendar_meeting",
                source="gcal",
                event_time=self.base_time + timedelta(minutes=30),
                payload={"title": "Team Sprint Sync", "duration_mins": 30},
            ),
        ]

        # 3. Mock Hermes reasoning response
        hermes_synthesis = {
            "what_is_happening": "User has been in continuous intense coding for 150 minutes with an upcoming Team Sprint Sync in 30 minutes.",
            "evidence_summary": [
                "Continuous VSCode focus since 11:30 (150 mins) (event:evt-focus-start)",
                "Team Sprint Sync scheduled at 14:30 (event:evt-meeting-upcoming)",
            ],
            "inferences": [
                "Mental fatigue may set in without a short break prior to the sync.",
            ],
            "predictions": [
                "Uninterrupted coding up to 14:30 will result in rushed context switching.",
            ],
            "recommendations": [
                "Step away for a 5-minute break at 14:15 to refresh before the sync.",
            ],
            "uncertainties": [],
            "requires_follow_up": True,
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_synthesis),
            duration_ms=420,
        )

        # 4. Run Evaluation Cycle (user is available)
        cycle_res = self.loop.run_cycle(
            incoming_events=events,
            user_context=UserContext.AVAILABLE.value,
            as_of=self.base_time,
        )

        # 5. Verify 16-step pipeline outputs
        self.assertEqual(cycle_res.events_processed_count, 2)
        self.assertIsNotNone(cycle_res.current_state)
        self.assertGreaterEqual(len(cycle_res.candidate_situations), 1)
        self.assertEqual(len(cycle_res.episodes_created), len(cycle_res.situations_evaluated))
        self.assertGreaterEqual(len(cycle_res.episodes_created), 1)

        # Verify intervention decision: HIGH + HIGH + STRONG + AVAILABLE -> INTERRUPT
        episode = cycle_res.episodes_created[0]
        self.assertEqual(episode.urgency, "high")
        self.assertEqual(episode.actionability, "high")
        self.assertEqual(episode.evidence_strength, "strong")
        action_val = episode.intervention_decision.get("action") if isinstance(episode.intervention_decision, dict) else episode.intervention_decision
        self.assertEqual(action_val, PolicyAction.INTERRUPT.value)

        # Verify scheduled follow-up
        self.assertGreaterEqual(len(cycle_res.scheduled_follow_ups), 1)
        self.assertIsNotNone(episode.follow_up_at)

        # Verify episode persisted in database
        persisted_episodes = self.episode_store.list_recent(limit=10)
        self.assertGreaterEqual(len(persisted_episodes), 1)
        self.assertTrue(any(e.id == episode.id for e in persisted_episodes))

    def test_strict_idempotency_no_duplicate_situations_or_episodes(self) -> None:
        """
        Verify that running the evaluation loop consecutively against the same state
        without new events or scheduled re-evaluations produces 0 new situations and 0 new episodes.
        """
        # Seed initial event
        init_event = Event(
            id="evt-session-1",
            event_type="app_focus",
            source="macos_window",
            event_time=self.base_time - timedelta(minutes=130),
            payload={"app": "VSCode", "duration_minutes": 130},
        )

        hermes_synthesis = {
            "what_is_happening": "Prolonged coding activity detected.",
            "evidence_summary": ["VSCode focus duration 130m"],
            "inferences": ["Cognitive fatigue risk"],
            "predictions": ["Focus degradation"],
            "recommendations": ["Take a short hydration break."],
            "uncertainties": [],
            "requires_follow_up": False,
            "urgency": "medium",
            "actionability": "medium",
            "relevance": "medium",
            "evidence_strength": "strong",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_synthesis),
            duration_ms=350,
        )

        # First run: Ingests event, creates situation, creates episode
        res1 = self.loop.run_cycle(
            incoming_events=[init_event],
            user_context=UserContext.AVAILABLE.value,
            as_of=self.base_time,
        )
        self.assertEqual(res1.events_processed_count, 1)
        self.assertEqual(len(res1.episodes_created), len(res1.situations_evaluated))
        self.assertGreaterEqual(len(res1.episodes_created), 1)
        sit_count_1 = len(self.situation_store.list_active())
        ep_count_1 = len(self.episode_store.list_recent(limit=10))
        self.assertGreaterEqual(sit_count_1, 1)
        self.assertGreaterEqual(ep_count_1, 1)

        # Second run: No new events, same timestamp -> IDEMPOTENCY GUARANTEE
        res2 = self.loop.run_cycle(
            incoming_events=[],
            user_context=UserContext.AVAILABLE.value,
            as_of=self.base_time,
        )

        self.assertEqual(res2.events_processed_count, 0)
        self.assertEqual(len(res2.episodes_created), 0)
        self.assertEqual(len(res2.situations_evaluated), 0)

        # Database situation and episode counts remain strictly identical (no duplicates)
        sit_count_2 = len(self.situation_store.list_active())
        ep_count_2 = len(self.episode_store.list_recent(limit=10))
        self.assertEqual(sit_count_2, sit_count_1)
        self.assertEqual(ep_count_2, ep_count_1)

    def test_scheduled_follow_up_triggers_reevaluation_and_clearing(self) -> None:
        """
        Verify that advancing time to the scheduled follow-up triggers re-evaluation,
        and if condition has cleared, resolves the situation.
        """
        init_event = Event(
            id="evt-meeting-conflict-1",
            event_type="calendar_conflict",
            source="gcal",
            event_time=self.base_time,
            payload={"event1": "Client Call", "event2": "Strategy Meeting"},
        )

        # Attempt 1: Conflict active -> requires follow-up in 60 mins
        synth_1 = {
            "what_is_happening": "Overlapping calendar commitments.",
            "evidence_summary": ["Overlapping client call and strategy meeting."],
            "inferences": ["Double booking requires manual adjustment."],
            "predictions": ["User cannot attend both simultaneously."],
            "recommendations": ["Reschedule internal strategy meeting."],
            "uncertainties": [],
            "requires_follow_up": True,
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }

        # Attempt 2 at follow-up time: Conflict resolved/cleared
        synth_2 = {
            "what_is_happening": "Strategy meeting moved to tomorrow; schedule conflict cleared.",
            "evidence_summary": ["No overlapping calendar events remain."],
            "inferences": ["Schedule conflict successfully resolved."],
            "predictions": ["Nominal calendar schedule."],
            "recommendations": ["No further action needed."],
            "uncertainties": [],
            "requires_follow_up": False,
            "urgency": "low",
            "actionability": "low",
            "relevance": "low",
            "evidence_strength": "strong",
        }

        run_stage = [1]
        def dynamic_hermes_call(*args, **kwargs):
            if run_stage[0] == 2:
                return HermesInvocationResponse(raw_response=json.dumps(synth_2), duration_ms=300)
            return HermesInvocationResponse(raw_response=json.dumps(synth_1), duration_ms=300)

        self.mock_hermes.invoke_reasoning.side_effect = dynamic_hermes_call

        # Run 1: Detects conflict, schedules follow-up at base_time + 60m
        res1 = self.loop.run_cycle(
            incoming_events=[init_event],
            as_of=self.base_time,
            follow_up_delay_minutes=60,
        )
        self.assertGreaterEqual(len(res1.scheduled_follow_ups), 1)
        sit_id, follow_up_time = res1.scheduled_follow_ups[0]

        # Run 2: Advance time to follow_up_time (60m later)
        run_stage[0] = 2
        res2 = self.loop.run_cycle(
            incoming_events=[],
            as_of=follow_up_time,
        )

        # Re-evaluation executed
        self.assertGreaterEqual(len(res2.episodes_created), 1)
        self.assertGreaterEqual(len(res2.situations_evaluated), 1)

        # Verify situation is now RESOLVED in store
        sit_persisted = self.situation_store.get(sit_id)
        self.assertEqual(sit_persisted.status, SituationStatus.RESOLVED.value)


if __name__ == "__main__":
    unittest.main()
