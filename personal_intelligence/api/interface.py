"""
Client-Agnostic Capability Interface for Personal Intelligence.

Exposes clean, versioned, provenance-preserving intelligence capabilities:
- World & State
- Timeline & Context
- Situations & Changes
- Reasoning & Bounded Contexts
- Recommendations & Pending Interventions
- Episodes, User Responses, and Longitudinal Outcomes
- Source-Backed Observation Ingestion

Zero client-specific (e.g. Hive) dependencies or UI concepts.
Any client (web dashboard, CLI, background daemon, IDE extension, third-party assistant)
can interact with Personal Intelligence through this interface.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from personal_intelligence.core.activity.stream import ActivityStream
from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.context.models import BoundedReasoningContext
from personal_intelligence.core.episodes.models import (
    EpisodeStatus,
    OutcomeRecord,
    ReasoningEpisode,
    UserResponseRecord,
)
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import (
    Event,
    EventBatch,
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.evidence_quality import (
    EvidenceQualityCalculator,
    EvidenceQualityLevel,
    EvidenceStrengthCalculator,
    EvidenceStrengthLevel,
)
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.loop import (
    EvaluationLoopResult,
    PersonalIntelligenceEvaluationLoop,
)
from personal_intelligence.core.novelty import NoveltyEngine
from personal_intelligence.core.patterns.models import Pattern, PatternStatus
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.policy.engine import InterventionPolicyEngine
from personal_intelligence.core.policy.models import (
    PolicyAction,
    PolicyEvaluationResult,
    UserContext,
)
from personal_intelligence.core.significance import (
    PersonalSignificanceEngine,
    SignificanceAssessment,
    SignificanceLevel,
)
from personal_intelligence.core.situations.eligibility import (
    ReasoningEligibilityGate,
    ReasoningEligibilityResult,
)
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.lifecycle import SituationLifecycleManager
from personal_intelligence.core.situations.models import (
    Situation,
    SituationPriority,
    SituationStatus,
)
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.core.world.changes import WhatChangedAnalyzer
from personal_intelligence.core.world.graph import (
    BoundedContextGraph,
    CanonicalEntityType,
    CanonicalRelationship,
    ContextGraph,
    EntityEdge,
    EntityNode,
)
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.core.world.models import (
    Commitment,
    CurrentState,
    FactProvenance,
    OpenIssue,
    PersonalWorldModelSnapshot,
)
from personal_intelligence.core.context.query_engine import ContextQueryEngine
from personal_intelligence.core.query.ask import AskPersonalIntelligenceEngine
from personal_intelligence.hermes_bridge.client import HermesClient, HermesInvocationRequest
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow, ReasoningWorkflowResult
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore

logger = logging.getLogger(__name__)


class PersonalIntelligenceCapabilityInterface:
    """
    Client-Agnostic Capability Interface for Personal Intelligence.
    
    Provides standardized programmatic access to Personal Intelligence capabilities:
    1. World & Current State
    2. Timeline & Chronological Events
    3. Context Graph & Bounded Subgraphs
    4. Situations & Meaningful Changes
    5. Reasoning & Epistemic Boundaries
    6. Recommendations & Proactive Interventions
    7. Episodes, User Responses, and Outcome Tracking
    8. Observation Ingestion
    """

    INTERFACE_VERSION = "1.0.0"
    SCHEMA_VERSION = "1.0"

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        world_model: Optional[PersonalWorldModel] = None,
        hermes_client: Optional[HermesClient] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

        self.local_store = LocalStateStore(db_manager=self.db_manager)
        self.world_model = world_model or PersonalWorldModel(
            db_manager=self.db_manager, local_store=self.local_store
        )

        self.event_store = self.local_store.event_store
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.goal_store = self.local_store.goal_store
        self.situation_store = self.local_store.situation_store
        self.episode_store = self.local_store.episode_store
        self.pattern_store = self.local_store.pattern_store
        self.state_engine = StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.novelty_engine = NoveltyEngine()
        self.context_graph = self.world_model.context_graph

        self.context_builder = ContextBuilder(
            situation_store=self.situation_store,
            goal_store=self.goal_store,
        )
        self.situation_lifecycle = SituationLifecycleManager(
            situation_store=self.situation_store,
            context_builder=self.context_builder,
            db_manager=self.db_manager,
        )
        self.hermes_client = hermes_client or HermesClient()
        self.reasoning_workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=self.hermes_client,
        )
        self.policy_engine = InterventionPolicyEngine()
        self.significance_engine = PersonalSignificanceEngine()
        self.eligibility_gate = ReasoningEligibilityGate()
        self.evidence_calculator = EvidenceStrengthCalculator()
        self.what_changed_analyzer = WhatChangedAnalyzer(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            pattern_store=self.pattern_store,
            state_engine=self.state_engine,
            db_manager=self.db_manager,
        )

        self.evaluation_loop = PersonalIntelligenceEvaluationLoop(
            db_manager=self.db_manager,
            event_store=self.event_store,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            episode_store=self.episode_store,
            pattern_store=self.pattern_store,
            world_model=self.world_model,
        )

        self.context_query_engine = ContextQueryEngine(
            context_graph=self.context_graph,
            event_store=self.event_store,
            timeline_engine=self.timeline_engine,
            state_engine=self.state_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            db_manager=self.db_manager,
        )
        self.evidence_quality_calculator = EvidenceQualityCalculator()
        self.ask_engine = AskPersonalIntelligenceEngine(
            db_manager=self.db_manager,
            event_store=self.event_store,
            state_engine=self.state_engine,
            situation_store=self.situation_store,
            goal_store=self.goal_store,
            pattern_store=self.pattern_store,
            timeline_engine=self.timeline_engine,
            world_model=self.world_model,
            hermes_client=self.hermes_client,
        )

    # -------------------------------------------------------------------------
    # 1. World & State Capabilities
    # -------------------------------------------------------------------------

    def get_current_world(self, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Retrieves the complete authoritative snapshot of the Personal World Model.
        Includes commitments, open issues, upcoming events, active activities, and goals.
        """
        snapshot = self.world_model.get_snapshot(reference_time=as_of)
        commits = self.world_model.get_commitments()
        issues = self.world_model.get_open_issues()
        upcoming = self.world_model.get_upcoming_events(as_of=as_of)
        return {
            "interface_version": self.INTERFACE_VERSION,
            "timestamp": format_iso8601(snapshot.timestamp),
            "current_state": snapshot.current_state.to_dict() if hasattr(snapshot.current_state, "to_dict") else snapshot.current_state,
            "commitments": [c.to_dict() for c in commits],
            "open_issues": [i.to_dict() for i in issues],
            "upcoming_events": [e.to_dict() for e in upcoming],
            "goals": [g.to_dict() for g in self.goal_store.list_active_goals()],
            "active_situations_count": len(self.situation_store.list_active()),
        }

    def get_current_state(self, reference_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Retrieves the computed point-in-time multi-dimensional state representation.
        """
        state_rep = self.state_engine.compute_current_state(reference_time=reference_time)
        return state_rep.to_dict()

    # -------------------------------------------------------------------------
    # 2. Timeline Capabilities
    # -------------------------------------------------------------------------

    def get_timeline(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Retrieves chronologically sorted and normalized observation events within a time range.
        """
        now = datetime.now(timezone.utc)
        s_dt = start_time or (now - timedelta(days=7))
        e_dt = end_time or (now + timedelta(days=1))
        timeline = self.timeline_engine.get_time_range(start_time=s_dt, end_time=e_dt)
        events = timeline.events[:limit] if timeline else []
        return {
            "start_time": format_iso8601(s_dt),
            "end_time": format_iso8601(e_dt),
            "events_count": len(events),
            "events": [ev.to_dict() for ev in events],
        }

    def get_relevant_timeline(
        self,
        situation_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        window_hours: int = 24,
        as_of: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves timeline events specifically bounded and relevant to a situation or entity.
        """
        if as_of is not None:
            start_dt = as_of - timedelta(hours=window_hours)
            timeline = self.timeline_engine.get_time_range(start_time=start_dt, end_time=as_of)
            all_events = timeline.events if timeline else []
        else:
            all_events = self.event_store.list_all(limit=200)

        if situation_id:
            sit = self.situation_store.get(situation_id)
            if sit and sit.evidence:
                evidence_set = set(sit.evidence)
                return [ev.to_dict() for ev in all_events if ev.id in evidence_set]

        if entity_id:
            matched = []
            for ev in all_events:
                e_refs = ev.entity_refs or (ev.payload.get("entity_refs") if isinstance(ev.payload, dict) else []) or []
                subj = ev.subject_id or (ev.payload.get("subject_id") if isinstance(ev.payload, dict) else "")
                if entity_id in e_refs or subj == entity_id or entity_id in str(ev.payload):
                    matched.append(ev.to_dict())
            return matched

        return [ev.to_dict() for ev in all_events]

    # -------------------------------------------------------------------------
    # 3. Context & Graph Capabilities
    # -------------------------------------------------------------------------

    def get_context(
        self,
        target_id: str,
        depth: int = 1,
        time_window: Optional[Tuple[datetime, datetime]] = None,
        include_inferred: bool = True,
    ) -> Dict[str, Any]:
        """
        Retrieves bounded graph context around any entity, situation, goal, or observation.
        """
        bounded_graph = self.context_graph.get_bounded_context(
            target_id=target_id,
            depth=depth,
            time_window=time_window,
            include_inferred=include_inferred,
        )
        return bounded_graph.to_dict()

    def get_context_for_entity(self, entity_id: str, depth: int = 1) -> Dict[str, Any]:
        """Retrieves bounded subgraph around a specific entity."""
        return self.get_context(target_id=entity_id, depth=depth)

    def get_context_for_situation(self, situation_id: str, depth: int = 1) -> Dict[str, Any]:
        """Retrieves bounded subgraph surrounding an active situation."""
        return self.get_context(target_id=situation_id, depth=depth)

    def get_context_for_goal(self, goal_id: str, depth: int = 1) -> Dict[str, Any]:
        """Retrieves bounded subgraph surrounding an active goal."""
        return self.get_context(target_id=goal_id, depth=depth)

    # -------------------------------------------------------------------------
    # 4. Situations & Changes Capabilities
    # -------------------------------------------------------------------------

    def get_active_situations(
        self,
        priority: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves currently active, unresolved situations.
        """
        situations = self.situation_store.list_active()
        if priority:
            prio_clean = priority.strip().lower()
            situations = [s for s in situations if str(s.priority).lower() == prio_clean]
        return [s.to_dict() for s in situations[:limit]]

    def get_significant_changes(
        self,
        since_time: Optional[datetime] = None,
        window_hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves detected structured changes across state, goals, and commitments.
        """
        ref_dt = datetime.now(timezone.utc)
        since_dt = since_time or (ref_dt - timedelta(hours=window_hours))
        hours = max(1, int((ref_dt - since_dt).total_seconds() / 3600))
        changes = self.what_changed_analyzer.analyze_changes(as_of=ref_dt, window_hours=hours)
        return [c.to_dict() for c in changes]

    # -------------------------------------------------------------------------
    # 5. Reasoning & Epistemic Capabilities
    # -------------------------------------------------------------------------

    def evaluate_situation(
        self,
        situation_id: str,
        as_of: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates personal significance and reasoning eligibility for a situation.
        """
        sit = self.situation_store.get(situation_id)
        if not sit:
            return {"status": "error", "error": f"Situation '{situation_id}' not found."}

        ref_dt = as_of or datetime.now(timezone.utc)
        active_goals = self.goal_store.list_active_goals()
        patterns = self.pattern_store.list_active()

        sig = self.significance_engine.evaluate_situation(
            situation_type=sit.type,
            situation_priority=sit.priority,
            evidence_count=len(sit.evidence) if sit.evidence else 0,
            novelty_score=sit.novelty,
            has_information_gap=bool(sit.information_required),
            goals=active_goals,
            patterns=patterns,
            reference_time=ref_dt,
        )

        elig = self.eligibility_gate.evaluate(
            situation=sit,
            significance=sig,
            is_new_situation=False,
            has_new_events=True,
        )

        return {
            "situation_id": sit.id,
            "significance": sig.to_dict(),
            "eligibility": elig.to_dict(),
            "requires_hermes": elig.requires_hermes,
        }

    def get_reasoning_context(
        self,
        situation_id: str,
        objective: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Builds a compact, epistemically-partitioned BoundedReasoningContext for Hermes.
        """
        sit = self.situation_store.get(situation_id)
        if not sit:
            return {"status": "error", "error": f"Situation '{situation_id}' not found."}

        now = datetime.now(timezone.utc)
        curr_state = self.state_engine.compute_current_state(reference_time=now)
        bounded = self.context_builder.build_bounded_context(
            situation=sit,
            current_state=curr_state,
            objective=objective,
        )
        return bounded.to_dict()

    def request_reasoning(
        self,
        situation_id: str,
        objective: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes bounded Hermes reasoning for a situation and captures structured output.
        """
        sit = self.situation_store.get(situation_id)
        if not sit:
            return {"status": "error", "error": f"Situation '{situation_id}' not found."}

        now = datetime.now(timezone.utc)
        curr_state = self.state_engine.compute_current_state(reference_time=now)
        result = self.reasoning_workflow.run_workflow(
            situation=sit,
            current_state=curr_state,
            objective=objective,
        )

        return {
            "episode_id": result.episode.id,
            "situation_id": sit.id,
            "status": result.episode.status,
            "success": result.success,
            "recommendation": result.episode.recommendation.to_dict() if hasattr(result.episode.recommendation, "to_dict") else result.episode.recommendation,
            "evidence_evaluated": result.synthesis.evidence_evaluated if hasattr(result.synthesis, "evidence_evaluated") else [],
            "interpretations": result.synthesis.interpretations if hasattr(result.synthesis, "interpretations") else [],
            "hypotheses": result.synthesis.hypotheses if hasattr(result.synthesis, "hypotheses") else [],
            "predictions": result.synthesis.predictions if hasattr(result.synthesis, "predictions") else [],
            "uncertainties": result.synthesis.uncertainties if hasattr(result.synthesis, "uncertainties") else [],
        }

    # -------------------------------------------------------------------------
    # 5b. Interactive Reasoning Capabilities (Unified Intelligence Boundary)
    # -------------------------------------------------------------------------

    def ask(
        self,
        query: str,
        situation_id: Optional[str] = None,
        as_of: Optional[datetime] = None,
        user_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Interactive personal reasoning entrypoint for Hive and client applications.

        Flow:
        HIVE USER
            ↓
        PI CLIENT API (ask)
            ↓
        PI CONTEXT QUERY (ContextQueryEngine)
            ↓
        BOUNDED PERSONAL CONTEXT (BoundedRelevantPersonalContext)
            ↓
        HERMES (Structured Reasoning)
            ↓
        STRUCTURED REASONING (StructuredReasoningResult)
            ↓
        PI EVIDENCE QUALITY (EvidenceQualityCalculator)
            ↓
        PI RESPONSE / POLICY
            ↓
        HIVE
        """
        clean_query = (query or "").strip()
        if not clean_query:
            return {
                "status": "error",
                "error": "Query cannot be empty.",
                "query": query,
                "answer": "Please provide a query for Personal Intelligence.",
            }

        # 1. PI Context Query: determine relevance and bounded context
        if situation_id:
            sit = self.situation_store.get(situation_id)
            if sit:
                bounded_ctx = self.context_query_engine.query_for_situation(sit)
            else:
                bounded_ctx = self.context_query_engine.query_for_user_query(clean_query)
        else:
            bounded_ctx = self.context_query_engine.query_for_user_query(clean_query)

        is_personal = bool(bounded_ctx.metadata.get("is_personal", True))

        # 2. Non-personal queries: preserve ordinary Hermes usage with zero personal context leakage
        if not is_personal:
            prompt = f"You are an AI assistant. Answer the following general question accurately and concisely:\n{clean_query}"
            req = HermesInvocationRequest(prompt=prompt, timeout_seconds=15)
            try:
                hermes_res = self.hermes_client.invoke(req)
                ans = hermes_res.raw_response if (hermes_res and hermes_res.success and hermes_res.raw_response) else "General inquiry processed."
                if ans.startswith("```"):
                    ans = re.sub(r"^```(?:json)?\s*", "", ans).rstrip("`").strip()
            except Exception as ex:
                ans = f"General query received: {clean_query}"

            return {
                "status": "success",
                "query": clean_query,
                "answer": ans,
                "is_personal": False,
                "evidence": [],
                "evidence_quality": "none",
                "uncertainty": "None (general knowledge inquiry, zero personal context attached)",
                "sources": ["Hermes General Knowledge"],
                "recommended_next_step": "",
                "bounded_context": bounded_ctx.to_dict(),
                "requires_hermes": True,
                "timestamp": format_iso8601(as_of or datetime.now(timezone.utc)),
            }

        # 3. Personal queries: execute through unified Ask engine with bounded context
        ask_res = self.ask_engine.ask(query=clean_query, situation_id=situation_id)

        # 4. PI Evidence Quality evaluation
        evidence_dicts = []
        for ev in ask_res.evidence:
            evidence_dicts.append({"summary": str(ev), "epistemic_type": "observed"})
        eq = self.evidence_quality_calculator.calculate(
            evidence_items=evidence_dicts,
            reference_time=as_of or datetime.now(timezone.utc),
        )

        # 5. Record reasoning episode in unified EpisodeStore
        ep_id = str(uuid.uuid4())
        try:
            self.episode_store.create_episode(
                episode_id=ep_id,
                situation_id=situation_id or (bounded_ctx.relevant_situations[0]["id"] if bounded_ctx.relevant_situations else None),
                status=EpisodeStatus.REASONING_COMPLETED.value,
                created_at=as_of or datetime.now(timezone.utc),
                context_snapshot=bounded_ctx.to_dict(),
                observations=ask_res.evidence,
                recommendation=ask_res.recommended_next_step,
                hermes_task=clean_query,
                hermes_result={"answer": ask_res.answer, "sources": ask_res.sources},
                evidence_strength=str(eq.value if hasattr(eq, "value") else eq),
            )
        except Exception as ex:
            logger.debug("Episode recording note in interactive ask: %s", ex)

        return {
            "status": "success",
            "query": clean_query,
            "answer": ask_res.answer,
            "is_personal": True,
            "evidence": ask_res.evidence,
            "evidence_quality": str(eq.value if hasattr(eq, "value") else eq),
            "uncertainty": ask_res.uncertainty,
            "sources": ask_res.sources,
            "recommended_next_step": ask_res.recommended_next_step,
            "bounded_context": bounded_ctx.to_dict(),
            "episode_id": ep_id,
            "requires_hermes": bool(ask_res.evidence or bounded_ctx.relevant_situations),
            "timestamp": format_iso8601(as_of or datetime.now(timezone.utc)),
        }

    def query_interactive(
        self,
        query: str,
        situation_id: Optional[str] = None,
        as_of: Optional[datetime] = None,
        user_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Alias for ask(). Routes interactive user inquiries through unified PI boundary."""
        return self.ask(query=query, situation_id=situation_id, as_of=as_of, user_context=user_context)

    # -------------------------------------------------------------------------
    # 6. Recommendations & Pending Interventions
    # -------------------------------------------------------------------------

    def get_recommendations(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves recent recommendations generated across reasoning episodes.
        """
        episodes = self.episode_store.list_recent(limit=limit)
        results = []
        for ep in episodes:
            if ep.recommendation:
                rec_dict = ep.recommendation.to_dict() if hasattr(ep.recommendation, "to_dict") else ep.recommendation
                results.append({
                    "episode_id": ep.id,
                    "situation_id": ep.situation_id,
                    "created_at": format_iso8601(ep.created_at),
                    "status": ep.status,
                    "recommendation": rec_dict,
                })
        return results

    def get_pending_interventions(
        self,
        limit: int = 50,
        user_context: Optional[str] = None,
        as_of: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Evaluates proactive intervention policy across active situations and returns
        interventions currently ready for presentation (INTERRUPT or BRIEFING).
        Clients decide how and where to display them.
        """
        ref_dt = as_of or datetime.now(timezone.utc)
        ctx = user_context or UserContext.AVAILABLE.value
        active_sits = self.situation_store.list_active()
        pending = []

        for sit in active_sits:
            # Check if there is an associated recommendation in recent episodes
            ep = self.episode_store.get_latest_for_situation(sit.id)
            rec_data = ep.recommendation if ep else None

            # Policy evaluation
            policy_res = self.policy_engine.evaluate(
                urgency=sit.priority or "medium",
                actionability="high" if rec_data else "medium",
                evidence_quality="strong" if len(sit.evidence) >= 2 else "moderate",
                evidence_strength="strong" if len(sit.evidence) >= 2 else "moderate",
                user_context=ctx,
            )

            act_val = policy_res.action.value if hasattr(policy_res.action, "value") else str(policy_res.action)
            if act_val in (PolicyAction.INTERRUPT.value, PolicyAction.BRIEFING.value, PolicyAction.INTERRUPT, PolicyAction.BRIEFING):
                pending.append({
                    "situation_id": sit.id,
                    "situation_type": sit.type,
                    "priority": sit.priority,
                    "policy_action": act_val,
                    "episode_id": ep.id if ep else None,
                    "recommendation": rec_data.to_dict() if hasattr(rec_data, "to_dict") else rec_data,
                    "rationale": policy_res.reasoning if hasattr(policy_res, "reasoning") else "Actionable situation",
                    "provenance": [self.event_store.get(eid).to_dict() for eid in sit.evidence if self.event_store.get(eid)] if sit.evidence else [],
                })

        return pending[:limit]

    def get_client_event_stream(
        self,
        limit: int = 100,
        since_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves real-time system activity and state transition events.
        """
        stream = ActivityStream.get_instance()
        events = stream.get_recent(limit=limit)
        return events

    # -------------------------------------------------------------------------
    # 7. Episodes, User Response, and Outcome Tracking
    # -------------------------------------------------------------------------

    def get_episode(self, episode_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a specific reasoning episode with complete context and recommendations."""
        ep = self.episode_store.get_episode(episode_id)
        return ep.to_dict() if ep else None

    def record_user_response(
        self,
        situation_id: str,
        action: str,  # 'acknowledge', 'accept', 'snooze', 'dismiss', 'not_relevant'
        snooze_days: int = 2,
        feedback_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Captures the user's explicit decision/feedback regarding a situation or recommendation.
        Updates situation lifecycle, records response in EpisodeStore, and notifies LearningEngine.
        """
        return self.world_model.process_user_feedback(
            situation_id=situation_id,
            action=action,
            snooze_days=snooze_days,
            feedback_notes=feedback_notes,
        )

    def record_outcome(
        self,
        episode_id: str,
        outcome: str,
        feedback_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Records the longitudinal outcome of a recommendation into EpisodeStore.
        """
        outcome_rec = self.episode_store.record_outcome(
            episode_id=episode_id,
            outcome_status=outcome,
            evaluation_notes=feedback_notes,
        )
        if outcome_rec and outcome_rec.outcome:
            out_dict = dict(outcome_rec.outcome) if isinstance(outcome_rec.outcome, dict) else {}
            out_dict["outcome"] = outcome
            out_dict["episode_id"] = episode_id
            return out_dict
        return {"status": "success", "episode_id": episode_id, "outcome": outcome}

    # -------------------------------------------------------------------------
    # 8. Observation Ingestion
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
        source_type: Optional[str] = None,
        observed_at: Optional[Union[datetime, str]] = None,
        entity_refs: Optional[List[str]] = None,
        schema_version: str = "1.0",
    ) -> Dict[str, Any]:
        """
        Generic entry point for ingesting source-backed observations from any connector or client.
        """
        event = self.world_model.record_observation(
            source=source,
            source_id=source_id,
            timestamp=timestamp,
            observation_type=observation_type,
            summary=summary,
            evidence=evidence,
            provenance=provenance,
            subject_id=subject_id,
            confidence=confidence,
            source_type=source_type,
            observed_at=observed_at,
            entity_refs=entity_refs,
            schema_version=schema_version,
        )
        return event.to_dict()

    def ingest_batch(self, observations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ingests a batch of observations and returns processing summary."""
        created_events = []
        for obs in observations:
            ev = self.record_observation(
                source=obs.get("source", "unknown"),
                source_id=obs.get("source_id", str(uuid.uuid4())),
                timestamp=obs.get("timestamp", datetime.now(timezone.utc)),
                observation_type=obs.get("observation_type", obs.get("event_type", "observation")),
                summary=obs.get("summary", ""),
                evidence=obs.get("evidence"),
                provenance=obs.get("provenance"),
                subject_id=obs.get("subject_id", "user"),
                confidence=float(obs.get("confidence", 1.0)),
                source_type=obs.get("source_type"),
                observed_at=obs.get("observed_at"),
                entity_refs=obs.get("entity_refs"),
                schema_version=obs.get("schema_version", "1.0"),
            )
            created_events.append(ev)

        return {
            "status": "success",
            "ingested_count": len(created_events),
            "event_ids": [e["id"] for e in created_events],
        }

    # -------------------------------------------------------------------------
    # 9. Evaluation Cycle Execution
    # -------------------------------------------------------------------------

    def run_evaluation_cycle(
        self,
        as_of: Optional[datetime] = None,
        user_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes one complete evaluation cycle across the 19-stage canonical sequence.
        """
        result = self.evaluation_loop.run_cycle(as_of=as_of, user_context=user_context)
        return result.to_dict()


# Public client aliases for client-agnostic interaction
PersonalIntelligenceClient = PersonalIntelligenceCapabilityInterface
PersonalIntelligenceInterface = PersonalIntelligenceCapabilityInterface

