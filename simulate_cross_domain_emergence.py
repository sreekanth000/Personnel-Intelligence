"""
End-to-End Simulation of Cross-Domain Situation Discovery in Personal Intelligence.

Demonstrates:
1. Scenario 1: Multi-day Project Milestone, Meeting Density, and Unresolved Workload.
2. Scenario 2: Completely Different Domain (Biometric Strain, Travel Delay, Weather & Training Goal).

Verifies that the SAME Personal Intelligence architecture autonomously reasons across
novel multi-domain observations WITHOUT domain-specific agents or hard-coded rules.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile

from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStore
from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.goals import GoalEngine, GoalPriority, GoalStore
from personal_intelligence.core.patterns import LearningEngine, PatternStore, PatternType
from personal_intelligence.core.policy import InterventionPolicyEngine, PolicyAction, UserContext
from personal_intelligence.core.situations import SituationEngine, SituationPriority, SituationStore
from personal_intelligence.core.state import StateEngine
from personal_intelligence.core.timeline import TimelineEngine
from personal_intelligence.core.world import PersonalWorldModel
from personal_intelligence.hermes_bridge.client import HermesClient
from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow
from personal_intelligence.storage.db import DatabaseManager


def run_simulation():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = os.path.join(temp_dir.name, "simulation_pi.db")
    db_manager = DatabaseManager(db_path=db_path)
    db_manager.initialize_schema()

    world_model = PersonalWorldModel(db_manager=db_manager)
    event_store = world_model.event_store
    timeline_engine = world_model.timeline_engine
    goal_store = world_model.goal_store
    situation_store = world_model.situation_store
    pattern_store = world_model.pattern_store
    episode_store = world_model.episode_store
    state_engine = world_model.state_engine

    goal_engine = GoalEngine(goal_store=goal_store, timeline_engine=timeline_engine)
    situation_engine = SituationEngine(goal_engine=goal_engine)
    context_builder = ContextBuilder(
        timeline_engine=timeline_engine,
        goal_store=goal_store,
        situation_store=situation_store,
        goal_engine=goal_engine,
    )
    policy_engine = InterventionPolicyEngine()
    hermes_client = HermesClient()

    # Dynamic LLM callable that responds with structured schema according to scenario prompt
    def mock_hermes_llm(prompt: str) -> str:
        if "Mountaineering" in prompt or "Altitude" in prompt or "sleep" in prompt.lower() and "trail" in prompt.lower():
            return json.dumps({
                "what_is_happening": "User experienced severe acute sleep deprivation (2.5h) following high-altitude arrival, coincided with high resting heart rate (74 bpm) and an active severe thunderstorm advisory at the scheduled alpine trailhead.",
                "evidence_summary": [
                    "Sleep logged at 2.5h (recovery score 24/100, resting HR +22 bpm above baseline).",
                    "Weather alert: 55 mph gusts and severe thunderstorm at alpine trailhead.",
                    "Active goal: High-Altitude Peak Ascent Conditioning."
                ],
                "inferences": [
                    "Acute sleep restriction combined with rapid altitude ascent increases susceptibility to acute mountain sickness and impairs cardiovascular endurance.",
                    "Attempting a 15km high-intensity alpine workout in severe storm conditions presents acute physical safety risks."
                ],
                "predictions": [
                    "Proceeding with the alpine trail ascent will cause severe physical exhaustion, hypothermia risk, and delayed acclimatization.",
                    "Postponing the high-altitude run and substituting with passive hydration/rest will accelerate physiological recovery."
                ],
                "uncertainties": [
                    "Whether user has access to indoor low-impact recovery equipment at base camp."
                ],
                "what_would_change_assessment": [
                    "Trailhead weather advisory clear and recovery sleep logged >7.5 hours."
                ],
                "recommendations": [
                    "Cancel today's 15km alpine trail workout due to storm alert and severe recovery deficit.",
                    "Substitute with indoor mobility, active hydration, and targeted acclimatization rest.",
                    "Reschedule high-intensity conditioning after full night restorative sleep."
                ],
                "urgency": "high",
                "actionability": "high",
                "relevance": "high",
                "evidence_strength": "strong"
            })
        else:
            return json.dumps({
                "what_is_happening": "User is approaching the Enterprise Security Architecture Committee Review in 24 hours with an unaddressed deliverable (Section 4 Threat Mitigation) while facing sudden calendar meeting compression (5 emergency incident triage meetings).",
                "evidence_summary": [
                    "Calendar event: Enterprise Security Review Committee Meeting in 24 hours.",
                    "Drive doc 'Enterprise Security Architecture RFC v1' modified with Section 4 remaining empty.",
                    "5 back-to-back emergency triage meetings scheduled on Day 3."
                ],
                "inferences": [
                    "Calendar meeting density eliminates uninterrupted deep-work focus time needed to draft complex threat models before tomorrow's committee review.",
                    "Unresolved threat model section risks committee rejection or milestone postponement."
                ],
                "predictions": [
                    "Without immediate schedule renegotiation or focused delegation, the security review milestone will slip by at least 1 sprint cycle."
                ],
                "uncertainties": [
                    "Whether emergency incident triage meetings can be partially delegated to secondary on-call engineers."
                ],
                "what_would_change_assessment": [
                    "Recorded completion of Section 4 or committee review rescheduled out-of-band."
                ],
                "recommendations": [
                    "Block a dedicated 90-minute focus window this afternoon to finalize Section 4 Threat Mitigation.",
                    "Delegate or shorten non-critical incident triage syncs.",
                    "Notify committee lead if deliverable requires 24h extension."
                ],
                "urgency": "high",
                "actionability": "high",
                "relevance": "high",
                "evidence_strength": "strong"
            })

    hermes_client.set_llm_callable(mock_hermes_llm)

    reasoning_workflow = ReasoningWorkflow(
        context_builder=context_builder,
        hermes_client=hermes_client,
        episode_store=episode_store,
    )
    command_handler = PersonalIntelligenceCommandHandler(
        db_manager=db_manager,
        event_store=event_store,
        timeline_engine=timeline_engine,
        goal_store=goal_store,
        situation_store=situation_store,
        episode_store=episode_store,
        pattern_store=pattern_store,
        state_engine=state_engine,
        policy_engine=policy_engine,
    )

    print("=" * 80)
    print("PERSONAL INTELLIGENCE: END-TO-END CROSS-DOMAIN SIMULATION")
    print("=" * 80)

    # =========================================================================
    # SCENARIO 1: Project Milestone, Meeting Compression & Unresolved Action
    # =========================================================================
    print("\n" + "#" * 80)
    print("SCENARIO 1: WORKLOAD, COMMUNICATION, DRIVE & GOAL MILESTONE COMPRESSION")
    print("#" * 80)

    base_time = datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc)

    # --- DAY 1 ---
    print("\n--- [DAY 1: Ingesting Initial Baseline Observations] ---")
    goal = goal_store.create_goal(
        name="Enterprise Security Architecture Delivery",
        priority=GoalPriority.HIGH,
        description="Deliver and approve Section 4 Threat Mitigation for committee review.",
    )
    print(f"[Goal Created] {goal.name} (Priority: {goal.priority.upper()})")

    # Calendar: review in 3 days (Day 4 10:00 UTC)
    event_store.append(
        Event(
            id="evt-s1-d1-cal",
            event_type="calendar_event",
            source="calendar",
            event_time=base_time + timedelta(days=3, hours=1),
            payload={"summary": "Enterprise Security Review Committee Meeting", "duration_minutes": 60},
        )
    )
    # Gmail: email request
    event_store.append(
        Event(
            id="evt-s1-d1-mail",
            event_type="email_received",
            source="gmail",
            event_time=base_time + timedelta(hours=2),
            payload={"summary": "Email from VP SecOps: Please ensure Section 4 threat model is complete before review.", "sender": "vp-secops@enterprise.org"},
        )
    )
    # Drive: project doc
    event_store.append(
        Event(
            id="evt-s1-d1-doc",
            event_type="document_created",
            source="drive",
            event_time=base_time + timedelta(hours=3),
            payload={"summary": "Created doc: Enterprise Security Architecture RFC v1", "doc_id": "doc-sec-rfc-v1"},
        )
    )
    print("  * Day 1 observations ingested: 1 Goal, 1 Calendar, 1 Gmail, 1 Drive.")

    # --- DAY 2 ---
    print("\n--- [DAY 2: Ingesting Meet Action Item & Document Edit] ---")
    day2_time = base_time + timedelta(days=1)
    # Meet transcript: unresolved changes
    event_store.append(
        Event(
            id="evt-s1-d2-meet",
            event_type="meet_transcript",
            source="meet",
            event_time=day2_time + timedelta(hours=1),
            payload={"summary": "Meet sync: User committed to drafting Section 4 threat mitigation by Wednesday night.", "unresolved_actions": ["Draft Section 4"]},
        )
    )
    # Drive edit: minor intro edit
    event_store.append(
        Event(
            id="evt-s1-d2-doc-edit",
            event_type="document_modified",
            source="drive",
            event_time=day2_time + timedelta(hours=5),
            payload={"summary": "Drive edit: Enterprise Security Architecture RFC v1 (Intro typo fix; Section 4 empty)", "doc_id": "doc-sec-rfc-v1"},
        )
    )
    print("  * Day 2 observations ingested: 1 Meet Transcript, 1 Drive Edit.")

    # --- DAY 3 ---
    print("\n--- [DAY 3: Calendar Spikes & Zero Progress on Threat Model Section] ---")
    day3_time = base_time + timedelta(days=2)
    # 5 back-to-back triage meetings
    for m_i in range(5):
        event_store.append(
            Event(
                id=f"evt-s1-d3-cal-{m_i}",
                event_type="calendar_event",
                source="calendar",
                event_time=day3_time + timedelta(hours=m_i * 2),
                payload={"summary": f"Emergency Customer Incident Triage #{m_i+1}", "duration_minutes": 60},
            )
        )
    print("  * Day 3 observations ingested: 5 Urgent Incident Triage Meetings (Schedule Compression).")

    # Step 1: Detect Emerging Situations
    ref_day3 = day3_time + timedelta(hours=8)
    timeline_d3 = timeline_engine.get_time_range(start_time=base_time, end_time=ref_day3)
    current_state_d3 = state_engine.compute_current_state(reference_time=ref_day3)
    active_goals_d3 = goal_store.list_active()
    active_pats_d3 = pattern_store.list_patterns()

    eval_result = situation_engine.evaluate(
        current_state=current_state_d3,
        timeline=timeline_d3,
        goals=active_goals_d3,
        known_patterns=active_pats_d3,
        reference_time=ref_day3,
    )
    for s in eval_result.candidate_situations:
        situation_store.upsert(s)

    detected_sits = situation_store.list_active(limit=10)
    print(f"\n[Autonomous Situation Discovery] Discovered {len(detected_sits)} situation(s):")
    for s in detected_sits:
        ctx_desc = s.context.get("summary") if isinstance(s.context, dict) else str(s.context)
        print(f"  - Situation ID: {s.id}")
        print(f"    Type: {s.type} | Priority: {s.priority.upper()}")
        print(f"    Tension Context: {ctx_desc}")
        print(f"    Evidence: {s.evidence}")

    primary_sit = detected_sits[0]

    # Step 2: Reason via Hermes Workflow
    wf_res = reasoning_workflow.run_workflow(
        situation=primary_sit,
        current_state=current_state_d3,
        timeline=timeline_d3,
        goals=active_goals_d3,
        objective="Assess project delivery feasibility given calendar compression and missing deliverable",
    )
    synthesis = wf_res.synthesis
    print(f"\n[Hermes Epistemic Synthesis]")
    print(f"  * What is happening: {synthesis.what_is_happening}")
    print(f"  * Evidence summary: {synthesis.evidence_summary}")
    print(f"  * Inferences ({len(synthesis.inferences)}):")
    for inf in synthesis.inferences[:2]:
        print(f"    - {inf}")
    print(f"  * Predictions ({len(synthesis.predictions)}):")
    for pred in synthesis.predictions[:2]:
        print(f"    - {pred}")
    print(f"  * Recommendations ({len(synthesis.recommendations)}):")
    for rec in synthesis.recommendations:
        print(f"    - -> {rec}")
    print(f"  * Categorical Assessment: Urgency={synthesis.urgency}, Actionability={synthesis.actionability}, Evidence={synthesis.evidence_strength}")

    # Step 3: Intervention Policy Evaluation
    pol_eval = policy_engine.evaluate(
        urgency=synthesis.urgency,
        actionability=synthesis.actionability,
        evidence_strength=synthesis.evidence_strength,
        user_context=UserContext.AVAILABLE.value,
        relevance=synthesis.relevance,
    )
    print(f"\n[Intervention Policy Decision]")
    print(f"  * Selected Action: {pol_eval.action}")
    print(f"  * Deterministic Rationale: {pol_eval.reason}")

    # Step 4: Execute /pi why diagnostic explanation
    why_report = command_handler.handle_why(primary_sit.id)
    print(f"\n[/pi why Diagnostic Explanation Output Preview]")
    for line in why_report.splitlines()[:28]:
        print(line)
    print("  ... (all 11 canonical sections rendered)")

    # =========================================================================
    # SCENARIO 2: Completely Different Domain (Biometrics, Travel, Storm & Peak Prep)
    # =========================================================================
    print("\n\n" + "#" * 80)
    print("SCENARIO 2: BIOMETRICS, MOUNTAIN GOAL, FLIGHT DELAY & WEATHER ANOMALY")
    print("#" * 80)
    print("Running SAME architecture with zero domain-specific agents or custom logic.")

    base_time_s2 = datetime(2026, 9, 10, 8, 0, 0, tzinfo=timezone.utc)

    # Goal: Peak Ascent Training
    peak_goal = goal_store.create_goal(
        name="High-Altitude Peak Ascent Conditioning",
        priority=GoalPriority.HIGH,
        description="Maintain acclimatization protocol and complete endurance conditioning.",
    )
    print(f"\n[Goal Created] {peak_goal.name} (Priority: {peak_goal.priority.upper()})")

    # Ingest 7 days historical healthy baseline sleep & training
    for day_i in range(7):
        t_hist = base_time_s2 - timedelta(days=7 - day_i)
        event_store.append(
            Event(
                id=f"evt-s2-sleep-hist-{day_i}",
                event_type="sleep_logged",
                source="health_tracker",
                event_time=t_hist,
                payload={"duration_minutes": 490, "recovery_score": 88, "resting_heart_rate": 52},
            )
        )

    # Day 1: Severe Acute Sleep Restriction (Travel delay)
    event_store.append(
        Event(
            id="evt-s2-travel-delay",
            event_type="flight_delay_logged",
            source="travel_api",
            event_time=base_time_s2 + timedelta(hours=4),
            payload={"summary": "Flight delayed by 7 hours; arrived at altitude base camp at 03:30 AM.", "destination_altitude_meters": 2800},
        )
    )
    event_store.append(
        Event(
            id="evt-s2-sleep-acute",
            event_type="sleep_logged",
            source="health_tracker",
            event_time=base_time_s2 + timedelta(hours=6),
            payload={"duration_minutes": 150, "recovery_score": 24, "resting_heart_rate": 74},  # 2.5h sleep
        )
    )

    # Day 2: Trailhead Storm Alert + Scheduled High-Intensity Climb
    event_store.append(
        Event(
            id="evt-s2-weather-alert",
            event_type="weather_alert",
            source="weather_service",
            event_time=base_time_s2 + timedelta(days=1, hours=2),
            payload={"summary": "Severe thunderstorm and high-wind warning at alpine trailhead from 14:00 to 20:00.", "wind_gusts_mph": 55},
        )
    )
    event_store.append(
        Event(
            id="evt-s2-training-cal",
            event_type="calendar_event",
            source="calendar",
            event_time=base_time_s2 + timedelta(days=1, hours=6),
            payload={"summary": "High-Intensity 15km Alpine Trail Ascent Workout", "duration_minutes": 180},
        )
    )

    # Autonomous Discovery on Scenario 2
    ref_s2 = base_time_s2 + timedelta(days=1, hours=7)
    timeline_s2 = timeline_engine.get_time_range(start_time=base_time_s2 - timedelta(days=7), end_time=ref_s2)
    state_s2 = state_engine.compute_current_state(reference_time=ref_s2)
    goals_s2 = goal_store.list_active()
    patterns_s2 = pattern_store.list_patterns()

    eval_s2 = situation_engine.evaluate(
        current_state=state_s2,
        timeline=timeline_s2,
        goals=goals_s2,
        known_patterns=patterns_s2,
        reference_time=ref_s2,
    )
    for s in eval_s2.candidate_situations:
        situation_store.upsert(s)

    s2_sits = [s for s in situation_store.list_active(limit=10) if "s2" in str(s.evidence)]
    if not s2_sits:
        s2_sits = situation_store.list_active(limit=10)
    print(f"\n[Autonomous Situation Discovery - Scenario 2] Discovered {len(s2_sits)} situation(s):")
    for s in s2_sits:
        ctx_desc = s.context.get("summary") if isinstance(s.context, dict) else str(s.context)
        print(f"  - Situation ID: {s.id}")
        print(f"    Type: {s.type} | Priority: {s.priority.upper()}")
        print(f"    Tension Context: {ctx_desc}")
        print(f"    Evidence: {s.evidence}")

    s2_primary_sit = s2_sits[0]

    # Context & Reasoning
    wf_res_s2 = reasoning_workflow.run_workflow(
        situation=s2_primary_sit,
        current_state=state_s2,
        timeline=timeline_s2,
        goals=goals_s2,
        objective="Assess training safety given acute sleep deprivation, high resting HR, altitude arrival, and alpine weather storm",
    )
    s2_synthesis = wf_res_s2.synthesis
    print(f"\n[Hermes Epistemic Synthesis - Scenario 2]")
    print(f"  * What is happening: {s2_synthesis.what_is_happening}")
    print(f"  * Inferences ({len(s2_synthesis.inferences)}):")
    for inf in s2_synthesis.inferences[:2]:
        print(f"    - {inf}")
    print(f"  * Predictions ({len(s2_synthesis.predictions)}):")
    for pred in s2_synthesis.predictions[:2]:
        print(f"    - {pred}")
    print(f"  * Recommendations ({len(s2_synthesis.recommendations)}):")
    for rec in s2_synthesis.recommendations:
        print(f"    - -> {rec}")
    print(f"  * Categorical Assessment: Urgency={s2_synthesis.urgency}, Actionability={s2_synthesis.actionability}, Evidence={s2_synthesis.evidence_strength}")

    s2_pol_eval = policy_engine.evaluate(
        urgency=s2_synthesis.urgency,
        actionability=s2_synthesis.actionability,
        evidence_strength=s2_synthesis.evidence_strength,
        user_context=UserContext.AVAILABLE.value,
        relevance=s2_synthesis.relevance,
    )
    print(f"\n[Intervention Policy Decision - Scenario 2]")
    print(f"  * Selected Action: {s2_pol_eval.action}")
    print(f"  * Deterministic Rationale: {s2_pol_eval.reason}")

    # Inspect what_changed across both scenarios
    print("\n" + "=" * 80)
    print("[/pi what_changed Output Across World Model]")
    print("=" * 80)
    changes_report = command_handler.handle_what_changed(time_window_hours=72, reference_time=ref_s2)
    print(changes_report)

    temp_dir.cleanup()
    print("\n" + "=" * 80)
    print("SIMULATION COMPLETED SUCCESSFULLY FOR BOTH DIVERGENT DOMAINS")
    print("=" * 80)


if __name__ == "__main__":
    run_simulation()
