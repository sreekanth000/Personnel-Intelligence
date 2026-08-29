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

from personal_intelligence.core.world.graph import EntityGraphStore, EntityNode, EntityEdge
from personal_intelligence.core.world.simulator import WorldModelSimulator, SimulationResult
from personal_intelligence.core.world.predictive import PredictiveProcessingEngine, ExpectedState
from personal_intelligence.core.world.person_model import PersonModelEngine, PersonEntity
from personal_intelligence.core.patterns.compaction import HippocampalCompactor, CompactionSummary
from personal_intelligence.core.world.mcts_simulator import MCTSWorldSimulator, MCTSTreeResult

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
    ProbabilisticFact,
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

        self.graph_store = EntityGraphStore(db_manager=self.db_manager)
        self.relationship_store = self.graph_store  # TemporalEntityRelationshipModel
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

        from personal_intelligence.core.significance import PersonalSignificanceEngine
        self.significance_engine = PersonalSignificanceEngine()

        # Deferred/Experimental Research Engines (Retained for backward compatibility)
        self.predictive_engine = PredictiveProcessingEngine(db_manager=self.db_manager)
        self.person_model_engine = PersonModelEngine(db_manager=self.db_manager)
        self.hippocampal_compactor = HippocampalCompactor(db_manager=self.db_manager)
        self.mcts_simulator = MCTSWorldSimulator()
        self.simulator = WorldModelSimulator(goal_engine=self.goal_engine)


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
        self.graph_store.record_commitment(
            commitment,
            project_id=(metadata or {}).get("project_id"),
            meeting_id=(metadata or {}).get("meeting_id"),
        )
        return commitment

    def resolve_commitment(
        self,
        commitment_id: str,
        status: str = CommitmentStatus.COMPLETED.value,
        resolution_notes: Optional[str] = None,
    ) -> Optional[Commitment]:
        """Updates status of a commitment in entity_state and graph_store."""
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
        self.graph_store.update_commitment_status(commitment_id, status)
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

        # 1. Commitments (deduplicate by description + due_at)
        commitment_entities = self.entity_store.list_by_type("commitment")
        commitments: List[Commitment] = []
        seen_commitments = set()
        for ent in commitment_entities:
            c = Commitment.from_dict(ent.state)
            if c.status in {CommitmentStatus.PENDING.value, CommitmentStatus.IN_PROGRESS.value}:
                key = (c.description.strip().lower(), str(c.due_at))
                if key not in seen_commitments:
                    seen_commitments.add(key)
                    commitments.append(c)

        # 2. Open Issues (open or investigating)
        issue_entities = self.entity_store.list_by_type("open_issue")
        open_issues: List[OpenIssue] = []
        for ent in issue_entities:
            iss = OpenIssue.from_dict(ent.state)
            if iss.status in {IssueStatus.OPEN.value, IssueStatus.INVESTIGATING.value}:
                open_issues.append(iss)

        # 3. Upcoming Events (query next 7 days from TimelineEngine)
        upcoming_events: List[UpcomingEvent] = []
        window_events = self.timeline_engine.get_time_range(
            start_time=ref_dt - timedelta(hours=24),
            end_time=ref_dt + timedelta(days=7),
            limit=100,
        )
        seen_event_ids = set()
        for ev in window_events.events:
            if ev.source == "calendar" or "calendar" in ev.event_type:
                if ev.id in seen_event_ids:
                    continue
                seen_event_ids.add(ev.id)
                payload = ev.payload if isinstance(ev.payload, dict) else {}
                evidence = payload.get("evidence", {}) if isinstance(payload.get("evidence"), dict) else payload
                title = (
                    evidence.get("event_title")
                    or evidence.get("title")
                    or payload.get("event_title")
                    or payload.get("title")
                    or payload.get("summary")
                    or "Calendar Event"
                )
                start_str = evidence.get("start_time") or payload.get("start_time") or format_iso8601(ev.event_time)
                try:
                    start_dt = ensure_timezone_aware(start_str, "start_time")
                except Exception:
                    start_dt = ev.event_time

                prov = FactProvenance(
                    source_observation_id=ev.id,
                    origin_source="calendar",
                    source_id=ev.source_id,
                    tool=ev.provenance.get("tool") if isinstance(ev.provenance, dict) else "google_calendar",
                    retrieval_query=ev.provenance.get("query") if isinstance(ev.provenance, dict) else None,
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
                        metadata=payload,
                    )
                )

        # 4. Recent Important Activity (salient events from last 48h)
        important_activity: List[ImportantActivity] = []
        recent_events = self.timeline_engine.get_last_n_hours(48, reference_time=ref_dt)
        for ev in recent_events.events[-15:]:
            payload = ev.payload if isinstance(ev.payload, dict) else {}
            summary = payload.get("summary") or payload.get("finding") or f"{ev.event_type} from {ev.source}"
            evidence = payload.get("evidence", {}) if isinstance(payload.get("evidence"), dict) else {}

            prov = FactProvenance(
                source_observation_id=ev.id,
                origin_source=ev.source,
                source_id=ev.source_id,
                tool=ev.provenance.get("tool") if isinstance(ev.provenance, dict) else None,
                retrieval_query=ev.provenance.get("query") if isinstance(ev.provenance, dict) else None,
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

    def get_ground_truth_facts(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Returns grounded, verifiable facts extracted directly from authentic observations in EventStore.
        Excludes mock/synthetic sample entries.
        """
        all_events = self.event_store.get_recent(limit=limit)
        facts: List[Dict[str, Any]] = []

        for ev in all_events:
            # Skip sample_generator or mock events
            if ev.source in ("sample_generator", "mock_host") or "synthetic" in ev.event_type:
                continue

            payload = ev.payload if isinstance(ev.payload, dict) else {}
            
            # Format clean, authentic fact summary
            source_label = ev.source.upper()
            if ev.source == "gmail":
                source_label = "Gmail"
                summary = payload.get("summary") or payload.get("finding") or "Email communication received."
            elif ev.source == "calendar":
                source_label = "Google Calendar"
                sum_text = payload.get("summary") or "Calendar Event"
                dur = payload.get("duration_minutes", 60)
                summary = f"{sum_text} ({dur} mins)"
            elif ev.source == "voice_notes":
                source_label = "Voice Notes"
                actions = payload.get("action_items", [])
                act_str = f" • Action Items: {', '.join(actions)}" if actions else ""
                summary = f"{payload.get('title', 'Voice Memo')}: {payload.get('summary', '')}{act_str}"
            elif ev.source == "user_interface":
                source_label = "User Feedback"
                act = str(payload.get("action", "feedback")).upper()
                notes = payload.get("notes") or ""
                summary = f"User feedback recorded [{act}] on situation {payload.get('situation_id', '')} {notes}".strip()
            else:
                summary = payload.get("summary") or f"{ev.event_type} observation"

            provenance_info = "verified_local_event"
            if isinstance(ev.provenance, dict):
                chain = ev.provenance.get("provenance_chain") or []
                if chain:
                    provenance_info = str(chain[0])
                elif ev.provenance.get("tool"):
                    provenance_info = f"tool:{ev.provenance.get('tool')}"
            elif ev.source_id:
                provenance_info = f"{ev.source}:{ev.source_id}"

            facts.append({
                "fact_id": ev.id,
                "domain_source": source_label,
                "source": ev.source,
                "event_type": ev.event_type,
                "summary": summary,
                "observed_at": format_iso8601(ev.event_time),
                "epistemic_level": "FACT",
                "confidence": ev.confidence if ev.confidence is not None else 1.0,
                "provenance": provenance_info,
                "payload": payload,
            })

        return facts

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
        Returns the unified Personal World Model Snapshot spanning all required sections:
        CURRENT STATE, GROUND TRUTH FACTS, TIMELINE, GOALS, OPEN SITUATIONS, KNOWN PATTERNS, EMERGING HYPOTHESES.
        """
        now = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        current_state = self.get_current_state(reference_time=now)
        ground_truth_facts = self.get_ground_truth_facts(limit=100)
        timeline_events = self.get_timeline(last_n_hours=24, reference_time=now)
        goals = self.get_goals(status="active")
        open_situations = self.get_open_situations()
        known_patterns = self.get_known_patterns()
        emerging_hypotheses = self.get_emerging_hypotheses()

        return PersonalWorldModelSnapshot(
            current_state=current_state,
            ground_truth_facts=ground_truth_facts,
            timeline_events=timeline_events,
            goals=goals,
            open_situations=open_situations,
            known_patterns=known_patterns,
            emerging_hypotheses=emerging_hypotheses,
            timestamp=now,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes current unified world model snapshot to JSON-serializable dict."""
        return self.get_snapshot().to_dict()

    # -------------------------------------------------------------------------
    # Next-Gen World Model Enhancements (Graph, Probabilistic, Simulation, Lineage)
    # -------------------------------------------------------------------------

    def record_probabilistic_fact(
        self,
        subject: str,
        predicate: str,
        object: str,
        initial_confidence: float = 0.5,
        evidence_id: Optional[str] = None,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> ProbabilisticFact:
        """
        Ingests or reinforces a probabilistic fact using Bayesian update rules.
        """
        conn = self.db_manager.get_connection()
        try:
            with conn:
                row = conn.execute(
                    "SELECT * FROM probabilistic_facts WHERE subject=? AND predicate=? AND object=?",
                    (subject, predicate, object),
                ).fetchone()

                if row:
                    fact = ProbabilisticFact.from_dict(dict(row))
                    fact.reinforce_evidence(initial_confidence)
                    if evidence_id and evidence_id not in fact.evidence_ids:
                        fact.evidence_ids.append(evidence_id)
                else:
                    fact = ProbabilisticFact(
                        subject=subject,
                        predicate=predicate,
                        object=object,
                        belief_score=initial_confidence,
                        salience_score=1.0,
                        evidence_ids=[evidence_id] if evidence_id else [],
                        provenance=provenance or {},
                    )

                conn.execute(
                    """
                    INSERT INTO probabilistic_facts (id, subject, predicate, object, belief_score, salience_score, status, provenance_json, evidence_ids_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        belief_score = excluded.belief_score,
                        salience_score = excluded.salience_score,
                        status = excluded.status,
                        evidence_ids_json = excluded.evidence_ids_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        fact.id,
                        fact.subject,
                        fact.predicate,
                        fact.object,
                        fact.belief_score,
                        fact.salience_score,
                        fact.status,
                        json.dumps(fact.provenance),
                        json.dumps(fact.evidence_ids),
                        format_iso8601(fact.created_at),
                        format_iso8601(fact.updated_at),
                    ),
                )
            return fact
        finally:
            conn.close()

    def retract_observation(self, observation_id: str) -> List[str]:
        """
        Performs cascading truth retraction across the provenance graph when an observation is invalidated.
        Returns list of retracted entity/commitment IDs.
        """
        retracted_ids: List[str] = [observation_id]
        conn = self.db_manager.get_connection()
        try:
            with conn:
                # Mark observation/event as retracted or confidence=0
                conn.execute(
                    "UPDATE event_log SET confidence = 0.0 WHERE id = ? OR source_id = ?",
                    (observation_id, observation_id),
                )
                # Retract probabilistic facts linked to this evidence ID
                rows = conn.execute("SELECT * FROM probabilistic_facts WHERE status='active'").fetchall()
                for r in rows:
                    d = dict(r)
                    ev_ids = json.loads(d.get("evidence_ids_json", "[]"))
                    if observation_id in ev_ids:
                        fact_id = d["id"]
                        conn.execute(
                            "UPDATE probabilistic_facts SET status='retracted', belief_score=0.0 WHERE id=?",
                            (fact_id,),
                        )
                        retracted_ids.append(fact_id)
            return retracted_ids
        finally:
            conn.close()

    def simulate_counterfactual(
        self,
        hypothetical_events: List[Event],
        scenario_description: str = "Counterfactual Scenario",
    ) -> SimulationResult:
        """
        Executes a counterfactual 'what-if' simulation on a snapshot of the current world model.
        """
        base_snapshot = self.get_snapshot()
        return self.simulator.simulate_hypothetical_scenario(
            base_snapshot=base_snapshot,
            hypothetical_events=hypothetical_events,
            scenario_description=scenario_description,
        )

    def apply_memory_salience_decay(self, elapsed_days: float = 1.0) -> int:
        """
        Applies Ebbinghaus memory decay to all stored probabilistic facts.
        Returns count of decayed facts.
        """
        conn = self.db_manager.get_connection()
        try:
            decayed_count = 0
            with conn:
                rows = conn.execute("SELECT * FROM probabilistic_facts WHERE status='active'").fetchall()
                for r in rows:
                    fact = ProbabilisticFact.from_dict(dict(r))
                    fact.apply_decay(elapsed_days=elapsed_days)
                    conn.execute(
                        "UPDATE probabilistic_facts SET salience_score=?, updated_at=? WHERE id=?",
                        (fact.salience_score, format_iso8601(datetime.now(timezone.utc)), fact.id),
                    )
                    decayed_count += 1
            return decayed_count
        finally:
            conn.close()

    def evaluate_prediction_error(self, actual_event: Event) -> float:
        """Computes top-down prediction error delta for incoming observation."""
        return self.predictive_engine.calculate_prediction_error(actual_event)

    def evaluate_person_urgency(self, sender_name: str, message_summary: str = "") -> float:
        """Computes Theory of Mind interpersonal urgency multiplier for sender."""
        return self.person_model_engine.evaluate_interpersonal_urgency(sender_name, message_summary)

    def run_mcts_tree_search(self, situation_id: str, scenario_title: str) -> MCTSTreeResult:
        """Executes multi-step Monte Carlo Tree Search and Pareto utility evaluation."""
        base_snapshot = self.get_snapshot()
        return self.mcts_simulator.evaluate_decision_tree(
            situation_id=situation_id,
            scenario_title=scenario_title,
            base_snapshot=base_snapshot,
        )

    def compact_memory_schema(self, hours_back: int = 24) -> CompactionSummary:
        """Runs hippocampal memory compaction over recent event logs."""
        return self.hippocampal_compactor.compact_memory(hours_back=hours_back)
