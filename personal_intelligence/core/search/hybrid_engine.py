"""
Local Hybrid Semantic & Lexical Search Engine with SQLite Vector Storage.
Combines 384-dimensional dense semantic vector similarity with sparse lexical search
using Reciprocal Rank Fusion (RRF) for sub-millisecond grounded context retrieval.
"""

from datetime import datetime, timezone
import json
import logging
import sqlite3
import struct
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from personal_intelligence.core.embeddings.vector_engine import (
    EMBEDDING_DIMENSION,
    LocalSemanticEmbedder,
    VectorRecord,
    compute_cosine_similarity,
)
from personal_intelligence.core.events.models import format_iso8601
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class HybridSearchEngine:
    """
    In-process SQLite-backed Hybrid Search Engine.
    Performs fast dense vector similarity + sparse lexical search across all personal streams.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        embedder: Optional[LocalSemanticEmbedder] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()
        self.embedder = embedder or LocalSemanticEmbedder()
        self._ensure_vector_table()

    def _get_connection(self) -> sqlite3.Connection:
        return self.db_manager.get_connection()

    def _ensure_vector_table(self) -> None:
        """Ensures the vector_embeddings table and indexes are created in SQLite."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS vector_embeddings (
                        id TEXT PRIMARY KEY,
                        source_type TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        content_text TEXT NOT NULL,
                        embedding_blob BLOB NOT NULL,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_vec_source ON vector_embeddings(source_type, source_id);")
        except Exception as ex:
            logger.debug("Vector table check note: %s", ex)

    def index_document(
        self,
        source_type: str,
        source_id: str,
        content_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generates dense embedding and stores/updates document in SQLite vector store.
        """
        if not content_text or not content_text.strip():
            return ""

        meta = metadata or {}
        vec = self.embedder.embed_text(content_text)
        blob = struct.pack(f"{len(vec)}f", *vec)
        doc_id = f"vec-{source_type}-{source_id}"

        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO vector_embeddings (id, source_type, source_id, content_text, embedding_blob, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_id,
                    source_type,
                    source_id,
                    content_text,
                    blob,
                    json.dumps(meta),
                    format_iso8601(datetime.now(timezone.utc)),
                ))
            return doc_id
        except Exception as ex:
            logger.warning("Failed to index vector record %s: %s", doc_id, ex)
            return ""

    def sync_all_unindexed(self) -> int:
        """
        Scans all event_log rows, situations, and entity states in SQLite and indexes any unindexed items.
        """
        conn = self._get_connection()
        indexed_count = 0

        # 1. Index Events
        try:
            cur = conn.cursor()
            events = cur.execute("""
                SELECT e.id, e.source, e.event_type, e.payload_json, e.provenance_json 
                FROM event_log e 
                WHERE e.id NOT IN (SELECT source_id FROM vector_embeddings WHERE source_type = 'event')
            """).fetchall()

            for row in events:
                e_id = row["id"]
                source = row["source"]
                p_data = json.loads(row["payload_json"]) if row["payload_json"] else {}
                summary = p_data.get("summary") or p_data.get("finding") or p_data.get("title") or ""
                if summary:
                    self.index_document(
                        source_type="event",
                        source_id=e_id,
                        content_text=f"[{source.upper()}] {summary}",
                        metadata={"source": source, "event_type": row["event_type"]},
                    )
                    indexed_count += 1
        except Exception as ex:
            logger.debug("Event sync note: %s", ex)

        # 2. Index Situations
        try:
            sits = cur.execute("""
                SELECT s.id, s.type, s.priority, s.context_json 
                FROM situations s 
                WHERE s.id NOT IN (SELECT source_id FROM vector_embeddings WHERE source_type = 'situation')
            """).fetchall()

            for row in sits:
                s_id = row["id"]
                ctx = json.loads(row["context_json"]) if row["context_json"] else {}
                summary = ctx.get("summary") or row["type"]
                sender = ctx.get("sender") or ""
                full_text = f"Situation: {summary} ({sender}) Priority: {row['priority']}"
                self.index_document(
                    source_type="situation",
                    source_id=s_id,
                    content_text=full_text,
                    metadata={"priority": row["priority"], "type": row["type"]},
                )
                indexed_count += 1
        except Exception as ex:
            logger.debug("Situation sync note: %s", ex)

        return indexed_count

    def search_dense(
        self,
        query: str,
        limit: int = 10,
        min_similarity: float = 0.05,
    ) -> List[Dict[str, Any]]:
        """
        Executes fast dense semantic vector search across all indexed vectors.
        """
        if not query or not query.strip():
            return []

        q_vec = self.embedder.embed_text(query)
        conn = self._get_connection()
        results = []

        try:
            cur = conn.cursor()
            rows = cur.execute("SELECT id, source_type, source_id, content_text, embedding_blob, metadata_json, created_at FROM vector_embeddings").fetchall()

            for r in rows:
                blob = r["embedding_blob"]
                count = len(blob) // 4
                doc_vec = struct.unpack(f"{count}f", blob)
                sim = compute_cosine_similarity(q_vec, doc_vec)

                if sim >= min_similarity:
                    meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
                    results.append({
                        "id": r["id"],
                        "source_type": r["source_type"],
                        "source_id": r["source_id"],
                        "content_text": r["content_text"],
                        "similarity_score": round(sim, 4),
                        "metadata": meta,
                        "created_at": r["created_at"],
                    })

            results.sort(key=lambda x: x["similarity_score"], reverse=True)
            return results[:limit]
        except Exception as ex:
            logger.error("Dense search failed: %s", ex)
            return []

    def search_lexical(
        self,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Executes keyword and token-matching sparse lexical search.
        """
        if not query or not query.strip():
            return []

        tokens = [t.lower() for t in query.split() if len(t) > 2]
        if not tokens:
            tokens = [query.lower().strip()]

        conn = self._get_connection()
        results = []

        try:
            cur = conn.cursor()
            rows = cur.execute("SELECT id, source_type, source_id, content_text, metadata_json, created_at FROM vector_embeddings").fetchall()

            for r in rows:
                content_lower = r["content_text"].lower()
                matches = sum(1 for tok in tokens if tok in content_lower)
                if matches > 0:
                    score = matches / len(tokens)
                    meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
                    results.append({
                        "id": r["id"],
                        "source_type": r["source_type"],
                        "source_id": r["source_id"],
                        "content_text": r["content_text"],
                        "lexical_score": round(score, 4),
                        "metadata": meta,
                        "created_at": r["created_at"],
                    })

            results.sort(key=lambda x: x["lexical_score"], reverse=True)
            return results[:limit]
        except Exception as ex:
            logger.error("Lexical search failed: %s", ex)
            return []

    def search_hybrid(
        self,
        query: str,
        limit: int = 10,
        rrf_k: int = 60,
        sync_unindexed: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Executes Hybrid Retrieval combining Dense Semantic and Sparse Lexical rankings
        using Reciprocal Rank Fusion (RRF). Dense embeddings are computed on-demand.
        """
        if sync_unindexed:
            self.sync_all_unindexed()

        dense_results = self.search_dense(query=query, limit=limit * 2)
        lexical_results = self.search_lexical(query=query, limit=limit * 2)

        rrf_scores: Dict[str, float] = {}
        doc_map: Dict[str, Dict[str, Any]] = {}

        # 1. Score dense ranks
        for rank, doc in enumerate(dense_results, 1):
            doc_id = doc["id"]
            doc_map[doc_id] = doc
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (rrf_k + rank))

        # 2. Score lexical ranks
        for rank, doc in enumerate(lexical_results, 1):
            doc_id = doc["id"]
            if doc_id not in doc_map:
                doc_map[doc_id] = doc
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (rrf_k + rank))

        # 3. Assemble merged ranking
        merged = []
        for doc_id, score in rrf_scores.items():
            item = dict(doc_map[doc_id])
            item["rrf_score"] = round(score, 6)
            merged.append(item)

        merged.sort(key=lambda x: x["rrf_score"], reverse=True)
        return merged[:limit]

    def get_index_stats(self) -> Dict[str, Any]:
        """Returns statistics on the local vector store."""
        conn = self._get_connection()
        cur = conn.cursor()
        total_vectors = cur.execute("SELECT count(*) FROM vector_embeddings").fetchone()[0]
        by_source = dict(cur.execute("SELECT source_type, count(*) FROM vector_embeddings GROUP BY source_type").fetchall())

        return {
            "total_vectors": total_vectors,
            "dimension": EMBEDDING_DIMENSION,
            "by_source": by_source,
            "storage_type": "SQLite BLOB In-Process Vector Table",
            "search_modes": ["dense_cosine", "sparse_lexical", "reciprocal_rank_fusion"],
        }
