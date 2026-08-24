"""
Hermes tool handlers for the Personal Intelligence plugin.
Provides bounded, read-heavy access and reasoning outcome storage without exposing raw SQLite.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStatus, EpisodeStore
from personal_intelligence.core.events import EventStore
from personal_intelligence.core.goals import GoalStore
from personal_intelligence.core.situations import SituationStore
from personal_intelligence.core.state import StateEngine
from personal_intelligence.core.timeline import TimelineEngine
from personal_intelligence.storage.db import DatabaseManager


# Singleton runtime instances (or instantiated per call with default db)
_db_manager = DatabaseManager()
_event_store = EventStore(db_manager=_db_manager)
_timeline_engine = TimelineEngine(event_store=_event_store)
_goal_store = GoalStore(db_manager=_db_manager)
_situation_store = SituationStore(db_manager=_db_manager)
_episode_store = EpisodeStore(db_manager=_db_manager)
_state_engine = StateEngine(timeline_engine=_timeline_engine, goal_store=_goal_store)
_context_builder = ContextBuilder(
    timeline_engine=_timeline_engine,
    goal_store=_goal_store,
    situation_store=_situation_store,
)


def get_current_personal_state(
    subject_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Query the current user state representation across standard dimensions
    (time_of_day, location, activity, event_density, duration, routine_deviation, goal_pressure).
    """
    try:
        state = _state_engine.compute_current_state(subject_id=subject_id)
        return {
            "status": "success",
            "timestamp": state.to_dict()["timestamp"],
            "state_representation": state.to_dict(),
            "compact_values": state.to_compact_dict()["values"],
        }
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def get_personal_timeline(
    last_n_minutes: Optional[int] = None,
    last_n_hours: Optional[int] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    subject_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Query a bounded, chronological slice of recent personal events from the timeline.
    """
    try:
        now = datetime.now(timezone.utc)
        if last_n_minutes is not None:
            tl = _timeline_engine.get_last_n_minutes(last_n_minutes, reference_time=now, subject_id=subject_id)
        elif last_n_hours is not None:
            tl = _timeline_engine.get_last_n_hours(last_n_hours, reference_time=now, subject_id=subject_id)
        elif event_type is not None:
            tl = _timeline_engine.get_for_type(event_type, limit=limit)
        else:
            tl = _timeline_engine.get_time_range(
                start_time=start_time,
                end_time=end_time,
                subject_id=subject_id,
                limit=limit,
            )

        events_data = [
            {
                "event_id": e.id,
                "timestamp": e.event_time.isoformat(),
                "event_type": e.event_type,
                "source": e.source,
                "subject": e.subject_id,
                "payload": e.payload,
                "confidence": e.confidence,
            }
            for e in tl.events[:limit]
        ]

        return {
            "status": "success",
            "event_count": len(events_data),
            "events": events_data,
            "summary_raw": tl.summarize_raw() if len(tl) > 0 else {},
        }
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def get_active_goals(
    status: str = "active",
) -> Dict[str, Any]:
    """
    Query active personal goals, priorities, and contextual objectives.
    """
    try:
        if status == "active":
            goals = _goal_store.list_active_goals()
        else:
            goals = _goal_store.list_all_goals(status=status)

        return {
            "status": "success",
            "goal_count": len(goals),
            "goals": [g.to_dict() for g in goals],
        }
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def get_situation(
    situation_id: str,
) -> Dict[str, Any]:
    """
    Query the specific situation frame and its associated evidence and context.
    """
    try:
        sit = _situation_store.get(situation_id)
        if not sit:
            return {"status": "not_found", "error": f"Situation '{situation_id}' not found."}

        return {
            "status": "success",
            "situation": sit.to_dict(),
        }
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def get_reasoning_context(
    situation_id: str,
    objective: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Construct a bounded, relevance-filtered reasoning context for a Situation.
    Contains relevant timeline events, active goals, emerging hypotheses, and uncertainties.
    """
    try:
        sit = _situation_store.get(situation_id)
        if not sit:
            return {"status": "not_found", "error": f"Situation '{situation_id}' not found."}

        state = _state_engine.compute_current_state()
        timeline = _timeline_engine.get_last_n_hours(24)
        goals = _goal_store.list_active_goals()

        context = _context_builder.build_bounded_context(
            situation=sit,
            current_state=state,
            timeline=timeline,
            goals=goals,
            objective=objective,
        )

        return {
            "status": "success",
            "context_id": context.context_id,
            "bounded_context": context.to_dict(),
            "formatted_prompt": context.to_prompt_string(),
        }
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def store_reasoning_episode(
    situation_id: str,
    trigger_type: str = "situation_investigation",
    outcome_evaluation: Optional[str] = None,
    outcome_success: bool = True,
    lessons_learned: Optional[List[str]] = None,
    observations: Optional[List[str]] = None,
    inferences: Optional[List[str]] = None,
    predictions: Optional[List[str]] = None,
    recommendations: Optional[List[str]] = None,
    uncertainties_identified: Optional[List[str]] = None,
    evidence_references: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Record the outcome of a Hermes situational reasoning investigation back to the audit history.
    Explicitly tracks observations, inferences, predictions, recommendations, and uncertainties.
    """
    try:
        now = datetime.now(timezone.utc)
        meta = dict(metadata or {})
        if observations:
            meta["observations"] = observations
        if inferences:
            meta["inferences"] = inferences
        if predictions:
            meta["predictions"] = predictions
        if recommendations:
            meta["recommendations"] = recommendations
        if uncertainties_identified:
            meta["uncertainties_identified"] = uncertainties_identified
        if evidence_references:
            meta["evidence_references"] = evidence_references

        ep = _episode_store.create_episode(
            trigger_type=trigger_type,
            situation_id=situation_id,
            metadata=meta,
        )

        updated_ep = _episode_store.update_episode(
            episode_id=ep.episode_id,
            status=EpisodeStatus.REASONING_COMPLETED,
            ended_at=now,
            outcome_evaluation=outcome_evaluation,
            outcome_success=outcome_success,
            lessons_learned=lessons_learned or [],
            metadata=meta,
        )

        return {
            "status": "success",
            "episode_id": ep.episode_id,
            "recorded_at": now.isoformat(),
            "outcome_success": outcome_success,
        }
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def record_observation(
    source: str,
    source_id: str,
    timestamp: str,
    observation_type: str,
    summary: str,
    evidence: Optional[Union[Dict[str, Any], List[Any], str]] = None,
    provenance: Optional[Dict[str, Any]] = None,
    subject_id: Optional[str] = "user",
    confidence: float = 1.0,
) -> Dict[str, Any]:
    """
    Record a normalized personal observation encountered during Hermes tool execution.
    Does NOT store raw multi-megabyte external documents; stores concise summaries and
    salient evidence while preserving retrieval provenance.
    """
    try:
        from personal_intelligence.core.events.observation import record_observation as core_record_obs

        event = core_record_obs(
            source=source,
            source_id=source_id,
            timestamp=timestamp,
            observation_type=observation_type,
            summary=summary,
            evidence=evidence,
            provenance=provenance,
            subject_id=subject_id,
            confidence=confidence,
            event_store=_event_store,
        )

        return {
            "status": "success",
            "event_id": event.id,
            "source": event.source,
            "source_id": event.source_id,
            "observation_type": event.event_type,
            "timestamp": event.event_time.isoformat(),
            "summary": event.payload.get("summary") if isinstance(event.payload, dict) else "",
            "provenance": event.provenance,
        }
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def get_personal_world_model(
    include_timeline_hours: int = 24,
) -> Dict[str, Any]:
    """
    Query the complete Personal World Model snapshot derived from observations:
    - CURRENT STATE (commitments, upcoming events, open issues, recent activity, goals, active situations)
    - TIMELINE
    - GOALS
    - OPEN SITUATIONS
    - KNOWN PATTERNS
    - EMERGING HYPOTHESES
    """
    try:
        from personal_intelligence.core.world.model import PersonalWorldModel

        world_model = PersonalWorldModel(db_manager=_db_manager)
        snapshot = world_model.get_snapshot()

        return {
            "status": "success",
            "world_model": snapshot.to_dict(),
        }
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def evaluate_candidate_situations(
    save_to_store: bool = True,
) -> Dict[str, Any]:
    """
    Run the Personal Intelligence Situation Engine to identify candidate situations
    across 9 generic categories without notifying the user or taking unprompted actions.
    """
    try:
        from personal_intelligence.core.situations.engine import SituationEngine
        from personal_intelligence.core.world.model import PersonalWorldModel

        world_model = PersonalWorldModel(db_manager=_db_manager)
        engine = SituationEngine()
        evaluation = engine.evaluate_world_model(world_model)

        if save_to_store:
            for sit in evaluation.candidate_situations:
                # Upsert or store active situation
                _situation_store.create(
                    type=sit.type,
                    priority=sit.priority,
                    novelty=sit.novelty,
                    context=sit.context,
                    evidence=sit.evidence,
                    related_goals=sit.related_goals,
                    situation_id=sit.id,
                )

        return {
            "status": "success",
            "candidate_count": len(evaluation.candidate_situations),
            "candidate_situations": [s.to_dict() for s in evaluation.candidate_situations],
            "evidence": evaluation.evidence,
        }
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def execute_pi_command(
    mode: str = "what_matters",
    situation_id: Optional[str] = None,
    limit: int = 5,
    user_context: str = "available",
    db_manager: Optional[DatabaseManager] = None,
) -> Dict[str, Any]:
    """
    Execute a Hermes Personal Intelligence (/pi) command mode.
    Modes: what_matters, status, investigate, patterns, timeline, goals, situations, briefing.
    """
    try:
        from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
        mgr = db_manager or _db_manager
        mgr.initialize_schema()
        handler = PersonalIntelligenceCommandHandler(db_manager=mgr)

        cmd = f"/pi {mode}"
        if situation_id and mode in ("investigate", "why"):
            cmd += f" {situation_id}"
        elif mode in ("timeline", "what_matters", "what_changed"):
            cmd += f" {limit}"


        result_text = handler.execute(cmd)
        return {
            "status": "success",
            "mode": mode,
            "result_text": result_text,
        }
    except Exception as ex:
        return {"status": "error", "mode": mode, "error": str(ex)}





