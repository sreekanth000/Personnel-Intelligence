"""
Personal World Model implementation for the Personal Intelligence system.

TARGET ARCHITECTURAL MODEL:

PERSONAL WORLD MODEL
    ├── Entities
    ├── State
    ├── Timeline
    ├── Goals
    ├── Commitments
    ├── Situations
    ├── Observations
    └── Context Graph

CONTEXT GRAPH
    ├── relationships
    ├── temporal links
    ├── evidence links
    ├── relevance links
    └── contextual traversal

ARCHITECTURAL DISTINCTION:
Personal World Model answers:
    "What do we currently know about this person's world?"
Context Graph answers:
    "How are the relevant things in that world connected?"

Context Graph is the relational connective substrate backed by SQLite.
PersonalWorldModel is the higher-level semantic representation and semantic owner.
Context Graph is NOT a second memory store, NOT a graph database,
and NOT a separate semantic knowledge engine.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
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

from personal_intelligence.core.world.graph import (
    BoundedContextGraph,
    CanonicalEntityType,
    CanonicalRelationship,
    ContextGraph,
    EntityEdge,
    EntityGraphStore,
    EntityNode,
)
from personal_intelligence.core.world.simulator import WorldModelSimulator, SimulationResult
from personal_intelligence.core.world.expectations import ExpectationProvider
from personal_intelligence.core.world.person_model import PersonModelEngine, PersonEntity
from personal_intelligence.core.memory.maintenance import MemoryMaintenanceJob, MemoryMaintenanceSummary


from personal_intelligence.core.world.models import (
    Commitment,
    CommitmentStatus,
    CurrentState,
    EpistemicIntegrityError,
    EpistemicRecord,
    EpistemicType,
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
        expectation_provider: Optional[ExpectationProvider] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.local_store = local_store or LocalStateStore(db_manager=self.db_manager)

        self.event_store = self.local_store.event_store
        self.entity_store = self.local_store.entity_store
        self.goal_store = self.local_store.goal_store
        self.situation_store = self.local_store.situation_store
        self.pattern_store = self.local_store.pattern_store
        self.episode_store = self.local_store.episode_store

        self.context_graph = ContextGraph(db_manager=self.db_manager)
        self.graph_store = self.context_graph
        self.relationship_store = self.context_graph  # TemporalEntityRelationshipModel
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

        # Optional Expectation Provider Extension (Plug-in hook)
        self.expectation_provider = expectation_provider

        # Deferred/Experimental Research Engines (Retained for research prototypes)
        self.person_model_engine = PersonModelEngine(db_manager=self.db_manager)
        self.memory_maintenance_job = MemoryMaintenanceJob(
            db_manager=self.db_manager,
            local_store=self.local_store,
            pattern_store=self.pattern_store,
            situation_store=self.situation_store,
        )
        self.simulator = WorldModelSimulator(goal_engine=self.goal_engine)


    # -------------------------------------------------------------------------
    # Structured Mutation Operations (No Silent LLM Writes)
    # -------------------------------------------------------------------------

    def record_observation(
        self,
        source: Union[str, Event],
        source_id: Optional[str] = None,
        timestamp: Optional[Union[datetime, str]] = None,
        observation_type: Optional[str] = None,
        summary: Optional[str] = None,
        evidence: Optional[Union[Dict[str, Any], List[Any], str]] = None,
        provenance: Optional[Dict[str, Any]] = None,
        subject_id: Optional[str] = "user",
        confidence: float = 1.0,
        source_type: Optional[str] = None,
        observed_at: Optional[Union[datetime, str]] = None,
        entity_refs: Optional[List[str]] = None,
        schema_version: str = "1.0",
    ) -> Event:
        """
        Ingests a normalized observation with provenance into event_log and automatically
        derives relevant structured state updates (commitments, upcoming events, activity).
        Accepts either an Event instance or individual observation attributes.
        """
        if isinstance(source, Event):
            event = source
            self.event_store.append(event)
            self._derive_state_from_observation(event)
            return event

        event = core_record_obs(
            source=source,
            source_id=source_id or f"obs-{uuid.uuid4().hex[:8]}",
            timestamp=timestamp or datetime.now(timezone.utc),
            observation_type=observation_type or "general",
            summary=summary or "Observation",
            evidence=evidence,
            provenance=provenance,
            subject_id=subject_id,
            confidence=confidence,
            source_type=source_type,
            observed_at=observed_at,
            entity_refs=entity_refs,
            schema_version=schema_version,
            event_store=self.event_store,
        )

        # Automatically derive structured entities and sync into context graph
        self._derive_state_from_observation(event)
        return event

    def _derive_state_from_observation(self, event: Event) -> None:
        """Derives structured commitments, issues, or activities from normalized observation."""
        # 0. Sync observation node and linked entities into Context Graph
        self.context_graph.sync_from_observation(event)
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
        name: Optional[str] = None,
        description: str = "",
        priority: str = GoalPriority.MEDIUM.value,
        status: str = GoalStatus.ACTIVE.value,
        goal_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Goal:
        """Stores a contextual goal via GoalStore and syncs into ContextGraph."""
        effective_name = name or title or "Untitled Goal"
        goal = self.goal_store.create_goal(
            name=effective_name,
            description=description,
            priority=priority,
            status=status,
            goal_id=goal_id,
        )
        self.context_graph.sync_from_goal(goal)
        return goal

    def create_situation(
        self,
        type: Optional[str] = None,
        priority: str = SituationPriority.MEDIUM.value,
        novelty: float = 0.0,
        context: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[Any]] = None,
        related_goals: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
        situation_id: Optional[str] = None,
        situation_type: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Situation:
        """Stores an assessed situation via SituationStore and syncs into ContextGraph."""
        effective_type = type or situation_type or "general"
        ctx = dict(context or {})
        if summary and "summary" not in ctx:
            ctx["summary"] = summary
        situation = self.situation_store.create(
            type=effective_type,
            priority=priority,
            novelty=novelty,
            context=ctx,
            evidence=evidence,
            related_goals=related_goals,
            expires_at=expires_at,
            situation_id=situation_id,
        )
        self.context_graph.sync_from_situation(situation)
        return situation

    def get_bounded_context(
        self,
        target_id: str,
        depth: int = 1,
        time_window: Optional[Tuple[datetime, datetime]] = None,
        relevance_constraints: Optional[Dict[str, Any]] = None,
        include_inferred: bool = True,
    ) -> BoundedContextGraph:
        """
        Retrieves a bounded subgraph around an entity, situation, goal, or observation.
        Does NOT dump the entire World Model or graph.
        """
        return self.context_graph.get_bounded_context(
            target_id=target_id,
            depth=depth,
            time_window=time_window,
            relevance_constraints=relevance_constraints,
            include_inferred=include_inferred,
        )

    def get_context(
        self,
        target_id: str,
        depth: int = 1,
        time_window: Optional[Tuple[datetime, datetime]] = None,
        relevance_constraints: Optional[Dict[str, Any]] = None,
        include_inferred: bool = True,
    ) -> BoundedContextGraph:
        """Alias for get_bounded_context."""
        return self.context_graph.get_context(
            target_id=target_id,
            depth=depth,
            time_window=time_window,
            relevance_constraints=relevance_constraints,
            include_inferred=include_inferred,
        )

    def get_related_entities(
        self,
        entity_id: str,
        relationship: Optional[Union[CanonicalRelationship, str]] = None,
        depth: int = 1,
        active_only: bool = True,
    ) -> List[EntityNode]:
        """Discovers related entities via the Context Graph."""
        return self.context_graph.get_related_entities(
            entity_id=entity_id,
            relationship=relationship,
            depth=depth,
            active_only=active_only,
        )

    def get_neighbors(
        self,
        node_id: str,
        depth: int = 1,
        include_ended: bool = False,
    ) -> List[Tuple[EntityNode, str, EntityNode]]:
        """Discovers direct graph neighbors via the Context Graph."""
        return self.context_graph.get_neighbors(
            node_id=node_id,
            depth=depth,
            include_ended=include_ended,
        )

    def get_related_goals(self, target_id: str, depth: int = 2) -> List[Dict[str, Any]]:
        """Discovers connected goals via the Context Graph."""
        return self.context_graph.get_related_goals(target_id=target_id, depth=depth)

    def get_related_situations(self, entity_id: str, depth: int = 2) -> List[Dict[str, Any]]:
        """Discovers connected situations via the Context Graph."""
        return self.context_graph.get_related_situations(entity_id=entity_id, depth=depth)

    def get_supporting_evidence(self, target_id: str) -> List[Dict[str, Any]]:
        """Discovers supporting observations and evidence for a situation or entity."""
        return self.context_graph.get_supporting_evidence(target_id=target_id)

    def get_temporal_context(
        self, entity_id: str, as_of: Optional[datetime] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Categorizes entity context into current, historical, stale, and future."""
        return self.context_graph.get_temporal_context(entity_id=entity_id, as_of=as_of)

    def find_relevant_context(
        self,
        situation_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Answers 'What is relevant to this situation?' via the Context Graph."""
        return self.context_graph.find_relevant_context(
            situation_id=situation_id,
            entity_id=entity_id,
            goal_id=goal_id,
            limit=limit,
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

    def get_situations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Returns situations from SituationStore.
        If status is None or 'active', returns all active situations.
        """
        if status is None or status == "active":
            return self.get_open_situations()
        return [s.to_dict() for s in self.situation_store.list_all(status=status)]

    def get_current_world(self, reference_time: Optional[datetime] = None) -> PersonalWorldModelSnapshot:
        """
        Answers: 'What do we currently know about this person's world?'
        Returns the authoritative semantic snapshot of the person's world.
        """
        return self.get_snapshot(reference_time=reference_time)

    def get_known_patterns(self) -> List[Dict[str, Any]]:
        """Returns patterns with active empirical support from PatternStore."""
        patterns = self.pattern_store.list_patterns()
        return [
            p.to_dict() for p in patterns
            if p.status in {PatternStatus.ACTIVE.value, PatternStatus.SUPPORTED.value, "ACTIVE", "SUPPORTED"}
        ]

    def get_commitments(self, status: Optional[str] = None) -> List[Commitment]:
        """Returns commitments stored in entity_store."""
        entities = self.entity_store.list(entity_type="commitment")
        commits = [Commitment.from_dict(e.state) for e in entities if isinstance(e.state, dict)]
        if status:
            stat_clean = status.strip().lower()
            commits = [c for c in commits if str(c.status).lower() == stat_clean]
        return commits

    def get_open_issues(self, status: Optional[str] = None) -> List[OpenIssue]:
        """Returns open issues stored in entity_store."""
        entities = self.entity_store.list(entity_type="open_issue")
        issues = [OpenIssue.from_dict(e.state) for e in entities if isinstance(e.state, dict)]
        if status:
            stat_clean = status.strip().lower()
            issues = [i for i in issues if str(i.status).lower() == stat_clean]
        return issues

    def get_upcoming_events(self, as_of: Optional[datetime] = None) -> List[UpcomingEvent]:
        """Returns upcoming events derived from timeline and commitments."""
        return []

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

    def snapshot(self, as_of: Optional[datetime] = None) -> PersonalWorldModelSnapshot:
        """Alias for get_snapshot."""
        return self.get_snapshot(reference_time=as_of)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes current unified world model snapshot to JSON-serializable dict."""
        return self.get_snapshot().to_dict()

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # Explicit Epistemic State Management (OBSERVED, DERIVED, INFERRED, PREDICTED, RECOMMENDED)
    # -------------------------------------------------------------------------

    def record_epistemic_record(self, record: EpistemicRecord) -> EpistemicRecord:
        """
        Durably persists an explicit epistemic state record in SQLite with full provenance.
        Ensures inferences explicitly retain their supporting observation lineage.
        """
        if record.epistemic_type in (EpistemicType.INFERRED.value, EpistemicType.PREDICTED.value) and not record.supporting_observation_ids:
            logger.warning(
                f"Epistemic record '{record.id}' of type '{record.epistemic_type}' registered without supporting observation IDs."
            )

        conn = self.db_manager.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO epistemic_records (
                        id, epistemic_type, statement, subject, predicate, object,
                        source, source_id, origin_event_id,
                        supporting_observation_ids_json, contradictory_observation_ids_json,
                        status, provenance_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        epistemic_type = excluded.epistemic_type,
                        statement = excluded.statement,
                        status = excluded.status,
                        supporting_observation_ids_json = excluded.supporting_observation_ids_json,
                        contradictory_observation_ids_json = excluded.contradictory_observation_ids_json,
                        provenance_json = excluded.provenance_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        record.id,
                        record.epistemic_type,
                        record.statement,
                        record.subject,
                        record.predicate,
                        record.object,
                        record.source,
                        record.source_id,
                        record.origin_event_id,
                        json.dumps(record.supporting_observation_ids),
                        json.dumps(record.contradictory_observation_ids),
                        record.status,
                        json.dumps(record.provenance),
                        format_iso8601(record.created_at),
                        format_iso8601(record.updated_at),
                    ),
                )
            return record
        finally:
            conn.close()

    def record_epistemic_fact(
        self,
        subject: str,
        predicate: str,
        object: str,
        epistemic_type: Union[str, EpistemicType] = "observed",
        statement: str = "",
        source: str = "unknown",
        source_id: Optional[str] = None,
        origin_event_id: Optional[str] = None,
        supporting_observation_ids: Optional[List[str]] = None,
        contradictory_observation_ids: Optional[List[str]] = None,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> EpistemicRecord:
        """
        Records or updates an explicit epistemic fact (triple) with verified ground-truth lineage.
        """
        type_str = epistemic_type.value if isinstance(epistemic_type, EpistemicType) else str(epistemic_type).lower()
        supp_ids = list(supporting_observation_ids or [])
        contra_ids = list(contradictory_observation_ids or [])

        # Strict Epistemic Safeguards (Observation vs Inference vs Prediction)
        if type_str == EpistemicType.OBSERVED.value:
            has_prov = bool(
                source_id
                or origin_event_id
                or provenance
                or supp_ids
                or contra_ids
                or (source and source != "unknown")
            )
            if not has_prov:
                raise EpistemicIntegrityError(
                    "Observations require verified ground-truth provenance coordinates (source_id, origin_event_id, or provenance metadata)."
                )
        elif type_str in (EpistemicType.INFERRED.value, EpistemicType.PREDICTED.value):
            if not supp_ids and not origin_event_id:
                raise EpistemicIntegrityError(
                    f"Epistemic '{type_str}' records must retain supporting observation IDs/evidence. Got empty supporting_observation_ids."
                )

        conn = self.db_manager.get_connection()
        try:
            with conn:
                row = conn.execute(
                    "SELECT * FROM epistemic_records WHERE subject=? AND predicate=? AND object=? AND epistemic_type=? AND status='active'",
                    (subject, predicate, object, type_str),
                ).fetchone()

                if row:
                    record = EpistemicRecord.from_dict(dict(row))
                    for obs_id in supp_ids:
                        if obs_id not in record.supporting_observation_ids:
                            record.supporting_observation_ids.append(obs_id)
                    for obs_id in contra_ids:
                        if obs_id not in record.contradictory_observation_ids:
                            record.contradictory_observation_ids.append(obs_id)
                    record.updated_at = datetime.now(timezone.utc)
                    if provenance:
                        record.provenance.update(provenance)
                else:
                    record = EpistemicRecord(
                        epistemic_type=type_str,
                        statement=statement or f"{subject} {predicate} {object}",
                        subject=subject,
                        predicate=predicate,
                        object=object,
                        source=source,
                        source_id=source_id,
                        origin_event_id=origin_event_id,
                        supporting_observation_ids=supp_ids,
                        contradictory_observation_ids=contra_ids,
                        provenance=provenance or {},
                    )

                conn.execute(
                    """
                    INSERT INTO epistemic_records (
                        id, epistemic_type, statement, subject, predicate, object,
                        source, source_id, origin_event_id,
                        supporting_observation_ids_json, contradictory_observation_ids_json,
                        status, provenance_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        epistemic_type = excluded.epistemic_type,
                        statement = excluded.statement,
                        status = excluded.status,
                        supporting_observation_ids_json = excluded.supporting_observation_ids_json,
                        contradictory_observation_ids_json = excluded.contradictory_observation_ids_json,
                        provenance_json = excluded.provenance_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        record.id,
                        record.epistemic_type,
                        record.statement,
                        record.subject,
                        record.predicate,
                        record.object,
                        record.source,
                        record.source_id,
                        record.origin_event_id,
                        json.dumps(record.supporting_observation_ids),
                        json.dumps(record.contradictory_observation_ids),
                        record.status,
                        json.dumps(record.provenance),
                        format_iso8601(record.created_at),
                        format_iso8601(record.updated_at),
                    ),
                )

            # Synchronize relational representation to Context Graph without creating a second store
            try:
                if subject and object and predicate:
                    self.context_graph.connect(
                        source_id=subject,
                        target_id=object,
                        relationship=predicate,
                        epistemic_type=type_str,
                        metadata={
                            "supporting_observation_ids": supp_ids,
                            "contradictory_observation_ids": contra_ids,
                            "statement": record.statement,
                        },
                        provenance=provenance,
                    )
            except Exception as e:
                logger.debug(f"ContextGraph synchronization skipped for epistemic fact: {e}")

            return record
        finally:
            conn.close()

    def get_epistemic_records(
        self,
        epistemic_type: Optional[str] = None,
        status: str = "active",
        subject: Optional[str] = None,
    ) -> List[EpistemicRecord]:
        """Queries epistemic records by type, status, and subject."""
        conn = self.db_manager.get_connection()
        try:
            query = "SELECT * FROM epistemic_records WHERE status = ?"
            params: List[Any] = [status]
            if epistemic_type:
                query += " AND epistemic_type = ?"
                params.append(str(epistemic_type).lower())
            if subject:
                query += " AND subject = ?"
                params.append(subject)

            rows = conn.execute(query, tuple(params)).fetchall()
            return [EpistemicRecord.from_dict(dict(r)) for r in rows]
        finally:
            conn.close()

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
        Backward-compatible adapter for recording facts into epistemic and legacy tables.
        """
        # Record into primary V1 epistemic_records table
        self.record_epistemic_fact(
            subject=subject,
            predicate=predicate,
            object=object,
            epistemic_type="observed",
            source=provenance.get("source", "unknown") if provenance else "unknown",
            source_id=provenance.get("source_id") if provenance else None,
            origin_event_id=evidence_id,
            supporting_observation_ids=[evidence_id] if evidence_id else [],
            provenance=provenance or {},
        )

        # Mirror in legacy probabilistic_facts table for backward compatibility
        conn = self.db_manager.get_connection()
        try:
            with conn:
                row = conn.execute(
                    "SELECT * FROM probabilistic_facts WHERE subject=? AND predicate=? AND object=?",
                    (subject, predicate, object),
                ).fetchone()

                if row:
                    fact = ProbabilisticFact.from_dict(dict(row))
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
        Retracts derived/inferred epistemic records and legacy fact records linked to observation_id.
        """
        retracted_ids: List[str] = [observation_id]
        conn = self.db_manager.get_connection()
        try:
            with conn:
                # 1. Mark observation/event as retracted (confidence = 0.0)
                conn.execute(
                    "UPDATE event_log SET confidence = 0.0 WHERE id = ? OR source_id = ?",
                    (observation_id, observation_id),
                )

                # 2. Retract epistemic records referencing this observation ID
                rows = conn.execute("SELECT * FROM epistemic_records WHERE status='active'").fetchall()
                for r in rows:
                    d = dict(r)
                    supp_ids = json.loads(d.get("supporting_observation_ids_json", "[]"))
                    origin_id = d.get("origin_event_id")
                    if observation_id == origin_id or observation_id in supp_ids:
                        rec_id = d["id"]
                        conn.execute(
                            "UPDATE epistemic_records SET status='retracted', updated_at=? WHERE id=?",
                            (format_iso8601(datetime.now(timezone.utc)), rec_id),
                        )
                        retracted_ids.append(rec_id)

                # 3. Retract legacy probabilistic facts if present
                p_rows = conn.execute("SELECT * FROM probabilistic_facts WHERE status='active'").fetchall()
                for r in p_rows:
                    d = dict(r)
                    ev_ids = json.loads(d.get("evidence_ids_json", "[]"))
                    if observation_id in ev_ids:
                        fact_id = d["id"]
                        conn.execute(
                            "UPDATE probabilistic_facts SET status='retracted', belief_score=0.0 WHERE id=?",
                            (fact_id,),
                        )
                        if fact_id not in retracted_ids:
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
        Applies decay to stored facts for backward compatibility.
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



    def evaluate_person_urgency(self, sender_name: str, message_summary: str = "") -> float:
        """Computes Theory of Mind interpersonal urgency multiplier for sender."""
        return self.person_model_engine.evaluate_interpersonal_urgency(sender_name, message_summary)

    def run_memory_maintenance(
        self,
        retention_days: Optional[int] = None,
        salience_decay_days: float = 1.0,
        situation_stale_hours: float = 72.0,
        pattern_decay_days: float = 30.0,
        optimize_db: bool = True,
    ) -> MemoryMaintenanceSummary:
        """Executes deterministic memory maintenance & consolidation."""
        return self.memory_maintenance_job.run_maintenance(
            retention_days=retention_days,
            salience_decay_days=salience_decay_days,
            situation_stale_hours=situation_stale_hours,
            pattern_decay_days=pattern_decay_days,
            optimize_db=optimize_db,
        )
