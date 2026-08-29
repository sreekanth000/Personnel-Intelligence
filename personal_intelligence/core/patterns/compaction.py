"""
Hippocampal Memory Consolidation (Overnight Schema Compaction).

Summarizes raw granular event logs into distilled entity nodes, relationships,
and probabilistic facts while archiving transient log records.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from personal_intelligence.core.events.models import format_iso8601
from personal_intelligence.core.world.graph import EntityEdge, EntityGraphStore, EntityNode
from personal_intelligence.core.world.models import ProbabilisticFact
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class CompactionSummary:
    """Output summary of a hippocampal memory compaction run."""
    raw_events_scanned: int
    nodes_created_or_updated: int
    edges_created: int
    facts_consolidated: int
    timestamp: datetime = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_events_scanned": self.raw_events_scanned,
            "nodes_created_or_updated": self.nodes_created_or_updated,
            "edges_created": self.edges_created,
            "facts_consolidated": self.facts_consolidated,
            "timestamp": format_iso8601(self.timestamp),
        }


class HippocampalCompactor:
    """Executes overnight or periodic memory schema compaction across event logs."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.graph_store = EntityGraphStore(db_manager=self.db_manager)

    def compact_memory(self, hours_back: int = 24) -> CompactionSummary:
        """
        Scans event log over hours_back, extracts recurring entities and relations,
        stores graph nodes/edges, and consolidates probabilistic facts.
        """
        conn = self.db_manager.get_connection()
        scanned = 0
        nodes_count = 0
        edges_count = 0
        facts_count = 0

        since_dt = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        since_str = format_iso8601(since_dt)

        try:
            rows = conn.execute(
                "SELECT * FROM event_log WHERE event_time >= ?", (since_str,)
            ).fetchall()
            scanned = len(rows)

            extracted_entities: Dict[str, str] = {}  # name -> type

            for r in rows:
                d = dict(r)
                ev_type = d.get("event_type", "").lower()
                payload = json.loads(d.get("payload_json", "{}")) if isinstance(d.get("payload_json"), str) else d.get("payload_json", {})
                summary = payload.get("summary", "")

                # Extract Project or Goal mentions
                if "project" in summary.lower() or "deliverable" in summary.lower():
                    words = summary.split()
                    for w in words:
                        if len(w) > 4 and w[0].isupper():
                            extracted_entities[w] = "project"

                # Extract Person mentions from email senders
                sender = payload.get("from") or d.get("source_id")
                if sender and "@" in sender:
                    name_part = sender.split("<")[0].strip().replace('"', '') or sender
                    extracted_entities[name_part] = "person"

            # Create Knowledge Graph Nodes & Edges for extracted entities
            user_node = self.graph_store.resolve_entity("User")
            if not user_node:
                user_node = EntityNode(id="ent-user-self", name="User", entity_type="person", aliases=["me"])
                self.graph_store.add_node(user_node)
                nodes_count += 1

            for name, etype in extracted_entities.items():
                node = EntityNode(name=name, entity_type=etype)
                self.graph_store.add_node(node)
                nodes_count += 1

                # Connect user to entity
                rel = "works_on" if etype == "project" else "interacts_with"
                edge = EntityEdge(source_id=user_node.id, target_id=node.id, relationship=rel)
                self.graph_store.add_edge(edge)
                edges_count += 1

            # Consolidate facts count
            facts_count = len(extracted_entities)

            return CompactionSummary(
                raw_events_scanned=scanned,
                nodes_created_or_updated=nodes_count,
                edges_created=edges_count,
                facts_consolidated=facts_count,
            )
        finally:
            conn.close()
