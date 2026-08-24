"""
Personal World Model implementation for the personal_intelligence Hermes plugin.

Derived strictly from verified observations and structured reasoning episodes.
Maintains:
1. CURRENT STATE (commitments, upcoming events, open issues, recent important activity, known goals, active situations)
2. TIMELINE (chronological personal observations)
3. GOALS (contextual intentions and objectives)
4. OPEN SITUATIONS (active tension frames)
5. KNOWN PATTERNS (empirically supported regularities)
6. EMERGING HYPOTHESES (candidate patterns under evaluation)

Uses SQLite. Does NOT use a graph database.
All state changes pass through validated structured operations with complete provenance.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Union
import uuid

from personal_intelligence.core.episodes.models import (
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.events.exceptions import EventValidationError
from personal_intelligence.core.events.models import Event, ensure_timezone_aware, format_iso8601
from personal_intelligence.core.events.observation import record_observation as core_record_obs
from personal_intelligence.core.goals.engine import GoalEngine
from personal_intelligence.core.goals.models import (
    Goal,
    GoalConflict,
    GoalEvaluation,
    GoalImpact,
    GoalPriority,
    GoalStatus,
)
from personal_intelligence.core.patterns.engine import LearningEngine
from personal_intelligence.core.patterns.models import (
    EvidenceObservationType,
    PatternStatus,
    PatternType,
)
from personal_intelligence.core.situations.models import (
    Situation,
    SituationPriority,
    SituationStatus,
)
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.state.entity_store import EntityState
from personal_intelligence.core.timeline.engine import TimelineEngine

from personal_intelligence.core.world.models import (
    Commitment,
    CommitmentStatus,
    CurrentState,
    FactProvenance,
    ImportantActivity,
    IssueSeverity,
    IssueStatus,
    OpenIssue,
    PersonalWorldModelSnapshot,
    UpcomingEvent,
)
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore

logger = logging.getLogger(__name__)


class PersonalWorldModel:
    """
    Unified Personal World Model.
    Maintains all active dimensions derived strictly from verified observations.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        local_store: Optional[LocalStateStore] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.local_store = local_store or LocalStateStore(db_manager=self.db_manager)

        self.event_store = self.local_store.event_store
        self.entity_store = self.local_store.entity_store
        self.goal_store = self.local_store.goal_store
        self.situation_store = self.local_store.situation_store
        self.pattern_store = self.local_store.pattern_store
        self.episode_store = self.local_store.episode_store

        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.goal_engine = GoalEngine(
            goal_store=self.goal_store,
            timeline_engine=self.timeline_engine,
        )
        self.state_engine = StateEngine(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
        )
        self.learning_engine = LearningEngine(
            pattern_store=self.pattern_store,
            db_manager=self.db_manager,
        )


    # -------------------------------------------------------------------------
    # Structured Mutation Operations (No Silent LLM Writes)
    # -------------------------------------------------------------------------

    def record_observation(
        self,
        source: str,
        source_id: str,
        timestamp: Union[datetime, str],
        observation_type: str,
        summary: str,
        evidence: Optional[Union[Dict[str, Any], List[Any], str]] = None,
        provenance: Optional[Dict[str, Any]] = None,
        subject_id: Optional[str] = "user",
        confidence: float = 1.0,
    ) -> Event:
        """
        Ingests a normalized observation with provenance into event_log and automatically
        derives relevant structured state updates (commitments, upcoming events, activity).
        """
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
            event_store=self.event_store,
        )

        # Automatically derive structured entities when observation represents a commitment or issue
        self._derive_state_from_observation(event)
        return event

    def _derive_state_from_observation(self, event: Event) -> None:
        """Derives structured commitments, issues, or activities from normalized observation."""
        evidence = event.payload.get("evidence", {}) if isinstance(event.payload, dict) else {}
        summary = event.payload.get("summary", "") if isinstance(event.payload, dict) else ""
        norm_type = event.event_type.lower()

        provenance = FactProvenance(
            source_observation_id=event.id,
            origin_source=event.source,
            source_id=event.source_id,
            tool=event.provenance.get("tool") if event.provenance else None,
            retrieval_query=event.provenance.get("query") if event.provenance else None,
            derivation_rule=f"observation_type:{norm_type}",
            recorded_at=event.event_time,
        )

        # 1. Action Items and Deadlines -> Commitment
        if norm_type in {"action_item_detected", "deadline_detected", "task_commitment_detected"}:
            due_at = None
            if isinstance(evidence, dict):
                due_val = evidence.get("detected_deadline") or evidence.get("due_at") or evidence.get("deadline")
                if due_val:
                    try:
                        due_at = ensure_timezone_aware(due_val, "due_at")
                    except Exception:
                        pass

            desc = summary
            if isinstance(evidence, dict) and evidence.get("action_item"):
                desc = str(evidence["action_item"])
            elif isinstance(evidence, dict) and evidence.get("commitment"):
                desc = str(evidence["commitment"])

            self.record_commitment(
                description=desc,
                due_at=due_at,
                provenance=provenance,
                metadata={"auto_derived": True, "observation_type": norm_type},
            )

        # 2. Blockers or Discrepancies -> OpenIssue
        elif norm_type in {"blocker_detected", "conflict_detected", "unusual_state"}:
            title = summary or f"Issue derived from {event.source}"
            desc = json.dumps(evidence, ensure_ascii=False) if isinstance(evidence, dict) else str(evidence)
            self.record_open_issue(
                title=title,
                description=desc,
                severity=IssueSeverity.HIGH.value if "blocker" in norm_type else IssueSeverity.MEDIUM.value,
                source_observation_ids=[event.id],
                provenance=provenance,
                metadata={"auto_derived": True, "observation_type": norm_type},
            )

    def record_commitment(
        self,
        description: str,
        due_at: Optional[Union[datetime, str]] = None,
        status: str = CommitmentStatus.PENDING.value,
        provenance: Optional[Union[FactProvenance, Dict[str, Any]]] = None,
        commitment_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Commitment:
        """
        Creates and stores a validated personal commitment in entity_state.
        """
        if not description or not isinstance(description, str) or not description.strip():
            raise EventValidationError("Commitment description must be a non-empty string.")

        due_dt = ensure_timezone_aware(due_at, "due_at") if due_at else None
        prov_obj = provenance if isinstance(provenance, FactProvenance) else (
            FactProvenance.from_dict(provenance) if provenance else FactProvenance()
        )

        cid = commitment_id or f"commit_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        commitment = Commitment(
            id=cid,
            description=description.strip(),
            status=status,
            due_at=due_dt,
            created_at=now,
            updated_at=now,
            provenance=prov_obj,
            metadata=metadata or {},
        )

        entity = EntityState(
            entity_id=commitment.id,
            entity_type="commitment",
            state=commitment.to_dict(),
            last_updated_at=now,
            source_event_ids=[prov_obj.source_observation_id] if prov_obj.source_observation_id else [],
            metadata=metadata or {},
        )
        self.entity_store.upsert(entity)
        return commitment

    def resolve_commitment(
        self,
        commitment_id: str,
        status: str = CommitmentStatus.COMPLETED.value,
        resolution_notes: Optional[str] = None,
    ) -> Optional[Commitment]:
        """Updates status of a commitment in entity_state."""
        entity = self.entity_store.get(commitment_id)
        if not entity or entity.entity_type != "commitment":
            return None

        now = datetime.now(timezone.utc)
        commit_data = entity.state
        commit_data["status"] = status
        commit_data["updated_at"] = format_iso8601(now)
        if resolution_notes:
            commit_data.setdefault("metadata", {})["resolution_notes"] = resolution_notes

        entity.state = commit_data
        entity.last_updated_at = now
        self.entity_store.upsert(entity)
        return Commitment.from_dict(commit_data)

    def record_open_issue(
        self,
        title: str,
        description: str,
        severity: str = IssueSeverity.MEDIUM.value,
        status: str = IssueStatus.OPEN.value,
        situation_id: Optional[str] = None,
        source_observation_ids: Optional[List[str]] = None,
        provenance: Optional[Union[FactProvenance, Dict[str, Any]]] = None,
        issue_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OpenIssue:
        """
        Creates and stores a validated open issue in entity_state.
        """
        if not title or not isinstance(title, str) or not title.strip():
            raise EventValidationError("Issue title must be a non-empty string.")

        prov_obj = provenance if isinstance(provenance, FactProvenance) else (
            FactProvenance.from_dict(provenance) if provenance else FactProvenance()
        )

        iid = issue_id or f"issue_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        issue = OpenIssue(
            id=iid,
            title=title.strip(),
            description=description,
            severity=severity,
            status=status,
            situation_id=situation_id,
            source_observation_ids=source_observation_ids or [],
            created_at=now,
            updated_at=now,
            provenance=prov_obj,
            metadata=metadata or {},
        )

        entity = EntityState(
            entity_id=issue.id,
            entity_type="open_issue",
            state=issue.to_dict(),
            last_updated_at=now,
            source_event_ids=source_observation_ids or [],
            metadata=metadata or {},
        )
        self.entity_store.upsert(entity)
        return issue

    def resolve_issue(
        self,
        issue_id: str,
        status: str = IssueStatus.RESOLVED.value,
        resolution_notes: Optional[str] = None,
    ) -> Optional[OpenIssue]:
        """Updates status of an open issue in entity_state."""
        entity = self.entity_store.get(issue_id)
        if not entity or entity.entity_type != "open_issue":
            return None

        now = datetime.now(timezone.utc)
        issue_data = entity.state
        issue_data["status"] = status
        issue_data["updated_at"] = format_iso8601(now)
        if resolution_notes:
            issue_data.setdefault("metadata", {})["resolution_notes"] = resolution_notes

        entity.state = issue_data
        entity.last_updated_at = now
        self.entity_store.upsert(entity)
        return OpenIssue.from_dict(issue_data)

    def create_goal(
        self,
        name: str,
        description: str = "",
        priority: str = GoalPriority.MEDIUM.value,
        status: str = GoalStatus.ACTIVE.value,
        goal_id: Optional[str] = None,
    ) -> Goal:
        """Stores a contextual goal via GoalStore."""
        return self.goal_store.create_goal(
            name=name,
            description=description,
            priority=priority,
            status=status,
            goal_id=goal_id,
        )

    def create_situation(
        self,
        type: str,
        priority: str = SituationPriority.MEDIUM.value,
        novelty: float = 0.0,
        context: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[Any]] = None,
        related_goals: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
        situation_id: Optional[str] = None,
    ) -> Situation:
        """Stores an assessed situation via SituationStore."""
        return self.situation_store.create(
            type=type,
            priority=priority,
            novelty=novelty,
            context=context,
            evidence=evidence,
            related_goals=related_goals,
            expires_at=expires_at,
            situation_id=situation_id,
        )

    def record_reasoning_episode(self, episode: ReasoningEpisode) -> ReasoningEpisode:
        """Records a completed Hermes reasoning episode via EpisodeStore."""
        return self.episode_store.create_episode(episode)

    def process_user_feedback(
        self,
        situation_id: str,
        action: str,  # "acknowledge", "snooze", "dismiss", "not_relevant"
        snooze_days: int = 2,
        feedback_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Applies interactive user feedback to a situation:
        1. Updates Situation status in SituationStore (e.g. RESOLVED, SUPPRESSED with snooze timestamp).
        2. Records the user's decision into EpisodeStore (user_response_json).
        3. Records user feedback event into EventStore.
        4. Notifies LearningEngine to learn user preferences (e.g. suppressing low-priority items or specific categories).
        5. Updates the Personal World Model's active state and knowledge base.
        """
        now = datetime.now(timezone.utc)
        action_clean = str(action).strip().lower()

        situation = self.situation_store.get(situation_id)
        if not situation:
            # Fallback search if id formatting differs
            all_sits = self.situation_store.list_all(limit=100)
            for s in all_sits:
                if s.id == situation_id or situation_id in s.id:
                    situation = s
                    break

        if not situation:
            return {"status": "error", "error": f"Situation '{situation_id}' not found."}

        # 1. Update Situation Status & Next Evaluation
        if action_clean in ("acknowledge", "acknowledged", "accept", "accepted", "completed"):
            situation.status = SituationStatus.RESOLVED.value
            situation.next_evaluation_at = None
            rec_result = RecommendationResult.ACCEPTED.value
            note = feedback_notes or "Situation explicitly acknowledged and resolved by user."
            display_action = "acknowledged"
        elif action_clean in ("snooze", "snoozed", "defer", "deferred"):
            snooze_until = now + timedelta(days=snooze_days)
            situation.status = SituationStatus.SUPPRESSED.value
            situation.next_evaluation_at = snooze_until
            rec_result = RecommendationResult.DEFERRED.value
            note = feedback_notes or f"Situation snoozed for {snooze_days} day(s) until {format_iso8601(snooze_until)}."
            display_action = f"snoozed_{snooze_days}d"
        elif action_clean in ("dismiss", "dismissed", "not_relevant", "not relevant", "ignore", "ignored"):
            situation.status = SituationStatus.SUPPRESSED.value
            situation.next_evaluation_at = None
            rec_result = RecommendationResult.DISMISSED.value
            note = feedback_notes or "Situation dismissed as not relevant by user."
            display_action = "dismissed_not_relevant"
        else:
            situation.status = SituationStatus.RESOLVED.value
            rec_result = RecommendationResult.ACCEPTED.value
            note = feedback_notes or f"User action '{action}' recorded."
            display_action = action_clean

        situation.updated_at = now
        self.situation_store.update(situation)

        # 2. Record into EpisodeStore (user_response)
        episodes = self.episode_store.list_by_situation(situation.id, limit=1)
        if episodes:
            target_ep = episodes[0]
            self.episode_store.record_user_response(
                episode_id=target_ep.id,
                response=rec_result,
                feedback_notes=note,
                metadata={
                    "action_taken": display_action,
                    "situation_type": situation.type,
                    "situation_id": situation.id,
                    "snooze_days": snooze_days if "snooze" in display_action else 0,
                    "recorded_at": format_iso8601(now),
                },
            )
            ep_id = target_ep.id
        else:
            # Create a tracking episode with the user response
            new_ep = self.episode_store.create_episode(
                situation_id=situation.id,
                observations=situation.evidence,
                recommendations=[situation.context.get("summary", situation.type)],
                user_response={
                    "response": rec_result,
                    "action_taken": display_action,
                    "feedback_notes": note,
                    "metadata": {
                        "situation_type": situation.type,
                        "situation_id": situation.id,
                    },
                },
                status="response_recorded",
            )
            ep_id = new_ep.id

        # 3. Ingest User Feedback Event to EventStore
        feedback_event = Event(
            source="user_interface",
            event_type="user_feedback_recorded",
            event_time=now,
            payload={
                "situation_id": situation.id,
                "situation_type": situation.type,
                "action": display_action,
                "recommendation_result": rec_result,
                "notes": note,
                "episode_id": ep_id,
            },
            provenance={
                "source": "ui_feedback_loop",
                "recorded_at": format_iso8601(now),
            },
        )
        self.event_store.append(feedback_event)

        # 4. PatternLearningEngine adapts user preferences
        learned_patterns = []
        try:
            # If user dismissed / suppressed item, learn preference to suppress similar items
            if rec_result == RecommendationResult.DISMISSED.value:
                pat_desc = f"User frequently suppresses or dismisses situations of type '{situation.type.replace('_', ' ')}'."
                learned_pat = self.learning_engine._upsert_pattern(
                    description=pat_desc,
                    pattern_type=PatternType.INTERACTION_PATTERN,
                    supporting_episodes=[ep_id],
                    first_seen=now,
                    last_seen=now,
                    metadata={
                        "dimension": "feedback_suppression",
                        "suppressed_type": situation.type,
                        "dismiss_count": 1,
                    },
                )
                learned_patterns.append(learned_pat.to_dict())
            elif rec_result == RecommendationResult.ACCEPTED.value:
                pat_desc = f"User actively prioritizes and acknowledges situations of type '{situation.type.replace('_', ' ')}'."
                learned_pat = self.learning_engine._upsert_pattern(
                    description=pat_desc,
                    pattern_type=PatternType.INTERACTION_PATTERN,
                    supporting_episodes=[ep_id],
                    first_seen=now,
                    last_seen=now,
                    metadata={
                        "dimension": "feedback_acceptance",
                        "accepted_type": situation.type,
                        "accept_count": 1,
                    },
                )
                learned_patterns.append(learned_pat.to_dict())
        except Exception as ex_learn:
            logger.debug("Learning engine feedback adaptation note: %s", ex_learn)

        return {
            "status": "success",
            "action": display_action,
            "situation_id": situation.id,
            "situation_status": situation.status,
            "episode_id": ep_id,
            "user_response": rec_result,
            "learned_patterns": learned_patterns,
            "message": f"Feedback applied: Situation marked as {situation.status.upper()}.",
            "timestamp": format_iso8601(now),
        }

    def get_suppressed_situation_types(self) -> List[str]:
        """Returns list of situation types the user has learned preferences to suppress."""
        suppressed = []
        for p in self.pattern_store.list_patterns():
            if p.pattern_type == PatternType.INTERACTION_PATTERN.value and "suppresses" in p.description:
                st = p.metadata.get("suppressed_type")
                if st and st not in suppressed:
                    suppressed.append(st)
        return suppressed

    # -------------------------------------------------------------------------
    # World Model State Queries
    # -------------------------------------------------------------------------

    def get_current_state(self, reference_time: Optional[datetime] = None) -> CurrentState:
        """
        Computes the complete, structured CURRENT STATE derived from observations.
        Includes:
        - current_commitments
        - upcoming_events
        - open_issues
        - recent_important_activity
        - known_goals
        - active_situations
        - computed_features
        """
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )

        # 1. Commitments (pending or in progress)
        commitment_entities = self.entity_store.list_by_type("commitment")
        commitments: List[Commitment] = []
        for ent in commitment_entities:
            c = Commitment.from_dict(ent.state)
            if c.status in {CommitmentStatus.PENDING.value, CommitmentStatus.IN_PROGRESS.value}:
                commitments.append(c)

        # 2. Open Issues (open or investigating)
        issue_entities = self.entity_store.list_by_type("open_issue")
        open_issues: List[OpenIssue] = []
        for ent in issue_entities:
            iss = OpenIssue.from_dict(ent.state)
            if iss.status in {IssueStatus.OPEN.value, IssueStatus.INVESTIGATING.value}:
                open_issues.append(iss)

        # 3. Upcoming Events (from recent calendar observations or future timestamps)
        upcoming_events: List[UpcomingEvent] = []
        recent_events = self.timeline_engine.get_last_n_hours(48, reference_time=ref_dt)
        for ev in recent_events.events:
            if ev.source == "calendar" or "calendar" in ev.event_type:
                payload = ev.payload if isinstance(ev.payload, dict) else {}
                evidence = payload.get("evidence", {}) if isinstance(payload.get("evidence"), dict) else payload
                title = evidence.get("event_title") or evidence.get("title") or payload.get("summary") or "Calendar Event"
                start_str = evidence.get("start_time") or format_iso8601(ev.event_time)
                try:
                    start_dt = ensure_timezone_aware(start_str, "start_time")
                except Exception:
                    start_dt = ev.event_time

                prov = FactProvenance(
                    source_observation_id=ev.id,
                    origin_source="calendar",
                    source_id=ev.source_id,
                    tool=ev.provenance.get("tool") if ev.provenance else "google_workspace_calendar",
                    retrieval_query=ev.provenance.get("query") if ev.provenance else None,
                    recorded_at=ev.event_time,
                )

                upcoming_events.append(
                    UpcomingEvent(
                        event_id=ev.id,
                        title=title,
                        start_time=start_dt,
                        origin_source="calendar",
                        source_observation_id=ev.id,
                        provenance=prov,
                        metadata=evidence,
                    )
                )

        # 4. Recent Important Activity (salient events from last 24h)
        important_activity: List[ImportantActivity] = []
        for ev in recent_events.events[-10:]:
            payload = ev.payload if isinstance(ev.payload, dict) else {}
            summary = payload.get("summary") or f"{ev.event_type} from {ev.source}"
            evidence = payload.get("evidence", {}) if isinstance(payload.get("evidence"), dict) else {}

            prov = FactProvenance(
                source_observation_id=ev.id,
                origin_source=ev.source,
                source_id=ev.source_id,
                tool=ev.provenance.get("tool") if ev.provenance else None,
                retrieval_query=ev.provenance.get("query") if ev.provenance else None,
                recorded_at=ev.event_time,
            )

            important_activity.append(
                ImportantActivity(
                    observation_id=ev.id,
                    source=ev.source,
                    observation_type=ev.event_type,
                    summary=summary,
                    timestamp=ev.event_time,
                    provenance=prov,
                    evidence=evidence,
                )
            )

        # 5. Known Goals (active goals)
        goals = [g.to_dict() for g in self.goal_store.list_active_goals()]

        # 6. Active Situations (open or monitoring)
        situations = [s.to_dict() for s in self.situation_store.list_active(limit=20)]

        # 7. Computed State Features (StateEngine)
        state_rep = self.state_engine.compute_current_state(reference_time=ref_dt)
        computed_feats = {name: feat.value for name, feat in state_rep.features.items()}

        return CurrentState(
            current_commitments=commitments,
            upcoming_events=upcoming_events,
            open_issues=open_issues,
            recent_important_activity=important_activity,
            known_goals=goals,
            active_situations=situations,
            computed_features=computed_feats,
            timestamp=ref_dt,
        )

    def get_timeline(
        self,
        last_n_hours: int = 24,
        limit: int = 50,
        reference_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Returns chronological validated events from TimelineEngine."""
        tl = self.timeline_engine.get_last_n_hours(
            last_n_hours, reference_time=reference_time, limit=limit
        )
        return [
            {
                "id": e.id,
                "timestamp": format_iso8601(e.event_time),
                "event_type": e.event_type,
                "source": e.source,
                "source_id": e.source_id,
                "summary": e.payload.get("summary") if isinstance(e.payload, dict) else "",
                "evidence": e.payload.get("evidence") if isinstance(e.payload, dict) else e.payload,
                "provenance": e.provenance,
            }
            for e in tl.events
        ]

    def get_goals(self, status: str = "active") -> List[Dict[str, Any]]:
        """Returns goals from GoalStore."""
        if status == "active":
            return [g.to_dict() for g in self.goal_store.list_active_goals()]
        return [g.to_dict() for g in self.goal_store.list_all_goals(status=status)]

    def get_open_situations(self) -> List[Dict[str, Any]]:
        """Returns open and monitoring situations from SituationStore."""
        return [s.to_dict() for s in self.situation_store.list_active(limit=50)]

    def get_known_patterns(self) -> List[Dict[str, Any]]:
        """Returns patterns with active empirical support from PatternStore."""
        patterns = self.pattern_store.list_patterns()
        return [
            p.to_dict() for p in patterns
            if p.status in {PatternStatus.ACTIVE.value, PatternStatus.SUPPORTED.value, "ACTIVE", "SUPPORTED"}
        ]

    def get_emerging_hypotheses(self) -> List[Dict[str, Any]]:
        """Returns candidate patterns in hypothesis or observed stage from PatternStore."""
        patterns = self.pattern_store.list_patterns()
        return [
            p.to_dict() for p in patterns
            if p.status in {PatternStatus.HYPOTHESIS.value, PatternStatus.OBSERVED.value, "HYPOTHESIS", "OBSERVED"}
        ]

    def get_snapshot(self, reference_time: Optional[datetime] = None) -> PersonalWorldModelSnapshot:
        """
        Returns the unified Personal World Model Snapshot spanning all 6 required sections:
        CURRENT STATE, TIMELINE, GOALS, OPEN SITUATIONS, KNOWN PATTERNS, EMERGING HYPOTHESES.
        """
        now = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        current_state = self.get_current_state(reference_time=now)
        timeline_events = self.get_timeline(last_n_hours=24, reference_time=now)
        goals = self.get_goals(status="active")
        open_situations = self.get_open_situations()
        known_patterns = self.get_known_patterns()
        emerging_hypotheses = self.get_emerging_hypotheses()

        return PersonalWorldModelSnapshot(
            current_state=current_state,
            timeline_events=timeline_events,
            goals=goals,
            open_situations=open_situations,
            known_patterns=known_patterns,
            emerging_hypotheses=emerging_hypotheses,
            timestamp=now,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes current snapshot into a standard dictionary representation."""
        return self.get_snapshot().to_dict()
