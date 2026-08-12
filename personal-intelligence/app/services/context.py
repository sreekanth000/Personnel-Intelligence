"""Context Engine implementation — Next-Level Context Retrieval.

Assembles task-specific subsets of the Personal World Model (ContextPackage)
for user queries and cognitive tasks using:
1. Multi-hop evidence-weighted graph traversal (seed entity matching + 1-hop / 2-hop graph expansion).
2. Evidence Weighting: Sums confidence scores & count of linked evidence records for each node & edge.
3. Temporal Filtering: Filters by start_date, end_date, as_of_date, recent_days, and validity bounds.
4. Relevance Ranking: Computes composite score = w_text * TextMatch + w_graph * GraphProximity + w_evidence * EvidenceWeight + w_recency * RecencyDecay.
5. Top-K Truncation & Provenance Lineage Preservation.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.config.logging import get_logger
from app.domain.context import ContextPackage, ContextRequest
from app.domain.enums import EntityType
from app.services.evidence import EvidenceService
from app.services.world_model import WorldModelService

if TYPE_CHECKING:
    from app.domain.claims import Claim
    from app.domain.entities import Entity, Relationship

logger = get_logger(__name__)


def _normalize_token(s: str) -> str:
    """Lowercase string token for flexible matching."""
    return " ".join(s.lower().strip().split())


def _compute_text_match_score(query_norm: str, name: str, aliases: list[str] | None = None) -> float:
    """Compute text match score [0.0 - 1.0] for query against name and aliases."""
    if not query_norm or not name:
        return 0.0

    name_norm = _normalize_token(name)
    if not name_norm:
        return 0.0

    if query_norm == name_norm:
        return 1.0
    if query_norm in name_norm or name_norm in query_norm:
        return 0.8

    if aliases:
        for alias in aliases:
            a_norm = _normalize_token(alias)
            if a_norm and (query_norm in a_norm or a_norm in query_norm):
                return 0.75

    query_words = set(query_norm.split())
    name_words = set(name_norm.split())
    common = query_words.intersection(name_words)
    if common:
        return 0.5 * (len(common) / max(len(query_words), 1))

    return 0.0


def _parse_iso_datetime(dt_val: Any) -> datetime | None:
    """Parse ISO datetime string or datetime object into timezone-aware UTC datetime."""
    if isinstance(dt_val, datetime):
        return dt_val if dt_val.tzinfo else dt_val.replace(tzinfo=UTC)
    if isinstance(dt_val, str) and dt_val.strip():
        try:
            cleaned = dt_val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except Exception:
            return None
    return None


def _compute_recency_decay(item_time: Any, as_of_date: datetime | None = None) -> float:
    """Compute exponential recency decay score exp(-0.02 * days_old) [0.0 - 1.0]."""
    dt_item = _parse_iso_datetime(item_time)
    if not dt_item:
        return 0.5

    now = as_of_date or datetime.now(UTC)
    if not now.tzinfo:
        now = now.replace(tzinfo=UTC)

    if dt_item > now:
        return 1.0

    days_old = (now - dt_item).total_seconds() / 86400.0
    return math.exp(-0.02 * max(0.0, days_old))


class BaseContextEngine(ABC):
    """Abstract interface for personal context retrieval and assembly."""

    @abstractmethod
    async def assemble_context(
        self,
        request: ContextRequest,
    ) -> ContextPackage:
        """Assemble a task-specific ContextPackage matching the request."""


class ContextEngine(BaseContextEngine):
    """Production implementation of Evidence-Weighted, Multi-Hop Context Engine."""

    def __init__(
        self,
        world_model_service: WorldModelService | None = None,
        evidence_service: EvidenceService | None = None,
    ) -> None:
        self._world_model = world_model_service or WorldModelService()
        if evidence_service is not None:
            self._evidence_service = evidence_service
        elif world_model_service is not None and getattr(world_model_service, "_duckdb", None) is not None:
            self._evidence_service = EvidenceService(duckdb_store=world_model_service._duckdb)
        else:
            self._evidence_service = EvidenceService()

    def _is_within_temporal_window(
        self,
        valid_from: Any,
        valid_to: Any,
        request: ContextRequest,
    ) -> bool:
        """Check if item's temporal validity falls within request temporal bounds."""
        dt_from = _parse_iso_datetime(valid_from)
        dt_to = _parse_iso_datetime(valid_to)

        if request.start_date and dt_to and dt_to < request.start_date:
            return False
        if request.end_date and dt_from and dt_from > request.end_date:
            return False
        if request.as_of_date:
            if dt_from and dt_from > request.as_of_date:
                return False
            if dt_to and dt_to < request.as_of_date:
                return False
        if request.recent_days is not None:
            now = request.requested_at or datetime.now(UTC)
            recent_cutoff = now.replace(tzinfo=UTC) if not now.tzinfo else now
            cutoff = recent_cutoff.timestamp() - (request.recent_days * 86400)
            if dt_to and dt_to.timestamp() < cutoff:
                return False

        return True

    async def assemble_context(
        self,
        request: ContextRequest,
    ) -> ContextPackage:
        """Filter World Model state and construct an evidence-weighted context package.

        Performs:
        1. Seed entity identification & multi-hop graph expansion (1-hop & 2-hop).
        2. Evidence weighting and grounding accumulation.
        3. Temporal filtering and exponential recency decay.
        4. Composite relevance ranking and top-K selection.
        """
        query_norm = _normalize_token(request.query)
        logger.info(
            "context.assemble.start",
            request_id=request.id,
            intent=request.task_intent,
            query=request.query,
        )

        # -------------------------------------------------------------------
        # Step 1: Fetch all World Model state
        # -------------------------------------------------------------------
        all_people = await self._world_model.get_entities_by_type(EntityType.PERSON)
        all_projects = await self._world_model.get_entities_by_type(EntityType.PROJECT)
        all_orgs = await self._world_model.get_entities_by_type(EntityType.ORGANIZATION)
        all_decisions = await self._world_model.get_entities_by_type(EntityType.DECISION)
        all_events = await self._world_model.get_entities_by_type(EntityType.EVENT)
        all_commitments = await self._world_model.get_entities_by_type(EntityType.COMMITMENT)
        all_goals = await self._world_model.get_entities_by_type(EntityType.GOAL)

        all_entities: list[Entity] = (
            list(all_people)
            + list(all_projects)
            + list(all_orgs)
            + list(all_decisions)
            + list(all_events)
            + list(all_commitments)
            + list(all_goals)
        )

        # -------------------------------------------------------------------
        # Step 2: Seed Entity Identification & Multi-Hop Graph Traversal
        # -------------------------------------------------------------------
        entity_scores: dict[str, float] = {}
        entity_map: dict[str, Entity] = {e.id: e for e in all_entities}
        target_ids_set = set(request.target_entity_ids)

        # 2a. 0-hop Seed Entities
        for e in all_entities:
            text_score = _compute_text_match_score(query_norm, e.name, e.aliases)
            if e.id in target_ids_set:
                text_score = max(text_score, 1.0)
            if text_score > 0.0:
                entity_scores[e.id] = text_score

        # Fallback if no direct seed matches
        if not entity_scores:
            for e in list(all_projects) + list(all_people[:5]):
                entity_scores[e.id] = 0.40

        # 2b. 1-Hop Graph Traversal
        one_hop_entity_ids: set[str] = set()
        relevant_relationships_map: dict[str, Relationship] = {}
        rel_proximity_scores: dict[str, float] = {}

        seed_ids = list(entity_scores.keys())
        for seed_id in seed_ids:
            seed_score = entity_scores[seed_id]
            seed_rels = await self._world_model.get_relationships_for_entity(seed_id)
            for r in seed_rels:
                # Temporal filtering on relationship validity
                valid_from = getattr(r.validity, "valid_from", None)
                valid_to = getattr(r.validity, "valid_to", None)
                if not self._is_within_temporal_window(valid_from, valid_to, request):
                    continue

                relevant_relationships_map[r.id] = r
                rel_conf = r.confidence.score if hasattr(r.confidence, "score") else 0.8
                rel_proximity_scores[r.id] = seed_score * rel_conf

                other_id = r.object if r.subject == seed_id else r.subject
                if other_id in entity_map and other_id not in entity_scores:
                    entity_scores[other_id] = seed_score * 0.60 * rel_conf
                    one_hop_entity_ids.add(other_id)

        # 2c. 2-Hop Graph Traversal
        for hop1_id in list(one_hop_entity_ids):
            hop1_score = entity_scores[hop1_id]
            hop1_rels = await self._world_model.get_relationships_for_entity(hop1_id)
            for r in hop1_rels:
                valid_from = getattr(r.validity, "valid_from", None)
                valid_to = getattr(r.validity, "valid_to", None)
                if not self._is_within_temporal_window(valid_from, valid_to, request):
                    continue

                if r.id not in relevant_relationships_map:
                    relevant_relationships_map[r.id] = r
                    rel_conf = r.confidence.score if hasattr(r.confidence, "score") else 0.8
                    rel_proximity_scores[r.id] = hop1_score * rel_conf

                other_id = r.object if r.subject == hop1_id else r.subject
                if other_id in entity_map and other_id not in entity_scores:
                    entity_scores[other_id] = hop1_score * 0.30 * rel_conf

        # -------------------------------------------------------------------
        # Step 3: Evidence Weighting & Retrieval
        # -------------------------------------------------------------------
        collected_evidence: list[Any] = []
        evidence_counts: dict[str, float] = {}

        for ent_id in list(entity_scores.keys()):
            ent_ev = await self._evidence_service.get_evidence_for_entity(ent_id)
            collected_evidence.extend(ent_ev)
            ev_weight = sum(ev.confidence.score if hasattr(ev, "confidence") else 0.8 for ev in ent_ev)
            evidence_counts[ent_id] = ev_weight

        for rel_id, rel in relevant_relationships_map.items():
            rel_ev = await self._evidence_service.get_evidence_for_relationship(rel_id)
            collected_evidence.extend(rel_ev)
            ev_weight = sum(ev.confidence.score if hasattr(ev, "confidence") else 0.8 for ev in rel_ev)
            evidence_counts[rel_id] = ev_weight

        # -------------------------------------------------------------------
        # Step 4: Claims Retrieval & Weighting
        # -------------------------------------------------------------------
        all_claims = await self._world_model.get_all_claims()
        relevant_claims: list[Claim] = []
        claim_scores: dict[str, float] = {}

        for cl in all_claims:
            is_matched = (
                cl.subject in entity_scores
                or cl.value in entity_scores
                or _compute_text_match_score(query_norm, cl.subject) > 0.0
                or _compute_text_match_score(query_norm, cl.value) > 0.0
                or "claim" in query_norm
            )
            if is_matched:
                cl_ev = await self._evidence_service.get_evidence_for_claim(cl.id)
                collected_evidence.extend(cl_ev)
                ev_weight = sum(ev.confidence.score if hasattr(ev, "confidence") else 0.8 for ev in cl_ev)
                cl_conf = cl.confidence.score if hasattr(cl.confidence, "score") else 0.8
                claim_scores[cl.id] = (0.5 * cl_conf) + (0.5 * min(1.0, ev_weight))
                relevant_claims.append(cl)

        # -------------------------------------------------------------------
        # Step 5: Ranking & Composite Scoring
        # -------------------------------------------------------------------
        # Rank Entities
        ranked_entities: list[tuple[Entity, float]] = []
        for ent_id, graph_score in entity_scores.items():
            ent = entity_map[ent_id]
            text_score = _compute_text_match_score(query_norm, ent.name, ent.aliases)
            ev_score = min(1.0, evidence_counts.get(ent_id, 0.0))
            recency = _compute_recency_decay(ent.updated_at, request.as_of_date)

            composite = (0.35 * text_score) + (0.35 * graph_score) + (0.20 * ev_score) + (0.10 * recency)
            ranked_entities.append((ent, composite))

        ranked_entities.sort(key=lambda x: x[1], reverse=True)
        final_entities = [e for e, _ in ranked_entities[: request.max_items]]

        # Rank Relationships
        ranked_relationships: list[tuple[Relationship, float]] = []
        for rel_id, rel in relevant_relationships_map.items():
            prox_score = rel_proximity_scores.get(rel_id, 0.5)
            ev_score = min(1.0, evidence_counts.get(rel_id, 0.0))
            rel_conf = rel.confidence.score if hasattr(rel.confidence, "score") else 0.8

            composite = (0.50 * prox_score) + (0.30 * rel_conf) + (0.20 * ev_score)
            ranked_relationships.append((rel, composite))

        ranked_relationships.sort(key=lambda x: x[1], reverse=True)
        final_relationships = [r for r, _ in ranked_relationships[: request.max_items]]

        # Rank Claims
        relevant_claims.sort(key=lambda cl: claim_scores.get(cl.id, 0.0), reverse=True)
        final_claims = relevant_claims[: request.max_items]

        # Decisions, Events, Commitments
        relevant_decisions = [d for d in all_decisions if d.id in entity_scores or "decision" in query_norm]
        relevant_commitments = [c for c in all_commitments if c.id in entity_scores or "commitment" in query_norm]
        relevant_events = [ev for ev in all_events if ev.id in entity_scores or "event" in query_norm]

        # -------------------------------------------------------------------
        # Step 6: Recent State Changes
        # -------------------------------------------------------------------
        recent_changes = await self._world_model.get_state_changes()

        # -------------------------------------------------------------------
        # Step 7: Assemble ContextPackage
        # -------------------------------------------------------------------
        summary_text = (
            f"Evidence-weighted context package assembled for '{request.query}'. "
            f"Traversed graph up to 2-hops: ranked {len(final_entities)} entities, "
            f"{len(final_relationships)} relationships, {len(final_claims)} claims, "
            f"and {len(collected_evidence)} supporting evidence records."
        )

        package = ContextPackage(
            request_id=request.id,
            purpose=request.purpose,
            entities=final_entities,
            relationships=final_relationships,
            claims=final_claims,
            decisions=relevant_decisions[: request.max_items],
            events=relevant_events[: request.max_items],
            commitments=relevant_commitments[: request.max_items],
            evidence=collected_evidence,
            state_changes=recent_changes[-10:],
            summary=summary_text,
        )

        logger.info(
            "context.assemble.complete",
            request_id=request.id,
            entities_count=len(package.entities),
            rels_count=len(package.relationships),
            claims_count=len(package.claims),
            evidence_count=len(package.evidence),
        )
        return package
