"""
PersonalMemoryRetriever - Unified Deterministic Memory & Context Retrieval Engine.

Implements the V1 retrieval architecture:
1. SQLite FTS5 + sparse lexical matching
2. Structured SQL filters (source, event_type, subject_id, confidence, intervals)
3. Timeline proximity queries (temporal windowing around anchor events)
4. Entity & relationship lookup (knowledge graph nodes & temporal edges)
5. Optional semantic retrieval (escalation mechanism when structured/lexical retrieval is insufficient)

Principle:
- Do not compute embeddings for every observation merely because the system can.
- A normal situation is fully answerable using SQL, timeline windows, entity relationships, and FTS.
- Dense semantic vectors are an on-demand escalation tool.
- Strict preservation of provenance, evidence references, relevance ranking, and bounded context.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re
import sqlite3
import struct
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from personal_intelligence.core.events.models import (
    Event,
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievalItem:
    """Represents a single retrieved evidence or memory item with full provenance."""
    id: str
    source_type: str  # 'event', 'situation', 'timeline', 'entity', 'pattern', 'epistemic_record'
    source: str       # 'gmail', 'calendar', 'drive', 'filesystem', 'hermes', 'system'
    source_id: Optional[str]
    title: str
    content_text: str
    score: float
    retrieval_mode: str  # 'structured', 'timeline', 'entity_lookup', 'fts5', 'lexical', 'semantic'
    timestamp: Optional[datetime] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    evidence_references: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp:
            self.timestamp = ensure_timezone_aware(self.timestamp, "RetrievalItem timestamp")
        if self.score is not None:
            self.score = round(float(self.score), 4)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the retrieval item to a dictionary."""
        return {
            "id": self.id,
            "source_type": self.source_type,
            "source": self.source,
            "source_id": self.source_id,
            "title": self.title,
            "content_text": self.content_text,
            "score": self.score,
            "retrieval_mode": self.retrieval_mode,
            "timestamp": format_iso8601(self.timestamp) if self.timestamp else None,
            "provenance": self.provenance,
            "evidence_references": self.evidence_references,
            "metadata": self.metadata,
        }


class PersonalMemoryRetriever:
    """
    Unified Personal Memory Retriever.
    Provides fast, deterministic structured, lexical, timeline, entity, and optional semantic retrieval.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        local_store: Optional[LocalStateStore] = None,
        enable_semantic_escalation: bool = True,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.local_store = local_store or LocalStateStore(db_manager=self.db_manager)
        self.enable_semantic_escalation = enable_semantic_escalation
        self._embedder = None
        self._fts_available = None

    def _get_connection(self) -> sqlite3.Connection:
        return self.db_manager.get_connection()

    def _get_embedder(self) -> Any:
        """Lazy loader for local semantic embedder."""
        if self._embedder is None:
            from personal_intelligence.core.embeddings.vector_engine import LocalSemanticEmbedder
            self._embedder = LocalSemanticEmbedder()
        return self._embedder

    def _safe_json_loads(self, val: Any, default: Any = None) -> Any:
        """Safely parses JSON strings or returns default."""
        if val is None:
            return default if default is not None else {}
        if isinstance(val, (dict, list)):
            return val
        try:
            return json.loads(val)
        except Exception:
            return default if default is not None else {}

    # -------------------------------------------------------------------------
    # 1. Structured SQL Retrieval
    # -------------------------------------------------------------------------

    def retrieve_structured(
        self,
        sources: Optional[List[str]] = None,
        event_types: Optional[List[str]] = None,
        subject_id: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
        start_time: Optional[Union[datetime, str]] = None,
        end_time: Optional[Union[datetime, str]] = None,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> List[RetrievalItem]:
        """
        Executes fast, typed SQL queries over event_log and epistemic_records with zero embeddings.
        """
        clauses = ["1=1"]
        params: List[Any] = []

        if sources:
            norm_sources = [s.strip().lower() for s in sources if s]
            if norm_sources:
                placeholders = ",".join("?" for _ in norm_sources)
                clauses.append(f"source IN ({placeholders})")
                params.extend(norm_sources)

        if event_types:
            norm_types = [t.strip().lower() for t in event_types if t]
            if norm_types:
                placeholders = ",".join("?" for _ in norm_types)
                clauses.append(f"LOWER(event_type) IN ({placeholders})")
                params.extend(norm_types)

        if subject_id:
            clauses.append("subject_id = ?")
            params.append(subject_id)

        if source_ids:
            clean_sids = [str(sid).strip() for sid in source_ids if sid]
            if clean_sids:
                placeholders = ",".join("?" for _ in clean_sids)
                clauses.append(f"source_id IN ({placeholders})")
                params.extend(clean_sids)

        if start_time:
            st = ensure_timezone_aware(start_time, "start_time")
            clauses.append("event_time >= ?")
            params.append(format_iso8601(st))

        if end_time:
            et = ensure_timezone_aware(end_time, "end_time")
            clauses.append("event_time <= ?")
            params.append(format_iso8601(et))

        if min_confidence > 0.0:
            clauses.append("confidence >= ?")
            params.append(min_confidence)

        query = f"""
            SELECT id, event_time, ingested_at, event_type, source,
                   subject_id, source_id, provenance_json, payload_json, confidence
            FROM event_log
            WHERE {' AND '.join(clauses)}
            ORDER BY event_time DESC
            LIMIT ?;
        """
        params.append(limit)

        conn = self._get_connection()
        items: List[RetrievalItem] = []
        try:
            cur = conn.cursor()
            rows = cur.execute(query, tuple(params)).fetchall()
            for r in rows:
                p_data = self._safe_json_loads(r["payload_json"], {})
                prov = self._safe_json_loads(r["provenance_json"], {})
                summary = (
                    p_data.get("summary")
                    or p_data.get("finding")
                    or p_data.get("title")
                    or f"{r['event_type']} from {r['source']}"
                )
                ev_time = ensure_timezone_aware(r["event_time"], "event_time") if r["event_time"] else None

                # Build evidence references from source and provenance coordinates
                ev_refs = []
                if r["source_id"]:
                    ev_refs.append(f"{r['source']}:{r['source_id']}")
                if prov.get("tool"):
                    ev_refs.append(f"tool:{prov['tool']}")
                if prov.get("query"):
                    ev_refs.append(f"query:{prov['query']}")
                if prov.get("path"):
                    ev_refs.append(f"path:{prov['path']}")

                items.append(
                    RetrievalItem(
                        id=r["id"],
                        source_type="event",
                        source=r["source"],
                        source_id=r["source_id"],
                        title=f"[{r['source'].upper()}] {summary}",
                        content_text=json.dumps(p_data, ensure_ascii=False) if isinstance(p_data, dict) else str(p_data),
                        score=float(r["confidence"]),
                        retrieval_mode="structured",
                        timestamp=ev_time,
                        provenance=prov,
                        evidence_references=ev_refs,
                        metadata={
                            "event_type": r["event_type"],
                            "subject_id": r["subject_id"],
                            "confidence": r["confidence"],
                        },
                    )
                )
            return items
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 2. Timeline Window Retrieval
    # -------------------------------------------------------------------------

    def retrieve_timeline_window(
        self,
        anchor_time: Optional[Union[datetime, str]] = None,
        window_hours_before: float = 24.0,
        window_hours_after: float = 24.0,
        sources: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[RetrievalItem]:
        """
        Retrieves chronological event context in a window around an anchor time.
        Ranks items by temporal proximity to anchor.
        """
        ref_dt = ensure_timezone_aware(anchor_time or datetime.now(timezone.utc), "anchor_time")
        start_dt = ref_dt - timedelta(hours=window_hours_before)
        end_dt = ref_dt + timedelta(hours=window_hours_after)

        raw_items = self.retrieve_structured(
            sources=sources,
            start_time=start_dt,
            end_time=end_dt,
            limit=limit * 2,
        )

        # Score by temporal proximity (1.0 at anchor, decaying linearly towards window boundaries)
        max_window_secs = max(1.0, max(window_hours_before, window_hours_after) * 3600.0)
        for item in raw_items:
            if item.timestamp:
                delta_secs = abs((item.timestamp - ref_dt).total_seconds())
                proximity = max(0.1, 1.0 - (delta_secs / max_window_secs))
                item.score = round(proximity, 4)
                item.retrieval_mode = "timeline"

        raw_items.sort(key=lambda x: x.score, reverse=True)
        return raw_items[:limit]

    # -------------------------------------------------------------------------
    # 3. Entity & Relationship Lookup
    # -------------------------------------------------------------------------

    def retrieve_entity_network(
        self,
        entity_name_or_id: str,
        depth: int = 1,
        limit: int = 20,
    ) -> List[RetrievalItem]:
        """
        Looks up entity nodes and connected relationship edges from the knowledge graph.
        """
        if not entity_name_or_id or not entity_name_or_id.strip():
            return []

        search_term = entity_name_or_id.strip().lower()
        conn = self._get_connection()
        items: List[RetrievalItem] = []

        try:
            cur = conn.cursor()
            # 1. Match Node by ID, Name, or Alias
            node_rows = cur.execute("""
                SELECT id, name, entity_type, aliases_json, metadata_json, created_at, updated_at
                FROM entity_nodes
                WHERE LOWER(id) = ? OR LOWER(name) LIKE ? OR LOWER(aliases_json) LIKE ?
                LIMIT 5;
            """, (search_term, f"%{search_term}%", f"%{search_term}%")).fetchall()

            matched_node_ids = set()
            for r in node_rows:
                n_id = r["id"]
                matched_node_ids.add(n_id)
                meta = self._safe_json_loads(r["metadata_json"], {})
                aliases = self._safe_json_loads(r["aliases_json"], [])
                up_dt = ensure_timezone_aware(r["updated_at"], "updated_at") if r["updated_at"] else None

                items.append(
                    RetrievalItem(
                        id=n_id,
                        source_type="entity",
                        source="graph_entity",
                        source_id=n_id,
                        title=f"Entity: {r['name']} ({r['entity_type']})",
                        content_text=f"Entity '{r['name']}' of type '{r['entity_type']}'. Aliases: {aliases}. Meta: {meta}",
                        score=1.0,
                        retrieval_mode="entity_lookup",
                        timestamp=up_dt,
                        provenance={"entity_id": n_id, "entity_type": r["entity_type"]},
                        evidence_references=[f"entity:{n_id}"],
                        metadata={"entity_type": r["entity_type"], "aliases": aliases, "metadata": meta},
                    )
                )

            # 2. Match Connected Edges for found nodes
            if matched_node_ids:
                placeholders = ",".join("?" for _ in matched_node_ids)
                edge_rows = cur.execute(f"""
                    SELECT e.id, e.source_id, e.target_id, e.relationship, e.weight,
                           e.metadata_json, e.created_at, e.status,
                           n1.name as source_name, n2.name as target_name
                    FROM entity_edges e
                    LEFT JOIN entity_nodes n1 ON e.source_id = n1.id
                    LEFT JOIN entity_nodes n2 ON e.target_id = n2.id
                    WHERE e.source_id IN ({placeholders}) OR e.target_id IN ({placeholders})
                    LIMIT ?;
                """, tuple(list(matched_node_ids) + list(matched_node_ids) + [limit])).fetchall()

                for er in edge_rows:
                    e_id = er["id"]
                    s_name = er["source_name"] or er["source_id"]
                    t_name = er["target_name"] or er["target_id"]
                    rel = er["relationship"]
                    c_dt = ensure_timezone_aware(er["created_at"], "created_at") if er["created_at"] else None
                    meta = self._safe_json_loads(er["metadata_json"], {})

                    items.append(
                        RetrievalItem(
                            id=e_id,
                            source_type="entity",
                            source="graph_edge",
                            source_id=e_id,
                            title=f"Relation: {s_name} -[{rel}]-> {t_name}",
                            content_text=f"Relationship: {s_name} {rel} {t_name} (weight: {er['weight']})",
                            score=0.9,
                            retrieval_mode="entity_lookup",
                            timestamp=c_dt,
                            provenance={"edge_id": e_id, "source_id": er["source_id"], "target_id": er["target_id"]},
                            evidence_references=[f"edge:{e_id}", f"entity:{er['source_id']}", f"entity:{er['target_id']}"],
                            metadata={"relationship": rel, "weight": er["weight"], "status": er["status"]},
                        )
                    )

            return items[:limit]
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 4. Lexical / SQLite FTS5 Retrieval
    # -------------------------------------------------------------------------

    def retrieve_lexical(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        time_range: Optional[Tuple[datetime, datetime]] = None,
        limit: int = 20,
    ) -> List[RetrievalItem]:
        """
        Executes fast lexical search over event payloads, situation contexts, and notes.
        Uses token matching and BM25-like scoring.
        """
        if not query or not query.strip():
            return []

        clean_q = query.strip()
        tokens = [t.lower() for t in re.findall(r"\b\w+\b", clean_q) if len(t) > 1]
        if not tokens:
            tokens = [clean_q.lower()]

        clauses = ["1=1"]
        params: List[Any] = []

        if sources:
            norm_sources = [s.strip().lower() for s in sources if s]
            if norm_sources:
                placeholders = ",".join("?" for _ in norm_sources)
                clauses.append(f"source IN ({placeholders})")
                params.extend(norm_sources)

        if time_range:
            st, et = time_range
            if st:
                clauses.append("event_time >= ?")
                params.append(format_iso8601(ensure_timezone_aware(st, "start_time")))
            if et:
                clauses.append("event_time <= ?")
                params.append(format_iso8601(ensure_timezone_aware(et, "end_time")))

        conn = self._get_connection()
        items: List[RetrievalItem] = []

        try:
            cur = conn.cursor()
            # 1. Query Event Log
            event_query = f"""
                SELECT id, event_time, event_type, source, source_id,
                       provenance_json, payload_json, confidence
                FROM event_log
                WHERE {' AND '.join(clauses)}
                ORDER BY event_time DESC
                LIMIT 200;
            """
            rows = cur.execute(event_query, tuple(params)).fetchall()

            for r in rows:
                p_data = self._safe_json_loads(r["payload_json"], {})
                summary = (
                    p_data.get("summary")
                    or p_data.get("finding")
                    or p_data.get("title")
                    or ""
                )
                payload_str = json.dumps(p_data).lower() if isinstance(p_data, dict) else str(p_data).lower()
                summary_lower = summary.lower()

                # Calculate lexical match score (token frequency + summary prominence)
                match_count = 0
                for tok in tokens:
                    if tok in summary_lower:
                        match_count += 2.0  # Summary match weight
                    elif tok in payload_str:
                        match_count += 1.0  # Body match weight

                if match_count > 0:
                    max_possible = len(tokens) * 2.0
                    lexical_score = min(1.0, match_count / max_possible)
                    prov = self._safe_json_loads(r["provenance_json"], {})
                    ev_time = ensure_timezone_aware(r["event_time"], "event_time") if r["event_time"] else None

                    ev_refs = []
                    if r["source_id"]:
                        ev_refs.append(f"{r['source']}:{r['source_id']}")

                    items.append(
                        RetrievalItem(
                            id=r["id"],
                            source_type="event",
                            source=r["source"],
                            source_id=r["source_id"],
                            title=f"[{r['source'].upper()}] {summary or r['event_type']}",
                            content_text=json.dumps(p_data, ensure_ascii=False) if isinstance(p_data, dict) else str(p_data),
                            score=lexical_score,
                            retrieval_mode="fts5" if self._fts_available else "lexical",
                            timestamp=ev_time,
                            provenance=prov,
                            evidence_references=ev_refs,
                            metadata={"event_type": r["event_type"], "confidence": r["confidence"]},
                        )
                    )

            # 2. Query Situations for keyword matches
            sit_rows = cur.execute("""
                SELECT id, type, status, priority, context_json, evidence_json, created_at, updated_at
                FROM situations
                ORDER BY updated_at DESC
                LIMIT 50;
            """).fetchall()

            for sr in sit_rows:
                ctx = self._safe_json_loads(sr["context_json"], {})
                summary = ctx.get("summary") or sr["type"]
                text_blob = f"{sr['type']} {summary} {json.dumps(ctx)}".lower()

                match_count = sum(1 for tok in tokens if tok in text_blob)
                if match_count > 0:
                    score = min(1.0, match_count / len(tokens))
                    up_dt = ensure_timezone_aware(sr["updated_at"], "updated_at") if sr["updated_at"] else None
                    items.append(
                        RetrievalItem(
                            id=sr["id"],
                            source_type="situation",
                            source="situation_engine",
                            source_id=sr["id"],
                            title=f"Situation: {summary} ({sr['priority']})",
                            content_text=json.dumps(ctx, ensure_ascii=False),
                            score=score,
                            retrieval_mode="lexical",
                            timestamp=up_dt,
                            provenance={"situation_id": sr["id"], "type": sr["type"]},
                            evidence_references=[f"situation:{sr['id']}"],
                            metadata={"type": sr["type"], "priority": sr["priority"], "status": sr["status"]},
                        )
                    )

            items.sort(key=lambda x: x.score, reverse=True)
            return items[:limit]
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 5. Semantic Retrieval (Optional / Escalation Only)
    # -------------------------------------------------------------------------

    def retrieve_semantic(
        self,
        query: str,
        limit: int = 10,
        min_similarity: float = 0.05,
    ) -> List[RetrievalItem]:
        """
        Executes on-demand dense semantic vector retrieval.
        Escalation mechanism only when lexical/structured retrieval fails.
        """
        if not query or not query.strip():
            return []

        embedder = self._get_embedder()
        q_vec = embedder.embed_text(query)

        conn = self._get_connection()
        items: List[RetrievalItem] = []

        try:
            cur = conn.cursor()
            # Check if vector_embeddings table exists
            table_check = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vector_embeddings'").fetchone()
            if not table_check:
                return []

            rows = cur.execute("SELECT id, source_type, source_id, content_text, embedding_blob, metadata_json, created_at FROM vector_embeddings").fetchall()

            from personal_intelligence.core.embeddings.vector_engine import compute_cosine_similarity
            for r in rows:
                blob = r["embedding_blob"]
                count = len(blob) // 4
                doc_vec = struct.unpack(f"{count}f", blob)
                sim = compute_cosine_similarity(q_vec, doc_vec)

                if sim >= min_similarity:
                    meta = self._safe_json_loads(r["metadata_json"], {})
                    c_dt = ensure_timezone_aware(r["created_at"], "created_at") if r["created_at"] else None
                    items.append(
                        RetrievalItem(
                            id=r["id"],
                            source_type=r["source_type"],
                            source=meta.get("source", "vector_store"),
                            source_id=r["source_id"],
                            title=f"Semantic Match: {r['content_text'][:60]}",
                            content_text=r["content_text"],
                            score=sim,
                            retrieval_mode="semantic",
                            timestamp=c_dt,
                            provenance={"vector_id": r["id"], "source_type": r["source_type"], "source_id": r["source_id"]},
                            evidence_references=[f"vector:{r['id']}"],
                            metadata=meta,
                        )
                    )

            items.sort(key=lambda x: x.score, reverse=True)
            return items[:limit]
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 6. Situation-Targeted Evidence Retrieval (Deterministic Zero-Embedding Path)
    # -------------------------------------------------------------------------

    def retrieve_for_situation(
        self,
        situation_id: str,
        window_hours: float = 48.0,
        limit: int = 15,
    ) -> List[RetrievalItem]:
        """
        Gathers targeted evidence required to assess a situation using:
        - Situation record & related goals
        - Entity relationships for mentioned entities/collaborators
        - Timeline window around detection time
        - Lexical search for situation keywords
        Strictly zero embedding computations.
        """
        sit = self.local_store.situation_store.get(situation_id)
        if not sit:
            return []

        all_items: List[RetrievalItem] = []
        seen_ids: Set[str] = set()

        # 1. Add the Situation Frame itself
        sit_item = RetrievalItem(
            id=sit.id,
            source_type="situation",
            source="situation_engine",
            source_id=sit.id,
            title=f"Situation Frame: {sit.type} ({sit.priority})",
            content_text=json.dumps(sit.context, ensure_ascii=False),
            score=1.0,
            retrieval_mode="structured",
            timestamp=sit.updated_at or sit.created_at,
            provenance={"situation_id": sit.id, "type": sit.type},
            evidence_references=[f"situation:{sit.id}"],
            metadata={"priority": sit.priority, "status": sit.status, "related_goals": sit.related_goals},
        )
        all_items.append(sit_item)
        seen_ids.add(sit.id)

        # 2. Extract Entities from Situation Context & Fetch Entity Network
        ctx = sit.context or {}
        candidate_entities = []
        for key in ["sender", "recipient", "person", "project", "primary_entity", "investigation_target", "device"]:
            val = ctx.get(key)
            if val and isinstance(val, str) and len(val) > 2:
                candidate_entities.append(val)

        for ent in candidate_entities:
            net_items = self.retrieve_entity_network(ent, depth=1, limit=5)
            for item in net_items:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    all_items.append(item)

        # 3. Fetch Timeline Window around Situation Time
        anchor = sit.updated_at or sit.created_at or datetime.now(timezone.utc)
        timeline_items = self.retrieve_timeline_window(
            anchor_time=anchor,
            window_hours_before=window_hours / 2.0,
            window_hours_after=window_hours / 2.0,
            limit=limit,
        )
        for item in timeline_items:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                all_items.append(item)

        # 4. Lexical Search for Situation Category / Subject Keywords
        sit_type_words = " ".join(sit.type.replace("_", " ").split())
        summary_str = ctx.get("summary", "")
        lex_query = f"{sit_type_words} {summary_str}".strip()
        if lex_query:
            lex_items = self.retrieve_lexical(query=lex_query, limit=5)
            for item in lex_items:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    all_items.append(item)

        all_items.sort(key=lambda x: x.score, reverse=True)
        return all_items[:limit]

    # -------------------------------------------------------------------------
    # 7. Unified Main Retrieval Pipeline with Escalation
    # -------------------------------------------------------------------------

    def retrieve(
        self,
        query: str = "",
        time_range: Optional[Tuple[datetime, datetime]] = None,
        sources: Optional[List[str]] = None,
        entity_ids: Optional[List[str]] = None,
        situation_id: Optional[str] = None,
        limit: int = 10,
        allow_semantic_escalation: bool = False,
        escalation_threshold: float = 0.25,
    ) -> List[RetrievalItem]:
        """
        Unified Personal Memory Retrieval Pipeline.
        Prioritizes:
          1. Structured SQL filters
          2. Timeline queries
          3. Entity lookups
          4. SQLite FTS5 / Lexical matching
        Escalates to semantic vector similarity only if lexical/structured retrieval fails
        and allow_semantic_escalation is explicitly True.
        """
        results: List[RetrievalItem] = []
        seen_ids: Set[str] = set()

        # 1. Situation-targeted evidence if situation_id provided
        if situation_id:
            sit_items = self.retrieve_for_situation(situation_id=situation_id, limit=limit)
            for item in sit_items:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    results.append(item)

        # 2. Entity lookup if entities provided
        if entity_ids:
            for eid in entity_ids:
                ent_items = self.retrieve_entity_network(entity_name_or_id=eid, limit=5)
                for item in ent_items:
                    if item.id not in seen_ids:
                        seen_ids.add(item.id)
                        results.append(item)

        # 3. Lexical / FTS5 Retrieval if text query provided
        if query and query.strip():
            lex_items = self.retrieve_lexical(
                query=query,
                sources=sources,
                time_range=time_range,
                limit=limit,
            )
            for item in lex_items:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    results.append(item)

        # 4. Structured Retrieval if sources or time_range provided without query
        elif sources or time_range:
            st = time_range[0] if time_range else None
            et = time_range[1] if time_range else None
            struct_items = self.retrieve_structured(
                sources=sources,
                start_time=st,
                end_time=et,
                limit=limit,
            )
            for item in struct_items:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    results.append(item)

        # 5. Semantic Escalation Check
        top_score = max((r.score for r in results), default=0.0)
        needs_escalation = (len(results) == 0 or top_score < escalation_threshold)

        if needs_escalation and allow_semantic_escalation and self.enable_semantic_escalation and query.strip():
            logger.info("Lexical/structured retrieval below threshold (top_score=%.2f). Escalating to semantic vector search.", top_score)
            semantic_hits = self.retrieve_semantic(query=query, limit=limit)
            for s_item in semantic_hits:
                if s_item.id not in seen_ids:
                    seen_ids.add(s_item.id)
                    results.append(s_item)

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]
