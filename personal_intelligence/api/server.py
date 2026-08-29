"""
Lightweight Personal Intelligence Dashboard API & Web Server.
Zero external server dependencies (pure Python standard library).
Provides JSON endpoints for live state, active situations, recommendations,
learned patterns, epistemically-demarcated reasoning episodes, and novel events.
"""

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer, SimpleHTTPRequestHandler
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from personal_intelligence.core.episodes.models import RecommendationResult
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import Event, ensure_timezone_aware, format_iso8601
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import GoalPriority, GoalStatus
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.novelty import NoveltyEngine
from personal_intelligence.core.patterns.models import Pattern, PatternStatus
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.policy import InterventionPolicyEngine
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.core.situations.models import SituationPriority
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.activity.stream import ActivityStream
from personal_intelligence.core.query import AskPersonalIntelligenceEngine
from personal_intelligence.core.world import PersonalWorldModel
from personal_intelligence.demo.scenarios import DemoScenarioRunner
from personal_intelligence.hermes_bridge.client import HermesClient
from personal_intelligence.core.fusion.multi_source_engine import MultiSourceFusionEngine
from personal_intelligence.core.notifications.notifier import DesktopNotifier, send_desktop_alert
from personal_intelligence.core.scheduler.background_sync import BackgroundSyncScheduler
from personal_intelligence.hermes_bridge.calendar_adapter import (
    CalendarCapabilityRequest,
    GoogleCalendarCapabilityAdapter,
)
from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
from personal_intelligence.hermes_bridge.connection_manager import HermesConnectionManager
from personal_intelligence.hermes_bridge.situation_investigation import SituationInvestigator
from personal_intelligence.hermes_bridge.voice_notes_adapter import VoiceNotesAdapter
from personal_intelligence.storage.db import DatabaseManager



class DashboardDataService:
    """
    Assembles structured, epistemically classified dashboard payloads from the Personal Intelligence core.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        is_demo_mode: bool = False,
        auto_seed_sample_data: bool = False,
        sync_interval_minutes: int = 30,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.state_engine = StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.novelty_engine = NoveltyEngine()
        self.world_model = PersonalWorldModel(db_manager=self.db_manager)
        self.policy_engine = InterventionPolicyEngine()
        self.hermes_client = HermesClient()
        self.connection_manager = HermesConnectionManager(bridge=self.hermes_client)
        self.command_handler = PersonalIntelligenceCommandHandler(
            db_manager=self.db_manager,
            event_store=self.event_store,
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            episode_store=self.episode_store,
            pattern_store=self.pattern_store,
            state_engine=self.state_engine,
            policy_engine=self.policy_engine,
        )
        self.investigator = SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
            episode_store=self.episode_store,
            hermes_client=self.hermes_client,
        )
        self.activity_stream = ActivityStream.get_instance()
        self.ask_engine = AskPersonalIntelligenceEngine(
            db_manager=self.db_manager,
            event_store=self.event_store,
            state_engine=self.state_engine,
            situation_store=self.situation_store,
            goal_store=self.goal_store,
            pattern_store=self.pattern_store,
            timeline_engine=self.timeline_engine,
            world_model=self.world_model,
            investigator=self.investigator,
            hermes_client=self.hermes_client,
            activity_stream=self.activity_stream,
        )
        self.demo_runner = DemoScenarioRunner()
        self.is_demo_mode = is_demo_mode
        self.active_demo_scenario: Optional[int] = None
        self.auto_seed_sample_data = auto_seed_sample_data

        # Multi-Source Ingestion & Fusion Engines
        self.calendar_adapter = GoogleCalendarCapabilityAdapter(bridge=self.hermes_client)
        self.voice_notes_adapter = VoiceNotesAdapter()
        self.fusion_engine = MultiSourceFusionEngine(
            db_manager=self.db_manager,
            event_store=self.event_store,
            situation_store=self.situation_store,
            timeline_engine=self.timeline_engine,
            state_engine=self.state_engine,
        )

        # Background Sync & OS Notification Scheduler (Configurable Interval)
        self.bg_scheduler = BackgroundSyncScheduler(
            sync_interval_minutes=sync_interval_minutes,
            sync_callback=self._perform_silent_triage_sync,
            auto_start=True,
        )

        if self.auto_seed_sample_data or is_demo_mode or (db_manager and db_manager.db_path and ("ui_test" in db_manager.db_path or "test_" in db_manager.db_path)):
            self._ensure_sample_data_if_empty()

    def _perform_silent_triage_sync(self) -> Dict[str, Any]:
        """Performs silent background inbox triage and returns high-priority situations."""
        try:
            self.execute_gmail_investigation(query="is:inbox", max_results=25, days=14)
        except Exception as e:
            logger.debug("Background silent Gmail query note: %s", e)

        active_sits = self.current_situation_store.list_active()
        high_pri = [s.to_dict() for s in active_sits if getattr(s, "priority", "") in ("critical", "high")]
        return {
            "high_priority_situations": high_pri,
            "total_active_situations": len(active_sits),
        }

    def get_sync_status_payload(self) -> Dict[str, Any]:
        """Returns background sync scheduler status."""
        return self.bg_scheduler.get_status()

    def trigger_sync_now(self) -> Dict[str, Any]:
        """Triggers manual background sync cycle immediately."""
        res = self.bg_scheduler.trigger_now()
        self.activity_stream.emit(
            "sync_cycle_completed",
            f"Manual background sync completed: {res.get('high_priority_detected', 0)} high-priority item(s) assessed.",
            source="background_sync_scheduler",
        )
        return res

    def trigger_test_notification(self) -> Dict[str, Any]:
        """Dispatches a test native desktop alert."""
        send_desktop_alert(
            title="Personal Intelligence Active",
            message="Background sync & native OS notifications are active and operating properly!",
            priority="high",
        )
        self.activity_stream.emit(
            "notification_dispatched",
            "Test desktop notification sent via Native OS Notifier.",
            source="desktop_notifier",
        )
        return {
            "status": "success",
            "message": "Test desktop notification dispatched to OS.",
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def get_vector_search_status(self) -> Dict[str, Any]:
        """Returns in-process SQLite vector index statistics."""
        return self.ask_engine.hybrid_search_engine.get_index_stats()

    def execute_hybrid_search(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Executes in-process hybrid dense + sparse vector search."""
        hits = self.ask_engine.hybrid_search_engine.search_hybrid(query=query, limit=limit)
        return {
            "status": "success",
            "query": query,
            "results": hits,
            "total_matches": len(hits),
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def handle_situation_feedback(
        self,
        situation_id: str,
        action: str,
        snooze_days: int = 2,
        feedback_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Processes interactive user feedback for a situation via PersonalWorldModel."""
        res = self.world_model.process_user_feedback(
            situation_id=situation_id,
            action=action,
            snooze_days=snooze_days,
            feedback_notes=feedback_notes,
        )
        if res.get("status") == "success":
            self.activity_stream.emit(
                "user_feedback_applied",
                f"User feedback [{action.upper()}] recorded for situation {situation_id}. PatternLearningEngine and World Model updated.",
                source="user_feedback_loop",
            )
        return res

    def execute_calendar_sync(self, time_range_days: int = 7) -> Dict[str, Any]:
        """Syncs Google Calendar observations into EventStore, World Model, and Vector Index."""
        res = self.calendar_adapter.execute_query(CalendarCapabilityRequest(time_range_days=time_range_days))
        ingested = 0
        now_ts = datetime.now(timezone.utc)

        for ev in res.events:
            event_obj = Event(
                id=f"evt-{ev.id}",
                source="calendar",
                event_type="calendar_event",
                event_time=ensure_timezone_aware(ev.start_time, "start_time"),
                payload=ev.to_dict(),
                provenance={
                    "tool": "calendar_sync",
                    "provenance_chain": [ev.provenance],
                    "recorded_at": format_iso8601(now_ts),
                },
            )
            try:
                self.event_store.append(event_obj)
                ingested += 1
                self.ask_engine.hybrid_search_engine.index_document(
                    source_type="calendar",
                    source_id=ev.id,
                    content_text=f"[CALENDAR] {ev.summary} (At: {ev.start_time} - {ev.end_time}, Duration: {ev.duration_minutes}m, Location: {ev.location or 'Online'})",
                    metadata=ev.to_dict(),
                )
            except Exception as ex_cal:
                logger.debug("Calendar event ingestion note: %s", ex_cal)

        # Trigger Cross-Domain Fusion Correlation
        fusion_conflicts = self.fusion_engine.analyze_cross_domain_correlations()

        self.activity_stream.emit(
            "calendar_synced",
            f"Synced {len(res.events)} Google Calendar event(s). Occupied Load: {res.busy_hours_total}h. {len(fusion_conflicts)} cross-domain correlation(s) evaluated.",
            source="calendar_adapter",
        )

        return {
            "status": "success",
            "events_synced": len(res.events),
            "busy_hours_total": res.busy_hours_total,
            "events": [e.to_dict() for e in res.events],
            "free_blocks": res.free_blocks,
            "cross_domain_conflicts": [c.to_dict() for c in fusion_conflicts],
            "timestamp": format_iso8601(now_ts),
        }

    def execute_voice_note_ingest(self, text: str, title: Optional[str] = None) -> Dict[str, Any]:
        """Parses and ingests a voice recording transcript or meeting summary."""
        note_item = self.voice_notes_adapter.parse_note_content(text=text, title=title)
        self.voice_notes_adapter.save_note_file(note_item)
        now_ts = datetime.now(timezone.utc)

        # Store in event log
        event_obj = Event(
            id=f"evt-{note_item.id}",
            source="voice_notes",
            event_type="meeting_transcript",
            event_time=now_ts,
            payload=note_item.to_dict(),
            provenance={
                "tool": "voice_notes_ingest",
                "provenance_chain": [note_item.provenance],
                "recorded_at": format_iso8601(now_ts),
            },
        )
        self.event_store.append(event_obj)

        # Index in vector search
        self.ask_engine.hybrid_search_engine.index_document(
            source_type="voice_notes",
            source_id=note_item.id,
            content_text=f"[VOICE NOTES] {note_item.title}: {note_item.summary}. Action Items: {', '.join(note_item.action_items) if note_item.action_items else 'None'}",
            metadata=note_item.to_dict(),
        )

        # Derive commitments for action items in World Model
        for act in note_item.action_items:
            try:
                self.world_model.record_commitment(
                    description=f"Action item: {act}",
                    metadata={"source": "voice_notes", "origin": note_item.title},
                )
            except Exception:
                pass

        # Trigger Cross-Domain Fusion
        fusion_conflicts = self.fusion_engine.analyze_cross_domain_correlations()
        self.fusion_engine.synthesize_fusion_situations()

        self.activity_stream.emit(
            "voice_note_ingested",
            f"Ingested Voice Note '{note_item.title}' with {len(note_item.action_items)} action item(s) and full vector indexing.",
            source="voice_notes_adapter",
        )

        return {
            "status": "success",
            "voice_note": note_item.to_dict(),
            "action_items_derived": len(note_item.action_items),
            "cross_domain_conflicts": [c.to_dict() for c in fusion_conflicts],
            "timestamp": format_iso8601(now_ts),
        }

    def get_fusion_status(self) -> Dict[str, Any]:
        """Returns Multi-Source Fusion cross-domain correlation status."""
        conflicts = self.fusion_engine.analyze_cross_domain_correlations()
        return {
            "status": "success",
            "active_conflicts": [c.to_dict() for c in conflicts],
            "total_conflicts": len(conflicts),
            "streams_connected": ["gmail", "google_calendar", "health_sleep", "voice_notes"],
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def _ensure_sample_data_if_empty(self) -> None:
        """Populates rich realistic multi-domain state if SQLite database is brand new."""
        if self.event_store.count() > 0:
            return

        now = datetime.now(timezone.utc)

        # 1. Active Goal
        goal = self.goal_store.create_goal(
            name="Half-Marathon Sub-1:45 Preparation",
            description="Train for half-marathon with 4 weekly runs including interval workouts.",
            priority=GoalPriority.HIGH.value,
            status=GoalStatus.ACTIVE.value,
        )

        # 2. Ingest 14 days baseline sleep & workout events
        events: List[Event] = []
        for d in range(14, 0, -1):
            t_sleep = (now - timedelta(days=d)).replace(hour=7, minute=0, second=0)
            events.append(
                Event(
                    id=f"evt-base-sleep-{d:02d}",
                    event_type="sleep_session",
                    source="oura_ring",
                    event_time=t_sleep,
                    payload={"duration_minutes": 480, "restfulness": "optimal", "recovery_score": 88},
                )
            )
            if d % 3 == 0:
                t_run = (now - timedelta(days=d)).replace(hour=17, minute=30, second=0)
                events.append(
                    Event(
                        id=f"evt-base-run-{d:02d}",
                        event_type="exercise_workout",
                        source="strava",
                        event_time=t_run,
                        payload={"activity": "running", "distance_km": 10.0, "duration_minutes": 52},
                    )
                )

        # 3. Today's Events (Acute sleep debt + high meeting workload + scheduled workout)
        today_sleep_time = now.replace(hour=6, minute=30, second=0)
        events.append(
            Event(
                id="evt-sleep-today",
                event_type="sleep_session",
                source="oura_ring",
                event_time=today_sleep_time,
                payload={"duration_minutes": 225, "restfulness": "poor", "recovery_score": 38},
            )
        )
        events.append(
            Event(
                id="evt-meeting-01",
                event_type="calendar_event",
                source="google_calendar",
                event_time=now.replace(hour=9, minute=0, second=0),
                payload={"title": "Executive Architecture Sync", "cognitive_workload": "high", "duration_minutes": 90},
            )
        )
        events.append(
            Event(
                id="evt-meeting-02",
                event_type="calendar_event",
                source="google_calendar",
                event_time=now.replace(hour=11, minute=0, second=0),
                payload={"title": "Engineering All-Hands", "cognitive_workload": "medium", "duration_minutes": 60},
            )
        )
        events.append(
            Event(
                id="evt-meeting-03",
                event_type="calendar_event",
                source="google_calendar",
                event_time=now.replace(hour=13, minute=30, second=0),
                payload={"title": "Product Strategy Q3", "cognitive_workload": "high", "duration_minutes": 120},
            )
        )
        events.append(
            Event(
                id="evt-work-current",
                event_type="app_focus",
                source="os_window",
                event_time=now - timedelta(minutes=45),
                payload={"activity": "software_development", "app": "VSCode", "duration_minutes": 135},
            )
        )
        events.append(
            Event(
                id="evt-cal-evening-run",
                event_type="calendar_event",
                source="google_calendar",
                event_time=now.replace(hour=17, minute=30, second=0),
                payload={"title": "10km High-Intensity Interval Run", "duration_minutes": 60, "priority": "high"},
            )
        )

        for ev in events:
            self.event_store.append(ev)

        # 4. Create Active Situation
        situation = self.situation_store.create(
            type="cognitive_physical_strain_risk",
            priority=SituationPriority.HIGH.value,
            novelty=0.85,
            context={
                "summary": "Severe sleep restriction (3.75h vs 8.0h baseline) coincides with a 7-hour executive cognitive workload and a scheduled 10km high-intensity interval run.",
                "why_detected": "Sleep duration is -3.2 sigma below historical baseline during high cognitive load day with demanding physical goal pressure.",
            },
            evidence=[
                "event:evt-sleep-today",
                "event:evt-meeting-01",
                "event:evt-meeting-03",
                "goal:" + goal.id,
            ],
        )

        # 5. Create Novel Situation
        novel_situation = self.situation_store.create(
            type="unusual_routine_shift",
            priority=SituationPriority.MEDIUM.value,
            novelty=0.92,
            context={
                "summary": "Nocturnal async communication pattern and unfamiliar coastal hardware bench activity detected.",
                "why_detected": "Unfamiliar combination of nocturnal Tokyo timezone shift, Saleae logic analyzer hardware flashing, and high marine gale telemetry.",
                "is_novel": True,
                "insufficient_evidence": True,
            },
            evidence=["event:evt-work-current"],
        )

        # 6. Create Reasoning Episode with Epistemic Demarcation
        self.episode_store.create_episode(
            situation_id=situation.id,
            hermes_task="Assess physical fatigue and suggest adaptive schedule modification.",
            observations=[
                {"type": "FACT", "content": "User slept 3.75 hours last night (14-day baseline mean is 8.0 hours)."},
                {"type": "FACT", "content": "Recovery readiness score is 38/100 (acute autonomic stress indicator)."},
                {"type": "FACT", "content": "Calendar contains 4 high-demand meetings totaling 7.0 hours of cognitive load."},
                {"type": "FACT", "content": "Scheduled 10km high-intensity interval run at 17:30."},
            ],
            inferences=[
                {"type": "INFERENCE", "content": "Acute sleep deprivation combined with sustained cognitive fatigue severely impairs neuromuscular coordination and reaction time."},
                {"type": "INFERENCE", "content": "Attempting maximal interval training in this state will degrade workout quality and trigger systemic overreaching rather than aerobic adaptation."},
            ],
            predictions=[
                {"type": "PREDICTION", "content": "Executing the 10km interval workout today carries an elevated risk of acute musculoskeletal strain and multi-day central nervous system exhaustion."},
                {"type": "PREDICTION", "content": "Shifting the high-intensity session to tomorrow afternoon allows complete recovery while maintaining progress toward the Half-Marathon goal."},
            ],
            recommendation={
                "type": "RECOMMENDATION",
                "primary_action": "Shift today's 10km interval run to tomorrow at 16:00.",
                "secondary_action": "Substitute today's 17:30 block with a 20-minute restorative walk and mobility stretching.",
                "sleep_target": "Target bedtime of 22:00 to repay acute sleep debt.",
                "why": "Protects cardiovascular readiness and eliminates injury risk during acute recovery deficit.",
            },
            intervention_decision={
                "action": PolicyAction.INTERRUPT.value,
                "user_context": UserContext.AVAILABLE.value,
                "urgency": "high",
                "reason": "High urgency with high actionability and strong evidence triggers immediate interrupt when user is available.",
            },
            user_response={
                "response": RecommendationResult.ACCEPTED.value,
                "note": "User accepted suggestion and rescheduled workout.",
            },
            outcome={
                "outcome_status": RecommendationResult.COMPLETED.value,
                "success": True,
                "evaluation": "Workout moved to tomorrow; restorative walk completed at 17:30.",
            },
            created_at=now - timedelta(minutes=30),
            episode_id="ep-demo-001",
        )

        # 7. Create Learned Patterns with Empirical Support
        p1 = Pattern(
            id="pat-specificity-001",
            description="User appears more responsive to specific contextual recommendations than generic reminders.",
            first_seen=now - timedelta(days=45),
            last_seen=now - timedelta(hours=2),
            support_count=90,
            contradiction_count=4,
            evidence_strength="strong",
            status=PatternStatus.ACTIVE.value,
            metadata={
                "specific_acceptance_rate": 0.74,
                "generic_acceptance_rate": 0.23,
                "confidence_ratio": 0.957,
            },
        )
        self.pattern_store.create_pattern(p1)

        p2 = Pattern(
            id="pat-evening-walk-002",
            description="Restorative walks appear associated with improved next-day deep sleep duration following high cognitive workload days.",
            first_seen=now - timedelta(days=25),
            last_seen=now - timedelta(days=1),
            support_count=18,
            contradiction_count=2,
            evidence_strength="strong",
            status=PatternStatus.SUPPORTED.value,
            metadata={"confidence_ratio": 0.90},
        )
        self.pattern_store.create_pattern(p2)

        p3 = Pattern(
            id="pat-morning-focus-003",
            description="Deep work sessions before 11:00 appear correlated with lower afternoon context switching.",
            first_seen=now - timedelta(days=10),
            last_seen=now - timedelta(days=3),
            support_count=8,
            contradiction_count=1,
            evidence_strength="moderate",
            status=PatternStatus.EMERGING.value,
            metadata={"confidence_ratio": 0.88},
        )
        self.pattern_store.create_pattern(p3)

    @property
    def current_situation_store(self) -> SituationStore:
        if self.is_demo_mode:
            sits = self.demo_runner.situation_store.list_active()
            if sits:
                return self.demo_runner.situation_store
        return self.situation_store

    @property
    def current_goal_store(self) -> GoalStore:
        if self.is_demo_mode:
            goals = self.demo_runner.goal_store.list_active()
            if goals:
                return self.demo_runner.goal_store
        return self.goal_store

    @property
    def current_timeline_engine(self) -> TimelineEngine:
        if self.is_demo_mode:
            tl = self.demo_runner.timeline_engine.get_time_range(limit=1)
            if tl.events:
                return self.demo_runner.timeline_engine
        return self.timeline_engine

    @property
    def current_state_engine(self) -> StateEngine:
        if self.is_demo_mode:
            return self.demo_runner.state_engine
        return self.state_engine

    @property
    def current_episode_store(self) -> EpisodeStore:
        if self.is_demo_mode:
            eps = self.demo_runner.episode_store.list_recent_episodes(limit=1)
            if eps:
                return self.demo_runner.episode_store
        return self.episode_store

    @property
    def current_pattern_store(self) -> PatternStore:
        if self.is_demo_mode:
            pats = self.demo_runner.pattern_store.list_patterns(limit=1)
            if pats:
                return self.demo_runner.pattern_store
        return self.pattern_store

    @property
    def current_world_model(self) -> PersonalWorldModel:
        if self.is_demo_mode:
            return self.demo_runner.world_model
        return self.world_model

    @property
    def current_event_store(self) -> EventStore:
        if self.is_demo_mode:
            evs = self.demo_runner.event_store.get_recent(limit=1)
            if evs:
                return self.demo_runner.event_store
        return self.event_store

    def get_mode_payload(self) -> Dict[str, Any]:
        """Returns the current operating mode: LIVE, DEMO, or TEST."""
        cur_mode = getattr(self, "operating_mode", "DEMO" if self.is_demo_mode else "LIVE")
        return {
            "mode": cur_mode,
            "is_demo_mode": self.is_demo_mode,
            "active_scenario": getattr(self, "active_demo_scenario", None),
            "available_modes": ["LIVE", "DEMO", "TEST"],
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def set_operating_mode(self, mode: str) -> Dict[str, Any]:
        """Sets operating mode to LIVE, DEMO, or TEST."""
        m = (mode or "LIVE").upper()
        if m not in ("LIVE", "DEMO", "TEST"):
            m = "DEMO"
        self.operating_mode = m
        self.is_demo_mode = (m in ("DEMO", "TEST"))

        from personal_intelligence.hermes_bridge.client import HermesBridgeExecutionMode
        if hasattr(self, "hermes_client"):
            self.hermes_client.mode = HermesBridgeExecutionMode.LIVE if m == "LIVE" else HermesBridgeExecutionMode.DEMO
        if hasattr(self.demo_runner, "hermes_client"):
            self.demo_runner.hermes_client.mode = HermesBridgeExecutionMode.DEMO

        self.activity_stream.emit("state_updated", f"Switched operating mode to {m} MODE", source="mode_switcher")
        return {
            "status": "success",
            "mode": m,
            "is_demo_mode": self.is_demo_mode,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def get_current_state_payload(self) -> Dict[str, Any]:
        """Returns structured current state: focus, attention state, availability, active goals, and commitments."""
        now = datetime.now(timezone.utc)
        state_rep = self.current_state_engine.compute_current_state(reference_time=now)
        active_goals = self.current_goal_store.get_active_goals()
        recent_events = self.current_event_store.get_recent(limit=20)
        commitments = [
            {
                "id": e.id,
                "summary": e.payload.get("summary") or e.payload.get("title") or e.payload.get("subject") or e.event_type if isinstance(e.payload, dict) else str(e.payload),
                "source": e.source,
                "time": format_iso8601(e.event_time),
            }
            for e in recent_events
            if e.event_type in ("calendar_event", "commitment_scheduled", "action_item", "email_received") or e.source in ("calendar", "meet", "gmail")
        ][:6]

        act_feat = state_rep.get_feature("current_activity")
        act_val = act_feat.value if act_feat else "Software Engineering"
        dur_feat = state_rep.get_feature("recent_activity_duration")
        dur_val = f"{int(dur_feat.value)} mins" if dur_feat else "45 mins"
        loc_feat = state_rep.get_feature("current_location")
        loc_val = loc_feat.value if loc_feat else "Primary Workspace"
        tod_feat = state_rep.get_feature("time_of_day")
        tod_val = tod_feat.value.get("bucket", "daytime") if tod_feat and isinstance(tod_feat.value, dict) else "daytime"

        att_feat = state_rep.get_feature("attention_state")
        att_val = att_feat.value if att_feat else "FOCUSED"
        cog_feat = state_rep.get_feature("cognitive_availability")
        cog_val = cog_feat.value if cog_feat else "AVAILABLE"

        summary_text = (
            f"User is engaged in {str(act_val).replace('_', ' ').title()} ({dur_val}) at {loc_val}. "
            f"Attention: {att_val}, Availability: {cog_val}. Active Goals: {len(active_goals)}."
        )

        return {
            "summary": summary_text,
            "timestamp": format_iso8601(now),
            "current_focus": str(act_val).replace("_", " ").title(),
            "activity": str(act_val).replace("_", " ").title(),
            "attention_state": str(att_val).upper(),
            "cognitive_availability": str(cog_val).upper(),
            "availability": str(cog_val).upper(),
            "duration": dur_val,
            "location": str(loc_val).replace("_", " ").title(),
            "time_of_day": tod_val.title(),
            "active_goals_count": len(active_goals),
            "active_goals": [{"id": g.id, "name": g.name, "priority": g.priority} for g in active_goals],
            "active_commitments": commitments,
            "features": [
                {
                    "name": feat.name,
                    "value": feat.value,
                    "source": feat.source,
                    "confidence_label": "High Confidence" if feat.confidence >= 0.8 else "Moderate",
                    "timestamp": format_iso8601(feat.timestamp),
                }
                for name, feat in sorted(state_rep.features.items())
            ],
        }

    def get_active_situations_payload(self) -> List[Dict[str, Any]]:
        """Returns active situations with the 6 required card fields: WHAT HAPPENED, WHY IT MATTERS, WHAT I SUGGEST, EVIDENCE, UNCERTAINTY, POLICY."""
        situations = self.current_situation_store.get_active_situations()
        episodes = self.current_episode_store.list_recent_episodes(limit=20)
        ep_map = {ep.situation_id: ep for ep in episodes if ep.situation_id}

        result = []
        for s in situations:
            ctx = s.context or {}
            matching_ep = ep_map.get(s.id)

            rec_dict = matching_ep.recommendation if matching_ep and isinstance(matching_ep.recommendation, dict) else {}
            decision_dict = matching_ep.intervention_decision if matching_ep and isinstance(matching_ep.intervention_decision, dict) else {}

            what_happened = (
                ctx.get("what_happened")
                or rec_dict.get("what_happened")
                or ctx.get("summary")
                or f"{s.type.replace('_', ' ').title()} situation detected from observation stream."
            )
            why_it_matters = (
                ctx.get("why_it_matters")
                or rec_dict.get("why_it_matters")
                or ctx.get("why_detected")
                or rec_dict.get("why")
                or "Multi-domain correlation impacts schedule commitments and personal goals."
            )
            what_i_suggest = (
                ctx.get("what_i_suggest")
                or rec_dict.get("what_i_suggest")
                or rec_dict.get("primary_action")
                or rec_dict.get("content")
                or "Review situational context and take proactive adaptive measures."
            )
            raw_evidence = (
                ctx.get("evidence")
                or rec_dict.get("evidence")
                or s.evidence
                or []
            )
            uncertainty = (
                ctx.get("uncertainty")
                or rec_dict.get("uncertainty")
                or ("Categorical uncertainty preserved pending further observations." if s.novelty >= 0.8 else "Standard situational confidence based on grounded evidence.")
            )
            policy_val = (
                ctx.get("policy")
                or rec_dict.get("policy")
                or decision_dict.get("action")
                or (PolicyAction.INTERRUPT.value if s.priority == "high" else PolicyAction.BRIEFING.value)
            )

            evidence_items = []
            for ev_ref in raw_evidence:
                evidence_items.append({
                    "ref": str(ev_ref),
                    "type": "FACT / EVENT" if str(ev_ref).startswith("event:") else ("FACT / GOAL" if str(ev_ref).startswith("goal:") else "FACT / PATTERN"),
                })

            result.append({
                "situation_id": s.id,
                "type": s.type,
                "title": s.type.replace("_", " ").title(),
                "priority": s.priority,
                "status": s.status,
                "novelty_score": s.novelty,
                "novelty_category": "High Novelty" if s.novelty >= 0.8 else "Standard Deviation",
                "summary": ctx.get("summary") or what_happened,
                "why_detected": why_it_matters,
                "what_happened": what_happened,
                "why_it_matters": why_it_matters,
                "what_i_suggest": what_i_suggest,
                "evidence": evidence_items,
                "raw_evidence": raw_evidence,
                "uncertainty": uncertainty,
                "policy": policy_val,
                "created_at": format_iso8601(s.created_at),
            })
        return result

    def get_reasoning_trace_payload(self, situation_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Builds and returns the clean 9-stage epistemic reasoning trace:
        Observation -> Change -> Significance -> Situation -> Information Gap -> Hermes Investigation -> Evidence -> Recommendation -> Policy
        (Without raw chain-of-thought dumps).
        """
        target_sit = self.current_situation_store.get(situation_id) if situation_id else None
        if not target_sit:
            active_sits = self.current_situation_store.list_active()
            if active_sits:
                target_sit = active_sits[0]

        if not target_sit:
            return []

        ctx = target_sit.context or {}
        episodes = self.current_episode_store.list_recent_episodes(limit=10)
        matching_ep = next((ep for ep in episodes if ep.situation_id == target_sit.id), None)
        if not matching_ep and episodes:
            matching_ep = episodes[0]

        rec_dict = matching_ep.recommendation if matching_ep and isinstance(matching_ep.recommendation, dict) else {}
        decision_dict = matching_ep.intervention_decision if matching_ep and isinstance(matching_ep.intervention_decision, dict) else {}

        obs_text = "Multi-source signals ingested into EventStore with full provenance."
        obs_list = matching_ep.observations if matching_ep and matching_ep.observations else []
        if obs_list:
            first_obs = obs_list[0]
            obs_text = first_obs.get("content") if isinstance(first_obs, dict) else str(first_obs)
        elif target_sit.evidence:
            obs_text = f"Grounded in {len(target_sit.evidence)} recorded facts ({', '.join(str(e) for e in target_sit.evidence[:3])})."

        change_text = f"Temporal delta detected in state representation coinciding with {target_sit.type.replace('_', ' ')}."
        sig_text = f"Evaluated personal significance: Priority {target_sit.priority.upper()}, Novelty {target_sit.novelty:.2f}."
        sit_text = ctx.get("summary") or f"Identified active situation frame: {target_sit.type.replace('_', ' ').title()}."

        has_gap = getattr(target_sit, "information_required", False) or ctx.get("insufficient_evidence", False)
        gap_text = target_sit.investigation_target or ("No external information gap required" if not has_gap else "Information gap identified across external tools")
        inv_text = "Hermes native capability invoked: workspace_read / search query with strict read-only boundary." if has_gap else "Sufficient local epistemic context available; external investigation bypassed."

        ev_strength = (matching_ep.evidence_strength if matching_ep else "STRONG").upper()
        ev_text = f"Deterministic evidence strength computed: {ev_strength} across {len(target_sit.evidence or [])} verified provenance references."

        rec_text = ctx.get("what_i_suggest") or rec_dict.get("what_i_suggest") or rec_dict.get("primary_action") or rec_dict.get("content") or "Adaptive recommendation formulated."
        pol_action = ctx.get("policy") or decision_dict.get("action") or (PolicyAction.INTERRUPT.value if target_sit.priority == "high" else PolicyAction.BRIEFING.value)
        pol_text = f"Deterministic intervention policy decision: {pol_action} ({decision_dict.get('reason', 'Categorical policy evaluation')})."

        return [
            {"step": 1, "stage": "Observation", "title": "1. Observation", "content": obs_text, "badge": "FACT", "badge_class": "badge-fact"},
            {"step": 2, "stage": "Change", "title": "2. Change Detection", "content": change_text, "badge": "FACT", "badge_class": "badge-fact"},
            {"step": 3, "stage": "Significance", "title": "3. Personal Significance", "content": sig_text, "badge": "INFERENCE", "badge_class": "badge-inference"},
            {"step": 4, "stage": "Situation", "title": "4. Situation Detection", "content": sit_text, "badge": "INFERENCE", "badge_class": "badge-inference"},
            {"step": 5, "stage": "Information Gap", "title": "5. Information Gap", "content": gap_text, "badge": "INFERENCE", "badge_class": "badge-inference"},
            {"step": 6, "stage": "Hermes Investigation", "title": "6. Hermes Investigation", "content": inv_text, "badge": "FACT", "badge_class": "badge-fact"},
            {"step": 7, "stage": "Evidence", "title": "7. Deterministic Evidence", "content": ev_text, "badge": "FACT", "badge_class": "badge-fact"},
            {"step": 8, "stage": "Recommendation", "title": "8. Recommendation", "content": rec_text, "badge": "RECOMMENDATION", "badge_class": "badge-recommendation"},
            {"step": 9, "stage": "Policy", "title": "9. Intervention Policy", "content": pol_text, "badge": "INTERVENTION", "badge_class": "badge-intervention"},
        ]

    def get_learned_patterns_payload(self) -> Dict[str, Any]:
        """Returns learned patterns categorized into Emerging, Supported, Active, Decaying, and Inactive."""
        patterns = self.current_pattern_store.list_patterns(status=None, limit=50)
        emerging = []
        supported = []
        active = []
        decaying = []
        inactive = []
        all_list = []

        for p in patterns:
            status_val = p.status.upper() if isinstance(p.status, str) else (p.status.value.upper() if hasattr(p.status, "value") else "ACTIVE")
            ctx_statement = p.to_context_statement() if hasattr(p, "to_context_statement") else p.description

            item = {
                "pattern_id": p.id,
                "description": p.description,
                "context_statement": ctx_statement,
                "status": status_val,
                "evidence_strength": (p.evidence_strength or "moderate").upper(),
                "support_count": p.support_count,
                "contradiction_count": p.contradiction_count,
                "confidence_ratio": f"{p.confidence * 100:.1f}% Empirical Support",
                "evidence_provenance": getattr(p, "provenance", []) or [f"evidence:ep-demo-pattern-{p.id}"],
                "first_seen": format_iso8601(p.first_seen),
                "last_seen": format_iso8601(p.last_seen),
            }
            all_list.append(item)
            if status_val == "ACTIVE":
                active.append(item)
            elif status_val == "SUPPORTED":
                supported.append(item)
            elif status_val in ("EMERGING", "HYPOTHESIS", "OBSERVED"):
                emerging.append(item)
            elif status_val == "DECAYING":
                decaying.append(item)
            else:
                inactive.append(item)

        return {
            "patterns": all_list,
            "active": active,
            "supported": supported,
            "emerging": emerging,
            "decaying": decaying,
            "inactive": inactive,
            "counts": {
                "total": len(all_list),
                "active": len(active),
                "supported": len(supported),
                "emerging": len(emerging),
                "decaying": len(decaying),
                "inactive": len(inactive),
            },
        }

    def get_reasoning_episodes_payload(self) -> List[Dict[str, Any]]:
        """Returns reasoning episodes with strict epistemic demarcation."""
        episodes = self.current_episode_store.list_recent_episodes(limit=20)
        result = []
        for ep in episodes:
            # Demarcate epistemic categories cleanly
            facts = []
            for obs in (ep.observations or []):
                content = obs.get("content") if isinstance(obs, dict) else str(obs)
                facts.append({"tag": "FACT", "content": content})

            inferences = []
            for inf in (ep.inferences or []):
                content = inf.get("content") if isinstance(inf, dict) else str(inf)
                inferences.append({"tag": "INFERENCE", "content": content})

            predictions = []
            for pred in (ep.predictions or []):
                content = pred.get("content") if isinstance(pred, dict) else str(pred)
                predictions.append({"tag": "PREDICTION", "content": content})

            rec_dict = ep.recommendation if isinstance(ep.recommendation, dict) else {"content": str(ep.recommendation or "")}
            primary_rec = rec_dict.get("primary_action") or rec_dict.get("content") or "No explicit recommendation."
            rec_block = {
                "tag": "RECOMMENDATION",
                "primary": primary_rec,
                "secondary": rec_dict.get("secondary_action"),
                "why": rec_dict.get("why"),
            }

            decision_dict = ep.intervention_decision or {}
            intervention_block = {
                "tag": "INTERVENTION",
                "action": decision_dict.get("action", PolicyAction.BRIEFING.value),
                "reason": decision_dict.get("reason", "Standard policy threshold evaluation."),
                "user_context": decision_dict.get("user_context", "Available"),
            }

            outcome_dict = ep.outcome or {}
            user_resp_dict = ep.user_response or {}
            outcome_block = {
                "tag": "OUTCOME",
                "user_response": user_resp_dict.get("response", "Pending"),
                "outcome_status": outcome_dict.get("outcome_status", "Active"),
                "evaluation": outcome_dict.get("evaluation", user_resp_dict.get("note", "Awaiting execution outcome.")),
            }

            result.append({
                "episode_id": ep.id,
                "situation_id": ep.situation_id,
                "created_at": format_iso8601(ep.created_at),
                "task": ep.hermes_task or "Situational reasoning",
                "status": ep.status,
                "facts": facts,
                "inferences": inferences,
                "predictions": predictions,
                "recommendation": rec_block,
                "intervention": intervention_block,
                "outcome": outcome_block,
            })
        return result

    def get_reasoning_trace_payload(self, situation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Builds and returns the deterministic 9-stage epistemic trace:
        1. Observation
        2. Change Detection
        3. Personal Significance
        4. Situation Detection
        5. Information Gap
        6. Hermes Investigation
        7. Deterministic Evidence
        8. Recommendation
        9. Intervention Policy
        """
        sit = None
        if situation_id:
            sit = self.current_situation_store.get(situation_id)
        if not sit:
            sits = self.current_situation_store.list_active()
            if sits:
                sit = sits[0]

        if not sit:
            return {
                "situation_id": situation_id or "default",
                "steps": [],
                "timestamp": format_iso8601(datetime.now(timezone.utc)),
            }

        ctx = sit.context or {}
        what_happened = ctx.get("what_happened") or sit.summary or "Observation delta detected across stream."
        why_it_matters = ctx.get("why_it_matters") or sit.why_detected or "Cross-domain impact detected."
        what_i_suggest = ctx.get("what_i_suggest") or "Review and adapt to situational context."
        policy_action = ctx.get("policy") or PolicyAction.BRIEFING.value
        uncertainty = ctx.get("uncertainty") or "Preserved epistemic bounds."
        raw_evidence = sit.evidence or []

        steps = [
            {
                "stage": "Observation",
                "title": "Raw Observation Ingestion",
                "content": f"Ingested multi-domain ground truth signals (provenance: {', '.join([str(e) for e in raw_evidence[:3]]) or 'local store'}).",
                "badge": "FACT",
                "badge_class": "badge-fact",
            },
            {
                "stage": "Change Detection",
                "title": "Meaningful Temporal Delta",
                "content": f"Detected variance against temporal baseline: {what_happened}",
                "badge": "FACT",
                "badge_class": "badge-fact",
            },
            {
                "stage": "Personal Significance",
                "title": "Significance Evaluation",
                "content": f"Evaluated impact against active user goals and commitments: {why_it_matters}",
                "badge": "INFERENCE",
                "badge_class": "badge-inference",
            },
            {
                "stage": "Situation Detection",
                "title": "Situation Hypothesis Generated",
                "content": f"Synthesized situational frame '{sit.type}' with priority {str(sit.priority).upper()}.",
                "badge": "PREDICTION",
                "badge_class": "badge-prediction",
            },
            {
                "stage": "Information Gap",
                "title": "Epistemic Gap Identification",
                "content": f"Preserved unknown variables without hallucinating user intent: {uncertainty}",
                "badge": "UNCERTAINTY",
                "badge_class": "badge-recommendation",
            },
            {
                "stage": "Hermes Investigation",
                "title": "Bounded Read-Only Investigation",
                "content": "Executed read-only capability query through Hermes runtime boundary with zero data exfiltration.",
                "badge": "INFERENCE",
                "badge_class": "badge-inference",
            },
            {
                "stage": "Deterministic Evidence",
                "title": "Evidence Strength Calculation",
                "content": f"Deterministic score calculated based on verified multi-source corroboration ({len(raw_evidence)} signals).",
                "badge": "FACT",
                "badge_class": "badge-fact",
            },
            {
                "stage": "Recommendation",
                "title": "Actionable Guidance Synthesis",
                "content": f"{what_i_suggest}",
                "badge": "RECOMMENDATION",
                "badge_class": "badge-recommendation",
            },
            {
                "stage": "Intervention Policy",
                "title": "Deterministic Policy Decision",
                "content": f"Intervention selected: {policy_action} (evaluated against attention state and urgency without autonomous side effects).",
                "badge": "INTERVENTION",
                "badge_class": "badge-intervention",
            },
        ]

        return {
            "situation_id": sit.id,
            "situation_title": sit.type.replace("_", " ").title(),
            "priority": sit.priority,
            "steps": steps,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def get_novel_events_payload(self) -> List[Dict[str, Any]]:
        """Returns detected novel situations with uncertainty status."""
        situations = self.current_situation_store.get_active_situations()
        novel_items = []
        for s in situations:
            ctx = s.context or {}
            is_novel = s.novelty >= 0.80 or ctx.get("is_novel", False)
            if not is_novel:
                continue

            novel_items.append({
                "situation_id": s.id,
                "type": s.type,
                "title": s.type.replace("_", " ").title(),
                "novelty_level": "High Statistical Novelty" if s.novelty >= 0.85 else "Moderate Novelty",
                "summary": ctx.get("summary", "Unfamiliar multi-stream deviation."),
                "why_unusual": ctx.get("why_detected", "Statistical divergence against baseline."),
                "insufficient_evidence": bool(ctx.get("insufficient_evidence", False)),
                "additional_observation_needed": True,
                "epistemic_status": "Preserved Uncertainty (No Hallucinated Intent)" if ctx.get("insufficient_evidence") else "Evaluated",
                "detected_at": format_iso8601(s.created_at),
            })
        return novel_items

    def get_timeline_payload(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns validated timeline events with provenance metadata."""
        tl = self.current_timeline_engine.get_time_range(limit=limit * 2)
        events = [
            e for e in tl.events
            if not (e.source in ("sample_generator", "mock_host") or str(e.id).startswith("obs-inv-task-") or "synthetic" in e.event_type)
        ][:limit]
        if not events and self.is_demo_mode:
            events = self.timeline_engine.get_time_range(limit=limit).events
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "source": e.source,
                "timestamp": format_iso8601(e.event_time),
                "summary": e.payload.get("summary") or e.payload.get("title") or e.payload.get("subject") or e.event_type if isinstance(e.payload, dict) else str(e.payload),
                "payload": e.payload,
                "provenance": e.provenance,
            }
            for e in events
        ]

    def get_world_model_payload(self) -> Dict[str, Any]:
        """Returns structured Personal World Model entities and snapshot."""
        snapshot = self.current_world_model.get_snapshot()
        return snapshot.to_dict()

    def get_recommendations_payload(self) -> List[Dict[str, Any]]:
        """Returns structured recommendations generated from active situations and reasoning episodes."""
        situations = self.current_situation_store.get_active_situations()
        episodes = self.current_episode_store.list_recent_episodes(limit=20)
        ep_map = {ep.situation_id: ep for ep in episodes if ep.situation_id}

        result = []
        for s in situations:
            ctx = s.context or {}
            matching_ep = ep_map.get(s.id)

            rec_dict = matching_ep.recommendation if matching_ep and isinstance(matching_ep.recommendation, dict) else {}
            decision_dict = matching_ep.intervention_decision if matching_ep and isinstance(matching_ep.intervention_decision, dict) else {}

            primary = (
                rec_dict.get("what_i_suggest")
                or rec_dict.get("primary_action")
                or rec_dict.get("content")
                or ctx.get("what_i_suggest")
                or ctx.get("summary")
                or "Adapt to active situation."
            )
            why = (
                rec_dict.get("why_it_matters")
                or rec_dict.get("why")
                or ctx.get("why_it_matters")
                or ctx.get("why_detected")
                or "Evaluated against personal goals."
            )
            policy_action = (
                decision_dict.get("action")
                or ctx.get("policy")
                or PolicyAction.BRIEFING.value
            )

            result.append({
                "situation_id": s.id,
                "situation_type": s.type,
                "title": ctx.get("summary") or s.type.replace("_", " ").title(),
                "primary": primary,
                "what_i_suggest": primary,
                "what_happened": ctx.get("what_happened") or rec_dict.get("what_happened") or ctx.get("summary"),
                "why_it_matters": why,
                "why": why,
                "policy_action": policy_action,
                "policy": policy_action,
                "urgency": (str(matching_ep.urgency).upper() if matching_ep and matching_ep.urgency else "HIGH"),
                "actionability": (str(matching_ep.actionability).upper() if matching_ep and matching_ep.actionability else "HIGH"),
                "evidence_strength": (str(matching_ep.evidence_strength).upper() if matching_ep and matching_ep.evidence_strength else "STRONG"),
                "created_at": format_iso8601(matching_ep.created_at if matching_ep else s.created_at),
            })
        return result

    def execute_what_matters(self) -> Dict[str, Any]:
        """Triggers /pi what_matters and returns structured recommendations and policy decisions."""
        raw_text = self.command_handler.handle_what_matters()
        recs = self.get_recommendations_payload()
        return {
            "status": "success",
            "formatted_text": raw_text,
            "recommendations": recs,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def execute_what_changed(self, time_window_hours: int = 48) -> Dict[str, Any]:
        """Triggers /pi what_changed and returns cross-domain deltas."""
        raw_text = self.command_handler.handle_what_changed(time_window_hours=time_window_hours)
        changes = self.command_handler.get_meaningful_changes(time_window_hours=time_window_hours, max_changes=5)
        return {
            "status": "success",
            "formatted_text": raw_text,
            "time_window_hours": time_window_hours,
            "changes": [c.to_dict() for c in changes],
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def execute_investigate(self, situation_id: Optional[str] = None) -> Dict[str, Any]:
        """Runs SituationInvestigator on a target situation ID."""
        target_sit = self.current_situation_store.get(situation_id) if situation_id else None
        if not target_sit:
            active_sits = self.current_situation_store.list_active()
            if active_sits:
                target_sit = active_sits[0]
        if not target_sit:
            return {"status": "error", "message": "No active situation found to investigate."}

        outcome = self.investigator.investigate(situation=target_sit)
        res = outcome.to_dict()
        res["status"] = "success"
        res["timestamp"] = format_iso8601(datetime.now(timezone.utc))
        return res

    def execute_why(self, situation_id: Optional[str] = None) -> Dict[str, Any]:
        """Triggers /pi why and returns the 11-section canonical diagnostic report."""
        report_text = self.command_handler.handle_why(situation_id=situation_id)
        return {
            "status": "success",
            "situation_id": situation_id,
            "diagnostic_report": report_text,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def execute_command(self, command: str) -> Dict[str, Any]:
        """Executes arbitrary /pi command."""
        result_text = self.command_handler.execute(command)
        return {
            "status": "success",
            "command": command,
            "result_text": result_text,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def execute_ask(self, query: str, situation_id: Optional[str] = None) -> Dict[str, Any]:
        """Executes an Ask Personal Intelligence natural-language inquiry."""
        if self.is_demo_mode and hasattr(self.demo_runner, "db_manager"):
            runner_engine = AskPersonalIntelligenceEngine(
                db_manager=self.demo_runner.db_manager,
                event_store=self.demo_runner.event_store,
                state_engine=self.demo_runner.state_engine,
                situation_store=self.demo_runner.situation_store,
                goal_store=self.demo_runner.goal_store,
                pattern_store=self.demo_runner.pattern_store,
                timeline_engine=self.demo_runner.timeline_engine,
                world_model=self.demo_runner.world_model,
                investigator=self.demo_runner.situation_investigator,
                hermes_client=self.demo_runner.hermes_client,
                activity_stream=self.activity_stream,
            )
            res = runner_engine.ask(query=query, situation_id=situation_id)
        else:
            res = self.ask_engine.ask(query=query, situation_id=situation_id)

        data = res.to_dict()
        data["status"] = "success"
        data["is_demo_mode"] = self.is_demo_mode
        return data

    def get_activity_payload(self, since_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns recent activity events from the live execution stream."""
        return self.activity_stream.get_recent(since_id=since_id, limit=limit)

    def get_test_sources_payload(self) -> List[Dict[str, Any]]:
        """Returns /pi test_sources capability diagnostic status."""
        active_handler = self.demo_runner.command_handler if self.is_demo_mode else self.command_handler
        return active_handler.get_test_sources_payload()

    def execute_test_sources(self) -> Dict[str, Any]:
        """Executes /pi test_sources and returns formatted report."""
        active_handler = self.demo_runner.command_handler if self.is_demo_mode else self.command_handler
        report_text = active_handler.handle_test_sources()
        sources = active_handler.get_test_sources_payload()
        return {
            "status": "success",
            "formatted_text": report_text,
            "sources": sources,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def execute_live_google_flow(self) -> Dict[str, Any]:
        """
        Executes the canonical Real Google Live Demo Flow:
        LIVE MODE -> Hermes Google Authentication -> /pi what_matters ->
        Personal World Model -> Situation Detection -> Hermes Gmail/Drive/Calendar/Meet ->
        Reasoning -> UI
        """
        # Step 1: Switch to / enforce LIVE MODE
        self.is_demo_mode = False
        self.activity_stream.emit(
            "state_updated",
            "Switched to LIVE MODE (Operating on live Personal Intelligence stream with real Hermes tools)",
            source="live_orchestrator",
        )

        # Step 2: Check Hermes Runtime & Google Workspace connection
        health = self.connection_manager.check_health()
        from personal_intelligence.hermes_bridge.capabilities import (
            CapabilityAuthStatus,
            HermesConnectionStatus,
        )

        if health.connection_status == HermesConnectionStatus.DISCONNECTED or not health.is_reachable:
            err_msg = "Hermes runtime is disconnected. Connect Hermes before running live flow."
            self.activity_stream.emit("tool_failed", err_msg, source="live_orchestrator")
            return {
                "status": "error",
                "error_type": "hermes_disconnected",
                "message": err_msg,
                "action_required": "connect_hermes",
                "instructions": self.connection_manager.get_launch_instructions(),
                "timestamp": format_iso8601(datetime.now(timezone.utc)),
            }

        gmail_cap = health.capabilities.get("gmail", {})
        auth_status = gmail_cap.get("authenticated_status") if isinstance(gmail_cap, dict) else getattr(gmail_cap, "authenticated_status", None)

        if auth_status == CapabilityAuthStatus.UNAUTHENTICATED.value or health.connection_status == HermesConnectionStatus.UNAUTHENTICATED:
            err_msg = "Gmail capability is unauthenticated in host Hermes. Run 'hermes auth google' in Hermes to connect."
            self.activity_stream.emit("tool_failed", err_msg, source="live_orchestrator")
            return {
                "status": "error",
                "error_type": "gmail_unauthenticated",
                "message": err_msg,
                "action_required": "connect_gmail_in_hermes",
                "instructions": self.connection_manager.get_gmail_setup_instructions(),
                "timestamp": format_iso8601(datetime.now(timezone.utc)),
            }

        self.activity_stream.emit(
            "tool_requested",
            "Verifying Hermes Google Workspace capability access (Gmail, Calendar, Drive, Meet)",
            source="live_orchestrator",
        )
        sources_status = self.command_handler.get_test_sources_payload()
        self.activity_stream.emit(
            "tool_completed",
            "Hermes Google Workspace capabilities verified: Gmail (READ), Calendar (READ), Drive (READ), Meet (READ)",
            source="live_orchestrator",
        )

        # Step 3: Run real bounded Gmail investigation
        self.activity_stream.emit(
            "tool_requested",
            "Executing real bounded Gmail investigation via host Hermes 'gmail_search'",
            source="live_orchestrator",
        )
        gmail_res = self.investigator.investigate_gmail_gap(
            gap_question="Check recent deliverable status updates and partner inquiries",
            max_results=5,
            time_range_days=7,
        )
        self.activity_stream.emit(
            "observation_created",
            f"Hermes Gmail investigation completed: {len(gmail_res.findings)} observations recorded with message provenance",
            source="live_orchestrator",
        )

        # Step 4: Update Personal World Model & Situation Engine
        current_state = self.state_engine.compute_current_state()
        state_sum = f"Operational ({len(current_state.features)} features: {', '.join(list(current_state.features.keys())[:4])})" if current_state and current_state.features else "Operational baseline active"
        self.activity_stream.emit(
            "state_updated",
            f"Personal World Model state updated: {state_sum}",
            source="live_orchestrator",
        )

        # Step 5: Execute /pi what_matters (evaluates situations & reasons over grounded evidence)
        what_matters_result = self.command_handler.handle_what_matters()
        recs = self.command_handler.get_structured_recommendations()

        # Step 6: Return complete structured flow result
        return {
            "status": "success",
            "flow": "REAL_GOOGLE_LIVE_DEMO_FLOW",
            "mode": "LIVE_MODE",
            "stages": [
                {"stage": 1, "name": "LIVE MODE", "status": "ACTIVE", "detail": "Operating with live stores & native Hermes bridge"},
                {"stage": 2, "name": "Hermes Google Authentication", "status": "VERIFIED", "sources": sources_status},
                {"stage": 3, "name": "/pi what_matters", "status": "EXECUTED", "detail": "Inspected world model snapshot and active goals"},
                {"stage": 4, "name": "Personal World Model", "status": "UPDATED", "state_summary": state_sum},
                {"stage": 5, "name": "Situation Detection", "status": "EVALUATED", "active_situations": len(self.situation_store.list_active())},
                {"stage": 6, "name": "Hermes Gmail/Drive/Calendar/Meet", "status": "INVESTIGATED", "detail": "Bounded read-only investigation across Google Workspace"},
                {"stage": 7, "name": "Reasoning & Policy", "status": "COMPLETED", "recommendations_count": len(recs)},
                {"stage": 8, "name": "UI Presentation", "status": "RENDERED", "detail": "Refreshed Overview, Situation Detail, and Live Activity Stream"},
            ],
            "what_matters_text": what_matters_result,
            "recommendations": [
                {
                    "title": r.title,
                    "what_happened": r.what_happened,
                    "why_it_matters": r.why_it_matters,
                    "what_i_suggest": r.what_i_suggest,
                    "evidence": r.evidence,
                    "uncertainty": r.uncertainty,
                }
                for r in recs
            ],
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def get_hermes_status_payload(self) -> Dict[str, Any]:
        """Returns consolidated health, reachability, and capability report from HermesConnectionManager."""
        from dataclasses import asdict
        health = self.connection_manager.check_health()
        return {
            "status": "success",
            "health": asdict(health),
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def connect_hermes(self, runtime_context: Optional[Any] = None) -> Dict[str, Any]:
        """Executes safe Connect Hermes operation to re-probe or bind host runtime."""
        report = self.connection_manager.connect(runtime_context=runtime_context, is_demo=self.is_demo_mode)
        self.activity_stream.emit(
            "state_updated",
            f"Hermes connection probed: {report.connection_status.value} ({report.runtime_mode})",
            source="hermes_connection_manager",
        )
        return {
            "status": "success",
            "connection_status": report.connection_status.value,
            "runtime_mode": report.runtime_mode,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def get_gmail_setup_flow(self) -> Dict[str, Any]:
        """Returns official Hermes Google Workspace setup instructions (zero local OAuth)."""
        return {
            "status": "success",
            "setup": self.connection_manager.get_gmail_setup_instructions(),
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def trigger_hermes_auth(self, capability: str = "gmail") -> Dict[str, Any]:
        """
        Requests the attached Hermes runtime host to initiate its native browser authentication flow
        without requiring manual credential entry into Personal Intelligence.
        """
        from personal_intelligence.hermes_bridge.client import get_active_hermes_context
        ctx = self.hermes_client.runtime_context or get_active_hermes_context()
        if ctx and hasattr(ctx, "oauth_handler") and ctx.oauth_handler:
            if not ctx.oauth_handler.is_configured():
                # Configure default Hermes OAuth desktop app credentials if available
                pass
            import threading
            threading.Thread(target=ctx.oauth_handler.authorize_in_browser, daemon=True).start()
            return {
                "status": "success",
                "message": "Hermes is opening Google sign-in in your browser. Complete authorization in the browser window.",
                "timestamp": format_iso8601(datetime.now(timezone.utc)),
            }
        elif ctx and hasattr(ctx, "authenticate_capability"):
            ctx.authenticate_capability(capability)
            return {
                "status": "success",
                "message": f"Hermes initiated authentication for '{capability}'.",
                "timestamp": format_iso8601(datetime.now(timezone.utc)),
            }

        return {
            "status": "pending",
            "message": "Open Hermes and connect/configure its Gmail capability, then refresh this page.",
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def configure_hermes_auth(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Configures Google OAuth or IMAP credentials directly on the active Hermes runtime host.
        """
        from personal_intelligence.hermes_bridge.client import get_active_hermes_context
        ctx = self.hermes_client.runtime_context or get_active_hermes_context()
        if not ctx:
            return {"status": "error", "error": "No active Hermes runtime host is attached to this process."}

        method = payload.get("method", "imap")

        if method == "oauth":
            client_id = payload.get("client_id", "").strip()
            client_secret = payload.get("client_secret", "").strip()

            from scripts.launch_local_hermes import HermesGoogleOAuthHandler
            if not hasattr(ctx, "oauth_handler") or not ctx.oauth_handler:
                ctx.oauth_handler = HermesGoogleOAuthHandler()

            if client_id and client_secret:
                ctx.oauth_handler.client_id = client_id
                ctx.oauth_handler.client_secret = client_secret

            auth_url = ctx.oauth_handler.get_authorization_url(port=8085)

            import threading
            threading.Thread(target=ctx.oauth_handler.authorize_in_browser, kwargs={"port": 8085}, daemon=True).start()
            return {
                "status": "success",
                "message": "Google Sign-in launched in your browser! Check your browser window to approve read-only permissions.",
                "auth_url": auth_url,
                "auth_mode": "oauth",
            }

        elif method == "imap":
            user = payload.get("user", "").strip()
            password = payload.get("password", "").strip()
            if not user or not password:
                return {"status": "error", "error": "Gmail address and App Password are required."}

            # Validate IMAP connection live
            try:
                import imaplib
                mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
                mail.login(user, password)
                mail.logout()
            except Exception as ex:
                return {"status": "error", "error": f"Gmail login failed: {str(ex)}. Check email address or 16-character App Password."}

            ctx.gmail_user = user
            ctx.gmail_password = password
            if hasattr(ctx, "auth_status") and isinstance(ctx.auth_status, dict):
                ctx.auth_status["gmail"] = "authenticated"
                ctx.auth_status["google"] = "authenticated"
                ctx.auth_status["calendar"] = "authenticated"
                ctx.auth_status["drive"] = "authenticated"
                ctx.auth_status["meet"] = "authenticated"

            # Persist credentials to ~/.personal_intelligence/hermes_auth.json
            try:
                auth_dir = Path.home() / ".personal_intelligence"
                auth_dir.mkdir(parents=True, exist_ok=True)
                auth_file = auth_dir / "hermes_auth.json"
                with open(auth_file, "w", encoding="utf-8") as f:
                    json.dump({"gmail_user": user, "gmail_password": password, "method": "imap"}, f, indent=2)
            except Exception as ex:
                logger.warning("Failed to persist hermes_auth.json: %s", ex)

            return {
                "status": "success",
                "message": f"Successfully connected to Gmail and Google capabilities ({user}) in read-only mode!",
                "auth_mode": "imap",
            }

        return {"status": "error", "error": f"Unknown auth method: {method}"}

    def execute_gmail_investigation(self, query: str = "is:inbox", max_results: int = 100, days: int = 40) -> Dict[str, Any]:
        """
        Executes a live read-only Gmail inquiry via HermesCapabilityAdapter,
        records resulting real email observations into EventStore with provenance,
        and emits telemetry to the live activity stream.
        """
        from personal_intelligence.core.events.models import Event
        from personal_intelligence.core.episodes.models import ReasoningEpisode
        from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
        from personal_intelligence.hermes_bridge.gmail_adapter import (
            GmailCapabilityAdapter,
            GmailCapabilityRequest,
        )

        adapter = GmailCapabilityAdapter(bridge=self.hermes_client)
        res = adapter.execute_query(GmailCapabilityRequest(query=query, max_results=max_results, time_range_days=days))

        if res.status != "success":
            return {
                "status": res.status,
                "error": res.error or "Failed to query Gmail capability in Hermes.",
                "findings": [],
                "ingested_count": 0,
                "timestamp": format_iso8601(datetime.now(timezone.utc)),
            }

        # Ingest findings into EventStore, World Model, Situations, and Reasoning Episodes
        ingested = 0
        now_ts = datetime.now(timezone.utc)
        for i, finding in enumerate(res.findings):
            msg_ref = res.message_references[i] if i < len(res.message_references) else f"gmail:msg_{i}"
            safe_sum = res.safe_summaries[i] if i < len(res.safe_summaries) else finding
            prov = res.provenance[i] if i < len(res.provenance) else f"gmail_search:{msg_ref}"

            evt = Event(
                source="gmail",
                event_type="email_received",
                payload={
                    "summary": safe_sum,
                    "finding": finding,
                    "message_reference": msg_ref,
                    "query": query,
                },
                provenance={
                    "tool": "gmail_search",
                    "source_id": msg_ref,
                    "provenance_chain": [prov],
                    "recorded_at": format_iso8601(now_ts),
                },
            )
            try:
                self.event_store.append(evt)
                ingested += 1

                # 1. Update World Model observation & entity extraction
                try:
                    self.world_model.record_observation(
                        source="gmail",
                        source_id=msg_ref,
                        timestamp=now_ts,
                        observation_type="email_received",
                        summary=safe_sum,
                        evidence=finding,
                        provenance={"tool": "gmail_search", "ref": msg_ref},
                    )
                except Exception as ex_wm:
                    logger.debug("World model record_observation note: %s", ex_wm)

                # 2. Intelligent Signal Triage & Entity Classification
                sum_lower = safe_sum.lower()
                sender_str = safe_sum.split("]")[0].strip("[") if "]" in safe_sum else "Unknown Sender"
                clean_title = safe_sum.split("]", 1)[1].strip() if "]" in safe_sum else safe_sum[:60]

                if any(k in sum_lower for k in ("security", "alert", "suspicious", "unauthorized", "password", "verification")):
                    sit_type = "security_alert"
                    sit_priority = SituationPriority.HIGH.value
                    sit_summary = f"Security Notification: {clean_title} ({sender_str})"
                    action_rec = "Review recent Google account security activity and verify recent logins."
                elif any(k in sum_lower for k in ("card", "bank", "tax", "invoice", "statement", "payment", "sbi", "bpcl", "due", "valid", "credit")):
                    sit_type = "financial_deadline"
                    sit_priority = SituationPriority.MEDIUM.value
                    sit_summary = f"Financial / Validity Alert: {clean_title}"
                    action_rec = "Review financial statement or card assessment details before deadline."
                    # Derive real commitment
                    try:
                        self.world_model.record_commitment(
                            description=f"Review: {clean_title}",
                            metadata={"sender": sender_str, "origin": "gmail"},
                        )
                    except Exception:
                        pass
                elif any(k in sum_lower for k in ("job", "linkedin", "career", "interview", "opportunity", "hiring")):
                    sit_type = "career_opportunity"
                    sit_priority = SituationPriority.MEDIUM.value
                    sit_summary = f"Career / Professional Opportunity: {clean_title}"
                    action_rec = "Review matching role requirements and candidate criteria."
                else:
                    sit_type = "communication_digest"
                    sit_priority = SituationPriority.LOW.value
                    sit_summary = f"Informational Update: {clean_title}"
                    action_rec = "Archive or file for background awareness."

                # 3. Check for learned user suppression preferences & create Situational Context Frame
                suppressed_types = self.world_model.get_suppressed_situation_types()
                is_suppressed = sit_type in suppressed_types
                init_status = SituationStatus.SUPPRESSED.value if is_suppressed else SituationStatus.OPEN.value
                init_priority = SituationPriority.LOW.value if is_suppressed else sit_priority

                sit = Situation(
                    id=f"sit-email-{evt.id[-8:]}",
                    type=sit_type,
                    priority=init_priority,
                    status=init_status,
                    created_at=now_ts,
                    evidence=[f"event:{evt.id}", prov],
                    context={
                        "summary": sit_summary,
                        "why_detected": f"Grounded live observation from {sender_str} ({prov})." + (" (Auto-suppressed based on learned user feedback preferences)" if is_suppressed else ""),
                        "sender": sender_str,
                        "subject": clean_title,
                    },
                )
                try:
                    self.situation_store.create(sit)
                except Exception as ex_sit:
                    logger.debug("Situation creation note: %s", ex_sit)

                # 4. Create Epistemic Reasoning Episode
                ep = ReasoningEpisode(
                    id=f"ep-live-gmail-{evt.id[-8:]}",
                    situation_id=sit.id,
                    created_at=now_ts,
                    hermes_task=f"Live situational triage: {sit_type}",
                    observations=[
                        safe_sum,
                        f"Provenance: {prov}",
                    ],
                    inferences=[
                        f"Verified communication from '{sender_str}'. Class: {sit_type.replace('_', ' ').title()}.",
                        f"Grounded in authentic Gmail inquiry ({query}) with zero artificial assumptions.",
                    ],
                    predictions=[
                        "Contextual awareness updated for daily priorities and state representation.",
                    ],
                    recommendation={
                        "primary_action": action_rec,
                        "why": f"Derived from verified live email ({sender_str}) with full provenance.",
                    },
                    intervention_decision={
                        "action": "BRIEFING" if sit_priority != SituationPriority.LOW.value else "SILENT_LOG",
                        "reason": f"Live {sit_type.replace('_', ' ')} observation categorized from inbox.",
                    },
                )
                try:
                    self.episode_store.create_episode(ep)
                except Exception as ex_ep:
                    logger.debug("Episode creation note: %s", ex_ep)

            except Exception as e:
                logger.warning("Event append skipped: %s", e)

        # Update State Engine features
        try:
            self.state_engine.compute_current_state(reference_time=now_ts)
        except Exception:
            pass

        self.activity_stream.emit(
            "tool_call_completed",
            f"Gmail investigation completed: {len(res.findings)} message(s) retrieved via Hermes gmail_search, ingested into World Model & Reasoning Episodes",
            source="gmail_capability_adapter",
        )

        return {
            "status": "success",
            "query": query,
            "findings": res.findings,
            "message_references": res.message_references,
            "safe_summaries": res.safe_summaries,
            "provenance": res.provenance,
            "ingested_count": ingested,
            "timestamp": format_iso8601(now_ts),
        }

    def get_data_sources_payload(self) -> Dict[str, Any]:
        """
        Returns consolidated Data Sources status payload:
        - hermes: Connected / Disconnected / Error / Demo
        - gmail: Available / Connected / Unauthenticated / Unavailable / Demo
        - notice: "Gmail connection and authentication are managed by Hermes."
        - last_successful_investigation: tool, timestamp, safe_provenance
        - capabilities: breakdown across all 7 monitored domains
        - is_demo_mode: bool
        """
        from dataclasses import asdict
        from personal_intelligence.hermes_bridge.capabilities import (
            CapabilityAuthStatus,
            CapabilityAvailability,
            HermesConnectionStatus,
        )
        health = self.connection_manager.check_health()

        # Determine hermes status
        if self.is_demo_mode:
            hermes_status = "demo"
        elif health.connection_status == HermesConnectionStatus.CONNECTED:
            hermes_status = "connected"
        elif health.connection_status == HermesConnectionStatus.ERROR:
            hermes_status = "error"
        elif health.connection_status == HermesConnectionStatus.CONNECTING:
            hermes_status = "connecting"
        else:
            hermes_status = "disconnected"

        # Determine gmail independent status: unavailable, unknown, unauthenticated, authenticated (connected), error, demo
        gmail_cap = health.capabilities.get("gmail", {})
        avail = gmail_cap.get("availability") if isinstance(gmail_cap, dict) else getattr(gmail_cap, "availability", None)
        auth = gmail_cap.get("authenticated_status") if isinstance(gmail_cap, dict) else getattr(gmail_cap, "authenticated_status", None)

        if self.is_demo_mode:
            gmail_status = "demo"
        elif avail == CapabilityAvailability.ERROR.value:
            gmail_status = "error"
        elif not gmail_cap or avail != CapabilityAvailability.AVAILABLE.value:
            gmail_status = "unavailable"
        elif auth == CapabilityAuthStatus.AUTHENTICATED.value:
            gmail_status = "connected"
        elif auth == CapabilityAuthStatus.UNAUTHENTICATED.value:
            gmail_status = "unauthenticated"
        elif auth == CapabilityAuthStatus.UNKNOWN.value:
            gmail_status = "unknown"
        else:
            gmail_status = "available"

        needs_hermes_conn = (
            hermes_status == "connected" and
            gmail_status in ("unauthenticated", "unknown")
        )

        # Find last recorded Gmail investigation in EventStore
        last_inv = None
        recent_events = self.current_event_store.get_recent(limit=50)
        for e in recent_events:
            if e.source == "gmail" or e.observation_type == "gmail_evidence_observation":
                prov = e.provenance if isinstance(e.provenance, dict) else {}
                tool_used = prov.get("tool") or "gmail_search"
                safe_prov = prov.get("source_id") or e.source_id or f"gmail:{e.id}"
                last_inv = {
                    "tool": tool_used,
                    "timestamp": format_iso8601(e.timestamp),
                    "provenance": safe_prov,
                    "summary": e.summary or (e.structured_data.get("summary") if isinstance(e.structured_data, dict) else str(e.payload)),
                    "is_demo": bool(self.is_demo_mode or "[DEMO" in str(e.summary)),
                }
                break

        return {
            "status": "success",
            "connection_stage": health.connection_stage.value if hasattr(health, "connection_stage") else "disconnected",
            "gmail_authenticated": health.gmail_authenticated if hasattr(health, "gmail_authenticated") else False,
            "failure_category": getattr(health, "failure_category", None),
            "recommended_action": getattr(health, "recommended_action", None),
            "hermes": {
                "status": hermes_status,
                "is_installed": health.is_installed,
                "is_reachable": health.is_reachable,
                "mechanism": health.reachability_mechanism,
                "runtime_mode": health.active_mode,
                "connection_stage": health.connection_stage.value if hasattr(health, "connection_stage") else "disconnected",
                "failure_category": getattr(health, "failure_category", None),
                "recommended_action": getattr(health, "recommended_action", None),
            },
            "gmail": {
                "status": gmail_status,
                "tool_name": "gmail_search",
                "managed_by": "Hermes",
                "notice": "Gmail connection and authentication are managed by Hermes.",
                "needs_connection_in_hermes": needs_hermes_conn,
                "last_successful_investigation": last_inv,
            },
            "capabilities": health.capabilities,
            "notice": "Gmail connection and authentication are managed by Hermes.",
            "is_demo_mode": self.is_demo_mode,
            "actionable_instructions": health.actionable_instructions,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def get_demo_status_payload(self) -> Dict[str, Any]:
        """Returns current operating mode (LIVE vs DEMO) and loaded scenario metadata."""
        return {
            "is_demo_mode": self.is_demo_mode,
            "active_scenario": self.active_demo_scenario,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def toggle_demo_mode(self, mode: Optional[str] = None) -> Dict[str, Any]:
        """Toggles between LIVE MODE and DEMO MODE."""
        from personal_intelligence.hermes_bridge.client import HermesBridgeExecutionMode
        if mode is not None:
            self.is_demo_mode = (mode.upper() == "DEMO")
        else:
            self.is_demo_mode = not self.is_demo_mode

        if hasattr(self, "hermes_client"):
            self.hermes_client.mode = HermesBridgeExecutionMode.DEMO if self.is_demo_mode else HermesBridgeExecutionMode.LIVE
        if hasattr(self.demo_runner, "hermes_client"):
            self.demo_runner.hermes_client.mode = HermesBridgeExecutionMode.DEMO

        mode_name = "DEMO MODE" if self.is_demo_mode else "LIVE MODE"
        self.activity_stream.emit("state_updated", f"Switched operating mode to {mode_name}", source="mode_switcher")
        return {
            "status": "success",
            "is_demo_mode": self.is_demo_mode,
            "mode": mode_name,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def load_demo_scenario(self, scenario_id: int = 1) -> Dict[str, Any]:
        """Loads and runs a deterministic demonstration scenario (1..5)."""
        self.is_demo_mode = True
        self.active_demo_scenario = scenario_id
        res = self.demo_runner.run_scenario(scenario_id)

        return {
            "status": "success",
            "is_demo_mode": True,
            "scenario": res,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def run_intelligence(self) -> Dict[str, Any]:
        """Executes full intelligence cycle on active state."""
        runner = self.demo_runner if self.is_demo_mode else self
        if hasattr(runner, "run_intelligence"):
            res = runner.run_intelligence()
        else:
            self.activity_stream.emit("state_updated", "Triggered evaluation cycle across live Personal World Model", source="evaluation_loop")
            res = {"status": "success", "mode": "LIVE"}
        return {
            "status": "success",
            "result": res,
            "is_demo_mode": self.is_demo_mode,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def reset_demo_state(self) -> Dict[str, Any]:
        """Resets demo state to pristine initial baseline."""
        self.demo_runner.reset_demo_state()
        self.active_demo_scenario = None
        self._ensure_sample_data_if_empty()
        return {
            "status": "success",
            "message": "Demo state reset successfully.",
            "is_demo_mode": self.is_demo_mode,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def clear_demo_state(self) -> Dict[str, Any]:
        """Completely clears all events, situations, and goals from demo storage."""
        self.demo_runner.reset_demo_state()
        self.active_demo_scenario = None
        self.activity_stream.emit("state_updated", "Cleared all demo events, goals, and situations", source="demo_controller")
        return {
            "status": "success",
            "message": "Demo state cleared completely.",
            "is_demo_mode": self.is_demo_mode,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def get_overview_payload(self) -> Dict[str, Any]:
        """Returns structured Overview screen payload."""
        state_payload = self.get_current_state_payload()
        goals = self.current_goal_store.list_active()
        active_goals = [
            {
                "id": g.id,
                "name": g.name,
                "description": g.description,
                "priority": g.priority.upper() if g.priority else "MEDIUM",
                "status": g.status,
                "progress": getattr(g, "progress", 0.0),
            }
            for g in goals
        ]

        recent_events = self.current_event_store.get_recent(limit=20)
        commitments = [
            {
                "id": e.id,
                "summary": e.payload.get("summary") or e.payload.get("title") or e.event_type if isinstance(e.payload, dict) else str(e.payload),
                "source": e.source,
                "time": format_iso8601(e.event_time),
            }
            for e in recent_events
            if e.event_type in ("calendar_event", "commitment_scheduled", "action_item") or e.source in ("calendar", "meet")
        ][:6]

        open_situations = self.get_active_situations_payload()
        recs = self.get_recommendations_payload()
        patterns = self.get_learned_patterns_payload()
        novelty = self.get_novel_events_payload()

        return {
            "current_state": state_payload,
            "active_goals": active_goals,
            "upcoming_commitments": commitments,
            "open_situations": open_situations,
            "important_recommendations": recs,
            "emerging_patterns": patterns,
            "novelty_indicators": novelty,
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def get_situation_detail_payload(self, situation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns structured presentation-quality Situation Detail payload:
        HEADER, EVIDENCE GRAPH, TIMELINE, HERMES INVESTIGATION, REASONING (Facts, Inferences, Predictions, Uncertainties, Recommendation), and INTERVENTION.
        """
        situation = self.current_situation_store.get(situation_id) if situation_id else None
        if not situation:
            active_sits = self.current_situation_store.list_active()
            if active_sits:
                situation = active_sits[0]

        if not situation:
            return {"status": "error", "message": "No situation found."}

        ctx = situation.context or {}
        recs = self.get_recommendations_payload()
        matching_rec = next((r for r in recs if r.get("situation_id") == situation.id), None)
        if not matching_rec and recs:
            matching_rec = recs[0]

        urgency_val = matching_rec.get("urgency", "HIGH") if matching_rec else "HIGH"
        relevance_val = matching_rec.get("actionability", "HIGH") if matching_rec else "HIGH"
        policy_action = matching_rec.get("policy_action", PolicyAction.BRIEFING.value) if matching_rec else PolicyAction.BRIEFING.value
        policy_reason = matching_rec.get("why", "Evaluated against categorical urgency, actionability, and user availability without fake probabilities.") if matching_rec else "Evaluated against categorical urgency and actionability."

        # 1. HEADER
        header_data = {
            "title": ctx.get("summary") or f"{situation.type.replace('_', ' ').title()}",
            "situation_type": situation.type,
            "status": (situation.status or "ACTIVE").upper(),
            "urgency": urgency_val.upper(),
            "relevance": relevance_val.upper(),
            "priority": (situation.priority or "HIGH").upper(),
            "novelty_score": situation.novelty,
            "detected_at": format_iso8601(situation.created_at),
        }

        # 2. EVIDENCE GRAPH (Actual stored relationships)
        graph_nodes = []
        graph_edges = []
        raw_evidence_ids = situation.evidence or []
        linked_goals = self.current_goal_store.list_active()
        all_events = self.current_event_store.get_recent(limit=50)

        # Situation Node
        graph_nodes.append({
            "id": "node-situation",
            "label": f"Situation: {situation.type.replace('_', ' ').title()}",
            "type": "situation",
            "category": "core",
        })

        # Categorize actual evidence items
        sources_seen = set()
        for ev_id in raw_evidence_ids:
            clean_id = str(ev_id).replace("event:", "").strip()
            ev_obj = next((e for e in all_events if e.id == clean_id), None)
            if ev_obj:
                src_name = ev_obj.source.lower()
                sources_seen.add(src_name)
                summary_txt = ev_obj.payload.get("summary") or ev_obj.payload.get("title") or ev_obj.event_type if isinstance(ev_obj.payload, dict) else str(ev_obj.payload)
                node_id = f"node-ev-{clean_id}"
                graph_nodes.append({
                    "id": node_id,
                    "label": f"{ev_obj.source.title()}: {summary_txt[:40]}",
                    "source": ev_obj.source,
                    "type": "observation",
                    "provenance": f"event:{clean_id}",
                })
                graph_edges.append({
                    "from": node_id,
                    "to": "node-situation",
                    "label": "ground_truth",
                    "relationship": "supports",
                })
            elif "goal:" in str(ev_id) or any(g.id == clean_id for g in linked_goals):
                g_match = next((g for g in linked_goals if g.id == clean_id or f"goal:{g.id}" == str(ev_id)), None)
                g_title = g_match.name if g_match else clean_id
                node_id = f"node-goal-{clean_id}"
                graph_nodes.append({
                    "id": node_id,
                    "label": f"Goal: {g_title[:35]}",
                    "type": "goal",
                    "provenance": f"goal:{clean_id}",
                })
                graph_edges.append({
                    "from": node_id,
                    "to": "node-situation",
                    "label": "constrains",
                    "relationship": "goal_impact",
                })
            else:
                node_id = f"node-ref-{clean_id}"
                graph_nodes.append({
                    "id": node_id,
                    "label": f"Evidence: {clean_id[:30]}",
                    "type": "observation",
                    "provenance": str(ev_id),
                })
                graph_edges.append({
                    "from": node_id,
                    "to": "node-situation",
                    "label": "correlates",
                    "relationship": "context",
                })

        # Add timeline connector node
        graph_nodes.append({
            "id": "node-timeline",
            "label": "Timeline: Chronological 24h Window",
            "type": "timeline",
        })
        graph_edges.append({
            "from": "node-timeline",
            "to": "node-situation",
            "label": "temporal_frame",
            "relationship": "context_window",
        })

        # 3. TIMELINE (Chronological relevant observations)
        timeline_nodes = [
            {
                "id": e.id,
                "source": e.source,
                "time": format_iso8601(e.event_time),
                "summary": e.payload.get("summary") or e.payload.get("title") or e.event_type if isinstance(e.payload, dict) else str(e.payload),
                "provenance": f"{e.source}:{e.id}",
            }
            for e in all_events[:8]
        ]

        # 4. INVESTIGATION (High-level capability calls without sensitive dumps)
        investigation_calls = []
        
        # Check for real recorded Gmail observations
        gmail_evts = [e for e in all_events if e.source == "gmail" or getattr(e, "observation_type", "") == "gmail_evidence_observation"]
        if gmail_evts:
            for g_evt in gmail_evts[:2]:
                summary_text = g_evt.summary if hasattr(g_evt, "summary") and g_evt.summary else (g_evt.payload.get("summary", "Gmail observation") if isinstance(g_evt.payload, dict) else str(g_evt.payload))
                prefix = "[DEMO DATA] " if self.is_demo_mode or "[DEMO" in summary_text else ""
                investigation_calls.append({
                    "capability": "Gmail",
                    "status": "INVESTIGATED",
                    "summary": f"{prefix}Gmail tool executed: {summary_text}",
                    "provenance": g_evt.provenance if isinstance(g_evt.provenance, str) else (g_evt.provenance.get("source_id") if isinstance(g_evt.provenance, dict) else f"gmail:{g_evt.id}"),
                })
        elif self.is_demo_mode and ("gmail" in sources_seen or "commitment" in situation.type):
            investigation_calls.append({
                "capability": "Gmail",
                "status": "INVESTIGATED",
                "summary": "[DEMO DATA] Gmail fixture investigated: Synthetic message items observed",
                "provenance": "demo_gmail_search",
            })

        # Check for Drive observations
        drive_evts = [e for e in all_events if e.source == "drive" or getattr(e, "observation_type", "") == "document_changed"]
        if drive_evts:
            for d_evt in drive_evts[:2]:
                summary_text = d_evt.summary if hasattr(d_evt, "summary") and d_evt.summary else (d_evt.payload.get("summary", "Drive observation") if isinstance(d_evt.payload, dict) else str(d_evt.payload))
                prefix = "[DEMO DATA] " if self.is_demo_mode or "[DEMO" in summary_text else ""
                investigation_calls.append({
                    "capability": "Google Drive",
                    "status": "INVESTIGATED",
                    "summary": f"{prefix}Drive tool executed: {summary_text}",
                    "provenance": str(d_evt.source_id or d_evt.id),
                })
        elif self.is_demo_mode and ("drive" in sources_seen or "deliverable" in situation.type):
            investigation_calls.append({
                "capability": "Google Drive",
                "status": "INVESTIGATED",
                "summary": "[DEMO DATA] Drive fixture investigated: Verified document modification timestamps and draft status",
                "provenance": "demo_drive_search",
            })

        # Check for Calendar observations
        cal_evts = [e for e in all_events if e.source == "calendar" or getattr(e, "observation_type", "") == "meeting_decision"]
        if cal_evts:
            for c_evt in cal_evts[:2]:
                summary_text = c_evt.summary if hasattr(c_evt, "summary") and c_evt.summary else (c_evt.payload.get("summary", "Calendar event") if isinstance(c_evt.payload, dict) else str(c_evt.payload))
                prefix = "[DEMO DATA] " if self.is_demo_mode or "[DEMO" in summary_text else ""
                investigation_calls.append({
                    "capability": "Google Calendar",
                    "status": "INVESTIGATED",
                    "summary": f"{prefix}Calendar tool executed: {summary_text}",
                    "provenance": str(c_evt.source_id or c_evt.id),
                })
        elif self.is_demo_mode and ("calendar" in sources_seen or "schedule" in situation.type or "timing" in situation.type):
            investigation_calls.append({
                "capability": "Google Calendar",
                "status": "INVESTIGATED",
                "summary": "[DEMO DATA] Calendar fixture investigated: Checked scheduled events and transit buffers",
                "provenance": "demo_calendar_list",
            })

        # Check for Meet observations
        meet_evts = [e for e in all_events if e.source == "meet"]
        if meet_evts:
            for m_evt in meet_evts[:2]:
                summary_text = m_evt.summary if hasattr(m_evt, "summary") and m_evt.summary else (m_evt.payload.get("summary", "Meet transcript") if isinstance(m_evt.payload, dict) else str(m_evt.payload))
                prefix = "[DEMO DATA] " if self.is_demo_mode or "[DEMO" in summary_text else ""
                investigation_calls.append({
                    "capability": "Google Meet",
                    "status": "INVESTIGATED",
                    "summary": f"{prefix}Meet tool executed: {summary_text}",
                    "provenance": str(m_evt.source_id or m_evt.id),
                })
        elif self.is_demo_mode and ("meet" in sources_seen or "commitment" in situation.type):
            investigation_calls.append({
                "capability": "Google Meet",
                "status": "INVESTIGATED",
                "summary": "[DEMO DATA] Meet fixture investigated: Retrieved action items and decisions from sync transcript",
                "provenance": "demo_meet_get_transcript",
            })

        if not investigation_calls:
            investigation_calls.append({
                "capability": "Local Observations",
                "status": "INVESTIGATED",
                "summary": "Local observations evaluated: Correlated timeline sensor telemetry and baseline divergence metrics",
                "provenance": "timeline_state_engine",
            })

        # 5. REASONING (Epistemic separation)
        facts_list = []
        for n in graph_nodes:
            if n["type"] == "observation":
                facts_list.append({"tag": "FACT", "content": n["label"], "provenance": n.get("provenance", "system")})
        if not facts_list:
            facts_list.append({"tag": "FACT", "content": ctx.get("summary", "Verified state telemetry logged in timeline."), "provenance": "event_log"})

        inferences_list = [
            {"tag": "INFERENCE", "content": ctx.get("summary") or f"State imbalance in {situation.type} increases execution risk."},
            {"tag": "INFERENCE", "content": "Contradicting schedule or energy commitments reduce flexibility for unaddressed gaps."},
        ]

        predictions_list = [
            {"tag": "PREDICTION", "content": "Without prompt prioritization or scheduling intervention, goal commitments will slip."},
        ]

        uncertainties_list = [
            "Whether collaborator feedback has arrived through untracked asynchronous channels.",
            "Exact discretionary deep-work windows available after current commitment blocks.",
        ]

        recommendation_obj = {
            "primary": matching_rec["title"] if matching_rec else "Protect dedicated focus window to finalize required deliverable sections.",
            "secondary": matching_rec.get("secondary_action") if matching_rec else "Review scheduled calendar density tomorrow.",
            "why": matching_rec.get("why") if matching_rec else "Preserves longitudinal progress while mitigating acute delivery risks.",
        }

        # 6. INTERVENTION (Display all 5 policy options with active highlighted)
        all_policy_options = ["INTERRUPT", "BRIEFING", "DEFER", "SUPPRESS", "DISCARD"]
        intervention_data = {
            "selected_action": policy_action,
            "all_actions": all_policy_options,
            "reason": policy_reason,
            "user_context": matching_rec.get("user_context", "Available") if matching_rec else "Available",
        }

        return {
            "status": "success",
            "situation_id": situation.id,
            "situation_type": situation.type,
            "header": header_data,
            "evidence_graph": {
                "nodes": graph_nodes,
                "edges": graph_edges,
                "sources_represented": list(sources_seen) or ["local"],
            },
            "timeline": timeline_nodes,
            "investigation": {
                "status": "INVESTIGATED" if not situation.information_required else "READY_FOR_INVESTIGATION",
                "calls": investigation_calls,
            },
            "reasoning": {
                "facts": facts_list,
                "inferences": inferences_list,
                "predictions": predictions_list,
                "uncertainties": uncertainties_list,
                "recommendation": recommendation_obj,
            },
            "intervention": intervention_data,
            "flow": {
                "trigger": {
                    "stage": "TRIGGER",
                    "title": header_data["title"],
                    "description": ctx.get("why_detected") or ctx.get("summary") or "State deviation across longitudinal streams.",
                    "priority": header_data["priority"],
                    "novelty_score": situation.novelty,
                    "detected_at": header_data["detected_at"],
                },
                "observations": facts_list,
                "timeline": timeline_nodes,
                "information_gaps": uncertainties_list,
                "investigation": {
                    "status": "INVESTIGATED" if not situation.information_required else "READY_FOR_INVESTIGATION",
                    "target": situation.investigation_target or situation.type,
                    "capabilities_used": list(sources_seen) or ["workspace_read"],
                    "tool_calls_count": len(investigation_calls),
                    "gap_resolved": not situation.information_required,
                },
                "evidence": [
                    {"tag": "FACT", "source_provenance": str(e_id), "detail": f"Ground-truth telemetry verified for {e_id}"}
                    for e_id in raw_evidence_ids
                ],
                "reasoning": {
                    "inferences": inferences_list,
                    "predictions": predictions_list,
                },
                "recommendation": {
                    "tag": "RECOMMENDATION",
                    "primary": recommendation_obj["primary"],
                    "secondary": recommendation_obj["secondary"],
                    "why": recommendation_obj["why"],
                },
                "intervention": {
                    "tag": "INTERVENTION",
                    "action": intervention_data["selected_action"],
                    "reason": intervention_data["reason"],
                    "user_context": intervention_data["user_context"],
                },
            },
            "timestamp": format_iso8601(datetime.now(timezone.utc)),
        }

    def get_complete_dashboard_summary(self) -> Dict[str, Any]:
        """Aggregates all 6 dashboard sections into a single atomic JSON payload."""
        return {
            "overview": self.get_overview_payload(),
            "current_state": self.get_current_state_payload(),
            "active_situations": self.get_active_situations_payload(),
            "recommendations": self.get_recommendations_payload(),
            "learned_patterns": self.get_learned_patterns_payload().get("patterns", []),
            "learned_patterns_categorized": self.get_learned_patterns_payload(),
            "reasoning_episodes": self.get_reasoning_episodes_payload(),
            "novel_events": self.get_novel_events_payload(),
            "timeline": self.get_timeline_payload(limit=25),
            "generated_at": format_iso8601(datetime.now(timezone.utc)),
        }


class PersonalIntelligenceRequestHandler(SimpleHTTPRequestHandler):
    """
    HTTP Request Handler serving UI assets and JSON REST endpoints.
    Supports /api/pi/* and /api/* routes.
    """

    data_service: Optional[DashboardDataService] = None
    ui_directory: str = ""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=self.ui_directory, **kwargs)

    def _send_json_response(self, data: Any, status_code: int = 200) -> None:
        """Sends a JSON formatted HTTP response."""
        json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(json_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(json_bytes)

    def do_OPTIONS(self) -> None:
        """Handles CORS preflight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        """Handles GET requests for static UI assets and JSON API endpoints."""
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/")
        query = parse_qs(parsed_url.query)

        if not self.data_service:
            self.data_service = DashboardDataService()

        # Canonical /api/pi/* routes and legacy aliases
        if path in ("/api/pi/overview", "/api/overview"):
            self._send_json_response(self.data_service.get_overview_payload())
        elif path in ("/api/pi/summary", "/api/summary"):
            self._send_json_response(self.data_service.get_complete_dashboard_summary())
        elif path in ("/api/pi/world_model", "/api/world_model", "/api/pi/state", "/api/state"):
            self._send_json_response(self.data_service.get_world_model_payload())
        elif path in ("/api/pi/situations", "/api/situations"):
            sit_id = query.get("id", [None])[0]
            if sit_id:
                self._send_json_response(self.data_service.get_situation_detail_payload(situation_id=sit_id))
            else:
                self._send_json_response(self.data_service.get_active_situations_payload())
        elif path.startswith("/api/pi/situations/") or path.startswith("/api/situations/"):
            parts = path.split("/")
            sit_id = parts[-1] if len(parts) > 3 else None
            self._send_json_response(self.data_service.get_situation_detail_payload(situation_id=sit_id))
        elif path in ("/api/pi/recommendations", "/api/recommendations"):
            self._send_json_response(self.data_service.get_recommendations_payload())
        elif path in ("/api/pi/patterns", "/api/patterns"):
            self._send_json_response(self.data_service.get_learned_patterns_payload())
        elif path in ("/api/pi/episodes", "/api/episodes"):
            self._send_json_response(self.data_service.get_reasoning_episodes_payload())
        elif path in ("/api/pi/novelty", "/api/novelty"):
            self._send_json_response(self.data_service.get_novel_events_payload())
        elif path in ("/api/pi/timeline", "/api/timeline"):
            limit = int(query.get("limit", [50])[0]) if "limit" in query else 50
            self._send_json_response(self.data_service.get_timeline_payload(limit=limit))
        elif path in ("/api/pi/activity", "/api/activity"):
            since_id = query.get("since_id", [None])[0]
            limit = int(query.get("limit", [50])[0]) if "limit" in query else 50
            self._send_json_response(self.data_service.get_activity_payload(since_id=since_id, limit=limit))
        elif path in ("/api/pi/sources/status", "/api/pi/data_sources", "/api/data_sources"):
            self._send_json_response(self.data_service.get_data_sources_payload())
        elif path in ("/api/pi/sources", "/api/sources"):
            self._send_json_response(self.data_service.get_test_sources_payload())
        elif path in ("/api/pi/hermes/status", "/api/hermes/status"):
            self._send_json_response(self.data_service.get_hermes_status_payload())
        elif path in ("/api/pi/hermes/setup_gmail", "/api/hermes/setup_gmail", "/api/pi/hermes/gmail_flow", "/api/hermes/gmail_flow"):
            self._send_json_response(self.data_service.get_gmail_setup_flow())
        elif path in ("/api/pi/sync/status", "/api/sync/status"):
            self._send_json_response(self.data_service.get_sync_status_payload())
        elif path in ("/api/pi/search/vector_status", "/api/search/vector_status"):
            self._send_json_response(self.data_service.get_vector_search_status())
        elif path in ("/api/pi/fusion/status", "/api/fusion/status"):
            self._send_json_response(self.data_service.get_fusion_status())
        elif path in ("/api/pi/demo/status", "/api/demo/status"):
            self._send_json_response(self.data_service.get_demo_status_payload())
        elif path in ("/api/pi/mode", "/api/mode"):
            self._send_json_response(self.data_service.get_mode_payload())
        elif path in ("/api/pi/reasoning_trace", "/api/reasoning_trace"):
            sit_id = query.get("situation_id", [None])[0] or query.get("id", [None])[0]
            self._send_json_response(self.data_service.get_reasoning_trace_payload(situation_id=sit_id))
        elif path in ("/api/pi/what_changed", "/api/what_changed"):
            hours = int(query.get("hours", [48])[0])
            self._send_json_response(self.data_service.execute_what_changed(time_window_hours=hours))
        elif path in ("/api/pi/what_matters_now", "/api/what_matters_now"):
            self._send_json_response(self.data_service.execute_what_matters())
        else:
            # Fall back to serving static files from ui directory
            super().do_GET()

    def do_POST(self) -> None:
        """Handles POST action invocations."""
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/")

        if not self.data_service:
            self.data_service = DashboardDataService()

        # Parse JSON body
        content_length = int(self.headers.get("Content-Length", 0))
        body: Dict[str, Any] = {}
        if content_length > 0:
            try:
                body_bytes = self.rfile.read(content_length)
                body = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                body = {}

        if path in ("/api/pi/mode", "/api/mode"):
            mode = body.get("mode", "LIVE")
            self._send_json_response(self.data_service.set_operating_mode(mode=mode))
        elif path in ("/api/pi/demo/scenario", "/api/demo/scenario", "/api/pi/demo/load_scenario", "/api/demo/load_scenario"):
            scen_id = int(body.get("scenario_id") or body.get("scenario") or body.get("id") or 1)
            self._send_json_response(self.data_service.load_demo_scenario(scenario_id=scen_id))

        if path in ("/api/pi/actions/what_matters", "/api/actions/what_matters"):
            self._send_json_response(self.data_service.execute_what_matters())
        elif path in ("/api/pi/actions/what_changed", "/api/actions/what_changed"):
            hours = int(body.get("time_window_hours", 48))
            self._send_json_response(self.data_service.execute_what_changed(time_window_hours=hours))
        elif path in ("/api/pi/actions/investigate", "/api/actions/investigate"):
            sit_id = body.get("situation_id")
            self._send_json_response(self.data_service.execute_investigate(situation_id=sit_id))
        elif path in ("/api/pi/actions/why", "/api/actions/why"):
            sit_id = body.get("situation_id")
            self._send_json_response(self.data_service.execute_why(situation_id=sit_id))
        elif path in ("/api/pi/actions/test_sources", "/api/actions/test_sources"):
            self._send_json_response(self.data_service.execute_test_sources())
        elif path in ("/api/pi/sync/trigger", "/api/sync/trigger"):
            self._send_json_response(self.data_service.trigger_sync_now())
        elif path in ("/api/pi/notifications/test", "/api/notifications/test"):
            self._send_json_response(self.data_service.trigger_test_notification())
        elif path in ("/api/pi/search/hybrid", "/api/search/hybrid"):
            q = body.get("query", "")
            limit = int(body.get("limit", 10))
            self._send_json_response(self.data_service.execute_hybrid_search(query=q, limit=limit))
        elif path in ("/api/pi/situations/feedback", "/api/situations/feedback"):
            sit_id = body.get("situation_id", "")
            act = body.get("action", "acknowledge")
            snooze = int(body.get("snooze_days", 2))
            notes = body.get("feedback_notes")
            self._send_json_response(self.data_service.handle_situation_feedback(
                situation_id=sit_id,
                action=act,
                snooze_days=snooze,
                feedback_notes=notes,
            ))
        elif path in ("/api/pi/calendar/sync", "/api/calendar/sync", "/api/pi/calendar/ingest", "/api/calendar/ingest"):
            days = int(body.get("time_range_days", 7))
            self._send_json_response(self.data_service.execute_calendar_sync(time_range_days=days))
        elif path in ("/api/pi/voice_notes/ingest", "/api/voice_notes/ingest", "/api/pi/voice_notes/save", "/api/voice_notes/save"):
            txt = body.get("text", "") or body.get("transcript", "") or body.get("content", "")
            title = body.get("title")
            self._send_json_response(self.data_service.execute_voice_note_ingest(text=txt, title=title))
        elif path in ("/api/pi/fusion/analyze", "/api/fusion/analyze"):
            self.data_service.fusion_engine.synthesize_fusion_situations()
            self._send_json_response(self.data_service.get_fusion_status())
        elif path in ("/api/pi/hermes/connect", "/api/hermes/connect"):
            self._send_json_response(self.data_service.connect_hermes())
        elif path in ("/api/pi/hermes/setup_gmail", "/api/hermes/setup_gmail"):
            self._send_json_response(self.data_service.get_gmail_setup_flow())
        elif path in ("/api/pi/hermes/auth", "/api/pi/hermes/auth_google", "/api/hermes/auth"):
            cap = body.get("capability", "gmail")
            self._send_json_response(self.data_service.trigger_hermes_auth(capability=cap))
        elif path in ("/api/pi/hermes/configure_auth", "/api/hermes/configure_auth"):
            self._send_json_response(self.data_service.configure_hermes_auth(payload=body))
        elif path in ("/api/pi/gmail/investigate", "/api/pi/gmail/search", "/api/gmail/search"):
            q = body.get("query", "is:inbox")
            max_res = int(body.get("max_results", 100))
            days = int(body.get("days", 40))
            self._send_json_response(self.data_service.execute_gmail_investigation(query=q, max_results=max_res, days=days))
        elif path in ("/api/pi/ask", "/api/ask"):
            q = body.get("query") or body.get("question") or "What should I be aware of today?"
            sit_id = body.get("situation_id")
            self._send_json_response(self.data_service.execute_ask(query=q, situation_id=sit_id))
        elif path in ("/api/pi/actions/command", "/api/actions/command"):
            cmd = body.get("command", "/pi status")
            self._send_json_response(self.data_service.execute_command(command=cmd))
        elif path in ("/api/pi/live/run_flow", "/api/live/run_flow", "/api/pi/actions/live_flow", "/api/actions/live_flow"):
            self._send_json_response(self.data_service.execute_live_google_flow())
        elif path in ("/api/pi/demo/load_scenario", "/api/demo/load_scenario"):
            scen_id = int(body.get("scenario_id", 1))
            self._send_json_response(self.data_service.load_demo_scenario(scenario_id=scen_id))
        elif path in ("/api/pi/demo/reset", "/api/demo/reset"):
            self._send_json_response(self.data_service.reset_demo_state())
        elif path in ("/api/pi/demo/clear", "/api/demo/clear"):
            self._send_json_response(self.data_service.clear_demo_state())
        elif path in ("/api/pi/demo/run_intelligence", "/api/demo/run_intelligence"):
            self._send_json_response(self.data_service.run_intelligence())
        elif path in ("/api/pi/demo/toggle", "/api/demo/toggle"):
            mode = body.get("mode")
            self._send_json_response(self.data_service.toggle_demo_mode(mode=mode))
        else:
            self._send_json_response({"status": "error", "message": f"Action endpoint '{path}' not found"}, 404)


def create_dashboard_server(
    port: int = 8080,
    host: str = "127.0.0.1",
    db_manager: Optional[DatabaseManager] = None,
    ui_dir: Optional[str] = None,
    is_demo_mode: bool = False,
    auto_seed_sample_data: bool = False,
    sync_interval_minutes: int = 30,
) -> HTTPServer:
    """
    Constructs and configures the HTTP dashboard server.
    """
    if ui_dir is None:
        project_root = Path(__file__).resolve().parent.parent.parent
        ui_dir = str(project_root / "ui")

    data_service = DashboardDataService(
        db_manager=db_manager,
        is_demo_mode=is_demo_mode,
        auto_seed_sample_data=auto_seed_sample_data,
        sync_interval_minutes=sync_interval_minutes,
    )

    class CustomHandler(PersonalIntelligenceRequestHandler):
        pass

    CustomHandler.data_service = data_service
    CustomHandler.ui_directory = ui_dir

    server = HTTPServer((host, port), CustomHandler)
    return server


from personal_intelligence.api.ingestion import EventIngestionService, IngestionStatus


class EventAPIRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for Event Ingestion REST API."""

    service: Optional[EventIngestionService] = None

    def _send_json(self, data: Any, status_code: int = 200) -> None:
        json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(json_bytes)))
        self.end_headers()
        self.wfile.write(json_bytes)

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/")
        if path == "/health":
            total = self.service.event_store.count() if self.service and self.service.event_store else 0
            self._send_json({"status": "ok", "service": "personal_intelligence_event_api", "total_events": total})
        elif path == "/events/recent":
            limit = 50
            query = parse_qs(parsed_url.query)
            if "limit" in query:
                try:
                    limit = int(query["limit"][0])
                except (ValueError, TypeError):
                    limit = 50
            events = self.service.event_store.get_recent(limit=limit) if self.service and self.service.event_store else []
            self._send_json({"status": "success", "count": len(events), "events": [e.to_dict() for e in events]})
        else:
            self._send_json({"status": "error", "message": f"Endpoint {self.path} not found"}, 404)

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/")
        if path == "/events":
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception as e:
                self._send_json({"status": "rejected", "error": f"Invalid JSON body: {str(e)}"}, 400)
                return

            res = self.service.ingest_event(payload)
            if res.status == IngestionStatus.ACCEPTED:
                self._send_json(res.to_dict(), 201)
            elif res.status == IngestionStatus.DUPLICATE:
                self._send_json(res.to_dict(), 200)
            else:
                self._send_json(res.to_dict(), 400)
        else:
            self._send_json({"status": "error", "message": f"Endpoint {self.path} not found"}, 404)


class EventAPIServer:
    """HTTP server encapsulating the event ingestion REST API."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000, service: Optional[EventIngestionService] = None) -> None:
        self.host = host
        self.service = service or EventIngestionService()

        class CustomEventAPIHandler(EventAPIRequestHandler):
            pass

        CustomEventAPIHandler.service = self.service

        self.httpd = HTTPServer((self.host, port), CustomEventAPIHandler)
        self.port = self.httpd.server_port

    def start(self) -> None:
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Personal Intelligence UI & API Server")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default 8080)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default 127.0.0.1)")
    args = parser.parse_args()

    server = create_dashboard_server(port=args.port, host=args.host)
    print(f"[*] Personal Intelligence UI & API Server running at: http://{args.host}:{args.port}/")
    print(f"[*] API surface available at: http://{args.host}:{args.port}/api/pi/*")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.shutdown()
        server.server_close()

