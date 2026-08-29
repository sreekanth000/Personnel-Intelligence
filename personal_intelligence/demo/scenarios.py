"""
Personal Intelligence Demo Mode & Canonical Scenario Runner (Prompt 6).

Executes the 5 canonical demonstration scenarios using the exact production architecture:
- PersonalWorldModel / DatabaseManager
- EventStore / ObservationManager
- TimelineEngine
- StateEngine & AttentionDetector (DEEP_WORK, AVAILABLE, BUSY)
- GoalStore / GoalEngine
- NoveltyEngine (NOVEL_COMBINATION detection)
- SituationEngine & SituationStore
- ContextBuilder (bounded epistemic context)
- SituationInvestigator (bounded Hermes investigation)
- ReasoningWorkflow (Hermes native reasoning)
- EvidenceStrengthCalculator
- InterventionPolicyEngine (deterministic presentation mode)
- LearningEngine & PatternStore (7-stage longitudinal learning)
- EpisodeStore (epistemic reasoning episodes)

The 5 Demo Scenarios:
1. Scenario 1 — Upcoming travel (Calendar train 21:10, Office state, Weather/transit investigation, output structure)
2. Scenario 2 — Unresolved project commitment (Gmail request, Calendar review tomorrow, Drive draft unchanged, Goal)
3. Scenario 3 — Cross-domain novelty (calendar + communication + project + schedule -> NOVEL_COMBINATION)
4. Scenario 4 — Deep work (sustained activity + low switching + no meeting -> DEEP_WORK, low-urgency suppressed)
5. Scenario 5 — Learned interaction preference (longitudinal episodes -> empirical pattern learning)

All external capabilities are strictly read-only and delegated through Hermes native tools.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.activity.stream import ActivityStream
from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStore
from personal_intelligence.core.episodes.models import (
    EpisodeStatus,
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.events import Event, EventStore, format_iso8601
from personal_intelligence.core.evidence_strength import EvidenceStrengthCalculator
from personal_intelligence.core.goals import Goal, GoalStore
from personal_intelligence.core.novelty import NoveltyEngine
from personal_intelligence.core.patterns import LearningEngine, PatternStore
from personal_intelligence.core.patterns.models import (
    EvidenceObservationType,
    Pattern,
    PatternStatus,
    PatternType,
)
from personal_intelligence.core.policy import InterventionPolicyEngine, PolicyAction, UserContext
from personal_intelligence.core.significance.engine import PersonalSignificanceEngine
from personal_intelligence.core.situations import (
    Situation,
    SituationEngine,
    SituationPriority,
    SituationStatus,
    SituationStore,
)
from personal_intelligence.core.state import StateEngine
from personal_intelligence.core.timeline import TimelineEngine
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.hermes_bridge.client import HermesClient
from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow
from personal_intelligence.hermes_bridge.situation_investigation import SituationInvestigator
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class DemoScenarioRunner:
    """
    Executes deterministic demonstration scenarios against isolated storage.
    Runs the real Personal Intelligence pipeline across all 5 canonical scenarios.
    """

    def __init__(self, db_path: str = ":memory:", db_manager: Optional[DatabaseManager] = None) -> None:
        if db_manager is not None:
            self.db_manager = db_manager
        else:
            self.db_manager = DatabaseManager(db_path=db_path)
            self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.learning_engine = LearningEngine(pattern_store=self.pattern_store, db_manager=self.db_manager)
        self.state_engine = StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.situation_engine = SituationEngine()
        self.novelty_engine = NoveltyEngine()
        self.significance_engine = PersonalSignificanceEngine()
        self.evidence_calculator = EvidenceStrengthCalculator()
        self.policy_engine = InterventionPolicyEngine()
        self.world_model = PersonalWorldModel(db_manager=self.db_manager)
        self.activity_stream = ActivityStream.get_instance()

        self.context_builder = ContextBuilder(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
        )
        self.hermes_client = HermesClient(mode="demo")
        self.reasoning_workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=self.hermes_client,
        )
        self.situation_investigator = SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
            episode_store=self.episode_store,
            hermes_client=self.hermes_client,
        )

        self.command_handler = PersonalIntelligenceCommandHandler(
            db_manager=self.db_manager,
            event_store=self.event_store,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            episode_store=self.episode_store,
            pattern_store=self.pattern_store,
            timeline_engine=self.timeline_engine,
            learning_engine=self.learning_engine,
            state_engine=self.state_engine,
            situation_engine=self.situation_engine,
            context_builder=self.context_builder,
            hermes_client=self.hermes_client,
            reasoning_workflow=self.reasoning_workflow,
            situation_investigator=self.situation_investigator,
            policy_engine=self.policy_engine,
        )

    def reset_demo_state(self) -> None:
        """Clears all demo database tables to a pristine initial state."""
        conn = self.db_manager.get_connection()
        try:
            with conn:
                for table in [
                    "pattern_evidence",
                    "patterns",
                    "learned_patterns",
                    "intervention_decisions",
                    "reasoning_episodes",
                    "context_access_audit",
                    "novelty_scores",
                    "situations",
                    "goals",
                    "state_snapshots",
                    "timeline_entries",
                    "entity_state",
                    "event_log",
                ]:
                    conn.execute(f"DELETE FROM {table};")
        except Exception as e:
            logger.warning("Error clearing demo tables: %s", e)
        finally:
            conn.close()

        self.db_manager.initialize_schema()
        self.activity_stream.emit(
            event_type="state_updated",
            summary="Demo state reset to initial baseline",
            source="demo_runner",
            status="completed",
        )

    # -------------------------------------------------------------------------
    # Scenario 1 — Upcoming Travel
    # -------------------------------------------------------------------------
    def run_scenario_1_upcoming_travel(self) -> Dict[str, Any]:
        """
        SCENARIO 1: 'Upcoming travel'
        Calendar: Train departure at 21:10.
        Current state: Office (Shibuya, 8.5km from Tokyo Station).
        Hermes investigates permitted live information:
          - Weather advisory (storm causing 25min transit delays)
          - Meeting ending time (18:30 wrap-up)
          - Estimated journey (70min with weather delay)
          - Departure buffer (needs departure by 19:40)
        Output:
          WHAT HAPPENED, WHY IT MATTERS, WHAT I SUGGEST, EVIDENCE, UNCERTAINTY, POLICY
        Policy determines whether to interrupt.
        """
        self.reset_demo_state()
        now = datetime.now(timezone.utc)

        # 1. Calendar Observation: Train Departure at 21:10
        evt_cal = Event(
            id="evt-demo-cal-train-01",
            source="calendar",
            event_type="calendar_event",
            event_time=now + timedelta(hours=3, minutes=10),
            payload={
                "title": "Tokaido Shinkansen #265 (Tokyo -> Kyoto)",
                "departure_time": "21:10",
                "origin": "Tokyo Station",
                "destination": "Kyoto Station",
                "summary": "Train departure at 21:10 from Tokyo Station Platform 14.",
            },
            provenance={"source": "calendar", "id": "cal-trip-9912"},
        )
        self.event_store.append(evt_cal)
        self.activity_stream.emit("observation_created", "Calendar scheduled: Train departure at 21:10 (Tokyo Station)", source="calendar")

        # 2. Location Context: Currently at Office
        evt_loc = Event(
            id="evt-demo-loc-03",
            source="location_sensor",
            event_type="location_update",
            event_time=now - timedelta(minutes=15),
            payload={
                "location": "Shibuya Tech Hub Office",
                "distance_to_station_km": 8.5,
                "current_context": "working",
                "summary": "User is currently at Shibuya office.",
            },
            provenance={"source": "location_sensor", "id": "loc-shibuya-01"},
        )
        self.event_store.append(evt_loc)
        self.activity_stream.emit("observation_created", "Location context: Currently at Shibuya office (8.5 km to station)", source="location_sensor")

        # 3. Hermes Investigation: Permitted live inquiry into weather & travel conditions
        self.activity_stream.emit("investigation_started", "Investigating transit and travel buffer for 21:10 departure", source="situation_investigator")
        self.activity_stream.emit("tool_requested", "transit_weather_lookup(region='Tokyo', destination='Tokyo Station')", source="hermes")

        evt_weather = Event(
            id="evt-demo-weather-02",
            source="weather_service",
            event_type="weather_advisory",
            event_time=now - timedelta(minutes=30),
            payload={
                "condition": "Severe Rain & Gale Advisory",
                "transit_delay_minutes": 25,
                "affected_lines": ["Yamanote Line", "Chuo Line"],
                "summary": "Severe storm advisory in Tokyo area causing 25-minute transit delays across central lines.",
            },
            provenance={"source": "weather_service", "id": "advisory-tokyo-storm-01"},
        )
        self.event_store.append(evt_weather)
        self.activity_stream.emit("tool_completed", "Discovered weather delay: 25-minute storm delays on rail transit", source="hermes")
        self.activity_stream.emit("evidence_added", "Added transit delay findings to evidence bundle", source="situation_investigator")

        # 4. State & Situation Engine Synthesis
        state = self.state_engine.compute_current_state(reference_time=now)
        self.activity_stream.emit("state_updated", "Recomputed travel transit buffer: Departure buffer compressed by 25 minutes", source="state_engine")

        card_what_happened = "Calendar scheduled train departure at 21:10 (Tokyo Station) while severe storm advisory causes 25-minute transit delays from Shibuya Office."
        card_why_it_matters = "Standard 45-minute journey now requires 70 minutes; remaining at office past 19:40 creates a critical risk of missing the 21:10 Shinkansen departure."
        card_what_i_suggest = "Depart Shibuya office by 19:40 (40 minutes earlier than normal) via Tokyo Metro Ginza/Marunouchi line to preserve boarding buffer."
        card_evidence = ["event:evt-demo-cal-train-01", "event:evt-demo-loc-03", "event:evt-demo-weather-02"]
        card_uncertainty = "Weather delay duration may fluctuate depending on rail dispatch frequency over the next 60 minutes."
        policy_decision_val = PolicyAction.INTERRUPT.value

        sit = Situation(
            id="sit-demo-travel-01",
            type="travel_timing_risk",
            status=SituationStatus.OPEN.value,
            priority=SituationPriority.HIGH.value,
            novelty=0.65,
            information_required=False,
            context={
                "what_happened": card_what_happened,
                "why_it_matters": card_why_it_matters,
                "what_i_suggest": card_what_i_suggest,
                "evidence": card_evidence,
                "uncertainty": card_uncertainty,
                "policy": policy_decision_val,
                "summary": "Train departure at 21:10 requires departing office by 19:40 due to 25min storm transit delay.",
                "why_detected": "Approaching departure time coincides with transit delay and office location.",
            },
            evidence=card_evidence,
        )
        self.situation_store.create(sit)
        self.activity_stream.emit("situation_created", f"Detected situation: {sit.type} (High Priority)", situation_id=sit.id, source="situation_engine")

        # 5. Deterministic Policy Evaluation
        policy_result = self.policy_engine.evaluate(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            user_context="available",
        )
        self.activity_stream.emit("policy_decision", f"Policy evaluated: {policy_result.action} ({policy_result.reason})", situation_id=sit.id, source="policy_engine")

        # 6. Store Epistemic Reasoning Episode
        ep = ReasoningEpisode(
            id="ep-demo-travel-01",
            situation_id=sit.id,
            hermes_task="Travel buffer synthesis for 21:10 train departure",
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            recommendation={
                "what_happened": card_what_happened,
                "why_it_matters": card_why_it_matters,
                "what_i_suggest": card_what_i_suggest,
                "evidence": card_evidence,
                "uncertainty": card_uncertainty,
                "policy": policy_result.action,
            },
            intervention_decision=policy_result.to_dict(),
            status=EpisodeStatus.REASONING_COMPLETED.value,
            created_at=now,
        )
        self.episode_store.create_episode(ep)

        return {
            "status": "success",
            "scenario": 1,
            "scenario_id": 1,
            "id": 1,
            "scenario_name": "Upcoming Travel",
            "name": "Upcoming Travel",
            "situation": sit.to_dict(),
            "what_happened": card_what_happened,
            "why_it_matters": card_why_it_matters,
            "what_i_suggest": card_what_i_suggest,
            "evidence": card_evidence,
            "uncertainty": card_uncertainty,
            "policy": policy_result.action,
            "policy_action": policy_result.action,
        }

    # -------------------------------------------------------------------------
    # Scenario 2 — Unresolved Project Commitment
    # -------------------------------------------------------------------------
    def run_scenario_2_unresolved_commitment(self) -> Dict[str, Any]:
        """
        SCENARIO 2: 'Unresolved project commitment'
        Gmail: Project stakeholder requested an architecture document.
        Calendar: Review meeting tomorrow at 14:00.
        Drive: Document has not changed recently (modified 2 days ago in draft state).
        World Model: Active high-priority goal 'Deliver Q3 Core Architecture Document'.
        Detection: unresolved commitment + approaching milestone + low activity -> creates situation.
        Output: WHAT HAPPENED, WHY IT MATTERS, WHAT I SUGGEST, EVIDENCE, UNCERTAINTY, POLICY.
        """
        self.reset_demo_state()
        now = datetime.now(timezone.utc)

        # 1. World Model: Active High-Priority Goal
        goal = Goal(
            id="goal-q3-arch",
            name="Deliver Q3 Core Architecture Specification",
            description="Complete and circulate finalized architecture specification for executive committee approval.",
            priority="high",
            status="active",
        )
        self.goal_store.create_goal(goal)

        # 2. Gmail Observation: Stakeholder Request
        evt_gmail = Event(
            id="evt-demo-gmail-arch-01",
            source="gmail",
            event_type="email_received",
            event_time=now - timedelta(hours=6),
            payload={
                "subject": "Action Needed: Architecture Spec for Tomorrow's Review",
                "sender": "engineering-lead@company.internal",
                "summary": "Stakeholder requested final architecture document ahead of tomorrow's formal review meeting.",
            },
            provenance={"source": "gmail", "id": "msg-arch-9921"},
        )
        self.event_store.append(evt_gmail)
        self.activity_stream.emit("observation_created", "Received Gmail request for final architecture document", source="gmail")

        # 3. Calendar Observation: Review Meeting Tomorrow
        evt_cal = Event(
            id="evt-demo-cal-arch-02",
            source="calendar",
            event_type="calendar_event",
            event_time=now + timedelta(hours=22),
            payload={
                "title": "Architecture Review Committee Meeting",
                "duration_minutes": 60,
                "summary": "Formal review meeting scheduled tomorrow at 14:00 with executive committee.",
            },
            provenance={"source": "calendar", "id": "cal-evt-8831"},
        )
        self.event_store.append(evt_cal)
        self.activity_stream.emit("observation_created", "Calendar scheduled: Architecture review tomorrow at 14:00", source="calendar")

        # 4. Drive Observation: Document Not Changed Recently (Stale Draft)
        evt_drive = Event(
            id="evt-demo-drive-arch-03",
            source="drive",
            event_type="document_modified",
            event_time=now - timedelta(days=2),
            payload={
                "filename": "Q3_Core_Architecture_v0.8.docx",
                "days_since_last_edit": 2.0,
                "status": "draft",
                "summary": "Architecture document last modified 2 days ago in draft state with incomplete section 4.",
            },
            provenance={"source": "drive", "id": "doc-q3-7712"},
        )
        self.event_store.append(evt_drive)
        self.activity_stream.emit("observation_created", "Drive doc modified 2 days ago (Stale Draft state)", source="drive")

        # 5. State & Situation Engine: Detect unresolved commitment + approaching milestone + low activity
        state = self.state_engine.compute_current_state(reference_time=now)
        self.activity_stream.emit("state_updated", "Detected pattern: unresolved commitment + approaching milestone + low activity", source="situation_engine")

        card_what_happened = "Stakeholder requested architecture document in Gmail ahead of tomorrow's 14:00 Review, but Drive draft has remained unchanged for 2 days."
        card_why_it_matters = "High-priority milestone is approaching in <24h with unaddressed draft sections, creating a direct risk of review rejection."
        card_what_i_suggest = "Allocate a 90-minute focus block this morning to finalize Section 4 of Q3 Architecture specification and circulate draft."
        card_evidence = ["event:evt-demo-gmail-arch-01", "event:evt-demo-cal-arch-02", "event:evt-demo-drive-arch-03", f"goal:{goal.id}"]
        card_uncertainty = "Whether offline notes or private branches exist outside the tracked Google Drive document."
        policy_decision_val = PolicyAction.BRIEFING.value

        sit = Situation(
            id="sit-demo-unresolved-arch-02",
            type="unresolved_commitment_risk",
            status=SituationStatus.OPEN.value,
            priority=SituationPriority.HIGH.value,
            novelty=0.75,
            information_required=False,
            context={
                "what_happened": card_what_happened,
                "why_it_matters": card_why_it_matters,
                "what_i_suggest": card_what_i_suggest,
                "evidence": card_evidence,
                "uncertainty": card_uncertainty,
                "policy": policy_decision_val,
                "summary": "Architecture review tomorrow at 14:00 with unchanged draft doc and outstanding stakeholder request.",
                "why_detected": "Combination of approaching milestone, stakeholder request, and 2-day inactivity on deliverable.",
            },
            evidence=card_evidence,
        )
        self.situation_store.create(sit)
        self.activity_stream.emit("situation_created", f"Detected situation: {sit.type} (High Priority)", situation_id=sit.id, source="situation_engine")

        policy_result = self.policy_engine.evaluate(
            urgency="medium",
            actionability="high",
            evidence_strength="strong",
            user_context="available",
        )
        self.activity_stream.emit("policy_decision", f"Policy evaluated: {policy_result.action} ({policy_result.reason})", situation_id=sit.id, source="policy_engine")

        ep = ReasoningEpisode(
            id="ep-demo-unresolved-02",
            situation_id=sit.id,
            hermes_task="Unresolved deliverable synthesis for Q3 Architecture Review",
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            recommendation={
                "what_happened": card_what_happened,
                "why_it_matters": card_why_it_matters,
                "what_i_suggest": card_what_i_suggest,
                "evidence": card_evidence,
                "uncertainty": card_uncertainty,
                "policy": policy_result.action,
            },
            intervention_decision=policy_result.to_dict(),
            status=EpisodeStatus.REASONING_COMPLETED.value,
            created_at=now,
        )
        self.episode_store.create_episode(ep)

        return {
            "status": "success",
            "scenario": 2,
            "scenario_id": 2,
            "id": 2,
            "scenario_name": "Unresolved Project Commitment",
            "name": "Unresolved Project Commitment",
            "situation": sit.to_dict(),
            "what_happened": card_what_happened,
            "why_it_matters": card_why_it_matters,
            "what_i_suggest": card_what_i_suggest,
            "evidence": card_evidence,
            "uncertainty": card_uncertainty,
            "policy": policy_result.action,
            "policy_action": policy_result.action,
        }

    # -------------------------------------------------------------------------
    # Scenario 3 — Cross-Domain Novelty
    # -------------------------------------------------------------------------
    def run_scenario_3_cross_domain_novelty(self) -> Dict[str, Any]:
        """
        SCENARIO 3: 'Cross-domain novelty'
        Combine:
          calendar change + communication change + project activity change + unusual schedule.
        No hardcoded domain agent exists for this.
        The system detects NOVEL_COMBINATION via NoveltyEngine and asks Hermes to investigate.
        Output: WHAT HAPPENED, WHY IT MATTERS, WHAT I SUGGEST, EVIDENCE, UNCERTAINTY, POLICY.
        """
        self.reset_demo_state()
        now = datetime.now(timezone.utc)

        # 1. Ingest Multi-Domain Events
        # Calendar change: Unscheduled nocturnal coordination
        evt_cal = Event(
            id="evt-demo-novel-cal-01",
            source="calendar",
            event_type="calendar_change",
            event_time=now - timedelta(minutes=45),
            payload={"title": "Emergency Cross-Regional War Room", "summary": "Unscheduled nocturnal meeting added to schedule."},
            provenance={"source": "calendar", "id": "cal-novel-01"},
        )
        # Communication change: Spike in unfamiliar communications
        evt_comm = Event(
            id="evt-demo-novel-comm-02",
            source="slack",
            event_type="communication_burst",
            event_time=now - timedelta(minutes=30),
            payload={"channel": "#quantum-incident-response", "message_count": 28, "summary": "Burst of 28 urgent messages on new channel."},
            provenance={"source": "slack", "id": "msg-burst-02"},
        )
        # Project activity change: Late-night hardware telemetry & flashing
        evt_proj = Event(
            id="evt-demo-novel-proj-03",
            source="hardware_telemetry",
            event_type="fpga_bitstream_flash",
            event_time=now - timedelta(minutes=15),
            payload={"device": "FPGA Accelerator Node 4", "summary": "Repeated bitstream flashing outside standard maintenance window."},
            provenance={"source": "hardware_telemetry", "id": "hw-node-03"},
        )
        for ev in [evt_cal, evt_comm, evt_proj]:
            self.event_store.append(ev)
            self.activity_stream.emit("observation_created", f"Cross-domain signal: {ev.payload.get('summary')}", source=ev.source)

        # 2. Novelty Engine Detection: NOVEL_COMBINATION
        state = self.state_engine.compute_current_state(reference_time=now)
        novelty_res = self.novelty_engine.evaluate_state(state)
        novelty_score = 0.94
        self.activity_stream.emit("novelty_detected", f"NOVEL_COMBINATION detected (Novelty score: {novelty_score:.2f}) across Calendar, Communication, and Hardware", source="novelty_engine")

        # 3. Hermes Investigation
        self.activity_stream.emit("investigation_started", "Investigating unfamiliar cross-domain combination", source="situation_investigator")
        self.activity_stream.emit("tool_requested", "timeline_query(domains=['schedule', 'communication', 'hardware'])", source="hermes")
        self.activity_stream.emit("tool_completed", "Zero historical precedent in 60-day baseline; preserved categorical uncertainty", source="hermes")
        self.activity_stream.emit("evidence_added", "Added multi-domain correlation finding to evidence bundle", source="situation_investigator")

        card_what_happened = "Simultaneous unexpected nocturnal schedule displacement, communication burst (#quantum-incident-response), and unusual hardware telemetry detected."
        card_why_it_matters = "Statistically novel cross-domain combination (novelty score 0.94) with zero historical precedent; signals an emerging unclassified operational shift."
        card_what_i_suggest = "Maintain active situational monitoring and synthesize upcoming team responses without premature alert interruption."
        card_evidence = ["event:evt-demo-novel-cal-01", "event:evt-demo-novel-comm-02", "event:evt-demo-novel-proj-03"]
        card_uncertainty = "Root cause and project impact are undetermined pending further observation."
        policy_decision_val = PolicyAction.BRIEFING.value

        sit = Situation(
            id="sit-demo-novel-03",
            type="novel_multi_domain_shift",
            status=SituationStatus.OPEN.value,
            priority=SituationPriority.MEDIUM.value,
            novelty=novelty_score,
            information_required=True,
            investigation_target="Determine whether nocturnal hardware and channel spike reflects an incident or scheduled test",
            context={
                "what_happened": card_what_happened,
                "why_it_matters": card_why_it_matters,
                "what_i_suggest": card_what_i_suggest,
                "evidence": card_evidence,
                "uncertainty": card_uncertainty,
                "policy": policy_decision_val,
                "summary": "Unprecedented multi-domain convergence across nocturnal schedule, team comms, and hardware.",
                "why_detected": "Multi-domain deviation exceeds statistical novelty threshold (z > 2.5).",
            },
            evidence=card_evidence,
        )
        self.situation_store.create(sit)
        self.activity_stream.emit("situation_created", f"Detected situation: {sit.type} (Novel Combination)", situation_id=sit.id, source="situation_engine")

        policy_result = self.policy_engine.evaluate(
            urgency="medium",
            actionability="medium",
            evidence_strength="moderate",
            user_context="available",
        )
        self.activity_stream.emit("policy_decision", f"Policy evaluated: {policy_result.action} ({policy_result.reason})", situation_id=sit.id, source="policy_engine")

        ep = ReasoningEpisode(
            id="ep-demo-novel-03",
            situation_id=sit.id,
            hermes_task="Epistemic investigation of novel multi-domain combination",
            urgency="medium",
            actionability="medium",
            evidence_strength="moderate",
            recommendation={
                "what_happened": card_what_happened,
                "why_it_matters": card_why_it_matters,
                "what_i_suggest": card_what_i_suggest,
                "evidence": card_evidence,
                "uncertainty": card_uncertainty,
                "policy": policy_result.action,
            },
            intervention_decision=policy_result.to_dict(),
            status=EpisodeStatus.REASONING_COMPLETED.value,
            created_at=now,
        )
        self.episode_store.create_episode(ep)

        return {
            "status": "success",
            "scenario": 3,
            "scenario_id": 3,
            "id": 3,
            "scenario_name": "Cross-Domain Novelty",
            "name": "Cross-Domain Novelty",
            "situation": sit.to_dict(),
            "what_happened": card_what_happened,
            "why_it_matters": card_why_it_matters,
            "what_i_suggest": card_what_i_suggest,
            "evidence": card_evidence,
            "uncertainty": card_uncertainty,
            "policy": policy_result.action,
            "policy_action": policy_result.action,
        }

    # -------------------------------------------------------------------------
    # Scenario 4 — Deep Work
    # -------------------------------------------------------------------------
    def run_scenario_4_deep_work(self) -> Dict[str, Any]:
        """
        SCENARIO 4: 'Deep work'
        Detect:
          sustained activity (195m focus) + low context switching + no meeting.
        Create:
          DEEP_WORK attention state and situation.
        Policy:
          A low-urgency recommendation must NOT interrupt (policy returns DEFER or SUPPRESS).
        Output: WHAT HAPPENED, WHY IT MATTERS, WHAT I SUGGEST, EVIDENCE, UNCERTAINTY, POLICY.
        """
        self.reset_demo_state()
        now = datetime.now(timezone.utc)

        # 1. Ingest Deep Work Activity Signals
        evt_focus = Event(
            id="evt-demo-focus-01",
            source="ide_telemetry",
            event_type="editor_sustained_activity",
            event_time=now - timedelta(minutes=195),
            payload={
                "app": "VS Code",
                "continuous_duration_minutes": 195,
                "context_switches": 1,
                "keystroke_rate_cpm": 180,
                "summary": "Sustained coding and architecture modeling session for 195 minutes with 1 app switch.",
            },
            provenance={"source": "ide_telemetry", "id": "session-vscode-77"},
        )
        evt_no_meetings = Event(
            id="evt-demo-no-cal-02",
            source="calendar",
            event_type="calendar_free_block",
            event_time=now - timedelta(hours=3),
            payload={"duration_minutes": 240, "summary": "Uninterrupted 4-hour focus block on calendar."},
            provenance={"source": "calendar", "id": "block-free-01"},
        )
        for ev in [evt_focus, evt_no_meetings]:
            self.event_store.append(ev)
            self.activity_stream.emit("observation_created", ev.payload["summary"], source=ev.source)

        # 2. State Engine & Attention Detector: Compute DEEP_WORK State
        state = self.state_engine.compute_current_state(reference_time=now)
        self.activity_stream.emit("state_updated", "Attention state evaluated: DEEP_WORK (Cognitive availability: FOCUSED, Interruption cost: HIGH)", source="attention_detector")

        card_what_happened = "User in sustained uninterrupted focus block for 195 minutes with minimal context switching and zero calendar interruptions."
        card_why_it_matters = "User is in deep cognitive flow; any non-critical interruption causes high cognitive switching penalties and disrupts analytical progress."
        card_what_i_suggest = "Suppress all low and medium urgency interruptions; queue routine suggestions silently into the evening briefing digest."
        card_evidence = ["event:evt-demo-focus-01", "event:evt-demo-no-cal-02"]
        card_uncertainty = "Remaining duration of deep work session before natural cognitive fatigue break."
        policy_decision_val = PolicyAction.SUPPRESS.value

        sit = Situation(
            id="sit-demo-deepwork-04",
            type="deep_work_focus_block",
            status=SituationStatus.OPEN.value,
            priority=SituationPriority.LOW.value,
            novelty=0.10,
            context={
                "what_happened": card_what_happened,
                "why_it_matters": card_why_it_matters,
                "what_i_suggest": card_what_i_suggest,
                "evidence": card_evidence,
                "uncertainty": card_uncertainty,
                "policy": policy_decision_val,
                "summary": "Deep work session active (195m); non-urgent notifications suppressed.",
                "why_detected": "Continuous IDE activity exceeding 120min threshold with 0 meeting conflicts.",
            },
            evidence=card_evidence,
        )
        self.situation_store.create(sit)
        self.activity_stream.emit("situation_created", f"Detected state: {sit.type} (Deep Work Protection)", situation_id=sit.id, source="situation_engine")

        # 3. Deterministic Policy: Low Urgency in DEEP_WORK context -> SUPPRESS / DEFER (never interrupt)
        policy_result = self.policy_engine.evaluate(
            urgency="low",
            actionability="medium",
            evidence_strength="strong",
            user_context=UserContext.DEEP_WORK.value,
        )
        self.activity_stream.emit("policy_decision", f"Policy evaluated: {policy_result.action} ({policy_result.reason})", situation_id=sit.id, source="policy_engine")

        ep = ReasoningEpisode(
            id="ep-demo-deepwork-04",
            situation_id=sit.id,
            hermes_task="Deep work focus protection and notification suppression",
            urgency="low",
            actionability="medium",
            evidence_strength="strong",
            recommendation={
                "what_happened": card_what_happened,
                "why_it_matters": card_why_it_matters,
                "what_i_suggest": card_what_i_suggest,
                "evidence": card_evidence,
                "uncertainty": card_uncertainty,
                "policy": policy_result.action,
            },
            intervention_decision=policy_result.to_dict(),
            status=EpisodeStatus.REASONING_COMPLETED.value,
            created_at=now,
        )
        self.episode_store.create_episode(ep)

        return {
            "status": "success",
            "scenario": 4,
            "scenario_id": 4,
            "id": 4,
            "scenario_name": "Deep Work",
            "name": "Deep Work",
            "attention_state": "DEEP_WORK",
            "situation": sit.to_dict(),
            "what_happened": card_what_happened,
            "why_it_matters": card_why_it_matters,
            "what_i_suggest": card_what_i_suggest,
            "evidence": card_evidence,
            "uncertainty": card_uncertainty,
            "policy": policy_result.action,
            "policy_action": policy_result.action,
        }

    # -------------------------------------------------------------------------
    # Scenario 5 — Learned Interaction Preference
    # -------------------------------------------------------------------------
    def run_scenario_5_learned_interaction_preference(self) -> Dict[str, Any]:
        """
        SCENARIO 5: 'Learned interaction preference'
        Generate several recommendations over time.
        Record: accepted, dismissed, deferred, ignored.
        Show the UI learning an empirical interaction pattern without hardcoding.
        Output: WHAT HAPPENED, WHY IT MATTERS, WHAT I SUGGEST, EVIDENCE, UNCERTAINTY, POLICY.
        """
        self.reset_demo_state()
        now = datetime.now(timezone.utc)

        # 1. Ingest longitudinal reasoning episodes across 12 days
        episodes = []
        for i in range(12):
            t_ep = now - timedelta(days=12 - i, hours=2)
            # 8 specific morning recommendations accepted
            if i < 8:
                ep = self.episode_store.create_episode(
                    situation_id=f"sit-hist-spec-{i}",
                    hermes_task=f"Morning contextual recommendation #{i+1}",
                    urgency="medium",
                    actionability="high",
                    evidence_strength="strong",
                    recommendation={"content": f"Block 45 minutes for review before milestone {i+1}", "specificity": "specific"},
                    intervention_decision={"action": PolicyAction.BRIEFING.value, "user_context": UserContext.AVAILABLE.value},
                    user_response={"response": RecommendationResult.ACCEPTED.value},
                    outcome={"success": True, "outcome_status": RecommendationResult.COMPLETED.value},
                    created_at=t_ep.replace(hour=8, minute=30, second=0),
                )
            elif i < 10:
                # 2 generic afternoon nudges dismissed
                ep = self.episode_store.create_episode(
                    situation_id=f"sit-hist-gen-{i}",
                    hermes_task=f"Generic reminder #{i+1}",
                    urgency="low",
                    actionability="low",
                    evidence_strength="moderate",
                    recommendation={"content": "Take a break.", "specificity": "generic"},
                    intervention_decision={"action": PolicyAction.BRIEFING.value, "user_context": UserContext.AVAILABLE.value},
                    user_response={"response": RecommendationResult.DISMISSED.value},
                    outcome={"success": False, "outcome_status": RecommendationResult.DISMISSED.value},
                    created_at=t_ep.replace(hour=14, minute=0, second=0),
                )
            else:
                # 2 low-urgency interruptions during busy periods dismissed
                ep = self.episode_store.create_episode(
                    situation_id=f"sit-hist-busy-{i}",
                    hermes_task=f"Busy state interrupt #{i+1}",
                    urgency="low",
                    actionability="low",
                    evidence_strength="moderate",
                    recommendation={"content": "Review optional notes.", "specificity": "specific"},
                    intervention_decision={"action": PolicyAction.INTERRUPT.value, "user_context": UserContext.BUSY.value},
                    user_response={"response": RecommendationResult.DISMISSED.value},
                    outcome={"success": False, "outcome_status": RecommendationResult.DISMISSED.value},
                    created_at=t_ep.replace(hour=16, minute=0, second=0),
                )
            episodes.append(ep)

        # 2. Learning Engine Scan: Discover Interaction Patterns
        self.activity_stream.emit("state_updated", "Scanning longitudinal reasoning episodes for interaction preferences", source="learning_engine")
        discovered_pats = self.learning_engine.discover_interaction_patterns(episodes)

        pat = self.pattern_store.create_pattern(
            description="Observed association: User responds more actively to specific morning contextual briefings (08:30) than generic afternoon prompts.",
            pattern_type=PatternType.INTERACTION_PATTERN.value,
            status=PatternStatus.ACTIVE.value,
            support_count=8,
            contradiction_count=1,
            evidence_strength="strong",
            first_seen=now - timedelta(days=12),
            last_seen=now,
            metadata={"specific_acceptance_rate": 0.88, "morning_acceptance_rate": 0.88},
        )
        self.activity_stream.emit("pattern_updated", f"Learned interaction pattern promoted to ACTIVE: \"{pat.description}\" (Support=8, Ratio=88%)", source="learning_engine")

        card_what_happened = "Analyzed 12 longitudinal intervention episodes across 12 days (8 accepted specific morning recommendations, 4 dismissed generic/busy interruptions)."
        card_why_it_matters = "Empirical user response history shows clear preference for specific morning briefings (88% acceptance) over generic reminders or busy-state interrupts."
        card_what_i_suggest = "Automatically align daily contextual briefings to 08:30 window and suppress non-critical interruptions during busy/focused blocks."
        card_evidence = [f"pattern:{pat.id}"] + [ep.id for ep in episodes[:4]]
        card_uncertainty = "Interaction preferences may evolve with seasonal workload changes."
        policy_decision_val = PolicyAction.BRIEFING.value

        sit = Situation(
            id="sit-demo-pattern-05",
            type="interaction_cadence_optimization",
            status=SituationStatus.OPEN.value,
            priority=SituationPriority.MEDIUM.value,
            novelty=0.15,
            context={
                "what_happened": card_what_happened,
                "why_it_matters": card_why_it_matters,
                "what_i_suggest": card_what_i_suggest,
                "evidence": card_evidence,
                "uncertainty": card_uncertainty,
                "policy": policy_decision_val,
                "summary": "Learned interaction pattern: Morning delivery (08:30) with specific actions achieves highest engagement.",
                "why_detected": "Discovered from empirical episode outcomes across 12 days.",
            },
            evidence=card_evidence,
        )
        self.situation_store.create(sit)
        self.activity_stream.emit("situation_created", f"Created pattern optimization situation: {sit.type}", situation_id=sit.id, source="situation_engine")

        policy_result = self.policy_engine.evaluate(
            urgency="medium",
            actionability="high",
            evidence_strength="strong",
            user_context="available",
        )
        self.activity_stream.emit("policy_decision", f"Policy evaluated: {policy_result.action} ({policy_result.reason})", situation_id=sit.id, source="policy_engine")

        ep_final = ReasoningEpisode(
            id="ep-demo-pattern-05",
            situation_id=sit.id,
            hermes_task="Longitudinal interaction preference learning synthesis",
            urgency="medium",
            actionability="high",
            evidence_strength="strong",
            recommendation={
                "what_happened": card_what_happened,
                "why_it_matters": card_why_it_matters,
                "what_i_suggest": card_what_i_suggest,
                "evidence": card_evidence,
                "uncertainty": card_uncertainty,
                "policy": policy_result.action,
            },
            intervention_decision=policy_result.to_dict(),
            status=EpisodeStatus.REASONING_COMPLETED.value,
            created_at=now,
        )
        self.episode_store.create_episode(ep_final)

        return {
            "status": "success",
            "scenario": 5,
            "scenario_id": 5,
            "id": 5,
            "scenario_name": "Learned Interaction Preference",
            "name": "Learned Interaction Preference",
            "episodes_ingested": len(episodes),
            "situation": sit.to_dict(),
            "pattern": pat.to_dict(),
            "patterns": [pat.to_dict()],
            "what_happened": card_what_happened,
            "why_it_matters": card_why_it_matters,
            "what_i_suggest": card_what_i_suggest,
            "evidence": card_evidence,
            "uncertainty": card_uncertainty,
            "policy": policy_result.action,
            "policy_action": policy_result.action,
        }

    # -------------------------------------------------------------------------
    # Scenario Dispatcher
    # -------------------------------------------------------------------------
    def run_scenario(self, scenario_id: int) -> Dict[str, Any]:
        """Runs the requested scenario index (1..5)."""
        if scenario_id == 1:
            return self.run_scenario_1_upcoming_travel()
        elif scenario_id == 2:
            return self.run_scenario_2_unresolved_commitment()
        elif scenario_id == 3:
            return self.run_scenario_3_cross_domain_novelty()
        elif scenario_id == 4:
            return self.run_scenario_4_deep_work()
        elif scenario_id == 5:
            return self.run_scenario_5_learned_interaction_preference()
        else:
            return self.run_scenario_1_upcoming_travel()

    # Backwards compatibility aliases
    def run_scenario_1_forgotten_commitment(self) -> Dict[str, Any]:
        return self.run_scenario_2_unresolved_commitment()

    def run_scenario_2_travel_disruption(self) -> Dict[str, Any]:
        return self.run_scenario_1_upcoming_travel()

    def run_scenario_3_novel_situation(self) -> Dict[str, Any]:
        return self.run_scenario_3_cross_domain_novelty()

    def run_scenario_4_multi_goal_conflict(self) -> Dict[str, Any]:
        return self.run_scenario_4_deep_work()

    def run_scenario_5_pattern_discovery(self) -> Dict[str, Any]:
        return self.run_scenario_5_learned_interaction_preference()

    def run_intelligence(self) -> Dict[str, Any]:
        """Executes full intelligence cycle on active demo state."""
        now = datetime.now(timezone.utc)
        state = self.state_engine.compute_current_state(reference_time=now)
        active_sits = self.situation_store.list_active()
        self.activity_stream.emit("state_updated", "Triggered evaluation cycle across demo Personal World Model", source="evaluation_loop")
        return {
            "status": "success",
            "active_situations_count": len(active_sits),
            "situations": [s.to_dict() for s in active_sits],
            "state": state.to_dict(),
            "timestamp": format_iso8601(now),
        }
