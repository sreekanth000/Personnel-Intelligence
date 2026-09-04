"""
SQLite-backed Context Graph for Personal Intelligence.

ARCHITECTURAL DEFINITION:
Personal World Model answers:
    "What do we currently know about this person's world?"
Context Graph answers:
    "How are the relevant things in that world connected?"

Context Graph provides the connective relational substrate:
- relationships (extensible generic relationship model with recommended archetypes: RELATED_TO, INVOLVES, AFFECTS, DEPENDS_ON, SUPPORTS, CONFLICTS_WITH, PRECEDES, FOLLOWS, OCCURS_AT, PART_OF, DERIVED_FROM, EVIDENCE_FOR, MENTIONED_IN)
- temporal links (valid_from, valid_until, what_was_true_at, what_changed_since)
- evidence links (supporting observations and provenance)
- relevance links (multi-hop neighborhood discovery)
- contextual traversal (bounded subgraphs for reasoning)

Strict Invariants:
- Backed strictly by SQLite tables (entity_nodes, entity_edges). Zero external graph databases.
- NOT a second memory store or separate semantic knowledge engine.
- PersonalWorldModel remains the higher-level semantic representation and semantic owner.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import re
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from personal_intelligence.core.events.models import ensure_timezone_aware, format_iso8601
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Domain-Agnostic Entity Type Validation & Canonical Recommendations
# -----------------------------------------------------------------------------

def validate_and_normalize_entity_type(val: Any) -> str:
    r"""
    Validates and normalizes an entity type.

    The architecture explicitly distinguishes 'recommended canonical types'
    from 'hard architectural restrictions'. The system is domain-agnostic and
    supports arbitrary, unforeseen entity types (e.g. 'thing', 'topic',
    'laboratory_instrument', 'financial_asset', 'satellite', etc.)
    without requiring source-code additions, subclasses, or new domain agents.

    Validation guarantees:
    - Non-empty, non-blank string representation.
    - Normalized lowercase representation.
    - Whitespace normalized to underscores.
    - Safe length: 1 to 64 characters.
    - Safe identifier: matches ^[a-z0-9_\-:\./]+$
    """
    if val is None:
        raise ValueError("entity_type cannot be None")

    if hasattr(val, "value"):
        raw_val = str(val.value)
    else:
        raw_val = str(val)

    cleaned = raw_val.strip()
    if not cleaned:
        raise ValueError("entity_type cannot be empty or blank")

    normalized = cleaned.lower()
    normalized = re.sub(r"\s+", "_", normalized)

    if len(normalized) > 64:
        raise ValueError(f"entity_type '{normalized}' exceeds maximum length of 64 characters")

    if not re.match(r"^[a-z0-9_\-:\./]+$", normalized):
        raise ValueError(
            f"entity_type '{normalized}' contains invalid characters. "
            "Must contain only alphanumeric characters, underscores, hyphens, colons, slashes, or dots."
        )

    return normalized


# -----------------------------------------------------------------------------
# Domain-Agnostic Relationship Type Validation & Canonical Recommendations
# -----------------------------------------------------------------------------

def validate_and_normalize_relationship_type(val: Any) -> str:
    r"""
    Validates and normalizes a relationship type.

    The architecture explicitly distinguishes 'recommended canonical relationships'
    from 'hard architectural restrictions'. The system is domain-agnostic and
    supports arbitrary, unforeseen relationship types (e.g. 'calibrated_with',
    'telemetry_streamed_to', 'authorized_by', 'manages', 'installed_in', etc.)
    without requiring source-code additions, subclasses, or rigid ontologies.

    Validation guarantees:
    - Non-empty, non-blank string representation.
    - Normalized lowercase representation.
    - Whitespace and hyphens normalized to underscores.
    - Safe length: 1 to 64 characters.
    - Safe identifier: matches ^[a-z0-9_\-:\./]+$
    """
    if val is None:
        raise ValueError("relationship cannot be None")

    if hasattr(val, "value"):
        raw_val = str(val.value)
    else:
        raw_val = str(val)

    cleaned = raw_val.strip()
    if not cleaned:
        raise ValueError("relationship cannot be empty or blank")

    normalized = cleaned.lower()
    normalized = re.sub(r"[\s\-]+", "_", normalized)

    if len(normalized) > 64:
        raise ValueError(f"relationship '{normalized}' exceeds maximum length of 64 characters")

    if not re.match(r"^[a-z0-9_\-:\./]+$", normalized):
        raise ValueError(
            f"relationship '{normalized}' contains invalid characters. "
            "Must contain only alphanumeric characters, underscores, hyphens, colons, slashes, or dots."
        )

    return normalized


# -----------------------------------------------------------------------------
# Canonical Relationship Types & Entity Types
# -----------------------------------------------------------------------------

class CanonicalRelationship(str, Enum):
    """
    Recommended canonical semantic relationship types for the Context Graph.

    ARCHITECTURAL PRINCIPLE:
    These are RECOMMENDED semantic relationship archetypes, NOT a closed ontology.
    Prefer generic relationships (RELATED_TO, INVOLVES, AFFECTS, DEPENDS_ON, SUPPORTS,
    CONFLICTS_WITH, PRECEDES, FOLLOWS, OCCURS_AT, PART_OF, DERIVED_FROM, EVIDENCE_FOR, MENTIONED_IN).
    Unforeseen relationships are dynamically supported without source code changes.
    """
    # Core Generic Recommendations
    RELATED_TO = "related_to"
    INVOLVES = "involves"
    AFFECTS = "affects"
    DEPENDS_ON = "depends_on"
    SUPPORTS = "supports"
    CONFLICTS_WITH = "conflicts_with"
    PRECEDES = "precedes"
    FOLLOWS = "follows"
    OCCURS_AT = "occurs_at"
    PART_OF = "part_of"
    DERIVED_FROM = "derived_from"
    EVIDENCE_FOR = "evidence_for"
    MENTIONED_IN = "mentioned_in"

    # Contextual and Structural Types (backward-compatible)
    ABOUT = "about"
    LOCATED_AT = "located_at"
    ASSOCIATED_WITH = "associated_with"
    CONNECTED_TO = "connected_to"
    BELONGS_TO = "belongs_to"
    RELEVANT_TO = "relevant_to"
    WORKS_WITH = "works_with"
    HAS_GOAL = "has_goal"
    OCCURS_DURING = "occurs_during"
    CAUSED_BY = "caused_by"
    COMMITTED_TO = "committed_to"
    BLOCKED_BY = "blocked_by"
    SUPPORTS_GOAL = "supports_goal"
    ATTENDED_BY = "attended_by"
    REPORTS_TO = "reports_to"
    COLLABORATES_WITH = "collaborates_with"
    ASSIGNED_TO = "assigned_to"
    CONTRADICTS = "contradicts"
    CORROBORATES = "corroborates"

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def _missing_(cls, value: object) -> Any:
        """
        Dynamically handles unseen relationship types so CanonicalRelationship('unseen')
        safely succeeds instead of throwing ValueError.
        """
        if isinstance(value, str):
            try:
                norm = validate_and_normalize_relationship_type(value)
                for member in cls:
                    if member.value == norm:
                        return member
                pseudo = str.__new__(cls, norm)
                pseudo._name_ = norm.upper().replace("-", "_").replace(".", "_").replace("/", "_").replace(":", "_")
                pseudo._value_ = norm
                return pseudo
            except Exception:
                return None
        return None

    @classmethod
    def list_recommended(cls) -> List[str]:
        """Returns the list of core recommended canonical relationship types."""
        return [
            cls.RELATED_TO.value,
            cls.INVOLVES.value,
            cls.AFFECTS.value,
            cls.DEPENDS_ON.value,
            cls.SUPPORTS.value,
            cls.CONFLICTS_WITH.value,
            cls.PRECEDES.value,
            cls.FOLLOWS.value,
            cls.OCCURS_AT.value,
            cls.PART_OF.value,
            cls.DERIVED_FROM.value,
            cls.EVIDENCE_FOR.value,
            cls.MENTIONED_IN.value,
        ]

    @classmethod
    def is_recommended(cls, relationship: str) -> bool:
        """Checks whether the given relationship is in the core recommended set."""
        try:
            norm = validate_and_normalize_relationship_type(relationship)
            return norm in cls.list_recommended()
        except Exception:
            return False


RECOMMENDED_RELATIONSHIP_TYPES: Set[str] = set(CanonicalRelationship.list_recommended())


class CanonicalEntityType(str, Enum):
    """
    Recommended canonical semantic entity types for nodes in the Context Graph.

    ARCHITECTURAL PRINCIPLE:
    These are a small semantic core of RECOMMENDED archetypes, NOT a closed taxonomy.
    The minimal semantic core consists of:
    PERSON, ORGANIZATION, PLACE, DOCUMENT, PROJECT, GOAL, COMMITMENT, ACTIVITY, EVENT, SITUATION, THING, TOPIC.

    Types such as MEETING, DEVICE, OBSERVATION, or CONCEPT do NOT require dedicated entity
    subclasses merely to be represented. Arbitrary unseen entity types (e.g. 'submersible_vehicle',
    'hydrothermal_vent', 'benthic_sensor_array', 'financial_holding', etc.) are first-class
    and fully supported without source-code additions, subclasses, or new domain agents.
    """
    # Minimal Semantic Core (Recommended Archetypes)
    PERSON = "person"
    ORGANIZATION = "organization"
    PLACE = "place"
    DOCUMENT = "document"
    PROJECT = "project"
    GOAL = "goal"
    COMMITMENT = "commitment"
    ACTIVITY = "activity"
    EVENT = "event"
    SITUATION = "situation"
    THING = "thing"
    TOPIC = "topic"

    # Backward-compatible common types (represented without dedicated subclasses)
    MEETING = "meeting"
    DEVICE = "device"
    OBSERVATION = "observation"
    CONCEPT = "concept"
    INFERRED_STATE = "inferred_state"

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def _missing_(cls, value: object) -> Any:
        """
        Allows dynamic resolution of unseen entity types so CanonicalEntityType('unseen')
        safely succeeds instead of throwing ValueError.
        """
        if isinstance(value, str):
            try:
                norm = validate_and_normalize_entity_type(value)
                for member in cls:
                    if member.value == norm:
                        return member
                pseudo = str.__new__(cls, norm)
                pseudo._name_ = norm.upper().replace("-", "_").replace(".", "_").replace("/", "_").replace(":", "_")
                pseudo._value_ = norm
                return pseudo
            except Exception:
                return None
        return None

    @classmethod
    def list_recommended(cls) -> List[str]:
        """Returns the minimal semantic core of recommended canonical entity types."""
        return [
            cls.PERSON.value,
            cls.ORGANIZATION.value,
            cls.PLACE.value,
            cls.DOCUMENT.value,
            cls.PROJECT.value,
            cls.GOAL.value,
            cls.COMMITMENT.value,
            cls.ACTIVITY.value,
            cls.EVENT.value,
            cls.SITUATION.value,
            cls.THING.value,
            cls.TOPIC.value,
        ]

    @classmethod
    def is_recommended(cls, entity_type: str) -> bool:
        """Checks whether the given entity type is in the minimal recommended set."""
        try:
            norm = validate_and_normalize_entity_type(entity_type)
            return norm in cls.list_recommended()
        except Exception:
            return False


RECOMMENDED_ENTITY_TYPES: Set[str] = set(CanonicalEntityType.list_recommended())


# -----------------------------------------------------------------------------
# Graph Node & Edge Data Structures
# -----------------------------------------------------------------------------

@dataclass
class EntityNode:
    """Represents a node in the Personal Context Graph."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    entity_type: str = CanonicalEntityType.CONCEPT.value
    aliases: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    epistemic_type: str = "observed"  # 'observed', 'inferred', 'predicted'
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.entity_type = validate_and_normalize_entity_type(self.entity_type)
        self.created_at = ensure_timezone_aware(self.created_at, "EntityNode created_at")
        self.updated_at = ensure_timezone_aware(self.updated_at, "EntityNode updated_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "entity_type": self.entity_type,
            "aliases": self.aliases,
            "metadata": self.metadata,
            "epistemic_type": self.epistemic_type,
            "created_at": format_iso8601(self.created_at),
            "updated_at": format_iso8601(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityNode":
        aliases = data.get("aliases") or data.get("aliases_json", [])
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except Exception:
                aliases = [aliases]
        meta = data.get("metadata") or data.get("metadata_json", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            entity_type=data.get("entity_type", CanonicalEntityType.CONCEPT.value),
            aliases=aliases,
            metadata=meta,
            epistemic_type=data.get("epistemic_type", "observed"),
            created_at=ensure_timezone_aware(data.get("created_at", datetime.now(timezone.utc)), "created_at"),
            updated_at=ensure_timezone_aware(data.get("updated_at", datetime.now(timezone.utc)), "updated_at"),
        )


@dataclass
class EntityEdge:
    """
    Represents a directed relationship between two entities in the Context Graph.
    Preserves temporal validity (valid_from / valid_to), epistemic status, and provenance.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str = ""
    target_id: str = ""
    relationship: str = CanonicalRelationship.RELATED_TO.value
    weight: float = 1.0
    epistemic_type: str = "observed"  # 'observed', 'inferred', 'predicted'
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    status: str = "active"  # 'active' or 'ended'

    def __post_init__(self) -> None:
        self.relationship = validate_and_normalize_relationship_type(self.relationship)
        self.created_at = ensure_timezone_aware(self.created_at, "EntityEdge created_at")
        if self.valid_from is not None:
            self.valid_from = ensure_timezone_aware(self.valid_from, "EntityEdge valid_from")
        else:
            self.valid_from = self.created_at
        if self.valid_to is not None:
            self.valid_to = ensure_timezone_aware(self.valid_to, "EntityEdge valid_to")
        valid_statuses = ("active", "ended", "stale", "expired", "planned")
        if self.status not in valid_statuses:
            self.status = "active"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship": self.relationship,
            "weight": self.weight,
            "epistemic_type": self.epistemic_type,
            "metadata": self.metadata,
            "created_at": format_iso8601(self.created_at),
            "valid_from": format_iso8601(self.valid_from) if self.valid_from else None,
            "valid_to": format_iso8601(self.valid_to) if self.valid_to else None,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityEdge":
        meta = data.get("metadata") or data.get("metadata_json", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        vf = data.get("valid_from")
        vt = data.get("valid_to")
        epist = data.get("epistemic_type") or (meta.get("epistemic_type") if isinstance(meta, dict) else None) or "observed"
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            source_id=data.get("source_id", ""),
            target_id=data.get("target_id", ""),
            relationship=data.get("relationship", CanonicalRelationship.RELATED_TO.value),
            weight=float(data.get("weight", 1.0)),
            epistemic_type=epist,
            metadata=meta,
            created_at=ensure_timezone_aware(data.get("created_at", datetime.now(timezone.utc)), "created_at"),
            valid_from=ensure_timezone_aware(vf, "valid_from") if vf else None,
            valid_to=ensure_timezone_aware(vt, "valid_to") if vt else None,
            status=str(data.get("status", "active")),
        )


@dataclass
class BoundedContextGraph:
    """
    Structured, bounded subgraph returned for contextual reasoning.
    Does NOT dump the entire world model or full graph.
    """
    center_node_id: str
    center_entity: Optional[EntityNode] = None
    nodes: List[EntityNode] = field(default_factory=list)
    edges: List[EntityEdge] = field(default_factory=list)
    related_goals: List[Dict[str, Any]] = field(default_factory=list)
    related_situations: List[Dict[str, Any]] = field(default_factory=list)
    supporting_observations: List[Dict[str, Any]] = field(default_factory=list)
    inferred_facts: List[Dict[str, Any]] = field(default_factory=list)
    temporal_window: Optional[Dict[str, str]] = None
    provenance_chain: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def root_id(self) -> str:
        """Alias for center_node_id."""
        return self.center_node_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "center_node_id": self.center_node_id,
            "center_entity": self.center_entity.to_dict() if self.center_entity else None,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "related_goals": self.related_goals,
            "related_situations": self.related_situations,
            "supporting_observations": self.supporting_observations,
            "inferred_facts": self.inferred_facts,
            "temporal_window": self.temporal_window,
            "provenance_chain": self.provenance_chain,
        }

    def to_reasoning_prompt_context(self) -> str:
        """Renders a concise, human/LLM-readable text summary of the bounded context."""
        lines = [f"=== BOUNDED CONTEXT GRAPH (Center: {self.center_node_id}) ==="]
        if self.center_entity:
            lines.append(f"Subject Entity: {self.center_entity.name} [{self.center_entity.entity_type}]")

        if self.nodes:
            lines.append("\nConnected Entities:")
            for n in self.nodes:
                if n.id != self.center_node_id:
                    lines.append(f"  - {n.name} [{n.entity_type}] (ID: {n.id})")

        if self.edges:
            lines.append("\nRelationships:")
            for e in self.edges:
                status_str = f" [status={e.status}]" if e.status != "active" else ""
                epist_str = f" ({e.epistemic_type.upper()})" if e.epistemic_type != "observed" else ""
                lines.append(f"  - {e.source_id} --[{e.relationship}{epist_str}]--> {e.target_id}{status_str}")

        if self.related_goals:
            lines.append("\nAffected/Connected Goals:")
            for g in self.related_goals:
                lines.append(f"  - Goal: {g.get('title', g.get('name', 'Goal'))} [status={g.get('status', 'active')}]")

        if self.related_situations:
            lines.append("\nConnected Situations:")
            for s in self.related_situations:
                lines.append(f"  - Situation: {s.get('type', 'Situation')} [priority={s.get('priority', 'medium')}]")

        if self.supporting_observations:
            lines.append("\nSupporting Source Evidence:")
            for obs in self.supporting_observations:
                src = obs.get("source", "source")
                sum_text = obs.get("summary", "")
                lines.append(f"  - [{src}] {sum_text}")

        return "\n".join(lines)


# -----------------------------------------------------------------------------
# ContextGraph Engine & Store
# -----------------------------------------------------------------------------

class ContextGraph:
    """
    SQLite-backed Context Graph for Personal Intelligence.
    Maintains entities, relationships, temporal context, and bounded graph queries.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()

    # -------------------------------------------------------------------------
    # Node Operations
    # -------------------------------------------------------------------------

    def add_node(self, node: EntityNode) -> EntityNode:
        """Upserts an entity node in the knowledge graph."""
        conn = self.db_manager.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO entity_nodes (id, name, entity_type, aliases_json, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        entity_type = excluded.entity_type,
                        aliases_json = excluded.aliases_json,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        node.id,
                        node.name,
                        node.entity_type,
                        json.dumps(node.aliases),
                        json.dumps(node.metadata),
                        format_iso8601(node.created_at),
                        format_iso8601(node.updated_at),
                    ),
                )
            return node
        finally:
            conn.close()

    def upsert_entity(
        self,
        name: str,
        entity_type: str = CanonicalEntityType.CONCEPT.value,
        id: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        epistemic_type: str = "observed",
    ) -> EntityNode:
        """Convenience method to upsert or resolve an entity node."""
        e_id = id or str(uuid.uuid4())
        node = EntityNode(
            id=e_id,
            name=name,
            entity_type=entity_type,
            aliases=aliases or [],
            metadata=metadata or {},
            epistemic_type=epistemic_type,
        )
        return self.add_node(node)

    def get_node(self, node_id: str) -> Optional[EntityNode]:
        """Retrieves a node by ID."""
        conn = self.db_manager.get_connection()
        try:
            row = conn.execute("SELECT * FROM entity_nodes WHERE id = ?", (node_id,)).fetchone()
            if not row:
                return None
            return EntityNode.from_dict(dict(row))
        finally:
            conn.close()

    def get_entity(self, entity_id: str) -> Optional[EntityNode]:
        """Alias for get_node."""
        return self.get_node(entity_id)

    def find_nodes_by_type(self, entity_type: str) -> List[EntityNode]:
        """Retrieves all entity nodes matching the given entity_type."""
        norm_type = validate_and_normalize_entity_type(entity_type)
        conn = self.db_manager.get_connection()
        try:
            rows = conn.execute("SELECT * FROM entity_nodes WHERE entity_type = ?", (norm_type,)).fetchall()
            return [EntityNode.from_dict(dict(r)) for r in rows]
        finally:
            conn.close()

    def list_all_nodes(self, limit: Optional[int] = None) -> List[EntityNode]:
        """Retrieves all entity nodes in the Context Graph across all entity types."""
        conn = self.db_manager.get_connection()
        try:
            if limit:
                rows = conn.execute("SELECT * FROM entity_nodes LIMIT ?", (limit,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM entity_nodes").fetchall()
            return [EntityNode.from_dict(dict(r)) for r in rows]
        finally:
            conn.close()

    def resolve_entity(self, name_or_alias: str) -> Optional[EntityNode]:
        """Resolves an entity by name or alias string."""
        if not name_or_alias:
            return None
        target = name_or_alias.lower().strip()
        conn = self.db_manager.get_connection()
        try:
            rows = conn.execute("SELECT * FROM entity_nodes").fetchall()
            for r in rows:
                d = dict(r)
                if d.get("name", "").lower() == target:
                    return EntityNode.from_dict(d)
                aliases = json.loads(d.get("aliases_json", "[]"))
                if any(a.lower() == target for a in aliases):
                    return EntityNode.from_dict(d)
            return None
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Edge / Relationship Operations
    # -------------------------------------------------------------------------

    def add_edge(self, edge: EntityEdge) -> EntityEdge:
        """Inserts a directed relationship edge between two entity nodes."""
        # Ensure source and target stub nodes exist so FOREIGN KEY constraints always succeed
        for node_id in (edge.source_id, edge.target_id):
            if node_id and not self.get_node(node_id):
                self.add_node(EntityNode(id=node_id, name=node_id, entity_type=CanonicalEntityType.CONCEPT.value))

        conn = self.db_manager.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO entity_edges (id, source_id, target_id, relationship, weight, metadata_json, created_at, valid_from, valid_to, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        relationship = excluded.relationship,
                        weight = excluded.weight,
                        metadata_json = excluded.metadata_json,
                        valid_from = excluded.valid_from,
                        valid_to = excluded.valid_to,
                        status = excluded.status
                    """,
                    (
                        edge.id,
                        edge.source_id,
                        edge.target_id,
                        edge.relationship,
                        edge.weight,
                        json.dumps(edge.metadata),
                        format_iso8601(edge.created_at),
                        format_iso8601(edge.valid_from) if edge.valid_from else None,
                        format_iso8601(edge.valid_to) if edge.valid_to else None,
                        edge.status,
                    ),
                )
            return edge
        finally:
            conn.close()

    def connect(
        self,
        source_id: str,
        target_id: str,
        relationship: Union[CanonicalRelationship, str],
        weight: float = 1.0,
        epistemic_type: str = "observed",
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        provenance: Optional[Dict[str, Any]] = None,
        status: str = "active",
        edge_id: Optional[str] = None,
    ) -> EntityEdge:
        """Connects two entities with a typed, provenance-preserving edge. Idempotent on identical edges."""
        rel_str = validate_and_normalize_relationship_type(relationship)
        meta = dict(metadata or {})
        if provenance:
            meta["provenance"] = provenance
        meta["epistemic_type"] = epistemic_type

        # Check existing edge for idempotency (same source, target, relationship, and status)
        existing = self.get_edges(node_id=source_id, active_only=(status == "active"), include_ended=True)
        for e in existing:
            if (
                e.source_id == source_id
                and e.target_id == target_id
                and e.relationship.lower() == rel_str.lower()
                and e.status == status
            ):
                updated = False
                if meta:
                    e.metadata.update(meta)
                    updated = True
                if weight != e.weight:
                    e.weight = weight
                    updated = True
                if valid_to and valid_to != e.valid_to:
                    e.valid_to = valid_to
                    updated = True
                if updated:
                    self.add_edge(e)
                return e

        edge = EntityEdge(
            id=edge_id or str(uuid.uuid4()),
            source_id=source_id,
            target_id=target_id,
            relationship=rel_str,
            weight=weight,
            epistemic_type=epistemic_type,
            metadata=meta,
            valid_from=valid_from,
            valid_to=valid_to,
            status=status,
        )
        return self.add_edge(edge)

    def end_edge(self, edge_id: str, ended_at: Optional[datetime] = None) -> bool:
        """Marks a relationship edge as ended by setting valid_to and status='ended'."""
        end_time = format_iso8601(ensure_timezone_aware(
            ended_at or datetime.now(timezone.utc), "ended_at"
        ))
        conn = self.db_manager.get_connection()
        try:
            with conn:
                result = conn.execute(
                    "UPDATE entity_edges SET valid_to = ?, status = 'ended' WHERE id = ?",
                    (end_time, edge_id),
                )
            return result.rowcount > 0
        finally:
            conn.close()

    def get_edges(
        self,
        node_id: Optional[str] = None,
        relationship: Optional[Union[CanonicalRelationship, str]] = None,
        active_only: bool = True,
        at_time: Optional[datetime] = None,
        include_ended: bool = False,
    ) -> List[EntityEdge]:
        """Queries edges with optional filtering by node, relationship, and temporal validity."""
        clauses = []
        params: List[Any] = []

        if node_id:
            clauses.append("(source_id = ? OR target_id = ?)")
            params.extend([node_id, node_id])

        if relationship:
            norm_rel = validate_and_normalize_relationship_type(relationship)
            clauses.append("LOWER(relationship) = LOWER(?)")
            params.append(norm_rel)

        if not include_ended and active_only:
            clauses.append("status = 'active'")

        if at_time:
            at_iso = format_iso8601(ensure_timezone_aware(at_time, "at_time"))
            clauses.append("(valid_from IS NULL OR valid_from <= ?)")
            params.append(at_iso)
            clauses.append("(valid_to IS NULL OR valid_to >= ?)")
            params.append(at_iso)

        where_stmt = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM entity_edges {where_stmt} ORDER BY created_at DESC"

        conn = self.db_manager.get_connection()
        try:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [EntityEdge.from_dict(dict(r)) for r in rows]
        finally:
            conn.close()

    def get_neighbors(
        self,
        node_id: str,
        depth: int = 1,
        include_ended: bool = False,
        relationship: Optional[Union[CanonicalRelationship, str]] = None,
    ) -> List[Tuple[EntityNode, str, EntityNode]]:
        """Returns connected triples (SourceNode, Relationship, TargetNode) up to given hop depth."""
        norm_rel = validate_and_normalize_relationship_type(relationship) if relationship else None
        conn = self.db_manager.get_connection()
        try:
            visited_node_ids: Set[str] = {node_id}
            current_frontier: Set[str] = {node_id}
            results: List[Tuple[EntityNode, str, EntityNode]] = []

            status_clause = "" if include_ended else "AND e.status = 'active'"

            for _ in range(depth):
                if not current_frontier:
                    break
                next_frontier: Set[str] = set()
                placeholders = ",".join(["?"] * len(current_frontier))
                query = f"""
                    SELECT e.*, n1.id as s_id, n1.name as s_name, n1.entity_type as s_type, n1.aliases_json as s_aliases, n1.metadata_json as s_meta, n1.created_at as s_created, n1.updated_at as s_updated,
                           n2.id as t_id, n2.name as t_name, n2.entity_type as t_type, n2.aliases_json as t_aliases, n2.metadata_json as t_meta, n2.created_at as t_created, n2.updated_at as t_updated
                    FROM entity_edges e
                    JOIN entity_nodes n1 ON e.source_id = n1.id
                    JOIN entity_nodes n2 ON e.target_id = n2.id
                    WHERE (e.source_id IN ({placeholders}) OR e.target_id IN ({placeholders})) {status_clause}
                """
                args = list(current_frontier) + list(current_frontier)
                rows = conn.execute(query, args).fetchall()

                for r in rows:
                    d = dict(r)
                    rel = d["relationship"]
                    if norm_rel and rel.lower() != norm_rel:
                        continue
                    s_node = EntityNode(
                        id=d["s_id"], name=d["s_name"], entity_type=d["s_type"],
                        aliases=json.loads(d.get("s_aliases", "[]")), metadata=json.loads(d.get("s_meta", "{}"))
                    )
                    t_node = EntityNode(
                        id=d["t_id"], name=d["t_name"], entity_type=d["t_type"],
                        aliases=json.loads(d.get("t_aliases", "[]")), metadata=json.loads(d.get("t_meta", "{}"))
                    )
                    results.append((s_node, rel, t_node))

                    if s_node.id not in visited_node_ids:
                        visited_node_ids.add(s_node.id)
                        next_frontier.add(s_node.id)
                    if t_node.id not in visited_node_ids:
                        visited_node_ids.add(t_node.id)
                        next_frontier.add(t_node.id)

                current_frontier = next_frontier

            return results
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Context Graph Capability & Discovery APIs
    # -------------------------------------------------------------------------

    def get_related_entities(
        self,
        entity_id: str,
        relationship: Optional[Union[CanonicalRelationship, str]] = None,
        depth: int = 1,
        active_only: bool = True,
    ) -> List[EntityNode]:
        """
        Retrieves all distinct entities connected to the specified entity within `depth` hops.
        Optionally filtered by relationship type and active status.
        Excludes the source entity itself.
        """
        rel_filter = validate_and_normalize_relationship_type(relationship) if relationship else None
        neighbors = self.get_neighbors(
            node_id=entity_id,
            depth=depth,
            include_ended=not active_only,
            relationship=rel_filter,
        )
        found_entities: Dict[str, EntityNode] = {}
        for s_node, rel_name, t_node in neighbors:
            if rel_filter and rel_name.lower() != rel_filter:
                continue
            if s_node.id != entity_id and s_node.id not in found_entities:
                found_entities[s_node.id] = s_node
            if t_node.id != entity_id and t_node.id not in found_entities:
                found_entities[t_node.id] = t_node
        return list(found_entities.values())

    def get_context(
        self,
        target_id: str,
        depth: int = 1,
        time_window: Optional[Tuple[datetime, datetime]] = None,
        relevance_constraints: Optional[Dict[str, Any]] = None,
        include_inferred: bool = True,
    ) -> BoundedContextGraph:
        """
        Primary Context Graph retrieval method.
        Returns a bounded, structured subgraph around the target node.
        """
        return self.get_bounded_context(
            target_id=target_id,
            depth=depth,
            time_window=time_window,
            relevance_constraints=relevance_constraints,
            include_inferred=include_inferred,
        )

    def get_related_goals(self, target_id: str, depth: int = 2) -> List[Dict[str, Any]]:
        """
        Discovers all goals connected to target_id (situation, entity, commitment, or project).
        """
        neighbors = self.get_neighbors(node_id=target_id, depth=depth, include_ended=False)
        goal_ids: Set[str] = set()
        for s_node, rel, t_node in neighbors:
            if s_node.entity_type == CanonicalEntityType.GOAL.value:
                goal_ids.add(s_node.id)
            if t_node.entity_type == CanonicalEntityType.GOAL.value:
                goal_ids.add(t_node.id)

        edges = self.get_edges(node_id=target_id, active_only=True)
        for e in edges:
            other_id = e.target_id if e.source_id == target_id else e.source_id
            node = self.get_node(other_id)
            if node and node.entity_type == CanonicalEntityType.GOAL.value:
                goal_ids.add(node.id)

        if not goal_ids:
            return []

        conn = self.db_manager.get_connection()
        try:
            ph = ",".join(["?"] * len(goal_ids))
            rows = conn.execute(f"SELECT * FROM goals WHERE id IN ({ph})", list(goal_ids)).fetchall()
            found_ids = set()
            goals_list = []
            for r in rows:
                d = dict(r)
                found_ids.add(d["id"])
                goals_list.append(d)
            for gid in goal_ids:
                if gid not in found_ids:
                    node = self.get_node(gid)
                    if node:
                        goals_list.append({
                            "id": node.id,
                            "name": node.name,
                            "title": node.name,
                            "description": node.metadata.get("description", ""),
                            "priority": node.metadata.get("priority", "medium"),
                            "status": node.metadata.get("status", "active"),
                        })
            return goals_list
        finally:
            conn.close()

    def get_related_situations(self, entity_id: str, depth: int = 2) -> List[Dict[str, Any]]:
        """
        Discovers all situations connected to entity_id (person, goal, place, activity).
        """
        neighbors = self.get_neighbors(node_id=entity_id, depth=depth, include_ended=False)
        sit_ids: Set[str] = set()
        for s_node, rel, t_node in neighbors:
            if s_node.entity_type == CanonicalEntityType.SITUATION.value:
                sit_ids.add(s_node.id)
            if t_node.entity_type == CanonicalEntityType.SITUATION.value:
                sit_ids.add(t_node.id)

        edges = self.get_edges(node_id=entity_id, active_only=True)
        for e in edges:
            other_id = e.target_id if e.source_id == entity_id else e.source_id
            node = self.get_node(other_id)
            if node and node.entity_type == CanonicalEntityType.SITUATION.value:
                sit_ids.add(node.id)

        if not sit_ids:
            return []

        conn = self.db_manager.get_connection()
        try:
            ph = ",".join(["?"] * len(sit_ids))
            rows = conn.execute(f"SELECT * FROM situations WHERE id IN ({ph})", list(sit_ids)).fetchall()
            found_ids = set()
            sits_list = []
            for r in rows:
                d = dict(r)
                found_ids.add(d["id"])
                sits_list.append(d)
            for sid in sit_ids:
                if sid not in found_ids:
                    node = self.get_node(sid)
                    if node:
                        sits_list.append({
                            "id": node.id,
                            "type": node.metadata.get("situation_type", node.entity_type),
                            "priority": node.metadata.get("priority", "medium"),
                            "status": node.metadata.get("status", "open"),
                            "context": node.metadata,
                        })
            return sits_list
        finally:
            conn.close()

    def get_supporting_evidence(self, target_id: str) -> List[Dict[str, Any]]:
        """
        Discovers supporting observations and evidence records linked to a situation or entity.
        Pulls observation records from the EventStore (event_log).
        """
        evidence_ids: Set[str] = set()

        conn = self.db_manager.get_connection()
        try:
            sit_row = conn.execute("SELECT evidence_json FROM situations WHERE id = ?", (target_id,)).fetchone()
            if sit_row and sit_row["evidence_json"]:
                try:
                    ev_list = json.loads(sit_row["evidence_json"])
                    if isinstance(ev_list, list):
                        for ev in ev_list:
                            clean_id = str(ev).replace("event:", "").strip()
                            evidence_ids.add(clean_id)
                except Exception:
                    pass
        finally:
            conn.close()

        edges = self.get_edges(node_id=target_id, active_only=True)
        for e in edges:
            rel_norm = e.relationship.lower()
            if rel_norm in ("derived_from", "evidence_for", "supports", "about", "involves"):
                other_id = e.target_id if e.source_id == target_id else e.source_id
                node = self.get_node(other_id)
                if node and node.entity_type == CanonicalEntityType.OBSERVATION.value:
                    evidence_ids.add(node.id)
                elif "event:" in other_id:
                    evidence_ids.add(other_id.replace("event:", ""))

        if not evidence_ids:
            return []

        conn = self.db_manager.get_connection()
        try:
            ph = ",".join(["?"] * len(evidence_ids))
            rows = conn.execute(f"SELECT * FROM event_log WHERE id IN ({ph})", list(evidence_ids)).fetchall()
            found_ids = set()
            evidence_items = []
            for r in rows:
                d = dict(r)
                found_ids.add(d["id"])
                payload = json.loads(d.get("payload_json") or "{}")
                prov = json.loads(d.get("provenance_json") or "{}") if d.get("provenance_json") else None
                evidence_items.append({
                    "id": d["id"],
                    "source": d["source"],
                    "event_type": d["event_type"],
                    "event_time": d["event_time"],
                    "summary": payload.get("summary") or payload.get("title") or d["event_type"],
                    "payload": payload,
                    "provenance": prov,
                })

            for eid in evidence_ids:
                if eid not in found_ids:
                    node = self.get_node(eid)
                    if node:
                        ts_str = node.created_at.isoformat() if hasattr(node.created_at, "isoformat") else str(node.created_at)
                        evidence_items.append({
                            "id": node.id,
                            "source": node.metadata.get("source", "graph"),
                            "event_type": node.entity_type,
                            "event_time": node.metadata.get("timestamp", ts_str),
                            "summary": node.name,
                            "payload": node.metadata,
                            "provenance": node.metadata.get("provenance"),
                        })
            return evidence_items
        finally:
            conn.close()

    def get_temporal_context(
        self, entity_id: str, as_of: Optional[datetime] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Distinguishes relationships and context by temporal horizon:
        - currently_relevant: active relationships valid at as_of
        - historically_relevant: relationships that were valid before as_of and ended
        - expired_or_stale: unreinforced or expired relationships
        - future_or_planned: relationships planned or valid in the future
        """
        ref_time = ensure_timezone_aware(as_of or datetime.now(timezone.utc), "as_of")
        edges = self.get_edges(node_id=entity_id, active_only=False, include_ended=True)

        result: Dict[str, List[Dict[str, Any]]] = {
            "currently_relevant": [],
            "historically_relevant": [],
            "expired_or_stale": [],
            "future_or_planned": [],
        }

        for edge in edges:
            d = edge.to_dict()
            status = edge.status.lower()
            vf = edge.valid_from
            vt = edge.valid_to

            if status in ("stale", "expired"):
                result["expired_or_stale"].append(d)
            elif status == "planned" or (vf is not None and vf > ref_time):
                result["future_or_planned"].append(d)
            elif status == "ended" or (vt is not None and vt < ref_time):
                result["historically_relevant"].append(d)
            else:
                result["currently_relevant"].append(d)

        # Convenient aliases for callers
        result["current"] = result["currently_relevant"]
        result["historical"] = result["historically_relevant"]

        return result

    def find_relevant_context(
        self,
        situation_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Answers 'What is relevant to this situation / entity / goal?'
        Returns connected entities, related goals, related situations, supporting evidence, and temporal context.
        """
        center_id = situation_id or entity_id or goal_id
        if not center_id:
            return {"error": "Must specify situation_id, entity_id, or goal_id."}

        bounded = self.get_bounded_context(target_id=center_id, depth=2)
        related_entities = [n.to_dict() for n in bounded.nodes if n.id != center_id][:limit]
        related_goals = self.get_related_goals(target_id=center_id)[:limit]
        related_situations = self.get_related_situations(entity_id=center_id)[:limit]
        evidence = self.get_supporting_evidence(target_id=center_id)[:limit]
        temporal = self.get_temporal_context(entity_id=center_id)

        return {
            "target_id": center_id,
            "center_node": bounded.center_entity.to_dict() if bounded.center_entity else None,
            "related_entities": related_entities,
            "related_goals": related_goals,
            "related_situations": related_situations,
            "supporting_evidence": evidence,
            "temporal_context": temporal,
            "provenance_chain": bounded.provenance_chain,
        }

    # -------------------------------------------------------------------------
    # Bounded Context Retrieval
    # -------------------------------------------------------------------------

    def get_bounded_context(
        self,
        target_id: str,
        depth: int = 1,
        time_window: Optional[Tuple[datetime, datetime]] = None,
        relevance_constraints: Optional[Dict[str, Any]] = None,
        include_inferred: bool = True,
    ) -> BoundedContextGraph:
        """
        Retrieves a bounded subgraph around a subject, event, situation, goal, or entity.
        Does NOT dump the whole graph.
        """
        center_node = self.get_node(target_id)
        bounded = BoundedContextGraph(
            center_node_id=target_id,
            center_entity=center_node,
        )

        visited_node_ids: Set[str] = {target_id}
        collected_nodes: Dict[str, EntityNode] = {}
        if center_node:
            collected_nodes[center_node.id] = center_node

        collected_edges: List[EntityEdge] = []
        provenance_chain: List[Dict[str, Any]] = []

        # 1. Multi-hop neighbor traversal
        neighbors = self.get_neighbors(target_id, depth=depth, include_ended=False)
        for s_node, rel, t_node in neighbors:
            collected_nodes[s_node.id] = s_node
            collected_nodes[t_node.id] = t_node
            visited_node_ids.add(s_node.id)
            visited_node_ids.add(t_node.id)

        # 2. Collect edges between visited nodes
        if visited_node_ids:
            edges = self.get_edges(active_only=True)
            for e in edges:
                if e.source_id in visited_node_ids and e.target_id in visited_node_ids:
                    # Filter inferred if requested
                    if not include_inferred and e.epistemic_type == "inferred":
                        continue
                    collected_edges.append(e)
                    if "provenance" in e.metadata:
                        provenance_chain.append(e.metadata["provenance"])

        bounded.nodes = list(collected_nodes.values())
        bounded.edges = collected_edges

        # 3. Pull connected Goals, Situations, and Observations via SQL
        conn = self.db_manager.get_connection()
        try:
            # Goals related directly or through edges
            goal_nodes = [n for n in bounded.nodes if n.entity_type == "goal"]
            goal_ids = [n.id for n in goal_nodes]
            if goal_ids:
                ph = ",".join(["?"] * len(goal_ids))
                g_rows = conn.execute(f"SELECT * FROM goals WHERE id IN ({ph})", goal_ids).fetchall()
                for gr in g_rows:
                    bounded.related_goals.append(dict(gr))

            # Situations related directly or through edges
            sit_nodes = [n for n in bounded.nodes if n.entity_type == "situation"]
            sit_ids = [n.id for n in sit_nodes]
            if sit_ids:
                ph = ",".join(["?"] * len(sit_ids))
                s_rows = conn.execute(f"SELECT * FROM situations WHERE id IN ({ph})", sit_ids).fetchall()
                for sr in s_rows:
                    bounded.related_situations.append(dict(sr))

            # Supporting observations
            obs_nodes = [n for n in bounded.nodes if n.entity_type == "observation"]
            obs_ids = [n.id for n in obs_nodes]
            if obs_ids:
                ph = ",".join(["?"] * len(obs_ids))
                o_rows = conn.execute(f"SELECT * FROM event_log WHERE id IN ({ph})", obs_ids).fetchall()
                for orow in o_rows:
                    od = dict(orow)
                    bounded.supporting_observations.append({
                        "id": od["id"],
                        "source": od["source"],
                        "observation_type": od["event_type"],
                        "event_time": od["event_time"],
                        "summary": json.loads(od["payload_json"]).get("summary", ""),
                        "provenance": json.loads(od["provenance_json"]) if od.get("provenance_json") else None,
                    })

            # Inferred epistemic facts linked to target_id or visited nodes
            if include_inferred and visited_node_ids:
                ph = ",".join(["?"] * len(visited_node_ids))
                f_rows = conn.execute(
                    f"SELECT * FROM epistemic_records WHERE origin_event_id IN ({ph}) OR subject IN ({ph})",
                    list(visited_node_ids) + list(visited_node_ids),
                ).fetchall()
                for fr in f_rows:
                    bounded.inferred_facts.append(dict(fr))

        finally:
            conn.close()

        # 4. Temporal bounds metadata
        if time_window:
            bounded.temporal_window = {
                "start": format_iso8601(time_window[0]),
                "end": format_iso8601(time_window[1]),
            }

        bounded.provenance_chain = provenance_chain
        return bounded

    # -------------------------------------------------------------------------
    # Temporal & Change Intelligence Queries
    # -------------------------------------------------------------------------

    def what_changed_since(
        self, since_time: datetime, entity_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Returns changes in entities and relationships since a given timestamp."""
        since_iso = format_iso8601(ensure_timezone_aware(since_time, "since_time"))
        conn = self.db_manager.get_connection()
        try:
            # 1. New or updated entities
            e_clause = "WHERE updated_at >= ?"
            e_params: List[Any] = [since_iso]
            if entity_ids:
                ph = ",".join(["?"] * len(entity_ids))
                e_clause += f" AND id IN ({ph})"
                e_params.extend(entity_ids)

            e_rows = conn.execute(f"SELECT * FROM entity_nodes {e_clause}", tuple(e_params)).fetchall()
            updated_entities = [EntityNode.from_dict(dict(r)).to_dict() for r in e_rows]

            # 2. New or ended edges
            rel_rows = conn.execute(
                "SELECT * FROM entity_edges WHERE created_at >= ? OR valid_to >= ?",
                (since_iso, since_iso),
            ).fetchall()
            updated_edges = [EntityEdge.from_dict(dict(r)).to_dict() for r in rel_rows]

            return {
                "since": since_iso,
                "updated_entities_count": len(updated_entities),
                "updated_entities": updated_entities,
                "updated_edges_count": len(updated_edges),
                "updated_edges": updated_edges,
            }
        finally:
            conn.close()

    def what_was_true_at(
        self, target_time: datetime, entity_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Answers 'What was true around this event?' by evaluating temporal validity."""
        target_iso = format_iso8601(ensure_timezone_aware(target_time, "target_time"))
        conn = self.db_manager.get_connection()
        try:
            clauses = [
                "(valid_from IS NULL OR valid_from <= ?)",
                "(valid_to IS NULL OR valid_to >= ?)",
            ]
            params: List[Any] = [target_iso, target_iso]

            if entity_id:
                clauses.append("(source_id = ? OR target_id = ?)")
                params.extend([entity_id, entity_id])

            query = f"SELECT * FROM entity_edges WHERE {' AND '.join(clauses)}"
            rows = conn.execute(query, tuple(params)).fetchall()
            active_relationships = [EntityEdge.from_dict(dict(r)).to_dict() for r in rows]

            return {
                "evaluated_at": target_iso,
                "active_relationships_count": len(active_relationships),
                "active_relationships": active_relationships,
            }
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Observation & Situation Synchronization (Without Domain Agents)
    # -------------------------------------------------------------------------

    def sync_from_observation(self, observation: Any) -> List[EntityNode]:
        """
        Synchronizes an incoming observation into the Context Graph without domain agents.
        Extracts subject, entity references, and creates generic relationship edges.
        """
        obs_id = getattr(observation, "id", None) or getattr(observation, "observation_id", str(uuid.uuid4()))
        obs_src = getattr(observation, "source", "external")
        obs_type = getattr(observation, "observation_type", getattr(observation, "event_type", "generic"))
        obs_time = getattr(observation, "timestamp", getattr(observation, "occurred_at", datetime.now(timezone.utc)))
        obs_summary = getattr(observation, "summary", f"{obs_type} from {obs_src}")
        payload = getattr(observation, "payload", getattr(observation, "structured_data", {})) or {}
        provenance = getattr(observation, "provenance", None)
        entity_refs = getattr(observation, "entity_refs", []) or []
        subject_id = getattr(observation, "subject_id", None) or "user"

        created_nodes: List[EntityNode] = []

        # 1. Observation Node
        obs_node = EntityNode(
            id=obs_id,
            name=obs_summary[:60] if obs_summary else f"Observation {obs_id[:8]}",
            entity_type=CanonicalEntityType.OBSERVATION.value,
            metadata={"source": obs_src, "observation_type": obs_type, "provenance": provenance},
            created_at=obs_time,
            updated_at=obs_time,
        )
        self.add_node(obs_node)
        created_nodes.append(obs_node)

        # 2. Subject Node
        subj_node = self.get_node(subject_id)
        if not subj_node:
            subj_node = EntityNode(id=subject_id, name=subject_id.capitalize(), entity_type=CanonicalEntityType.PERSON.value)
            self.add_node(subj_node)
        created_nodes.append(subj_node)

        # Edge: OBSERVATION -> ABOUT -> SUBJECT
        self.connect(
            source_id=obs_id,
            target_id=subject_id,
            relationship=CanonicalRelationship.ABOUT.value,
            valid_from=obs_time,
            provenance=provenance,
        )

        # 3. Entity References from observation contract
        for eref in entity_refs:
            if not eref:
                continue
            ref_node = self.resolve_entity(eref) or self.get_node(eref)
            if not ref_node:
                ref_node = EntityNode(id=eref, name=eref, entity_type=CanonicalEntityType.CONCEPT.value)
                self.add_node(ref_node)
            created_nodes.append(ref_node)

            self.connect(
                source_id=obs_id,
                target_id=ref_node.id,
                relationship=CanonicalRelationship.INVOLVES.value,
                valid_from=obs_time,
                provenance=provenance,
            )

        # 4. Generic Payload Entity Extraction (People, Projects, Locations, Organizations)
        if isinstance(payload, dict):
            # Project reference
            if "project" in payload and isinstance(payload["project"], str):
                proj_name = payload["project"].strip()
                proj_node = self.resolve_entity(proj_name)
                if not proj_node:
                    proj_node = EntityNode(
                        id=f"proj-{proj_name.lower().replace(' ', '_')}",
                        name=proj_name,
                        entity_type=CanonicalEntityType.PROJECT.value,
                    )
                    self.add_node(proj_node)
                created_nodes.append(proj_node)
                self.connect(obs_id, proj_node.id, CanonicalRelationship.INVOLVES.value, valid_from=obs_time, provenance=provenance)

            # Person reference (sender, assignee, attendee)
            for p_key in ["person", "assignee", "sender", "organizer"]:
                if p_key in payload and isinstance(payload[p_key], str) and payload[p_key].strip():
                    p_val = payload[p_key].strip()
                    p_node = self.resolve_entity(p_val)
                    if not p_node:
                        p_node = EntityNode(
                            id=f"person-{p_val.lower().replace(' ', '_')}",
                            name=p_val,
                            entity_type=CanonicalEntityType.PERSON.value,
                            aliases=[p_val],
                        )
                        self.add_node(p_node)
                    created_nodes.append(p_node)
                    self.connect(obs_id, p_node.id, CanonicalRelationship.INVOLVES.value, valid_from=obs_time, provenance=provenance)

            # Organization reference
            if "organization" in payload or "company" in payload:
                org_val = str(payload.get("organization") or payload.get("company")).strip()
                if org_val:
                    org_node = self.resolve_entity(org_val)
                    if not org_node:
                        org_node = EntityNode(
                            id=f"org-{org_val.lower().replace(' ', '_')}",
                            name=org_val,
                            entity_type=CanonicalEntityType.ORGANIZATION.value,
                        )
                        self.add_node(org_node)
                    created_nodes.append(org_node)
                    self.connect(obs_id, org_node.id, CanonicalRelationship.INVOLVES.value, valid_from=obs_time, provenance=provenance)

            # Location reference
            if "location" in payload and isinstance(payload["location"], str):
                loc_val = payload["location"].strip()
                loc_node = self.resolve_entity(loc_val)
                if not loc_node:
                    loc_node = EntityNode(
                        id=f"place-{loc_val.lower().replace(' ', '_')}",
                        name=loc_val,
                        entity_type=CanonicalEntityType.PLACE.value,
                    )
                    self.add_node(loc_node)
                created_nodes.append(loc_node)
                self.connect(obs_id, loc_node.id, CanonicalRelationship.LOCATED_AT.value, valid_from=obs_time, provenance=provenance)

            # 5. Domain-Agnostic Entity Ingestion: support arbitrary unseen domain entities in payload
            if "entities" in payload and isinstance(payload["entities"], list):
                for ent_item in payload["entities"]:
                    if isinstance(ent_item, dict):
                        raw_name = ent_item.get("name") or ent_item.get("id") or "unnamed_entity"
                        raw_type = ent_item.get("entity_type") or ent_item.get("type") or "thing"
                        e_id = ent_item.get("id") or f"{validate_and_normalize_entity_type(raw_type)}-{raw_name.lower().replace(' ', '_')}"
                        custom_node = self.resolve_entity(raw_name) or self.get_node(e_id)
                        if not custom_node:
                            custom_node = EntityNode(
                                id=e_id,
                                name=raw_name,
                                entity_type=raw_type,
                                aliases=ent_item.get("aliases", []),
                                metadata=ent_item.get("metadata", {}),
                            )
                            self.add_node(custom_node)
                        created_nodes.append(custom_node)
                        rel_type = ent_item.get("relationship", CanonicalRelationship.INVOLVES.value)
                        self.connect(obs_id, custom_node.id, rel_type, valid_from=obs_time, provenance=provenance)

        return created_nodes

    def sync_from_situation(self, situation: Any) -> EntityNode:
        """Synchronizes an active situation into the Context Graph."""
        s_id = getattr(situation, "id", str(uuid.uuid4()))
        s_type = getattr(situation, "type", "situation")
        created_at = getattr(situation, "created_at", datetime.now(timezone.utc))
        evidence = getattr(situation, "evidence", []) or []
        related_goals = getattr(situation, "related_goals", []) or []

        sit_node = EntityNode(
            id=s_id,
            name=f"Situation: {s_type}",
            entity_type=CanonicalEntityType.SITUATION.value,
            metadata={"type": s_type, "priority": getattr(situation, "priority", "medium")},
            created_at=created_at,
        )
        self.add_node(sit_node)

        # Connect evidence observations
        for ev_id in evidence:
            self.connect(
                source_id=s_id,
                target_id=ev_id,
                relationship=CanonicalRelationship.DERIVED_FROM.value,
                valid_from=created_at,
            )

        # Connect affected goals
        for g_id in related_goals:
            self.connect(
                source_id=s_id,
                target_id=g_id,
                relationship=CanonicalRelationship.AFFECTS.value,
                valid_from=created_at,
            )

        return sit_node

    def sync_from_goal(self, goal: Any) -> EntityNode:
        """Synchronizes a user goal into the Context Graph."""
        g_id = getattr(goal, "id", str(uuid.uuid4()))
        g_title = getattr(goal, "title", getattr(goal, "name", "Goal"))
        created_at = getattr(goal, "created_at", datetime.now(timezone.utc))

        goal_node = EntityNode(
            id=g_id,
            name=g_title,
            entity_type=CanonicalEntityType.GOAL.value,
            metadata={"status": getattr(goal, "status", "active"), "priority": getattr(goal, "priority", "medium")},
            created_at=created_at,
        )
        self.add_node(goal_node)

        # Connect to User
        self.connect(
            source_id="user_primary",
            target_id=g_id,
            relationship=CanonicalRelationship.HAS_GOAL.value,
            valid_from=created_at,
        )

        return goal_node

    # -------------------------------------------------------------------------
    # Commitment Management (Preserved for compatibility)
    # -------------------------------------------------------------------------

    def record_commitment(
        self,
        commitment: Any,
        user_id: str = "user_primary",
        project_id: Optional[str] = None,
        meeting_id: Optional[str] = None,
    ) -> Any:
        """Stores a commitment as an entity node and creates typed relationship edges."""
        # Ensure user node exists
        self.add_node(EntityNode(id=user_id, name="User", entity_type=CanonicalEntityType.PERSON.value))

        meta = commitment.to_dict() if hasattr(commitment, "to_dict") else dict(commitment)
        c_id = getattr(commitment, "id", meta.get("id", str(uuid.uuid4())))
        c_name = getattr(commitment, "name", meta.get("name", meta.get("description", "Commitment")))

        node = EntityNode(
            id=c_id,
            name=c_name,
            entity_type=CanonicalEntityType.COMMITMENT.value,
            metadata=meta,
        )
        self.add_node(node)

        # USER -> owns -> COMMITMENT
        self.add_edge(EntityEdge(
            source_id=user_id,
            target_id=c_id,
            relationship="owns",
            metadata={"source": "commitment_creation"},
        ))

        # COMMITMENT -> supports -> GOAL
        goal_id = getattr(commitment, "goal_id", meta.get("goal_id"))
        if goal_id:
            self.add_node(EntityNode(id=goal_id, name=f"Goal {goal_id}", entity_type=CanonicalEntityType.GOAL.value))
            self.add_edge(EntityEdge(
                source_id=c_id,
                target_id=goal_id,
                relationship="supports",
                metadata={"source": "goal_link"},
            ))

        # COMMITMENT -> concerns -> PROJECT
        if project_id:
            self.add_node(EntityNode(id=project_id, name=f"Project {project_id}", entity_type=CanonicalEntityType.PROJECT.value))
            self.add_edge(EntityEdge(
                source_id=c_id,
                target_id=project_id,
                relationship="concerns",
            ))

        # COMMITMENT -> associated_with -> MEETING
        if meeting_id:
            self.add_node(EntityNode(id=meeting_id, name=f"Meeting {meeting_id}", entity_type="meeting"))
            self.add_edge(EntityEdge(
                source_id=c_id,
                target_id=meeting_id,
                relationship="associated_with",
            ))

        return commitment

    def get_commitments(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries commitment entities from entity_nodes."""
        nodes = self.find_nodes_by_type(CanonicalEntityType.COMMITMENT.value)
        commitments: List[Dict[str, Any]] = []
        target_status = status.strip().upper() if status else None

        for node in nodes:
            meta = dict(node.metadata)
            meta["id"] = node.id
            meta["name"] = node.name
            st = str(meta.get("status", "OPEN")).strip().upper()
            if target_status is None or st == target_status:
                commitments.append(meta)

        return commitments

    def update_commitment_status(
        self,
        commitment_id: str,
        new_status: str,
        observation_source: Optional[str] = None,
    ) -> bool:
        """Updates commitment status derived strictly from verified observations or explicit user actions."""
        node = self.get_node(commitment_id)
        if node is None or node.entity_type != CanonicalEntityType.COMMITMENT.value:
            return False

        norm_status = new_status.strip().upper()
        meta = dict(node.metadata)
        meta["status"] = norm_status
        meta["last_updated_by"] = observation_source or "observation"
        meta["updated_at"] = format_iso8601(datetime.now(timezone.utc))

        node.metadata = meta
        node.updated_at = datetime.now(timezone.utc)
        self.add_node(node)
        return True


# Backward-compatible and architectural aliases
EntityGraphStore = ContextGraph
EntityRelationshipStore = ContextGraph
TemporalEntityRelationshipModel = ContextGraph
