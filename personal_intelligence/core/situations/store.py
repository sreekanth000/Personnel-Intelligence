"""
Local-first SituationStore for managing generic situational context frames.
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
from personal_intelligence.core.situations.models import (
    Situation,
    SituationPriority,
    SituationStatus,
)
from personal_intelligence.storage.db import DatabaseManager


class SituationStore:
    """
    SQLite-backed store for generic situational context frames.
    A Situation is NOT an agent; it is an assessable multi-event context structure.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return self.db_manager.get_connection()

    def _row_to_situation(self, row: sqlite3.Row) -> Situation:
        """Converts an SQLite row into a validated Situation object."""
        try:
            context = json.loads(row["context_json"])
        except Exception:
            context = {}

        try:
            evidence = json.loads(row["evidence_json"])
        except Exception:
            evidence = []

        try:
            related_goals = json.loads(row["related_goals_json"])
        except Exception:
            related_goals = []

        next_eval = None
        if "next_evaluation_at" in row.keys() and row["next_evaluation_at"]:
            next_eval = ensure_timezone_aware(row["next_evaluation_at"], "next_evaluation_at")

        return Situation(
            id=row["id"],
            type=row["type"],
            status=row["status"],
            created_at=ensure_timezone_aware(row["created_at"], "created_at"),
            updated_at=ensure_timezone_aware(row["updated_at"], "updated_at"),
            last_evaluated_at=ensure_timezone_aware(row["last_evaluated_at"], "last_evaluated_at") if row["last_evaluated_at"] else None,
            next_evaluation_at=next_eval,
            priority=row["priority"],
            novelty=float(row["novelty"]),
            context=context,
            evidence=evidence,
            related_goals=related_goals,
            expires_at=ensure_timezone_aware(row["expires_at"], "expires_at") if row["expires_at"] else None,
        )

    def create(
        self,
        type: Union[str, Situation],
        priority: str = SituationPriority.MEDIUM.value,
        novelty: float = 0.0,
        context: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[Any]] = None,
        related_goals: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
        next_evaluation_at: Optional[datetime] = None,
        status: str = SituationStatus.OPEN.value,
        situation_id: Optional[str] = None,
        information_required: bool = False,
        investigation_target: Optional[str] = None,
    ) -> Situation:
        """Creates and persists a new situation context frame."""
        if isinstance(type, Situation):
            situation = type
        else:
            now = datetime.now(timezone.utc)
            situation = Situation(
                id=situation_id or str(uuid.uuid4()),
                type=type,
                status=status,
                priority=priority,
                novelty=novelty,
                context=context or {},
                evidence=evidence or [],
                related_goals=related_goals or [],
                information_required=information_required,
                investigation_target=investigation_target,
                created_at=now,
                updated_at=now,
                last_evaluated_at=None,
                next_evaluation_at=next_evaluation_at,
                expires_at=expires_at,
            )

        query = """
            INSERT INTO situations (
                id, type, status, created_at, updated_at, last_evaluated_at, next_evaluation_at,
                priority, novelty, context_json, evidence_json, related_goals_json, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        priority_val = situation.priority.value if hasattr(situation.priority, "value") else str(situation.priority)
        status_val = situation.status.value if hasattr(situation.status, "value") else str(situation.status)
        params = (
            situation.id,
            situation.type,
            status_val,
            format_iso8601(situation.created_at),
            format_iso8601(situation.updated_at),
            format_iso8601(situation.last_evaluated_at) if situation.last_evaluated_at else None,
            format_iso8601(situation.next_evaluation_at) if situation.next_evaluation_at else None,
            priority_val,
            situation.novelty,
            json.dumps(situation.context or {}, sort_keys=True, ensure_ascii=False),
            json.dumps(situation.evidence or [], ensure_ascii=False),
            json.dumps(situation.related_goals or [], ensure_ascii=False),
            format_iso8601(situation.expires_at) if situation.expires_at else None,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return situation
        finally:
            conn.close()

    def create_situation(
        self,
        type: Optional[Union[str, Situation]] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        situation_type: Optional[str] = None,
        priority: str = SituationPriority.MEDIUM.value,
        novelty: float = 0.0,
        context: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[Any]] = None,
        related_goals: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
        next_evaluation_at: Optional[datetime] = None,
        status: str = SituationStatus.OPEN.value,
        situation_id: Optional[str] = None,
        information_required: bool = False,
        investigation_target: Optional[str] = None,
    ) -> Situation:
        """Convenience alias for create."""
        if isinstance(type, Situation):
            return self.create(type)
        sit_type = type or situation_type or "unusual_state"
        ctx = dict(context or {})
        if title:
            ctx["title"] = title
        if description:
            ctx["description"] = description
        return self.create(
            type=sit_type,
            priority=priority,
            novelty=novelty,
            context=ctx,
            evidence=evidence or [],
            related_goals=related_goals or [],
            expires_at=expires_at,
            next_evaluation_at=next_evaluation_at,
            status=status,
            situation_id=situation_id,
            information_required=information_required,
            investigation_target=investigation_target,
        )

    def get(self, situation_id: str) -> Optional[Situation]:

        """Retrieves a single situation by its unique ID, or None if not found."""
        if not situation_id or not isinstance(situation_id, str):
            return None

        query = "SELECT * FROM situations WHERE id = ? LIMIT 1;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (situation_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_situation(row)
            return None
        finally:
            conn.close()

    def find_active_by_type(
        self,
        situation_type: str,
        related_goals: Optional[List[str]] = None,
    ) -> Optional[Situation]:
        """
        Finds an already active situation (OPEN or MONITORING) matching situation_type
        to maintain identity and prevent duplicate situation records.
        """
        query = """
            SELECT * FROM situations
            WHERE type = ? AND status IN ('open', 'monitoring')
            ORDER BY updated_at DESC;
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (situation_type,))
            rows = cursor.fetchall()
            if not rows:
                return None

            if not related_goals:
                return self._row_to_situation(rows[0])

            # If related goals specified, check for overlapping goals
            target_goals = set(related_goals)
            for row in rows:
                sit = self._row_to_situation(row)
                if set(sit.related_goals) & target_goals or not sit.related_goals:
                    return sit

            return self._row_to_situation(rows[0])
        finally:
            conn.close()

    def upsert(self, situation: Situation) -> Situation:
        """Upserts a situation into the store."""
        existing = self.get(situation.id)
        if existing:
            return self.update_situation(
                situation_id=situation.id,
                type=situation.type,
                status=situation.status,
                priority=situation.priority,
                novelty=situation.novelty,
                context=situation.context,
                evidence=situation.evidence,
                related_goals=situation.related_goals,
            ) or situation
        else:
            return self.create(situation)

    def update(
        self,
        situation_id: Union[str, Situation],
        type: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        novelty: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[Any]] = None,
        related_goals: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
        last_evaluated_at: Optional[datetime] = None,
        next_evaluation_at: Optional[datetime] = None,
        clear_next_evaluation: bool = False,
    ) -> Optional[Situation]:
        """
        Updates an existing situation's fields and advances updated_at.
        Returns the updated Situation, or None if not found.
        """
        if isinstance(situation_id, Situation):
            actual_id = situation_id.id
            existing = self.get(actual_id)
            if existing is None:
                return None
            new_type = type if type is not None else situation_id.type
            new_status = status if status is not None else situation_id.status
            new_priority = priority if priority is not None else situation_id.priority
            new_novelty = novelty if novelty is not None else situation_id.novelty
            new_context = context if context is not None else situation_id.context
            new_evidence = evidence if evidence is not None else situation_id.evidence
            new_goals = related_goals if related_goals is not None else situation_id.related_goals
            new_expires_at = expires_at if expires_at is not None else situation_id.expires_at
            new_last_eval = last_evaluated_at if last_evaluated_at is not None else situation_id.last_evaluated_at
            if clear_next_evaluation:
                new_next_eval = None
            elif next_evaluation_at is not None:
                new_next_eval = next_evaluation_at
            else:
                new_next_eval = situation_id.next_evaluation_at
        else:
            actual_id = situation_id
            existing = self.get(actual_id)
            if existing is None:
                return None
            new_type = type if type is not None else existing.type
            new_status = status if status is not None else existing.status
            new_priority = priority if priority is not None else existing.priority
            new_novelty = novelty if novelty is not None else existing.novelty
            new_context = context if context is not None else existing.context
            new_evidence = evidence if evidence is not None else existing.evidence
            new_goals = related_goals if related_goals is not None else existing.related_goals
            new_expires_at = expires_at if expires_at is not None else existing.expires_at
            new_last_eval = last_evaluated_at if last_evaluated_at is not None else existing.last_evaluated_at
            if clear_next_evaluation:
                new_next_eval = None
            elif next_evaluation_at is not None:
                new_next_eval = next_evaluation_at
            else:
                new_next_eval = existing.next_evaluation_at

        now = datetime.now(timezone.utc)

        updated_situation = Situation(
            id=existing.id,
            type=new_type,
            status=new_status,
            priority=new_priority,
            novelty=new_novelty,
            context=new_context,
            evidence=new_evidence,
            related_goals=new_goals,
            created_at=existing.created_at,
            updated_at=now,
            last_evaluated_at=new_last_eval,
            next_evaluation_at=new_next_eval,
            expires_at=new_expires_at,
        )

        query = """
            UPDATE situations
            SET type = ?, status = ?, priority = ?, novelty = ?,
                context_json = ?, evidence_json = ?, related_goals_json = ?,
                expires_at = ?, last_evaluated_at = ?, next_evaluation_at = ?, updated_at = ?
            WHERE id = ?;
        """
        params = (
            updated_situation.type,
            updated_situation.status,
            updated_situation.priority,
            updated_situation.novelty,
            json.dumps(updated_situation.context, sort_keys=True, ensure_ascii=False),
            json.dumps(updated_situation.evidence, ensure_ascii=False),
            json.dumps(updated_situation.related_goals, ensure_ascii=False),
            format_iso8601(updated_situation.expires_at) if updated_situation.expires_at else None,
            format_iso8601(updated_situation.last_evaluated_at) if updated_situation.last_evaluated_at else None,
            format_iso8601(updated_situation.next_evaluation_at) if updated_situation.next_evaluation_at else None,
            format_iso8601(updated_situation.updated_at),
            updated_situation.id,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return updated_situation
        finally:
            conn.close()

    def schedule_reevaluation(
        self,
        situation_id: str,
        next_evaluation_at: datetime,
    ) -> Optional[Situation]:
        """Schedules a future re-evaluation and transitions situation to MONITORING status."""
        existing = self.get(situation_id)
        if existing is None:
            return None

        next_dt = ensure_timezone_aware(next_evaluation_at, "next_evaluation_at")
        new_status = SituationStatus.MONITORING.value if existing.status == SituationStatus.OPEN.value else existing.status

        return self.update(
            situation_id=situation_id,
            status=new_status,
            next_evaluation_at=next_dt,
        )

    def get_due_reevaluations(
        self,
        as_of: Optional[datetime] = None,
    ) -> List[Situation]:
        """Retrieves all active situations whose scheduled re-evaluation time has arrived."""
        ref_dt = as_of if as_of is not None else datetime.now(timezone.utc)
        ref_iso = format_iso8601(ensure_timezone_aware(ref_dt, "as_of"))

        query = """
            SELECT * FROM situations
            WHERE status IN ('open', 'monitoring')
              AND next_evaluation_at IS NOT NULL
              AND next_evaluation_at <= ?
            ORDER BY next_evaluation_at ASC;
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (ref_iso,))
            rows = cursor.fetchall()
            return [self._row_to_situation(r) for r in rows]
        finally:
            conn.close()

    def list_open(self, priority: Optional[str] = None) -> List[Situation]:
        """Lists all open situations, optionally filtered by priority."""
        clauses = ["status = 'open'"]
        params = []

        if priority is not None:
            clauses.append("priority = ?")
            params.append(priority)

        where_stmt = f"WHERE {' AND '.join(clauses)}"
        query = f"SELECT * FROM situations {where_stmt} ORDER BY created_at DESC;"

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_situation(r) for r in rows]
        finally:
            conn.close()

    def list_active(self, limit: Optional[int] = None) -> List[Situation]:
        """Lists all active situations (OPEN or MONITORING)."""
        if limit is not None:
            query = "SELECT * FROM situations WHERE status IN ('open', 'monitoring') ORDER BY updated_at DESC LIMIT ?;"
            params = (limit,)
        else:
            query = "SELECT * FROM situations WHERE status IN ('open', 'monitoring') ORDER BY updated_at DESC;"
            params = ()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_situation(r) for r in rows]
        finally:
            conn.close()

    def get_active_situations(self, limit: Optional[int] = None) -> List[Situation]:
        """Alias for list_active()."""
        return self.list_active(limit=limit)

    def list_all(self, limit: Optional[int] = None) -> List[Situation]:
        """Lists all situations across all statuses ordered by created_at DESC."""
        if limit is not None:
            query = "SELECT * FROM situations ORDER BY created_at DESC LIMIT ?;"
            params = (limit,)
        else:
            query = "SELECT * FROM situations ORDER BY created_at DESC;"
            params = ()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_situation(r) for r in rows]
        finally:
            conn.close()


    def resolve(
        self,
        situation_id: str,
        resolution_notes: Optional[str] = None,
    ) -> Optional[Situation]:
        """Marks a situation as RESOLVED, clears future re-evaluations, and saves resolution notes."""
        existing = self.get(situation_id)
        if existing is None:
            return None

        context = dict(existing.context)
        if resolution_notes:
            context["resolution_notes"] = resolution_notes

        return self.update(
            situation_id=situation_id,
            status=SituationStatus.RESOLVED.value,
            context=context,
            clear_next_evaluation=True,
        )

    def close(
        self,
        situation_id: str,
        resolution_notes: Optional[str] = None,
    ) -> Optional[Situation]:
        """Closes an open situation and optionally appends resolution notes to its context."""
        existing = self.get(situation_id)
        if existing is None:
            return None

        context = dict(existing.context)
        if resolution_notes:
            context["resolution_notes"] = resolution_notes

        return self.update(
            situation_id=situation_id,
            status=SituationStatus.CLOSED.value,
            context=context,
            clear_next_evaluation=True,
        )

    def suppress(
        self,
        situation_id: str,
        suppress_until: Optional[datetime] = None,
        reason: Optional[str] = None,
    ) -> Optional[Situation]:
        """Marks a situation as SUPPRESSED."""
        existing = self.get(situation_id)
        if existing is None:
            return None

        context = dict(existing.context)
        if reason:
            context["suppression_reason"] = reason

        return self.update(
            situation_id=situation_id,
            status=SituationStatus.SUPPRESSED.value,
            context=context,
            next_evaluation_at=suppress_until,
        )

    def expire(
        self,
        as_of_time: Optional[Union[datetime, str]] = None,
    ) -> List[Situation]:
        """
        Sweeps active situations whose expires_at is in the past, marks them as 'expired',
        and returns the list of newly expired situations.
        """
        if as_of_time is None:
            ref_time = datetime.now(timezone.utc)
        else:
            ref_time = ensure_timezone_aware(as_of_time, "as_of_time")

        ref_iso = format_iso8601(ref_time)
        select_query = """
            SELECT * FROM situations
            WHERE status IN ('open', 'monitoring')
              AND expires_at IS NOT NULL
              AND expires_at <= ?;
        """
        update_query = """
            UPDATE situations
            SET status = 'expired', updated_at = ?
            WHERE id = ?;
        """

        conn = self._get_connection()
        expired_situations: List[Situation] = []
        try:
            cursor = conn.cursor()
            cursor.execute(select_query, (ref_iso,))
            rows = cursor.fetchall()
            now_iso = format_iso8601(datetime.now(timezone.utc))

            with conn:
                for row in rows:
                    sit = self._row_to_situation(row)
                    sit.status = SituationStatus.EXPIRED.value
                    sit.updated_at = ensure_timezone_aware(now_iso, "updated_at")
                    cursor.execute(update_query, (now_iso, sit.id))
                    expired_situations.append(sit)

            return expired_situations
        finally:
            conn.close()

    def find_similar(
        self,
        situation_type: Optional[str] = None,
        related_goals: Optional[List[str]] = None,
        active_only: bool = False,
    ) -> List[Situation]:
        """Queries situations by type and/or shared related goals."""
        clauses = []
        params = []

        if active_only:
            clauses.append("status IN ('open', 'monitoring')")

        if situation_type:
            clauses.append("type = ?")
            params.append(situation_type)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM situations {where_clause} ORDER BY created_at DESC;"

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            situations = [self._row_to_situation(r) for r in rows]

            if not related_goals or situation_type:
                return situations

            target_goals = set(related_goals)
            matching = []
            for s in situations:
                if set(s.related_goals) & target_goals:
                    matching.append(s)
            return matching
        finally:
            conn.close()
