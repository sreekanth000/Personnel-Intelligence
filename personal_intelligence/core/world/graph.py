"""
SQLite-backed Entity Graph Store for Personal Intelligence Knowledge Graph.

Maintains nodes (entities, people, projects, goals, events) and typed directed edges
(relationships, commitments, constraints, associations) with alias resolution and multi-hop traversal.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from personal_intelligence.core.events.models import ensure_timezone_aware, format_iso8601
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class EntityNode:
    """Represents a node in the Personal Knowledge Graph."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    entity_type: str = "concept"  # e.g. 'person', 'project', 'goal', 'event', 'location', 'concept'
    aliases: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.created_at = ensure_timezone_aware(self.created_at, "EntityNode created_at")
        self.updated_at = ensure_timezone_aware(self.updated_at, "EntityNode updated_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "entity_type": self.entity_type,
            "aliases": self.aliases,
            "metadata": self.metadata,
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
            entity_type=data.get("entity_type", "concept"),
            aliases=aliases,
            metadata=meta,
            created_at=ensure_timezone_aware(data.get("created_at", datetime.now(timezone.utc)), "created_at"),
            updated_at=ensure_timezone_aware(data.get("updated_at", datetime.now(timezone.utc)), "updated_at"),
        )


@dataclass
class EntityEdge:
    """Represents a directed relationship between two entities in the graph.

    Temporal Validity (Blueprint §7)
    --------------------------------
    - valid_from: When this relationship became true (defaults to created_at).
    - valid_to:   When this relationship ended (None = still active).
    - status:     'active' or 'ended'.

    This allows the system to answer historical queries correctly without
    treating past relationships as permanently true.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str = ""
    target_id: str = ""
    relationship: str = "associated_with"  # e.g. 'owns', 'attends', 'has_goal', 'blocks', 'pertains_to'
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    status: str = "active"  # 'active' or 'ended'

    def __post_init__(self) -> None:
        self.created_at = ensure_timezone_aware(self.created_at, "EntityEdge created_at")
        if self.valid_from is not None:
            self.valid_from = ensure_timezone_aware(self.valid_from, "EntityEdge valid_from")
        else:
            self.valid_from = self.created_at
        if self.valid_to is not None:
            self.valid_to = ensure_timezone_aware(self.valid_to, "EntityEdge valid_to")
        if self.status not in ("active", "ended"):
            self.status = "active"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship": self.relationship,
            "weight": self.weight,
            "metadata": self.metadata,
            "created_at": format_iso8601(self.created_at),
            "valid_from": format_iso8601(self.valid_from) if self.valid_from else None,
            "valid_to": format_iso8601(self.valid_to) if self.valid_to else None,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityEdge":
        meta = data.get("metadata", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        vf = data.get("valid_from")
        vt = data.get("valid_to")
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            source_id=data.get("source_id", ""),
            target_id=data.get("target_id", ""),
            relationship=data.get("relationship", "associated_with"),
            weight=float(data.get("weight", 1.0)),
            metadata=meta,
            created_at=ensure_timezone_aware(data.get("created_at", datetime.now(timezone.utc)), "created_at"),
            valid_from=ensure_timezone_aware(vf, "valid_from") if vf else None,
            valid_to=ensure_timezone_aware(vt, "valid_to") if vt else None,
            status=str(data.get("status", "active")),
        )


class EntityRelationshipStore:
    """
    SQLite-backed Temporal Entity Relationship Store for Personal Intelligence.
    
    Maintains entity nodes and temporal relationship edges with alias resolution
    and multi-hop traversal purely in relational SQLite without external graph infrastructure.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()

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

    def find_nodes_by_type(self, entity_type: str) -> List[EntityNode]:
        """Retrieves all entity nodes matching the given entity_type."""
        conn = self.db_manager.get_connection()
        try:
            rows = conn.execute("SELECT * FROM entity_nodes WHERE entity_type = ?", (entity_type,)).fetchall()
            return [EntityNode.from_dict(dict(r)) for r in rows]
        finally:
            conn.close()

    def resolve_entity(self, name_or_alias: str) -> Optional[EntityNode]:
        """Resolves an entity by name or alias string (e.g. 'me', 'Sreekanth', 'user@company.com')."""
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

    def add_edge(self, edge: EntityEdge) -> EntityEdge:
        """Inserts a directed relationship edge between two entity nodes."""
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

    def get_neighbors(
        self, node_id: str, depth: int = 1, include_ended: bool = False
    ) -> List[Tuple[EntityNode, str, EntityNode]]:
        """Returns connected triples (SourceNode, Relationship, TargetNode) up to given hop depth.

        Parameters
        ----------
        include_ended : bool
            If False (default), only returns relationships with status='active'.
            Set to True to include historically ended relationships.
        """
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
                    s_node = EntityNode(
                        id=d["s_id"], name=d["s_name"], entity_type=d["s_type"],
                        aliases=json.loads(d.get("s_aliases", "[]")), metadata=json.loads(d.get("s_meta", "{}"))
                    )
                    t_node = EntityNode(
                        id=d["t_id"], name=d["t_name"], entity_type=d["t_type"],
                        aliases=json.loads(d.get("t_aliases", "[]")), metadata=json.loads(d.get("t_meta", "{}"))
                    )
                    rel = d["relationship"]
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


    def record_commitment(
        self,
        commitment: Any,
        user_id: str = "user_primary",
        project_id: Optional[str] = None,
        meeting_id: Optional[str] = None,
    ) -> Any:
        """
        Stores a commitment as an entity node (entity_type='commitment') and creates typed relationship edges:
          USER -> owns -> COMMITMENT
          COMMITMENT -> supports -> GOAL (if goal_id specified)
          COMMITMENT -> concerns -> PROJECT (if project_id specified)
          COMMITMENT -> associated_with -> MEETING (if meeting_id specified)
        """
        # Ensure user node exists
        self.add_node(EntityNode(id=user_id, name="User", entity_type="person"))

        # Commitment node
        meta = commitment.to_dict() if hasattr(commitment, "to_dict") else dict(commitment)
        c_id = getattr(commitment, "id", meta.get("id", str(uuid.uuid4())))
        c_name = getattr(commitment, "name", meta.get("name", meta.get("description", "Commitment")))

        node = EntityNode(
            id=c_id,
            name=c_name,
            entity_type="commitment",
            metadata=meta,
        )
        self.add_node(node)

        # Edge: USER -> owns -> COMMITMENT
        self.add_edge(EntityEdge(
            source_id=user_id,
            target_id=c_id,
            relationship="owns",
            metadata={"source": "commitment_creation"},
        ))

        # Edge: COMMITMENT -> supports -> GOAL
        goal_id = getattr(commitment, "goal_id", meta.get("goal_id"))
        if goal_id:
            self.add_node(EntityNode(id=goal_id, name=f"Goal {goal_id}", entity_type="goal"))
            self.add_edge(EntityEdge(
                source_id=c_id,
                target_id=goal_id,
                relationship="supports",
                metadata={"source": "goal_link"},
            ))

        # Edge: COMMITMENT -> concerns -> PROJECT
        if project_id:
            self.add_node(EntityNode(id=project_id, name=f"Project {project_id}", entity_type="project"))
            self.add_edge(EntityEdge(
                source_id=c_id,
                target_id=project_id,
                relationship="concerns",
            ))

        # Edge: COMMITMENT -> associated_with -> MEETING
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
        nodes = self.find_nodes_by_type("commitment")
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
        """
        Updates commitment status derived strictly from verified observations or explicit user actions.
        Hermes inference must NOT silently change commitment status.
        """
        node = self.get_node(commitment_id)
        if node is None or node.entity_type != "commitment":
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
EntityGraphStore = EntityRelationshipStore
TemporalEntityRelationshipModel = EntityRelationshipStore
