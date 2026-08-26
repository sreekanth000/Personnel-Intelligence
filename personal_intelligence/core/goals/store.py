"""
Local-first GoalStore for managing contextual user goals.
Goals provide situational context for reasoning (NOT workflow or task planning engines).
"""

from datetime import datetime, timezone
import json
import sqlite3
from typing import List, Optional, Union
import uuid

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.goals.models import (
    Goal,
    GoalPriority,
    GoalStatus,
)
from personal_intelligence.storage.db import DatabaseManager


class GoalStore:
    """
    SQLite-backed store for persisting and querying contextual user goals.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return self.db_manager.get_connection()

    def _row_to_goal(self, row: sqlite3.Row) -> Goal:
        """Converts an SQLite row into a validated Goal object."""
        row_keys = row.keys() if hasattr(row, "keys") else []
        parent_id = row["parent_goal_id"] if "parent_goal_id" in row_keys else None
        sub_ids_str = row["sub_goal_ids_json"] if "sub_goal_ids_json" in row_keys else "[]"
        try:
            sub_ids = json.loads(sub_ids_str) if sub_ids_str else []
        except Exception:
            sub_ids = []

        return Goal(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            priority=row["priority"],
            status=row["status"],
            parent_goal_id=parent_id,
            sub_goal_ids=sub_ids,
            created_at=ensure_timezone_aware(row["created_at"], "created_at"),
            updated_at=ensure_timezone_aware(row["updated_at"], "updated_at"),
        )

    def create_goal(
        self,
        name: Union[str, Goal],
        description: str = "",
        priority: str = GoalPriority.MEDIUM.value,
        status: str = GoalStatus.ACTIVE.value,
        goal_id: Optional[str] = None,
    ) -> Goal:
        """Creates and stores a new contextual goal."""
        if isinstance(name, Goal):
            goal = name
        else:
            now = datetime.now(timezone.utc)
            goal = Goal(
                id=goal_id or str(uuid.uuid4()),
                name=name,
                description=description,
                priority=priority,
                status=status,
                created_at=now,
                updated_at=now,
            )

        query = """
            INSERT INTO goals (id, name, description, priority, status, parent_goal_id, sub_goal_ids_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            goal.id,
            goal.name,
            goal.description,
            goal.priority,
            goal.status,
            goal.parent_goal_id,
            json.dumps(goal.sub_goal_ids),
            format_iso8601(goal.created_at),
            format_iso8601(goal.updated_at),
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return goal
        finally:
            conn.close()

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        """Retrieves a single goal by its unique ID, or None if not found."""
        if not goal_id or not isinstance(goal_id, str):
            return None

        query = "SELECT * FROM goals WHERE id = ? LIMIT 1;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (goal_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_goal(row)
            return None
        finally:
            conn.close()

    def get(self, goal_id: str) -> Optional[Goal]:
        """Convenience alias for get_goal."""
        return self.get_goal(goal_id)

    def update_goal(
        self,
        goal_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[Goal]:
        """
        Updates an existing goal's attributes and automatically refreshes updated_at.
        Returns the updated Goal object, or None if the goal_id was not found.
        """
        existing = self.get_goal(goal_id)
        if existing is None:
            return None

        new_name = name if name is not None else existing.name
        new_desc = description if description is not None else existing.description
        new_priority = priority if priority is not None else existing.priority
        new_status = status if status is not None else existing.status
        now = datetime.now(timezone.utc)

        # Validate with new fields
        updated_goal = Goal(
            id=existing.id,
            name=new_name,
            description=new_desc,
            priority=new_priority,
            status=new_status,
            created_at=existing.created_at,
            updated_at=now,
        )

        query = """
            UPDATE goals
            SET name = ?, description = ?, priority = ?, status = ?, updated_at = ?
            WHERE id = ?;
        """
        params = (
            updated_goal.name,
            updated_goal.description,
            updated_goal.priority,
            updated_goal.status,
            format_iso8601(updated_goal.updated_at),
            updated_goal.id,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return updated_goal
        finally:
            conn.close()

    def list_active_goals(self) -> List[Goal]:
        """Returns all goals with status 'active' ordered by priority and created_at."""
        query = "SELECT * FROM goals WHERE status = 'active' ORDER BY created_at ASC;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            return [self._row_to_goal(r) for r in rows]
        finally:
            conn.close()

    def get_active_goals(self) -> List[Goal]:
        """Alias for list_active_goals()."""
        return self.list_active_goals()

    def list_active(self) -> List[Goal]:
        """Alias for list_active_goals()."""
        return self.list_active_goals()


    def archive_goal(self, goal_id: str) -> Optional[Goal]:
        """Marks a goal's status as 'archived'."""
        return self.update_goal(goal_id, status=GoalStatus.ARCHIVED.value)

    def list_all_goals(self, status: Optional[str] = None) -> List[Goal]:
        """Lists all goals with optional status filtering."""
        clauses = []
        params = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where_stmt = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM goals {where_stmt} ORDER BY created_at ASC;"

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_goal(r) for r in rows]
        finally:
            conn.close()
