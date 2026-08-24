"""
Structured audit logger for access to sensitive personal context.
Tracks every invocation where personal state, events, or situations are assembled
for Hermes reasoning runtime or external inspection.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.storage.db import DatabaseManager


@dataclass
class ContextAccessRecord:
    """
    Structured record representing an access event to personal context.
    """
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    accessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    accessor: str = "hermes_reasoning"
    situation_id: Optional[str] = None
    events_accessed_count: int = 0
    features_accessed: List[str] = field(default_factory=list)
    sensitivity_level: str = "standard"  # "standard" | "sensitive" | "critical"
    purpose: str = "Bounded situational reasoning"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes audit record to dictionary."""
        return {
            "audit_id": self.audit_id,
            "accessed_at": format_iso8601(self.accessed_at),
            "accessor": self.accessor,
            "situation_id": self.situation_id,
            "events_accessed_count": self.events_accessed_count,
            "features_accessed": self.features_accessed,
            "sensitivity_level": self.sensitivity_level,
            "purpose": self.purpose,
            "metadata": self.metadata,
        }


class ContextAccessAuditor:
    """
    Audits and records access to personal data and reasoning contexts in SQLite.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

    def record_access(
        self,
        accessor: str,
        situation_id: Optional[str] = None,
        events_accessed_count: int = 0,
        features_accessed: Optional[List[str]] = None,
        sensitivity_level: str = "standard",
        purpose: str = "Bounded situational reasoning",
        metadata: Optional[Dict[str, Any]] = None,
        accessed_at: Optional[datetime] = None,
    ) -> ContextAccessRecord:
        """
        Persists a context access audit record to the context_access_audit table.
        """
        now = ensure_timezone_aware(accessed_at or datetime.now(timezone.utc), "accessed_at")
        record = ContextAccessRecord(
            audit_id=str(uuid.uuid4()),
            accessed_at=now,
            accessor=accessor,
            situation_id=situation_id,
            events_accessed_count=events_accessed_count,
            features_accessed=features_accessed or [],
            sensitivity_level=sensitivity_level,
            purpose=purpose,
            metadata=metadata or {},
        )

        query = """
            INSERT INTO context_access_audit (
                audit_id, accessed_at, accessor, situation_id,
                events_accessed_count, features_accessed_json,
                sensitivity_level, purpose, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            record.audit_id,
            format_iso8601(record.accessed_at),
            record.accessor,
            record.situation_id,
            record.events_accessed_count,
            json.dumps(record.features_accessed, ensure_ascii=False),
            record.sensitivity_level,
            record.purpose,
            json.dumps(record.metadata, ensure_ascii=False) if record.metadata else None,
        )

        conn = self.db_manager.get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return record
        finally:
            conn.close()

    def list_access_records(
        self,
        situation_id: Optional[str] = None,
        accessor: Optional[str] = None,
        limit: int = 50,
    ) -> List[ContextAccessRecord]:
        """
        Retrieves context access audit records ordered by accessed_at descending.
        """
        clauses = []
        params = []
        if situation_id:
            clauses.append("situation_id = ?")
            params.append(situation_id)
        if accessor:
            clauses.append("accessor = ?")
            params.append(accessor)

        where_stmt = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM context_access_audit {where_stmt} ORDER BY accessed_at DESC LIMIT ?;"
        params.append(limit)

        conn = self.db_manager.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            records = []
            for r in rows:
                feats = json.loads(r["features_accessed_json"]) if r["features_accessed_json"] else []
                meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
                records.append(
                    ContextAccessRecord(
                        audit_id=r["audit_id"],
                        accessed_at=ensure_timezone_aware(r["accessed_at"], "accessed_at"),
                        accessor=r["accessor"],
                        situation_id=r["situation_id"],
                        events_accessed_count=int(r["events_accessed_count"]),
                        features_accessed=feats,
                        sensitivity_level=r["sensitivity_level"],
                        purpose=r["purpose"],
                        metadata=meta,
                    )
                )
            return records
        finally:
            conn.close()
