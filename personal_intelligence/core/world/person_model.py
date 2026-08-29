"""
Theory of Mind & Interpersonal Dynamics Engine for Personal Intelligence.

Models key people in the user's life (manager, team leads, clients, family)
with metrics for response latency, priority sensitivity, communication channel preference,
and pending commitments.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.events.models import ensure_timezone_aware, format_iso8601
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class PersonEntity:
    """Represents a person profile with interpersonal Theory of Mind metrics."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    relationship_role: str = "collaborator"  # manager, teammate, client, family, mentor
    email: Optional[str] = None
    avg_response_delay_mins: float = 60.0  # Historical turnaround lag
    priority_sensitivity: float = 0.5     # 0.0 (lax) to 1.0 (strict deadline enforcement)
    preferred_channel: str = "email"       # email, slack, meet, phone
    metadata: Dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.updated_at = ensure_timezone_aware(self.updated_at, "PersonEntity updated_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "relationship_role": self.relationship_role,
            "email": self.email,
            "avg_response_delay_mins": self.avg_response_delay_mins,
            "priority_sensitivity": self.priority_sensitivity,
            "preferred_channel": self.preferred_channel,
            "metadata": self.metadata,
            "updated_at": format_iso8601(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonEntity":
        meta = data.get("metadata", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            relationship_role=data.get("relationship_role", "collaborator"),
            email=data.get("email"),
            avg_response_delay_mins=float(data.get("avg_response_delay_mins", 60.0)),
            priority_sensitivity=float(data.get("priority_sensitivity", 0.5)),
            preferred_channel=data.get("preferred_channel", "email"),
            metadata=meta,
            updated_at=ensure_timezone_aware(data.get("updated_at", datetime.now(timezone.utc)), "updated_at"),
        )


class PersonModelEngine:
    """Manages Person Profiles and Theory of Mind interpersonal dynamics in SQLite."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()

    def upsert_person(self, person: PersonEntity) -> PersonEntity:
        """Upserts a person profile with relationship role and metrics."""
        conn = self.db_manager.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO person_profiles (id, name, relationship_role, email, avg_response_delay_mins, priority_sensitivity, preferred_channel, metadata_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        relationship_role = excluded.relationship_role,
                        email = excluded.email,
                        avg_response_delay_mins = excluded.avg_response_delay_mins,
                        priority_sensitivity = excluded.priority_sensitivity,
                        preferred_channel = excluded.preferred_channel,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        person.id,
                        person.name,
                        person.relationship_role,
                        person.email,
                        person.avg_response_delay_mins,
                        person.priority_sensitivity,
                        person.preferred_channel,
                        json.dumps(person.metadata),
                        format_iso8601(person.updated_at),
                    ),
                )
            return person
        finally:
            conn.close()

    def get_person_by_name_or_email(self, identifier: str) -> Optional[PersonEntity]:
        """Resolves person entity by name or email string."""
        if not identifier:
            return None
        target = identifier.lower().strip()

        conn = self.db_manager.get_connection()
        try:
            rows = conn.execute("SELECT * FROM person_profiles").fetchall()
            for r in rows:
                d = dict(r)
                if d.get("name", "").lower() == target or (d.get("email") and d.get("email", "").lower() == target):
                    return PersonEntity.from_dict(d)
            return None
        finally:
            conn.close()

    def evaluate_interpersonal_urgency(self, sender_name: str, message_summary: str) -> float:
        """
        Computes interpersonal urgency multiplier (1.0 to 2.0) based on Theory of Mind profile.
        Higher sensitivity roles (e.g. Manager) boost priority score.
        """
        person = self.get_person_by_name_or_email(sender_name)
        if not person:
            return 1.0

        urgency_multiplier = 1.0 + (0.5 * person.priority_sensitivity)
        if person.relationship_role == "manager":
            urgency_multiplier += 0.3
        elif person.relationship_role == "client":
            urgency_multiplier += 0.2

        return min(2.0, urgency_multiplier)
