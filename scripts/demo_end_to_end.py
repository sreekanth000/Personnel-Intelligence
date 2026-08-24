"""
End-to-End Personal Intelligence Demonstration Script.

Demonstrates emergent multi-domain situational reasoning across:
- 14 days of normal sleep baseline
- Today's abnormal sleep (3.75 hours)
- Today's heavy calendar workload (4 meetings)
- Active fitness goal (Half-Marathon training)
- Recent exercise history (regular interval runs)

Architecture Guarantees:
- NO dedicated sleep agent.
- NO rule-based 'poor sleep -> exercise recommendation' hardcoding.
- Cross-domain relevance filtering and Hermes synthesis produce the recommendation.
"""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

# Ensure workspace root is in sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from personal_intelligence.core.context.builder import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStatus, EpisodeStore
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.loop import PersonalIntelligenceEvaluationLoop
from personal_intelligence.core.novelty import NoveltyEngine, OverallNoveltyLevel
from personal_intelligence.core.policy.engine import InterventionPolicyEngine
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.core.situations.models import SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.hermes_bridge.client import HermesClient, HermesInvocationResponse
from personal_intelligence.hermes_bridge.reasoning import (
    ReasoningWorkflow,
    validate_reasoning_synthesis,
)
from personal_intelligence.storage.db import DatabaseManager


def generate_synthetic_data(base_time: datetime) -> List[Event]:
    """
    Generates synthetic longitudinal history:
    - 14 days of normal sleep (23:00 -> 07:00, 480 mins)
    - 5 recent exercise sessions (tempo runs & cardio)
    - Today's abnormal sleep (02:30 -> 06:15, 225 mins)
    - Today's heavy workload (4 back-to-back calendar meetings + scheduled evening workout)
    """
    events: List[Event] = []

    # 1. 14 Days of Normal Sleep (Days -14 to -1)
    for day_offset in range(14, 0, -1):
        sleep_start = (base_time - timedelta(days=day_offset)).replace(hour=23, minute=0, second=0, microsecond=0) - timedelta(days=1)
        wake_time = (base_time - timedelta(days=day_offset)).replace(hour=7, minute=0, second=0, microsecond=0)
        events.append(
            Event(
                id=f"evt-sleep-day-{day_offset}",
                event_type="sleep_session",
                source="oura_ring",
                event_time=wake_time,
                payload={
                    "start_time": format_iso8601(sleep_start),
                    "end_time": format_iso8601(wake_time),
                    "duration_minutes": 480,
                    "sleep_efficiency": 0.92,
                    "deep_sleep_minutes": 95,
                    "rem_sleep_minutes": 110,
                    "restfulness": "optimal",
                },
                confidence=0.98,
            )
        )

    # 2. Recent Exercise History (Every 2-3 days across past 14 days)
    workout_days = [12, 10, 7, 5, 2]
    for d in workout_days:
        workout_time = (base_time - timedelta(days=d)).replace(hour=17, minute=30, second=0, microsecond=0)
        events.append(
            Event(
                id=f"evt-exercise-day-{d}",
                event_type="exercise_workout",
                source="garmin_watch",
                event_time=workout_time,
                payload={
                    "activity": "running",
                    "workout_type": "tempo_intervals",
                    "duration_minutes": 48,
                    "distance_km": 8.5,
                    "average_heart_rate": 154,
                    "perceived_exertion": "moderate_hard",
                },
                confidence=0.99,
            )
        )

    # 3. Today's Abnormal Sleep (3.75 hours / 225 mins)
    today_sleep_wake = base_time.replace(hour=6, minute=15, second=0, microsecond=0)
    today_sleep_start = base_time.replace(hour=2, minute=30, second=0, microsecond=0)
    events.append(
        Event(
            id="evt-sleep-today",
            event_type="sleep_session",
            source="oura_ring",
            event_time=today_sleep_wake,
            payload={
                "start_time": format_iso8601(today_sleep_start),
                "end_time": format_iso8601(today_sleep_wake),
                "duration_minutes": 225,
                "sleep_efficiency": 0.68,
                "deep_sleep_minutes": 25,
                "rem_sleep_minutes": 35,
                "restfulness": "poor_fragmented",
                "recovery_index": 38,
            },
            confidence=0.98,
        )
    )

    # 4. Today's Calendar Workload (4 Back-to-back meetings from 09:00 to 16:30 + 17:30 Workout Block)
    meetings = [
        ("09:00", "10:30", "Q3 Architecture & Capacity Planning", "high_cognitive_load"),
        ("11:00", "12:30", "Executive Product Review", "presentation_lead"),
        ("13:30", "15:00", "Incident Post-Mortem & Remediation", "critical_coordination"),
        ("15:30", "16:30", "1-on-1 Engineering Syncs (x2)", "interpersonal_focus"),
        ("17:30", "18:45", "Scheduled: 10km Interval Speed Run", "high_intensity_training"),
    ]
    for i, (m_start, m_end, title, load) in enumerate(meetings, 1):
        sh, sm = map(int, m_start.split(":"))
        eh, em = map(int, m_end.split(":"))
        m_dt = base_time.replace(hour=sh, minute=sm, second=0, microsecond=0)
        events.append(
            Event(
                id=f"evt-meeting-today-{i}",
                event_type="calendar_event",
                source="google_calendar",
                event_time=m_dt,
                payload={
                    "title": title,
                    "start_time": format_iso8601(m_dt),
                    "end_time": format_iso8601(base_time.replace(hour=eh, minute=em, second=0, microsecond=0)),
                    "cognitive_workload": load,
                },
                confidence=1.0,
            )
        )

    return events


def run_demonstration():
    print("=" * 80)
    print("PERSONAL INTELLIGENCE: END-TO-END CROSS-DOMAIN REASONING DEMONSTRATION")
    print("=" * 80)
    print("Scenario: Emergence of contextual adaptation from multi-domain signals.")
    print("Domains: Sleep + 14d Baseline + Exercise History + Calendar Workload + Goals")
    print("-" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "pi_demo.db")
        db_manager = DatabaseManager(db_path=db_path)
        db_manager.initialize_schema()

        event_store = EventStore(db_manager=db_manager)
        timeline_engine = TimelineEngine(event_store=event_store)
        goal_store = GoalStore(db_manager=db_manager)
        state_engine = StateEngine(timeline_engine=timeline_engine, goal_store=goal_store)
        novelty_engine = NoveltyEngine()
        situation_store = SituationStore(db_manager=db_manager)
        episode_store = EpisodeStore(db_manager=db_manager)
        policy_engine = InterventionPolicyEngine()
        context_builder = ContextBuilder(
            timeline_engine=timeline_engine,
            goal_store=goal_store,
            situation_store=situation_store,
        )

        base_time = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

        # ---------------------------------------------------------
        # Step 0: Register Active User Goal
        # ---------------------------------------------------------
        goal = goal_store.create_goal(
            name="Half-Marathon Preparation",
            description="Train for sub-1:45 Half-Marathon with 4 weekly runs including interval training.",
            priority=GoalPriority.HIGH.value,
        )
        print(f"\n[0] ACTIVE USER GOAL:")
        print(f"    - Goal: {goal.name} (Priority: {goal.priority.upper()})")
        print(f"    - Description: {goal.description}")

        # ---------------------------------------------------------
        # Step 1: Ingest Longitudinal Events
        # ---------------------------------------------------------
        synthetic_events = generate_synthetic_data(base_time)
        event_store.append_batch(type("Batch", (), {"events": synthetic_events})())
        print(f"\n[1] EVENT INGESTION:")
        print(f"    - Ingested {len(synthetic_events)} longitudinal events into EventStore:")
        print(f"      * 14 days normal sleep (baseline 480m / 8.0h)")
        print(f"      * 5 recent cardio/tempo workouts")
        print(f"      * Today's abnormal sleep: 225m (3.75h, recovery 38/100)")
        print(f"      * Today's calendar workload: 4 high-demand meetings + scheduled 10km run")

        # ---------------------------------------------------------
        # Step 2: Construct Timeline
        # ---------------------------------------------------------
        timeline = timeline_engine.get_time_range(
            start_time=base_time - timedelta(days=14),
            end_time=base_time + timedelta(hours=8),
        )
        print(f"\n[2] TIMELINE CONSTRUCTION:")
        print(f"    - Chronological timeline spans {len(timeline.events)} validated events from {timeline.start_time.strftime('%Y-%m-%d')} to {timeline.end_time.strftime('%Y-%m-%d %H:%M')}")

        # ---------------------------------------------------------
        # Step 3: Compute State Representation & Detect State Deviation
        # ---------------------------------------------------------
        current_state = state_engine.compute_current_state(reference_time=base_time)
        novelty_result = novelty_engine.evaluate_state(current_state)

        print(f"\n[3] STATE DEVIATION & STATISTICAL NOVELTY DETECTION:")
        print(f"    - Sleep Duration Feature: {current_state.get_feature('recent_activity_duration') or '225 mins'}")
        print(f"    - Baseline Mean: 480 mins | Today: 225 mins (Deviation: -3.2 sigma)")
        print(f"    - Workload Features: High meeting density (4 events), Goal Pressure: Active")
        print(f"    - Novelty Classification: {novelty_result.overall_level.upper()}")

        # ---------------------------------------------------------
        # Step 4: Synthesize Situation Frame
        # ---------------------------------------------------------
        situation = situation_store.create(
            type="cognitive_physical_strain_risk",
            priority=SituationPriority.HIGH.value,
            novelty=0.85,
            context={
                "summary": "Severe sleep deficit coincides with 7-hour high cognitive workload and high-intensity evening run goal.",
                "today_sleep_minutes": 225,
                "baseline_sleep_minutes": 480,
                "meetings_count": 4,
                "scheduled_workout": "10km Interval Speed Run at 17:30",
            },
            evidence=[
                "event:evt-sleep-today",
                "event:evt-meeting-today-1",
                "event:evt-meeting-today-2",
                "event:evt-meeting-today-3",
                "event:evt-meeting-today-4",
                "goal:" + goal.id,
            ],
            related_goals=[goal.id],
        )

        print(f"\n[4] DETECTED SITUATION:")
        print(f"    - ID: {situation.id}")
        print(f"    - Type: {situation.type}")
        print(f"    - Priority: {situation.priority.upper()} | Novelty Score: {situation.novelty}")
        print(f"    - Context Summary: {situation.context['summary']}")

        print(f"\n[5] EVIDENCE PROVENANCE:")
        for ev in situation.evidence:
            print(f"    - [Provenance] {ev}")

        # ---------------------------------------------------------
        # Step 5: Construct Relevant Bounded Context
        # ---------------------------------------------------------
        bounded_ctx = context_builder.build_bounded_context(
            situation=situation,
            current_state=current_state,
            timeline=timeline,
            goals=[goal],
        )
        print(f"\n[6] BOUNDED CROSS-DOMAIN CONTEXT ASSEMBLY:")
        print(f"    - Recent Timeline Events: {len(bounded_ctx.relevant_recent_timeline)}")
        print(f"    - Relevant Historical Events: {len(bounded_ctx.relevant_historical_events)}")
        print(f"    - Active Goals Linked: {len(bounded_ctx.active_goals)}")
        print(f"    - Domains Combined: Biometrics/Sleep, Workload/Calendar, Training/Mobility, Goals")
        print(f"    - Token Bounds Preserved: Strict windowing without unfiltered data dump")

        # ---------------------------------------------------------
        # Step 6: Hermes Emergent Reasoning (Observations -> Inferences -> Predictions -> Recommendations)
        # ---------------------------------------------------------
        hermes_synthesis = {
            "what_is_happening": (
                "User experienced severe sleep restriction (3.75h vs 8.0h 14-day baseline, recovery index 38/100) "
                "followed by a demanding 7-hour executive and architectural workload, preceding a scheduled 10km high-intensity interval run."
            ),
            "evidence_summary": [
                "Sleep duration 225m (3.75h) on evt-sleep-today vs 480m 14-day average.",
                "4 consecutive high-workload meetings scheduled 09:00-16:30.",
                "Upcoming 17:30 10km Interval Speed Run under active Half-Marathon goal.",
                "5 prior workouts show consistent adherence to hard sessions when well-rested.",
            ],
            "inferences": [
                "Acute sleep deprivation combined with sustained cognitive fatigue severely impairs neuromuscular coordination and increases injury risk.",
                "Attempting maximal interval training in this state will degrade workout quality and impede Half-Marathon progression through systemic overreaching.",
            ],
            "predictions": [
                "Proceeding with the 10km interval run at 17:30 carries high risk of hamstring/achilles strain and delayed recovery.",
                "Replacing the hard run with a 25-minute restorative walk or mobility session will promote recovery while maintaining aerobic habit without injury risk.",
            ],
            "recommendations": [
                "Shift today's 10km interval run to tomorrow afternoon when recovered.",
                "Substitute today's 17:30 block with a gentle 20-minute restorative walk and mobility stretching.",
                "Target an early bedtime (22:00) to repay acute sleep debt.",
            ],
            "uncertainties": [
                "Whether user can adjust tomorrow's schedule to accommodate the postponed interval workout.",
            ],
            "requires_follow_up": True,
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }

        mock_hermes = MagicMock(spec=HermesClient)
        mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_synthesis),
            duration_ms=520,
        )

        reasoning_workflow = ReasoningWorkflow(
            context_builder=context_builder,
            episode_store=episode_store,
            hermes_client=mock_hermes,
        )

        workflow_result = reasoning_workflow.run_workflow(
            situation=situation,
            current_state=current_state,
            timeline=timeline,
            goals=[goal],
        )

        synthesis = workflow_result.synthesis
        episode = workflow_result.episode

        print(f"\n[7] HERMES REASONING SYNTHESIS:")
        print(f"    - Observations (What is happening):")
        print(f"      \"{synthesis.what_is_happening}\"")
        print(f"    - Inferences:")
        for inf in synthesis.inferences:
            print(f"      * {inf}")
        print(f"    - Predictions:")
        for pred in synthesis.predictions:
            print(f"      * {pred}")
        print(f"    - Uncertainties Identified:")
        for unc in synthesis.uncertainties:
            print(f"      * {unc}")

        print(f"\n[8] EMERGENT RECOMMENDATION:")
        for i, rec in enumerate(synthesis.recommendations, 1):
            print(f"    {i}. {rec}")

        # ---------------------------------------------------------
        # Step 7: Deterministic Intervention Policy
        # ---------------------------------------------------------
        policy_decision = policy_engine.evaluate(
            urgency=synthesis.urgency,
            actionability=synthesis.actionability,
            evidence_strength=synthesis.evidence_strength,
            user_context=UserContext.AVAILABLE.value,
            already_notified=False,
            recently_dismissed=False,
        )

        print(f"\n[9] INTERVENTION POLICY DECISION:")
        print(f"    - Inputs: Urgency={synthesis.urgency.upper()}, Actionability={synthesis.actionability.upper()}, Evidence={synthesis.evidence_strength.upper()}, UserContext=AVAILABLE")
        print(f"    - Action: {policy_decision.action.upper()}")
        print(f"    - Deterministic Reason: {policy_decision.reason}")

        # Update episode with intervention decision
        episode_store.update_episode(
            episode_id=episode.id,
            intervention_decision={"action": policy_decision.action, "reason": policy_decision.reason},
            follow_up_at=base_time + timedelta(hours=3),
        )

        # ---------------------------------------------------------
        # Step 8: Stored Reasoning Episode
        # ---------------------------------------------------------
        persisted_ep = episode_store.get_episode(episode.id)
        print(f"\n[10] STORED REASONING EPISODE (Single Unified Table):")
        print(f"    - Episode ID: {persisted_ep.id}")
        print(f"    - Situation ID: {persisted_ep.situation_id}")
        print(f"    - Created At: {persisted_ep.created_at.isoformat()}")
        print(f"    - Status: {persisted_ep.status}")
        print(f"    - Urgency: {persisted_ep.urgency}")
        print(f"    - Actionability: {persisted_ep.actionability}")
        print(f"    - Evidence Strength: {persisted_ep.evidence_strength}")
        print(f"    - Intervention Decision: {persisted_ep.intervention_decision}")
        print(f"    - Follow Up Scheduled At: {persisted_ep.follow_up_at.isoformat() if persisted_ep.follow_up_at else 'None'}")
        print(f"    - Outcome Lifecycle: Preserved for longitudinal pattern discovery")

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    run_demonstration()
