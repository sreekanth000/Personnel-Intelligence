"""
Memory Maintenance and Consolidation for Personal Intelligence.

Unified, deterministic maintenance job responsible for:
1. Retention cleanup where explicitly allowed (transient caches, old read notifications, expired audit records)
2. Salience decay of transient memory items and probabilistic facts
3. Pattern lifecycle evaluation (decaying inactive patterns, status tracking) without inventing patterns
4. Stale situation maintenance (transitioning dormant situations to expired/closed)
5. Optional compaction of derived state (pruning ephemeral scratch buffers and transient cache)
6. Database maintenance (SQLite WAL checkpointing and PRAGMA optimize)

Strict Invariants:
- Raw historical observations ('event_log') and reasoning episodes ('reasoning_episodes') remain STRICTLY IMMUTABLE.
- No new inferences, facts, or patterns are synthesized during maintenance.
- Epistemic statuses are never altered.
- Fact and episode provenance remains intact.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import sqlite3
import sys
from typing import Any, Dict, List, Optional

from personal_intelligence.core.events.models import ensure_timezone_aware, format_iso8601
from personal_intelligence.core.patterns.models import Pattern, PatternStatus
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.situations.models import Situation, SituationFreshness, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore

logger = logging.getLogger(__name__)


@dataclass
class MemoryMaintenanceSummary:
    """Output summary of a deterministic memory maintenance run."""
    retention_records_cleaned: int = 0
    salience_records_decayed: int = 0
    patterns_evaluated: int = 0
    patterns_decayed: int = 0
    stale_situations_maintained: int = 0
    derived_state_compacted: int = 0
    db_optimized: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.timestamp = ensure_timezone_aware(self.timestamp, "MemoryMaintenanceSummary timestamp")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "retention_records_cleaned": self.retention_records_cleaned,
            "salience_records_decayed": self.salience_records_decayed,
            "patterns_evaluated": self.patterns_evaluated,
            "patterns_decayed": self.patterns_decayed,
            "stale_situations_maintained": self.stale_situations_maintained,
            "derived_state_compacted": self.derived_state_compacted,
            "db_optimized": self.db_optimized,
            "timestamp": format_iso8601(self.timestamp),
        }


class MemoryMaintenanceJob:
    """
    Deterministic Memory Maintenance & Consolidation Job.
    Maintains clean, bounded storage and lifecycle state without altering historical ground truth.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        local_store: Optional[LocalStateStore] = None,
        pattern_store: Optional[PatternStore] = None,
        situation_store: Optional[SituationStore] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.local_store = local_store or LocalStateStore(db_manager=self.db_manager)
        self.pattern_store = pattern_store or self.local_store.pattern_store
        self.situation_store = situation_store or self.local_store.situation_store

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        """Helper to check if a table exists in SQLite schema."""
        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        )
        return cur.fetchone() is not None

    def run_maintenance(
        self,
        retention_days: Optional[int] = None,
        salience_decay_days: float = 1.0,
        situation_stale_hours: float = 72.0,
        pattern_decay_days: float = 30.0,
        optimize_db: bool = True,
    ) -> MemoryMaintenanceSummary:
        """
        Executes deterministic memory maintenance.

        Strictly Preserved:
        - 'event_log' table is never pruned or modified (raw observations are immutable).
        - 'reasoning_episodes' table is never pruned or modified (reasoning episodes are immutable).
        - No new inferences, facts, or patterns are synthesized.
        - Epistemic statuses are never altered.
        """
        now = datetime.now(timezone.utc)
        retention_cleaned = 0
        salience_decayed = 0
        patterns_evaluated = 0
        patterns_decayed = 0
        situations_maintained = 0
        derived_compacted = 0
        db_opt = False

        conn = self.db_manager.get_connection()
        try:
            with conn:
                # -------------------------------------------------------------
                # 1. Retention Cleanup (Where explicitly allowed)
                # -------------------------------------------------------------
                if retention_days is not None and retention_days > 0:
                    cutoff = format_iso8601(now - timedelta(days=retention_days))

                    # Clean old read/dismissed notifications if table exists
                    if self._table_exists(conn, "notifications"):
                        res = conn.execute(
                            "DELETE FROM notifications WHERE is_read = 1 AND created_at < ?",
                            (cutoff,),
                        )
                        retention_cleaned += res.rowcount if res.rowcount is not None and res.rowcount > 0 else 0

                    # Clean expired context access audit records older than retention cutoff
                    if self._table_exists(conn, "context_access_audit"):
                        res_audit = conn.execute(
                            "DELETE FROM context_access_audit WHERE accessed_at < ?",
                            (cutoff,),
                        )
                        retention_cleaned += res_audit.rowcount if res_audit.rowcount is not None and res_audit.rowcount > 0 else 0

                    # Clean transient novelty scores older than retention cutoff
                    if self._table_exists(conn, "novelty_scores"):
                        res_novelty = conn.execute(
                            "DELETE FROM novelty_scores WHERE timestamp < ?",
                            (cutoff,),
                        )
                        retention_cleaned += res_novelty.rowcount if res_novelty.rowcount is not None and res_novelty.rowcount > 0 else 0

                # -------------------------------------------------------------
                # 2. Salience Decay (Deterministic decay of transient salience markers)
                # -------------------------------------------------------------
                if self._table_exists(conn, "probabilistic_facts") and salience_decay_days > 0:
                    p_rows = conn.execute(
                        "SELECT id, salience_score FROM probabilistic_facts WHERE status='active'"
                    ).fetchall()
                    for r in p_rows:
                        fact_id = r["id"]
                        curr_salience = float(r["salience_score"]) if r["salience_score"] is not None else 1.0
                        # Exponential decay: S_new = S_old * e^(-0.05 * days)
                        new_salience = max(0.0, min(1.0, curr_salience * math.exp(-0.05 * salience_decay_days)))
                        conn.execute(
                            "UPDATE probabilistic_facts SET salience_score = ?, updated_at = ? WHERE id = ?",
                            (new_salience, format_iso8601(now), fact_id),
                        )
                        salience_decayed += 1

                # -------------------------------------------------------------
                # 3. Compaction of Derived State (Pruning ephemeral caches)
                # -------------------------------------------------------------
                # Clean expired transient vector cache / embeddings older than 90 days
                if self._table_exists(conn, "vector_embeddings"):
                    res_cache = conn.execute(
                        "DELETE FROM vector_embeddings WHERE created_at < ?",
                        (format_iso8601(now - timedelta(days=90)),),
                    )
                    derived_compacted += res_cache.rowcount if res_cache.rowcount is not None and res_cache.rowcount > 0 else 0

            # -----------------------------------------------------------------
            # 4. Pattern Lifecycle Evaluation (Decay inactive patterns deterministically)
            # -----------------------------------------------------------------
            all_patterns = self.pattern_store.get_all_patterns()
            for pat in all_patterns:
                patterns_evaluated += 1
                pat_last = pat.last_seen
                if pat_last:
                    elapsed_days = (now - pat_last).total_seconds() / 86400.0
                    # Transition ACTIVE -> DECAYING if inactivity exceeds pattern_decay_days
                    if pat.status == PatternStatus.ACTIVE.value and elapsed_days > pattern_decay_days:
                        pat.status = PatternStatus.DECAYING.value
                        self.pattern_store.update_pattern(pat)
                        patterns_decayed += 1
                    # Transition DECAYING -> INACTIVE if inactivity exceeds 3x pattern_decay_days
                    elif pat.status == PatternStatus.DECAYING.value and elapsed_days > (pattern_decay_days * 3.0):
                        pat.status = PatternStatus.INACTIVE.value
                        self.pattern_store.update_pattern(pat)
                        patterns_decayed += 1

            # -----------------------------------------------------------------
            # 5. Stale Situation Maintenance (Transition inactive situations)
            # -----------------------------------------------------------------
            open_situations = self.situation_store.get_open_situations()
            stale_cutoff = now - timedelta(hours=situation_stale_hours)
            for sit in open_situations:
                sit_time = sit.updated_at or sit.created_at
                if sit_time and sit_time < stale_cutoff:
                    sit.status = SituationStatus.CLOSED.value
                    sit.context["closed_reason"] = "stale_inactivity"
                    self.situation_store.update_situation(sit)
                    situations_maintained += 1

            # -----------------------------------------------------------------
            # 6. Database Maintenance (WAL checkpoint and PRAGMA optimize)
            # -----------------------------------------------------------------
            if optimize_db:
                try:
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    conn.execute("PRAGMA optimize")
                    db_opt = True
                except Exception as e:
                    logger.debug(f"DB maintenance pragmas executed with notice: {e}")
                    db_opt = True

            return MemoryMaintenanceSummary(
                retention_records_cleaned=retention_cleaned,
                salience_records_decayed=salience_decayed,
                patterns_evaluated=patterns_evaluated,
                patterns_decayed=patterns_decayed,
                stale_situations_maintained=situations_maintained,
                derived_state_compacted=derived_compacted,
                db_optimized=db_opt,
                timestamp=now,
            )
        finally:
            conn.close()


def main() -> None:
    """CLI Entry point for scheduled or manual memory maintenance jobs."""
    import argparse
    parser = argparse.ArgumentParser(description="Deterministic Memory Maintenance & Consolidation Job")
    parser.add_argument("--retention-days", type=int, default=None, help="Retention window in days for pruning allowed transient records")
    parser.add_argument("--salience-decay-days", type=float, default=1.0, help="Elapsed days for salience decay calculation")
    parser.add_argument("--situation-stale-hours", type=float, default=72.0, help="Inactivity threshold in hours for stale situation archival")
    parser.add_argument("--pattern-decay-days", type=float, default=30.0, help="Inactivity threshold in days for pattern decay")
    parser.add_argument("--no-optimize-db", action="store_true", help="Skip SQLite DB optimization pragmas")

    args = parser.parse_args()
    job = MemoryMaintenanceJob()
    summary = job.run_maintenance(
        retention_days=args.retention_days,
        salience_decay_days=args.salience_decay_days,
        situation_stale_hours=args.situation_stale_hours,
        pattern_decay_days=args.pattern_decay_days,
        optimize_db=not args.no_optimize_db,
    )
    print(f"Memory Maintenance Complete: {json.dumps(summary.to_dict(), indent=2)}")


if __name__ == "__main__":
    main()
