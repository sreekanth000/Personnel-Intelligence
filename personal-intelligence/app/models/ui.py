"""Presentation-friendly Data Transfer Objects (DTOs) for UI read-only APIs (/api/v1/ui/*).

Ensures database objects and raw entities are decoupled from presentation responses.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, Field

from app.domain import EvidenceSpan

T = TypeVar("T")


class PaginatedResponse[T](BaseModel):
    """Generic paginated envelope for list endpoints."""

    items: list[T]
    total: int
    page: int
    limit: int
    has_more: bool


class UIGraphNode(BaseModel):
    """Presentation node for Kuzu graph representation."""

    id: str
    type: str
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class UIGraphEdge(BaseModel):
    """Presentation edge for Kuzu graph relationship edges."""

    id: str
    source: str
    target: str
    relationship_type: str
    confidence: float
    status: str  # "active" | "closed" | "uncertain"
    evidence_count: int = 0
    valid_from: str | None = None
    valid_to: str | None = None


class UIGraphDTO(BaseModel):
    """Small, optimized graph payload."""

    nodes: list[UIGraphNode]
    edges: list[UIGraphEdge]


class UIEntityDTO(BaseModel):
    """Presentation entity object."""

    id: str
    type: str
    name: str
    canonical_name: str | None = None
    email: str | None = None
    domain: str | None = None
    aliases: list[str] = Field(default_factory=list)
    confidence: float
    created_at: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class UIRelationshipDTO(BaseModel):
    """Presentation relationship object."""

    id: str
    subject_id: str
    subject_name: str
    predicate: str
    object_id: str
    object_name: str
    confidence: float
    status: str
    valid_from: str | None = None
    valid_to: str | None = None


class UIExtractionItemDTO(BaseModel):
    """Extracted item DTO for inspection."""

    id: str
    extraction_type: str  # "entity" | "relationship" | "claim" | "event" | "goal" | "project" | "decision" | "preference" | "constraint"
    value: str
    entity_type: str | None = None
    predicate: str | None = None
    subject: str | None = None
    object: str | None = None
    confidence: float
    evidence_span: EvidenceSpan


class UIEmailDTO(BaseModel):
    """Presentation object for raw observation email lineage."""

    id: str
    message_id: str
    thread_id: str
    sender: str
    recipients: list[str]
    subject: str
    timestamp: str
    snippet: str
    labels: list[str] = Field(default_factory=list)
    extracted_entities_count: int = 0


class UIEmailDetailDTO(BaseModel):
    """Detailed 3-column presentation object for email inspection."""

    id: str
    message_id: str
    thread_id: str
    sender: str
    recipients: list[str]
    subject: str
    timestamp: str
    snippet: str
    body: str
    labels: list[str] = Field(default_factory=list)
    extractions: list[UIExtractionItemDTO] = Field(default_factory=list)


class UIEvidenceDTO(BaseModel):
    """Presentation object for evidence records."""

    id: str
    observation_id: str
    source_message_id: str | None = None
    target_id: str
    target_type: str
    text_snippet: str
    confidence: float
    recorded_at: str


class UIDecisionDTO(BaseModel):
    """Presentation decision memory record."""

    id: str
    name: str
    question: str | None = None
    decision: str | None = None
    alternatives: list[str] = Field(default_factory=list)
    context: str | None = None
    status: str
    confidence: float
    created_at: str


class UIStateChangeDTO(BaseModel):
    """Presentation state change audit record."""

    id: str
    observation_id: str
    entity_id: str | None = None
    outcome: str
    description: str
    previous_value: str | None = None
    new_value: str | None = None
    requires_review: bool
    timestamp: str


class UITimelineItemDTO(BaseModel):
    """Presentation timeline element."""

    id: str
    timestamp: str
    type: str
    title: str
    description: str
    outcome: str | None = None
    requires_review: bool = False


class UIOverviewDTO(BaseModel):
    """Synthesized presentation overview dashboard payload."""

    active_projects_count: int
    active_relationships_count: int
    recent_changes_count: int
    unresolved_conflicts_count: int
    active_projects: list[UIEntityDTO]
    recent_state_changes: list[UIStateChangeDTO]
    unresolved_conflicts: list[dict[str, Any]]


class UISearchResultDTO(BaseModel):
    """Global search result presentation model."""

    id: str
    result_type: str
    subtype: str | None = None
    title: str
    current_status: str | None = None
    timestamp: str | None = None
    confidence: float | None = None
    evidence_count: int | None = None
    snippet: str | None = None


class UIMyWorldNode(BaseModel):
    """Presentation node for the My World curated canvas."""

    id: str
    label: str
    category: str  # people, projects, organizations, goals, decisions
    epistemic_state: str  # OBSERVED, INFERRED, USER_CONFIRMED, CONFLICTING, UNCERTAIN, HISTORICAL
    confidence: float


class UIMyWorldEdge(BaseModel):
    """Presentation edge for the My World curated canvas."""

    id: str
    source: str
    target: str
    label: str
    epistemic_state: str
    confidence: float


class UIMyWorldDTO(BaseModel):
    """Full payload for the My World canvas."""

    nodes: list[UIMyWorldNode]
    edges: list[UIMyWorldEdge]
