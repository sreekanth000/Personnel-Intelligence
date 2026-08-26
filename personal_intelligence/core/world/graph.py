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
from typing import Any, Dict, List, Optional, Set, Tuple
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
        aliases = data.get("aliases", [])
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except Exception:
                aliases = [aliases]
        meta = data.get("metadata", {})
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
    """Represents a directed relationship between two entities in the graph."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str = ""
    target_id: str = ""
    relationship: str = "associated_with"  # e.g. 'owns', 'attends', 'has_goal', 'blocks', 'pertains_to'
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.created_at = ensure_timezone_aware(self.created_at, "EntityEdge created_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship": self.relationship,
            "weight": self.weight,
            "metadata": self.metadata,
            "created_at": format_iso8601(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityEdge":
        meta = data.get("metadata", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            source_id=data.get("source_id", ""),
            target_id=data.get("target_id", ""),
            relationship=data.get("relationship", "associated_with"),
            weight=float(data.get("weight", 1.0)),
            metadata=meta,
            created_at=ensure_timezone_aware(data.get("created_at", datetime.now(timezone.utc)), "created_at"),
        )


class EntityGraphStore:
    """SQLite-backed Personal Knowledge Graph engine with alias resolution & multi-hop query support."""

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
                    INSERT INTO entity_edges (id, source_id, target_id, relationship, weight, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        relationship = excluded.relationship,
                        weight = excluded.weight,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        edge.id,
                        edge.source_id,
                        edge.target_id,
                        edge.relationship,
                        edge.weight,
                        json.dumps(edge.metadata),
                        format_iso8601(edge.created_at),
                    ),
                )
            return edge
        finally:
            conn.close()

    def get_neighbors(self, node_id: str, depth: int = 1) -> List[Tuple[EntityNode, str, EntityNode]]:
        """Returns connected triples (SourceNode, Relationship, TargetNode) up to given hop depth."""
        conn = self.db_manager.get_connection()
        try:
            visited_node_ids: Set[str] = {node_id}
            current_frontier: Set[str] = {node_id}
            results: List[Tuple[EntityNode, str, EntityNode]] = []

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
                    WHERE e.source_id IN ({placeholders}) OR e.target_id IN ({placeholders})
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
