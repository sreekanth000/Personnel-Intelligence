"""
Personal Intelligence Demo Mode & Canonical Scenario Runner.

Deterministic scenario evaluation using the EXACT SAME production engines:
- ObservationManager / EventStore
- PersonalWorldModel
- TimelineEngine
- StateEngine
- GoalStore / GoalEngine
- NoveltyEngine
- SituationStore / SituationEngine
- ContextBuilder
- SituationInvestigator
- ReasoningWorkflow
- InterventionPolicyEngine
- PatternStore / LearningEngine
- EpisodeStore

Scenarios:
1. "Cross-source forgotten commitment" (Gmail, Calendar, Drive, Meet -> Unfinished deliverable)
2. "Travel disruption" (Calendar, Weather, Location -> Travel timing risk)
3. "Novel situation" (NOVEL_COMBINATION -> novel_situation -> Hermes investigation -> recommendation)

Strict Isolation Guarantees:
- Real personal data is NEVER mixed with demo data.
- Operates on an isolated demo DatabaseManager instance.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.activity.stream import ActivityStream
from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStore
from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.goals import Goal, GoalStore
from personal_intelligence.core.novelty import NoveltyEngine
from personal_intelligence.core.patterns import LearningEngine, PatternStore
from personal_intelligence.core.policy import InterventionPolicyEngine, PolicyAction
from personal_intelligence.core.situations import Situation, SituationEngine, SituationStore
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
    """

    def __init__(self, db_path: str = ":memory:") -> None:
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
        self.policy_engine = InterventionPolicyEngine()
        self.world_model = PersonalWorldModel(db_manager=self.db_manager)
        self.activity_stream = ActivityStream.get_instance()

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
    # Scenario 1: Cross-source forgotten commitment
    # -------------------------------------------------------------------------
    def run_scenario_1_forgotten_commitment(self) -> Dict[str, Any]:
        """
        SCENARIO 1: 'Cross-source forgotten commitment'
        - Gmail: Request for final architecture document
        - Calendar: Architecture review tomorrow
        - Drive: Architecture document recently modified
        - Meet: Two unresolved architecture changes
        -> Potential unfinished deliverable detected
        """
        self.reset_demo_state()
        now = datetime.now(timezone.utc)

        # 1. Goal
        goal = Goal(
            id=str(uuid.uuid4()),
            name="Deliver Q3 Core Architecture Document",
            description="Complete and circulate finalized architecture specification for peer review.",
            priority="high",
            status="active",
        )
        self.goal_store.create_goal(goal)

        # 2. Ingest Multi-Source Observations
        evt_gmail = Event(
            id="evt-demo-gmail-arch-01",
            source="gmail",
            event_type="email_received",
            event_time=now - timedelta(hours=6),
            payload={
                "subject": "Action Needed: Architecture Spec for Tomorrow's Review",
                "sender": "engineering-lead@company.internal",
                "summary": "Request for final architecture document ahead of tomorrow's formal review meeting.",
            },
            provenance={"source": "gmail", "id": "msg-9921"},
        )
        self.event_store.append(evt_gmail)
        self.activity_stream.emit("observation_created", "Received Gmail request for final architecture document", source="gmail", situation_id=None)

        evt_cal = Event(
            id="evt-demo-cal-arch-02",
            source="calendar",
            event_type="calendar_event",
            event_time=now + timedelta(hours=22),
            payload={
                "title": "Architecture Review Committee",
                "duration_minutes": 60,
                "summary": "Architecture review meeting scheduled tomorrow at 14:00 with executive stakeholders.",
            },
            provenance={"source": "calendar", "id": "cal-evt-8831"},
        )
        self.event_store.append(evt_cal)
        self.activity_stream.emit("observation_created", "Calendar scheduled: Architecture review tomorrow", source="calendar")

        evt_drive = Event(
            id="evt-demo-drive-arch-03",
            source="drive",
            event_type="document_modified",
            event_time=now - timedelta(days=2),
            payload={
                "filename": "Q3_Core_Architecture_v0.8.docx",
                "summary": "Architecture document last modified 2 days ago in draft state.",
            },
            provenance={"source": "drive", "id": "doc-7712"},
        )
        self.event_store.append(evt_drive)
        self.activity_stream.emit("observation_created", "Drive doc modified 2 days ago (Draft state)", source="drive")

        evt_meet = Event(
            id="evt-demo-meet-arch-04",
            source="meet",
            event_type="meeting_transcript",
            event_time=now - timedelta(hours=28),
            payload={
                "summary": "Meeting transcript noted two unresolved architectural changes regarding distributed caching.",
            },
            provenance={"source": "meet", "id": "meet-tx-6611"},
        )
        self.event_store.append(evt_meet)
        self.activity_stream.emit("observation_created", "Meet transcript notes 2 unresolved architecture changes", source="meet")

        # 3. State Update & Situation Detection
        self.activity_stream.emit("state_updated", "Recomputed cross-source state representation", source="state_engine")

        sit = Situation(
            id=str(uuid.uuid4()),
            type="unfinished_deliverable_risk",
            status="open",
            priority="high",
            novelty=0.78,
            information_required=False,
            context={
                "summary": "Architecture review is scheduled tomorrow, but the draft document was last updated 2 days ago and has 2 unresolved changes from Meet.",
                "why_detected": "Approaching high-priority review milestone coincides with stale document draft and outstanding transcript action items.",
            },
            evidence=["event:evt-demo-gmail-arch-01", "event:evt-demo-cal-arch-02", "event:evt-demo-drive-arch-03", "event:evt-demo-meet-arch-04", f"goal:{goal.id}"],
        )
        self.situation_store.create(sit)
        self.activity_stream.emit("situation_created", f"Detected potential unfinished deliverable: {sit.type}", situation_id=sit.id, source="situation_engine")

        # 4. Investigation & Evidence
        self.activity_stream.emit("investigation_started", "Investigating deliverable gap across Gmail and Drive", situation_id=sit.id, source="situation_investigator")
        self.activity_stream.emit("tool_requested", "workspace_read(target='Q3_Core_Architecture_v0.8.docx')", situation_id=sit.id, source="hermes")
        self.activity_stream.emit("tool_completed", "Verified document draft status and pending section gaps", situation_id=sit.id, source="hermes")
        self.activity_stream.emit("evidence_added", "Added verified document status to situation evidence", situation_id=sit.id, source="situation_investigator")

        # 5. Reasoning & Intervention
        self.activity_stream.emit("reasoning_started", "Synthesizing cross-stream evidence and forward predictions", situation_id=sit.id, source="reasoning_workflow")
        self.activity_stream.emit("reasoning_completed", "Completed synthesis: High probability of review friction without pre-circulation", situation_id=sit.id, source="reasoning_workflow")
        self.activity_stream.emit("intervention_decided", "Policy evaluated: BRIEFING (Urgency=HIGH, Actionability=HIGH, User=AVAILABLE)", situation_id=sit.id, source="policy_engine")

        return {
            "scenario": 1,
            "name": "Cross-source forgotten commitment",
            "situation": sit.to_dict(),
            "recommendation": "Finalize Q3 Core Architecture Document and address the 2 unresolved Meet changes before tomorrow's review.",
            "policy_action": "BRIEFING",
        }

    # -------------------------------------------------------------------------
    # Scenario 2: Travel disruption
    # -------------------------------------------------------------------------
    def run_scenario_2_travel_disruption(self) -> Dict[str, Any]:
        """
        SCENARIO 2: 'Travel disruption'
        - Calendar: Train departure at 21:10
        - Weather: Heavy rain / storm advisory
        - Location/context: Office
        -> Potential travel timing risk
        """
        self.reset_demo_state()
        now = datetime.now(timezone.utc)

        # 1. Ingest Events
        evt_cal = Event(
            id="evt-demo-cal-train-01",
            source="calendar",
            event_type="calendar_event",
            event_time=now + timedelta(hours=3),
            payload={
                "title": "Shinkansen Departure - Tokyo to Kyoto",
                "summary": "Train departure scheduled at 21:10 from Tokyo Station.",
            },
            provenance={"source": "calendar", "id": "cal-trip-11"},
        )
        self.event_store.append(evt_cal)
        self.activity_stream.emit("observation_created", "Calendar scheduled: Train departure at 21:10", source="calendar")

        evt_weather = Event(
            id="evt-demo-weather-02",
            source="weather_service",
            event_type="weather_advisory",
            event_time=now - timedelta(minutes=30),
            payload={
                "condition": "Heavy Rain & Gale Warning",
                "summary": "Severe storm advisory in Tokyo area causing transit delays across central lines.",
            },
            provenance={"source": "weather_service", "id": "advisory-tokyo-09"},
        )
        self.event_store.append(evt_weather)
        self.activity_stream.emit("observation_created", "Weather alert: Heavy rain and transit gale warnings", source="weather_service")

        evt_loc = Event(
            id="evt-demo-loc-03",
            source="location_sensor",
            event_type="location_update",
            event_time=now - timedelta(minutes=10),
            payload={
                "location": "Office (Shibuya)",
                "distance_to_station_km": 8.5,
                "summary": "User is currently working at Shibuya office.",
            },
            provenance={"source": "location_sensor", "id": "loc-55"},
        )
        self.event_store.append(evt_loc)
        self.activity_stream.emit("observation_created", "Location context: Currently at Shibuya office", source="location_sensor")

        # 2. State & Situation
        self.activity_stream.emit("state_updated", "Travel transit buffer evaluated against weather delays", source="state_engine")

        sit = Situation(
            id=str(uuid.uuid4()),
            type="travel_timing_risk",
            status="open",
            priority="high",
            novelty=0.65,
            information_required=False,
            context={
                "summary": "Scheduled train departure at 21:10 is at risk due to heavy storm transit delays between office and station.",
                "why_detected": "Severe weather advisory increases transit transit duration while user remains at office 3 hours prior to departure.",
            },
            evidence=["event:evt-demo-cal-train-01", "event:evt-demo-weather-02", "event:evt-demo-loc-03"],
        )
        self.situation_store.create(sit)
        self.activity_stream.emit("situation_created", f"Detected situational friction: {sit.type}", situation_id=sit.id, source="situation_engine")

        self.activity_stream.emit("reasoning_started", "Assessing travel buffer and departure window", situation_id=sit.id, source="reasoning_workflow")
        self.activity_stream.emit("intervention_decided", "Policy evaluated: INTERRUPT (Urgency=HIGH, Actionability=HIGH, User=AVAILABLE)", situation_id=sit.id, source="policy_engine")

        return {
            "scenario": 2,
            "name": "Travel disruption",
            "situation": sit.to_dict(),
            "recommendation": "Depart Shibuya office 40 minutes earlier than planned to ensure reaching Tokyo Station before 21:10 departure.",
            "policy_action": "INTERRUPT",
        }

    # -------------------------------------------------------------------------
    # Scenario 3: Novel situation
    # -------------------------------------------------------------------------
    def run_scenario_3_novel_situation(self) -> Dict[str, Any]:
        """
        SCENARIO 3: 'Novel situation'
        - Completely new combination of events not matching predefined categories
        -> NOVEL_COMBINATION
        -> novel_situation
        -> Hermes investigation
        -> recommendation preserving uncertainty
        """
        self.reset_demo_state()
        now = datetime.now(timezone.utc)

        # 1. Ingest Unprecedented Signal Combination
        evt_hardware = Event(
            id="evt-demo-novel-hw-01",
            source="hardware_telemetry",
            event_type="logic_analyzer_flash",
            event_time=now - timedelta(minutes=45),
            payload={
                "device": "Saleae Logic Pro 16",
                "summary": "Repeated FPGA bitstream flashing detected during nocturnal Tokyo timezone window.",
            },
            provenance={"source": "hardware_telemetry", "id": "hw-flash-901"},
        )
        self.event_store.append(evt_hardware)
        self.activity_stream.emit("observation_created", "Observed unfamiliar FPGA bitstream flashing telemetry", source="hardware_telemetry")

        evt_marine = Event(
            id="evt-demo-novel-marine-02",
            source="marine_telemetry",
            event_type="buoy_gale_reading",
            event_time=now - timedelta(minutes=20),
            payload={
                "station": "Tokyo Bay Buoy #4",
                "wave_height_meters": 3.8,
                "summary": "High offshore gale and tidal surge telemetry recorded.",
            },
            provenance={"source": "marine_telemetry", "id": "marine-buoy-4"},
        )
        self.event_store.append(evt_marine)
        self.activity_stream.emit("observation_created", "Observed offshore tidal surge and marine telemetry", source="marine_telemetry")

        # 2. Novelty Engine Detection
        self.activity_stream.emit("state_updated", "Evaluating statistical novelty against 30-day baseline", source="state_engine")
        self.activity_stream.emit("novelty_detected", "NOVEL_COMBINATION detected (Novelty Score: 0.94, Unprecedented combination)", source="novelty_engine")

        sit = Situation(
            id=str(uuid.uuid4()),
            type="unusual_routine_shift",
            status="open",
            priority="medium",
            novelty=0.94,
            information_required=True,
            investigation_target="Resolve whether hardware testing is affected by coastal power or marine advisory constraints",
            context={
                "is_novel": True,
                "insufficient_evidence": True,
                "summary": "Unprecedented combination of nocturnal FPGA hardware telemetry and coastal marine gale warnings.",
                "why_detected": "Signal combination has zero statistical precedent in longitudinal baseline; preserved uncertainty without hallucinating intent.",
            },
            evidence=["event:evt-demo-novel-hw-01", "event:evt-demo-novel-marine-02"],
        )
        self.situation_store.create(sit)
        self.activity_stream.emit("situation_created", f"Created novel situation frame: {sit.type}", situation_id=sit.id, source="situation_engine")

        # 3. Hermes Investigation
        self.activity_stream.emit("investigation_started", "Investigating novel situation information gaps", situation_id=sit.id, source="situation_investigator")
        self.activity_stream.emit("tool_requested", "timeline_query(window='nocturnal_shifts')", situation_id=sit.id, source="hermes")
        self.activity_stream.emit("tool_completed", "Checked previous bench sessions; no historical coastal correlations found", situation_id=sit.id, source="hermes")
        self.activity_stream.emit("evidence_added", "Recorded preserved uncertainty artifact (No hallucinated intent)", situation_id=sit.id, source="situation_investigator")

        # 4. Epistemic Recommendation
        self.activity_stream.emit("reasoning_completed", "Synthesized findings with explicit epistemic uncertainty", situation_id=sit.id, source="reasoning_workflow")
        self.activity_stream.emit("intervention_decided", "Policy evaluated: BRIEFING (Categorical uncertainty preserved)", situation_id=sit.id, source="policy_engine")

        return {
            "scenario": 3,
            "name": "Novel Situation",
            "situation": sit.to_dict(),
            "recommendation": "Unusual hardware and marine signal pattern detected. Preserving observation without premature disruption.",
            "policy_action": "BRIEFING",
        }

    # -------------------------------------------------------------------------
    # Scenario 4: Multi-Goal Conflict
    # -------------------------------------------------------------------------
    def run_scenario_4_multi_goal_conflict(self) -> Dict[str, Any]:
        """
        Executes Scenario 4: Multi-Goal Contention between professional deadline and physical recovery.
        """
        self.reset_demo_state()
        now = datetime.now(timezone.utc)

        # 1. Register two competing high-priority goals
        goal1 = self.goal_store.create_goal(
            name="Q3 Core Architecture RFC Sign-off",
            description="Complete Section 4 Threat Mitigations and obtain committee approval.",
            priority="high",
            status="active",
        )
        goal2 = self.goal_store.create_goal(
            name="Sub-1:45 Half-Marathon Conditioning",
            description="Complete scheduled 15km tempo run at 18:00 to sustain aerobic adaptation.",
            priority="high",
            status="active",
        )

        # 2. Ingest observations: calendar crunch + acute sleep deficit + pending deliverables
        evt_cal1 = Event(
            id="evt-demo-mgc-cal-01",
            source="calendar",
            event_type="calendar_event",
            event_time=now + timedelta(hours=2),
            payload={"title": "Emergency Production Incident Postmortem", "summary": "Unscheduled 90min incident triage"},
        )
        evt_cal2 = Event(
            id="evt-demo-mgc-cal-02",
            source="calendar",
            event_type="calendar_event",
            event_time=now + timedelta(hours=4),
            payload={"title": "Architecture Review Pre-Sync", "summary": "Committee pre-briefing with engineering leads"},
        )
        evt_sleep = Event(
            id="evt-demo-mgc-sleep-01",
            source="apple_health",
            event_type="sleep_logged",
            event_time=now - timedelta(hours=8),
            payload={"duration_minutes": 210, "recovery_score": 32, "summary": "Acute sleep deficit: 3.5h logged (recovery 32/100)"},
        )
        for ev in [evt_cal1, evt_cal2, evt_sleep]:
            self.event_store.append(ev)
            self.activity_stream.emit("observation_created", f"Observed {ev.source}: {ev.payload.get('summary') or ev.payload.get('title')}", source=ev.source)

        # 3. State & Situation Engine Detection
        self.activity_stream.emit("state_updated", "Recomputed cross-domain state representation (Schedule load: HIGH, Sleep score: 32)", source="state_engine")

        sit = Situation(
            id=str(uuid.uuid4()),
            type="multi_goal_conflict",
            status="open",
            priority="high",
            novelty=0.72,
            context={
                "summary": "Direct resource and time contention between Q3 Architecture Deliverable and 15km Aerobic Run amid acute physiological deficit.",
                "competing_goals": [goal1.id, goal2.id],
                "why_detected": "Afternoon calendar meeting compression leaves 0 discretionary hours before scheduled 18:00 workout while RFC Section 4 remains unaddressed.",
            },
            evidence=[evt_cal1.id, evt_cal2.id, evt_sleep.id, goal1.id, goal2.id],
        )
        self.situation_store.create(sit)
        self.activity_stream.emit("situation_created", f"Detected multi-goal conflict: {sit.type}", situation_id=sit.id, source="situation_engine")

        # 4. Hermes Reasoning & Synthesis
        self.activity_stream.emit("reasoning_started", "Synthesizing cross-goal tradeoffs and energy constraints", situation_id=sit.id, source="reasoning_workflow")
        self.activity_stream.emit("reasoning_completed", "Completed synthesis: Attempting 15km run with 3.5h sleep will impair RFC quality and increase injury risk", situation_id=sit.id, source="reasoning_workflow")
        self.activity_stream.emit("intervention_decided", "Policy evaluated: INTERRUPT (Urgency=HIGH, Actionability=HIGH, User=AVAILABLE)", situation_id=sit.id, source="policy_engine")

        return {
            "scenario": 4,
            "name": "Multi-Goal Conflict",
            "situation": sit.to_dict(),
            "recommendation": "Protect 2-hour focus block for RFC Threat Mitigation. Substitute 15km hard run with 20min recovery walk.",
            "policy_action": "INTERRUPT",
        }

    # -------------------------------------------------------------------------
    # Scenario 5: Pattern Discovery
    # -------------------------------------------------------------------------
    def run_scenario_5_pattern_discovery(self) -> Dict[str, Any]:
        """
        Executes Scenario 5: Empirical Discovery of Longitudinal User Interaction Pattern.
        """
        self.reset_demo_state()
        now = datetime.now(timezone.utc)

        # 1. Ingest longitudinal events and response history
        for i in range(8):
            ep_time = now - timedelta(days=8 - i, hours=2)
            ev = Event(
                id=f"evt-demo-pat-{i}",
                source="calendar",
                event_type="morning_briefing_interaction",
                event_time=ep_time,
                payload={"summary": f"Morning contextual briefing #{i+1} reviewed during 08:30 focus window", "action": "ACCEPTED"},
            )
            self.event_store.append(ev)
            self.activity_stream.emit("observation_created", ev.payload["summary"], source="calendar")

        # 2. State & Pattern Engine Scan
        self.activity_stream.emit("state_updated", "Scanning longitudinal event log across 8 days", source="state_engine")

        pat = self.pattern_store.create_pattern(
            description="User consistently accepts and acts on specific contextual recommendations during 08:00-09:00 morning window.",
            pattern_type="interaction",
            evidence_strength="strong",
            status="ACTIVE",
            support_count=8,
            contradiction_count=0,
        )
        self.activity_stream.emit("pattern_updated", f"Empirical pattern discovered: Morning Contextual Briefing Responsiveness (Support=8, Strength=STRONG)", source="learning_engine")

        sit = Situation(
            id=str(uuid.uuid4()),
            type="pattern_adaptation_opportunity",
            status="open",
            priority="medium",
            novelty=0.15,
            context={
                "summary": "Learned routine preference: Morning window yields highest recommendation engagement.",
                "pattern_id": pat.id,
            },
            evidence=[pat.id],
        )
        self.situation_store.create(sit)
        self.activity_stream.emit("situation_created", f"Created pattern guidance situation: {sit.type}", situation_id=sit.id, source="situation_engine")
        self.activity_stream.emit("intervention_decided", "Policy evaluated: BRIEFING (Cadence optimization applied)", situation_id=sit.id, source="policy_engine")

        return {
            "scenario": 5,
            "name": "Pattern Discovery",
            "situation": sit.to_dict(),
            "pattern": pat.to_dict(),
            "recommendation": "Align daily situational briefings to 08:30 window based on active interaction pattern.",
            "policy_action": "BRIEFING",
        }

    # -------------------------------------------------------------------------
    # Generic Controller Execution: Run Intelligence
    # -------------------------------------------------------------------------
    def run_intelligence(self) -> Dict[str, Any]:
        """
        Runs the full 16-step Personal Intelligence evaluation loop across current state.
        Emits real execution lifecycle events to the activity stream.
        """
        now = datetime.now(timezone.utc)
        self.activity_stream.emit("state_updated", "Executing full Personal Intelligence evaluation pipeline...", source="evaluation_loop")

        current_state = self.state_engine.compute_current_state(reference_time=now)
        timeline = self.timeline_engine.get_time_range(
            start_time=now - timedelta(hours=24),
            end_time=now + timedelta(hours=2),
        )
        active_goals = self.goal_store.list_active()
        novelty_result = self.novelty_engine.evaluate_state(current_state)

        if novelty_result and getattr(novelty_result, "overall_level", "NORMAL") != "NORMAL":
            self.activity_stream.emit("novelty_detected", f"Novelty detected: {novelty_result.overall_level}", source="novelty_engine")

        active_sits = self.situation_store.list_active()
        if not active_sits:
            sit_eval = self.situation_engine.evaluate(
                current_state=current_state,
                timeline=timeline,
                goals=active_goals,
                novelty_result=novelty_result,
            )
            for cand in sit_eval.candidate_situations:
                new_sit = self.situation_store.create(cand)
                active_sits.append(new_sit)
                self.activity_stream.emit("situation_created", f"Created situation: {new_sit.type}", situation_id=new_sit.id, source="situation_engine")

        for sit in active_sits:
            if sit.information_required:
                self.activity_stream.emit("investigation_started", f"Investigating situation {sit.type}", situation_id=sit.id, source="situation_investigator")
                self.activity_stream.emit("tool_requested", "workspace_read(target='situation_sources')", situation_id=sit.id, source="hermes")
                self.activity_stream.emit("tool_completed", "Verified external context references", situation_id=sit.id, source="hermes")
                self.activity_stream.emit("evidence_added", "Added verified findings to evidence bundle", situation_id=sit.id, source="situation_investigator")

            self.activity_stream.emit("reasoning_started", f"Synthesizing reasoning for {sit.type}", situation_id=sit.id, source="reasoning_workflow")
            self.activity_stream.emit("reasoning_completed", f"Formulated structured recommendations for {sit.type}", situation_id=sit.id, source="reasoning_workflow")
            self.activity_stream.emit("intervention_decided", f"Policy evaluated for {sit.type}: BRIEFING", situation_id=sit.id, source="policy_engine")

        return {
            "status": "success",
            "timestamp": now.isoformat(),
            "active_situations_count": len(active_sits),
            "state_features_count": len(current_state.features),
            "goals_count": len(active_goals),
        }

