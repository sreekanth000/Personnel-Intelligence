"""
SQLite-backed persistence layer for Patterns and Pattern Evidence.
"""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional, Union
import uuid

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.patterns.models import (
    EvidenceObservationType,
    Pattern,
    PatternEvidence,
    PatternStatus,
    PatternType,
)
from personal_intelligence.storage.db import DatabaseManager



class PatternStore:
    """
    Manages SQLite storage and querying for patterns and longitudinal empirical evidence.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return self.db_manager.get_connection()

    def _row_to_pattern(self, row: sqlite3.Row) -> Pattern:
        """Converts an SQLite row to a Pattern instance."""
        def safe_json_load(val: Optional[str], default: Any) -> Any:
            if not val:
                return default
            try:
                return json.loads(val)
            except Exception:
                return default

        meta = safe_json_load(row["metadata_json"], {})
        p_type = row["pattern_type"] if "pattern_type" in row.keys() else meta.get("pattern_type", "BEHAVIORAL_PATTERN")

        return Pattern(
            id=row["id"],
            description=row["description"],
            pattern_type=p_type,
            first_seen=ensure_timezone_aware(row["first_seen"], "first_seen"),
            last_seen=ensure_timezone_aware(row["last_seen"], "last_seen"),
            support_count=int(row["support_count"]),
            contradiction_count=int(row["contradiction_count"]),
            evidence_strength=row["evidence_strength"],
            status=row["status"],
            metadata=meta,
        )

    def _row_to_evidence(self, row: sqlite3.Row) -> PatternEvidence:
        """Converts an SQLite row to a PatternEvidence instance."""
        def safe_json_load(val: Optional[str], default: Any) -> Any:
            if not val:
                return default
            try:
                return json.loads(val)
            except Exception:
                return default

        return PatternEvidence(
            evidence_id=row["evidence_id"],
            pattern_id=row["pattern_id"],
            observation_type=row["observation_type"],
            observed_at=ensure_timezone_aware(row["observed_at"], "observed_at"),
            episode_id=row["episode_id"],
            event_ids=safe_json_load(row["event_ids_json"], []),
            details=safe_json_load(row["details_json"], {}),
        )

    def create_pattern(
        self,
        description: Union[str, Pattern],
        first_seen: Optional[datetime] = None,
        last_seen: Optional[datetime] = None,
        support_count: int = 1,
        contradiction_count: int = 0,
        evidence_strength: str = "weak",
        status: str = PatternStatus.OBSERVED.value,
        pattern_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        pattern_type: Union[PatternType, str] = PatternType.BEHAVIORAL_PATTERN.value,
    ) -> Pattern:
        """
        Creates and persists a new candidate pattern.
        Supports passing either an existing Pattern instance or individual fields.
        """
        if isinstance(description, Pattern):
            pat = description
        else:
            now = datetime.now(timezone.utc)
            f_seen = ensure_timezone_aware(first_seen or now, "first_seen")
            l_seen = ensure_timezone_aware(last_seen or now, "last_seen")
            p_id = pattern_id or str(uuid.uuid4())
            p_type_val = pattern_type.value if hasattr(pattern_type, "value") else str(pattern_type).strip().upper()

            meta = dict(metadata or {})
            meta["pattern_type"] = p_type_val

            pat = Pattern(
                id=p_id,
                description=description,
                pattern_type=p_type_val,
                first_seen=f_seen,
                last_seen=l_seen,
                support_count=support_count,
                contradiction_count=contradiction_count,
                evidence_strength=evidence_strength,
                status=status,
                metadata=meta,
            )

        if "pattern_type" not in pat.metadata:
            pat.metadata["pattern_type"] = pat.pattern_type

        query = """
            INSERT INTO patterns (
                id, description, first_seen, last_seen, support_count,
                contradiction_count, evidence_strength, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            pat.id,
            pat.description,
            format_iso8601(pat.first_seen),
            format_iso8601(pat.last_seen),
            pat.support_count,
            pat.contradiction_count,
            pat.evidence_strength,
            pat.status,
            json.dumps(pat.metadata, ensure_ascii=False) if pat.metadata else None,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return pat
        finally:
            conn.close()

    def get_pattern(self, pattern_id: str) -> Optional[Pattern]:
        """Retrieves a pattern by its ID."""
        if not pattern_id:
            return None

        query = "SELECT * FROM patterns WHERE id = ? LIMIT 1;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (pattern_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_pattern(row)
            return None
        finally:
            conn.close()

    def list_patterns(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Pattern]:
        """Lists patterns optionally filtered by status ordered by last_seen DESC."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if status:
                stat_val = status.value if hasattr(status, "value") else str(status)
                query = "SELECT * FROM patterns WHERE LOWER(status) = ? ORDER BY last_seen DESC LIMIT ?;"
                cursor.execute(query, (stat_val.strip().lower(), limit))
            else:
                query = "SELECT * FROM patterns ORDER BY last_seen DESC LIMIT ?;"
                cursor.execute(query, (limit,))
            return [self._row_to_pattern(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def list_active(self, limit: int = 50) -> List[Pattern]:
        """Convenience method to list currently active patterns."""
        return self.list_patterns(status=PatternStatus.ACTIVE.value, limit=limit)

    def list_patterns_by_type(
        self,
        pattern_type: Union[PatternType, str],
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Pattern]:
        """Lists patterns filtered by PatternType and optionally status."""
        p_type_val = pattern_type.value if hasattr(pattern_type, "value") else str(pattern_type).strip().upper()
        all_matching = self.list_patterns(status=status, limit=limit * 2)
        filtered = [p for p in all_matching if p.pattern_type == p_type_val][:limit]
        return filtered

    def get_supporting_episodes(self, pattern_id: str) -> List[str]:
        """Retrieves distinct supporting reasoning episode IDs linked to this pattern."""
        query = """
            SELECT DISTINCT episode_id FROM pattern_evidence
            WHERE pattern_id = ? AND observation_type = 'SUPPORT' AND episode_id IS NOT NULL AND episode_id != '';
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (pattern_id,))
            rows = cursor.fetchall()
            from_db = [r["episode_id"] for r in rows if r["episode_id"]]
            pat = self.get_pattern(pattern_id)
            if pat and pat.supporting_episodes:
                combined = list(set(from_db + pat.supporting_episodes))
                return sorted(combined)
            return sorted(from_db)
        finally:
            conn.close()

    def get_contradicting_episodes(self, pattern_id: str) -> List[str]:
        """Retrieves distinct contradicting reasoning episode IDs linked to this pattern."""
        query = """
            SELECT DISTINCT episode_id FROM pattern_evidence
            WHERE pattern_id = ? AND observation_type = 'CONTRADICTION' AND episode_id IS NOT NULL AND episode_id != '';
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (pattern_id,))
            rows = cursor.fetchall()
            from_db = [r["episode_id"] for r in rows if r["episode_id"]]
            pat = self.get_pattern(pattern_id)
            if pat and pat.contradicting_episodes:
                combined = list(set(from_db + pat.contradicting_episodes))
                return sorted(combined)
            return sorted(from_db)
        finally:
            conn.close()

    def update_pattern(self, pattern: Pattern) -> Optional[Pattern]:
        """Updates an existing pattern record."""
        if "pattern_type" not in pattern.metadata:
            pattern.metadata["pattern_type"] = pattern.pattern_type

        query = """
            UPDATE patterns
            SET description = ?, first_seen = ?, last_seen = ?,
                support_count = ?, contradiction_count = ?,
                evidence_strength = ?, status = ?, metadata_json = ?
            WHERE id = ?;
        """
        params = (
            pattern.description,
            format_iso8601(pattern.first_seen),
            format_iso8601(pattern.last_seen),
            pattern.support_count,
            pattern.contradiction_count,
            pattern.evidence_strength,
            pattern.status,
            json.dumps(pattern.metadata, ensure_ascii=False) if pattern.metadata else None,
            pattern.id,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return self.get_pattern(pattern.id)
        finally:
            conn.close()

    def add_evidence(
        self,
        pattern_id: Union[str, PatternEvidence],
        observation_type: Optional[Union[EvidenceObservationType, str]] = None,
        observed_at: Optional[datetime] = None,
        episode_id: Optional[str] = None,
        event_ids: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> PatternEvidence:
        """
        Records an empirical supporting or contradictory evidence observation for a pattern.
        """
        if isinstance(pattern_id, PatternEvidence):
            ev = pattern_id
        else:
            now = datetime.now(timezone.utc)
            obs_dt = ensure_timezone_aware(observed_at or now, "observed_at")
            obs_type = observation_type.value if isinstance(observation_type, EvidenceObservationType) else str(observation_type or "SUPPORT").strip().upper()

            ev = PatternEvidence(
                pattern_id=pattern_id,
                observation_type=obs_type,
                observed_at=obs_dt,
                episode_id=episode_id,
                event_ids=event_ids or [],
                details=details or {},
            )

        query = """
            INSERT INTO pattern_evidence (
                evidence_id, pattern_id, observation_type, observed_at,
                episode_id, event_ids_json, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """
        obs_type_val = ev.observation_type.value if hasattr(ev.observation_type, "value") else str(ev.observation_type)
        params = (
            ev.evidence_id,
            ev.pattern_id,
            obs_type_val,
            format_iso8601(ev.observed_at),
            ev.episode_id,
            json.dumps(ev.event_ids, ensure_ascii=False) if ev.event_ids else None,
            json.dumps(ev.details, ensure_ascii=False) if ev.details else None,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return ev
        finally:
            conn.close()

    def list_evidence_for_pattern(
        self,
        pattern_id: str,
        limit: int = 100,
    ) -> List[PatternEvidence]:
        """Lists evidence observations for a specific pattern ID ordered by observed_at DESC."""
        query = "SELECT * FROM pattern_evidence WHERE pattern_id = ? ORDER BY observed_at DESC LIMIT ?;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (pattern_id, limit))
            rows = cursor.fetchall()
            return [self._row_to_evidence(r) for r in rows]
        finally:
            conn.close()


