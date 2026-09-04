"""
Generic Context Query Layer for Personal Intelligence.

Answers: 'What is relevant to this situation/entity/goal/event/query?'
Independent of downstream reasoning runtimes or prompt formatting.
Produces a first-class, structured, bounded RelevantPersonalContext object.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from personal_intelligence.core.context.models import (
    BoundedRelevantPersonalContext,
    RelevantPersonalContext,
    estimate_token_count,
)
from personal_intelligence.core.events.models import format_iso8601
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.situations.models import Situation
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.world.graph import (
    CanonicalEntityType,
    CanonicalRelationship,
    ContextGraph,
    EntityNode,
)
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class ContextQueryEngine:
    """
    Independent Context Query Layer inside Personal Intelligence.
    Synthesizes relevant context across Context Graph, Timeline, State, Goals, and Situations.
    Guarantees strict token bounds, provenance preservation, and untrusted data demarcation.
    """

    def __init__(
        self,
        context_graph: Optional[ContextGraph] = None,
        event_store: Optional[EventStore] = None,
        timeline_engine: Optional[TimelineEngine] = None,
        state_engine: Optional[StateEngine] = None,
        goal_store: Optional[GoalStore] = None,
        situation_store: Optional[SituationStore] = None,
        db_manager: Optional[DatabaseManager] = None,
        max_entities: int = 10,
        max_timeline_events: int = 15,
        max_goals: int = 5,
        max_situations: int = 3,
        token_cap: int = 2000,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.context_graph = context_graph or ContextGraph(db_manager=self.db_manager)
        self.event_store = event_store or EventStore(db_manager=self.db_manager)
        self.timeline_engine = timeline_engine or TimelineEngine(event_store=self.event_store)
        self.goal_store = goal_store or GoalStore(db_manager=self.db_manager)
        self.situation_store = situation_store or SituationStore(db_manager=self.db_manager)
        self.state_engine = state_engine or StateEngine(
            timeline_engine=self.timeline_engine, goal_store=self.goal_store
        )
        self.max_entities = max_entities
        self.max_timeline_events = max_timeline_events
        self.max_goals = max_goals
        self.max_situations = max_situations
        self.token_cap = token_cap

    # -------------------------------------------------------------------------
    # Core Situation Query
    # -------------------------------------------------------------------------

    def query_for_situation(
        self,
        situation: Union[Situation, Dict[str, Any]],
        depth: int = 2,
    ) -> RelevantPersonalContext:
        """
        Builds a structured RelevantPersonalContext for an emerging or active situation.
        Discovers related entities, affected goals, supporting observations, timeline slice,
        and current state without dumping the entire world model.
        """
        sit_dict = situation.to_dict() if hasattr(situation, "to_dict") else dict(situation)
        sit_id = sit_dict.get("id") or str(uuid.uuid4())
        sit_time = sit_dict.get("created_at")
        if isinstance(sit_time, str):
            try:
                ref_dt = datetime.fromisoformat(sit_time.replace("Z", "+00:00"))
            except Exception:
                ref_dt = datetime.now(timezone.utc)
        elif isinstance(sit_time, datetime):
            ref_dt = sit_time
        else:
            ref_dt = datetime.now(timezone.utc)

        # 1. Context Graph Bounded Traversal
        bounded = self.context_graph.get_bounded_context(target_id=sit_id, depth=depth)
        related_entities = [
            n.to_dict() for n in bounded.nodes if n.id != sit_id
        ][:self.max_entities]
        relationships = [
            e.to_dict() for e in bounded.edges
        ][:self.max_entities * 2]

        # 1b. Discover explicit primary entity references from situation context
        ctx_data = sit_dict.get("context", {})
        if isinstance(ctx_data, dict):
            for pe_id in ctx_data.get("primary_entity_ids", []):
                if not any(e["id"] == pe_id for e in related_entities):
                    node = self.context_graph.get_node(pe_id)
                    if node:
                        related_entities.append(node.to_dict())
                        # Also pull 1-hop connected edges
                        for edge in self.context_graph.get_edges(node.id):
                            if not any(e["id"] == edge.id for e in relationships):
                                relationships.append(edge.to_dict())

        # 2. Supporting Evidence & Provenance
        supporting_evidence = self.context_graph.get_supporting_evidence(target_id=sit_id)
        if not supporting_evidence:
            # Fall back to raw evidence IDs on situation
            raw_ev = sit_dict.get("evidence") or []
            for ev_id in raw_ev:
                clean_id = str(ev_id).replace("event:", "").strip()
                stored_evt = self.event_store.get(clean_id)
                if stored_evt:
                    supporting_evidence.append({
                        "id": stored_evt.id,
                        "source": stored_evt.source,
                        "event_type": stored_evt.event_type,
                        "event_time": format_iso8601(stored_evt.event_time),
                        "summary": stored_evt.payload.get("summary") if isinstance(stored_evt.payload, dict) else str(stored_evt.payload),
                        "payload": stored_evt.payload,
                        "provenance": stored_evt.provenance,
                    })

        # 3. Related Goals
        related_goals = self.context_graph.get_related_goals(target_id=sit_id)[:self.max_goals]
        if not related_goals and sit_dict.get("related_goals"):
            for gid in sit_dict["related_goals"]:
                g = self.goal_store.get(gid)
                if g:
                    related_goals.append(g.to_dict() if hasattr(g, "to_dict") else dict(g))

        # 4. Relevant Timeline Slice (Window around situation)
        start_time = ref_dt - timedelta(hours=48)
        timeline_events = self.timeline_engine.get_time_range(start_time=start_time, end_time=ref_dt).events
        relevant_timeline = []
        for e in timeline_events[-self.max_timeline_events:]:
            safe_payload = dict(e.payload) if isinstance(e.payload, dict) else {"content": str(e.payload)}
            relevant_timeline.append({
                "id": e.id,
                "source": e.source,
                "event_type": e.event_type,
                "event_time": format_iso8601(e.event_time),
                "summary": safe_payload.get("summary") or safe_payload.get("title") or e.event_type,
                "provenance": e.provenance,
            })

        # 5. Point-in-time Current State Representation
        state_dict: Dict[str, Any] = {}
        try:
            curr_state = self.state_engine.compute_state(as_of=ref_dt)
            state_dict = curr_state.to_dict() if hasattr(curr_state, "to_dict") else dict(curr_state)
        except Exception as ex:
            logger.debug("State computation fallback: %s", ex)

        # 6. Uncertainties
        uncertainties = []
        conf_val = sit_dict.get("confidence") or (sit_dict.get("context") or {}).get("confidence")
        if conf_val is not None and float(conf_val) < 0.8:
            uncertainties.append({
                "type": "confidence_boundary",
                "description": f"Situation confidence is moderate ({conf_val}). Corroboration advised.",
                "potential_impact": "high",
            })
        for ev in supporting_evidence:
            if isinstance(ev.get("payload"), dict) and "uncertainty" in ev["payload"]:
                uncertainties.append({
                    "type": "source_reported_uncertainty",
                    "description": str(ev["payload"]["uncertainty"]),
                    "potential_impact": "medium",
                })

        # 7. Epistemic Bounds
        observed_facts = [
            {
                "fact": ev.get("summary"),
                "source": ev.get("source"),
                "provenance": ev.get("provenance"),
                "observed_at": ev.get("event_time"),
            }
            for ev in supporting_evidence
        ]
        inferences = sit_dict.get("inferences") or [
            {"inference": f"Emergence of {sit_dict.get('type')} inferred from observation pattern", "epistemic_type": "inferred"}
        ]

        # 8. Provenance Synthesis
        provenance_chain = []
        for ev in supporting_evidence:
            if ev.get("provenance"):
                provenance_chain.append(ev["provenance"])

        return RelevantPersonalContext(
            target_id=sit_id,
            target_type="situation",
            relevant_entities=related_entities,
            relevant_events=[e for e in supporting_evidence],
            relevant_relationships=relationships,
            relevant_state=state_dict,
            relevant_timeline=relevant_timeline,
            relevant_goals=related_goals,
            relevant_situations=[sit_dict],
            supporting_evidence=supporting_evidence,
            uncertainties=uncertainties,
            provenance={"situation_id": sit_id, "primary_source": sit_dict.get("source", "world_model")},
            provenance_chain=provenance_chain,
            epistemic_bounds={
                "observed_facts": observed_facts,
                "inferences": inferences,
                "predictions": sit_dict.get("predictions") or [],
            },
            metadata={"priority": sit_dict.get("priority", "medium"), "type": sit_dict.get("type")},
        )

    # -------------------------------------------------------------------------
    # Interactive Query (Zero Leakage for Generic Questions)
    # -------------------------------------------------------------------------

    def query_for_user_query(
        self,
        query: str,
        depth: int = 1,
    ) -> RelevantPersonalContext:
        """
        Determines what personal context is relevant to an interactive user question.
        Guarantees:
        - Generic questions (coding, general knowledge, math) receive zero/minimal personal context.
        - Personal questions (schedule, commitments, projects, colleagues) receive targeted bounded context.
        """
        clean_query = (query or "").strip().lower()

        # Check for known entity mentions across all entity types (domain-agnostic)
        matched_entities: List[EntityNode] = []
        all_nodes = self.context_graph.list_all_nodes()
        for node in all_nodes:
            if node.name and len(node.name) >= 3 and node.name.lower() in clean_query:
                matched_entities.append(node)

        # Check active goals matching query terms
        matched_goals = []
        active_goals = self.goal_store.list_active()
        for g in active_goals:
            g_name_lower = g.name.lower()
            if any(w in clean_query for w in g_name_lower.split() if len(w) > 3) or "goal" in clean_query:
                matched_goals.append(g.to_dict() if hasattr(g, "to_dict") else dict(g))

        # Check active situations matching query terms
        matched_situations = []
        active_sits = self.situation_store.list_active()
        for s in active_sits:
            s_type_lower = s.type.lower().replace("_", " ")
            if any(w in clean_query for w in s_type_lower.split() if len(w) > 3) or any(k in clean_query for k in ("situation", "urgent", "priority", "status")):
                matched_situations.append(s.to_dict() if hasattr(s, "to_dict") else dict(s))

        # Personal intent triggers
        personal_intents = [
            r"\bmy schedule\b", r"\bmy calendar\b", r"\bmy email\b", r"\bmy meetings?\b",
            r"\bmy deadline\b", r"\bmy project\b", r"\bmy commitments?\b", r"\bmy goals?\b",
            r"\bmy priorities\b", r"\bwhat should i do\b", r"\bwhat are my\b", r"\bwho is\b",
        ]
        has_personal_intent = any(re.search(pat, clean_query) for pat in personal_intents)

        is_personal = bool(matched_entities or matched_goals or matched_situations or has_personal_intent)

        # Generic question with zero personal relevance: Return clean empty context
        if not is_personal:
            return RelevantPersonalContext(
                target_id="interactive_generic_query",
                target_type="user_query",
                metadata={"is_personal": False, "query": query},
            )

        # 2. Personal query: Retrieve strictly relevant bounded context
        collected_entities: Dict[str, Dict[str, Any]] = {}
        for ent in matched_entities:
            collected_entities[ent.id] = ent.to_dict()
            # 1-hop expansion for matched entities
            related = self.context_graph.get_related_entities(entity_id=ent.id, depth=depth)
            for r_ent in related[:self.max_entities]:
                if r_ent.id not in collected_entities:
                    collected_entities[r_ent.id] = r_ent.to_dict()

        # Relevant timeline events
        recent_events = self.event_store.query_by_time(limit=self.max_timeline_events, order="desc")
        relevant_timeline = []
        for e in recent_events:
            p_str = json.dumps(e.payload, ensure_ascii=False).lower()
            # Filter to events matching query or matched entities
            is_relevant = (
                any(ent_id.lower() in p_str for ent_id in collected_entities)
                or any(w in p_str for w in clean_query.split() if len(w) > 3)
                or "today" in clean_query
                or has_personal_intent
            )
            if is_relevant:
                relevant_timeline.append({
                    "id": e.id,
                    "source": e.source,
                    "event_type": e.event_type,
                    "event_time": format_iso8601(e.event_time),
                    "summary": e.payload.get("summary") if isinstance(e.payload, dict) else str(e.payload),
                    "provenance": e.provenance,
                })

        # Point-in-time State
        state_dict: Dict[str, Any] = {}
        try:
            curr_state = self.state_engine.compute_state(as_of=datetime.now(timezone.utc))
            state_dict = curr_state.to_dict() if hasattr(curr_state, "to_dict") else dict(curr_state)
        except Exception:
            pass

        return RelevantPersonalContext(
            target_id="interactive_personal_query",
            target_type="user_query",
            relevant_entities=list(collected_entities.values())[:self.max_entities],
            relevant_goals=matched_goals[:self.max_goals],
            relevant_situations=matched_situations[:self.max_situations],
            relevant_timeline=relevant_timeline[:self.max_timeline_events],
            relevant_state=state_dict,
            provenance={"query": query, "matched_entities_count": len(matched_entities)},
            metadata={"is_personal": True, "query": query},
        )

    def find_relevant_context_for_query(
        self,
        query: str,
        depth: int = 1,
    ) -> RelevantPersonalContext:
        """Determines relevant personal context for an interactive user query (alias)."""
        return self.query_for_user_query(query=query, depth=depth)
