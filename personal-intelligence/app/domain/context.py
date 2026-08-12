"""ContextRequest and ContextPackage domain models.

Context is a task-specific subset of the Personal World Model supplied to an AI system.
ContextRequest defines the query, task intent, privacy constraints, and temporal parameters.
ContextPackage is the filtered, evidence-weighted, purpose-specific subset of state returned by the Context Engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.claims import Claim
from app.domain.entities import Entity, Relationship
from app.domain.values import _new_id, _utcnow


class ContextRequest(BaseModel):
    """A request for a task-specific subset of personal context.

    Sent to the Context Engine when an AI task or client needs personal context.
    Specifies the task intent, topic scope, privacy limits, and temporal bounds.
    """

    id: str = Field(default_factory=_new_id, description="Unique context request identifier.")
    task_intent: str = Field(
        description="High-level intent of the task requesting context (e.g. 'draft_email', 'schedule_meeting')."
    )
    query: str = Field(
        default="",
        description="Free-text query or topic description guiding retrieval.",
    )
    target_entity_ids: list[str] = Field(
        default_factory=list,
        description="Specific entity IDs that must be included if relevant.",
    )
    max_items: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of context items to include in the package.",
    )
    purpose: str = Field(
        default="general",
        description="Declared purpose for the context request.",
    )
    start_date: datetime | None = Field(
        default=None,
        description="Optional start date threshold for temporal filtering.",
    )
    end_date: datetime | None = Field(
        default=None,
        description="Optional end date threshold for temporal filtering.",
    )
    as_of_date: datetime | None = Field(
        default=None,
        description="Optional snapshot date for point-in-time state evaluation.",
    )
    recent_days: int | None = Field(
        default=None,
        description="Optional limit restricting context to items active within N recent days.",
    )
    requested_at: datetime = Field(
        default_factory=_utcnow,
        description="When the request was issued.",
    )


class ContextPackage(BaseModel):
    """A filtered, purpose-specific subset of the Personal World Model.

    Produced by the Context Engine and passed through the Privacy / Context Firewall
    before being exposed to AI clients or external tools (MCP).
    """

    id: str = Field(default_factory=_new_id, description="Unique context package identifier.")
    request_id: str = Field(description="ID of the ContextRequest that generated this package.")
    purpose: str = Field(
        default="general",
        description="Declared purpose passed from ContextRequest.",
    )
    entities: list[Entity] = Field(
        default_factory=list,
        description="Entities matching the request criteria, ranked by relevance.",
    )
    relationships: list[Relationship] = Field(
        default_factory=list,
        description="Active relationships connecting matched entities.",
    )
    claims: list[Claim] = Field(
        default_factory=list,
        description="Claims grounded by evidence related to matched entities.",
    )
    decisions: list[Entity] = Field(
        default_factory=list,
        description="Relevant decision entities.",
    )
    events: list[Entity] = Field(
        default_factory=list,
        description="Relevant event entities.",
    )
    commitments: list[Entity] = Field(
        default_factory=list,
        description="Active commitments and promises.",
    )
    evidence: list[Any] = Field(
        default_factory=list,
        description="Supporting evidence records linking items to source observations.",
    )
    state_changes: list[Any] = Field(
        default_factory=list,
        description="Recent state change log entries.",
    )
    summary: str = Field(
        default="",
        description="Human-readable summary of the context package contents.",
    )
    assembled_at: datetime = Field(
        default_factory=_utcnow,
        description="Timestamp when context package was assembled.",
    )
    filtered_count: int = Field(
        default=0,
        description="Count of items removed by privacy or confidence filtering.",
    )
