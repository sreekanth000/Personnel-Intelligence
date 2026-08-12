"""Entity and Relationship domain models, plus entity subtypes.

Entities are the nodes of the Personal World Model graph.
Relationships are the typed, temporally-bounded edges between entities.

Entity subtypes (Event, Goal, Project, Task, Decision, Preference,
Constraint, Commitment) add domain-specific required fields on top
of the base Entity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import DecisionStatus, EntityType, RelationshipType
from app.domain.values import (
    ConfidenceScore,
    EvidenceSpan,
    Provenance,
    TemporalRange,
    TemporalReference,
    _new_id,
    _utcnow,
)

# ---------------------------------------------------------------------------
# Base Entity
# ---------------------------------------------------------------------------


class Entity(BaseModel):
    """A node in the personal world model graph."""

    id: str = Field(default_factory=_new_id, description="Unique entity identifier.")
    entity_type: EntityType = Field(description="Classification of this entity.")
    name: str = Field(description="Human-readable name.")
    description: str = Field(default="", description="Optional longer description.")
    confidence: ConfidenceScore = Field(
        description="How confident the system is about this entity."
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Known aliases, alternate names, or email addresses for this entity.",
    )
    email: str | None = Field(
        default=None,
        description="Canonical normalized email address if entity is a PERSON.",
    )
    domain: str | None = Field(
        default=None,
        description="Canonical organization domain if entity is an ORGANIZATION.",
    )
    temporal: TemporalReference | None = Field(
        default=None,
        description="Optional temporal reference associated with this entity.",
    )
    provenance: Provenance = Field(
        default_factory=Provenance,
        description="How this entity was derived.",
    )
    created_at: datetime = Field(
        default_factory=_utcnow, description="When this entity was created."
    )
    updated_at: datetime = Field(
        default_factory=_utcnow, description="When this entity was last updated."
    )


# ---------------------------------------------------------------------------
# Relationship (edge)
# ---------------------------------------------------------------------------


class Relationship(BaseModel):
    """A typed, evidence-grounded edge between two entities in the world model.

    Every extracted relationship MUST contain:
    subject, predicate, object, confidence, evidence_span, source_observation_id.
    """

    id: str = Field(default_factory=_new_id, description="Unique relationship identifier.")
    subject: str = Field(description="Subject entity ID or reference name.")
    predicate: RelationshipType | str = Field(
        description="Typed relationship predicate (e.g. WORKS_FOR, OWNS)."
    )
    object: str = Field(description="Object/target entity ID or reference name.")
    confidence: ConfidenceScore = Field(description="Confidence score in this relationship.")
    evidence_span: EvidenceSpan | None = Field(
        default=None,
        description="Exact text excerpt grounding this relationship in the source observation.",
    )
    source_observation_id: str = Field(
        default="",
        description="ID of the source Observation from which this relationship was extracted.",
    )
    validity: TemporalRange = Field(
        default_factory=TemporalRange,
        description="Temporal validity range (valid_from, valid_to).",
    )
    provenance: Provenance = Field(
        default_factory=Provenance,
        description="Lineage tracking how this relationship was derived.",
    )
    properties: dict[str, str] = Field(
        default_factory=dict,
        description="Additional typed properties of the relationship.",
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="before")
    @classmethod
    def _remap_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "source_entity_id" in data and "subject" not in data:
                data["subject"] = data["source_entity_id"]
            if "target_entity_id" in data and "object" not in data:
                data["object"] = data["target_entity_id"]
            if "relationship_type" in data and "predicate" not in data:
                data["predicate"] = data["relationship_type"]
        return data

    @property
    def source_entity_id(self) -> str:
        """Alias for subject entity identifier."""
        return self.subject

    @property
    def target_entity_id(self) -> str:
        """Alias for object entity identifier."""
        return self.object

    @property
    def relationship_type(self) -> str:
        """Alias for predicate relationship type string."""
        return str(self.predicate)


# ---------------------------------------------------------------------------
# Entity subtypes
# ---------------------------------------------------------------------------


class Event(Entity):
    """A calendar event, meeting, or scheduled occurrence."""

    entity_type: EntityType = Field(default=EntityType.EVENT, description="Always 'event'.")
    starts_at: datetime | None = Field(default=None, description="When the event starts.")
    ends_at: datetime | None = Field(default=None, description="When the event ends.")
    location: str | None = Field(default=None, description="Where the event takes place.")
    attendees: list[str] = Field(default_factory=list, description="Entity IDs of attendees.")


class Goal(Entity):
    """A desired outcome the user is working toward."""

    entity_type: EntityType = Field(default=EntityType.GOAL, description="Always 'goal'.")
    target_date: datetime | None = Field(
        default=None, description="When the goal should be achieved."
    )
    status: str = Field(
        default="active", description="Current status (active, achieved, abandoned)."
    )


class Project(Entity):
    """An ongoing body of work with a defined scope."""

    entity_type: EntityType = Field(default=EntityType.PROJECT, description="Always 'project'.")
    status: str = Field(default="active", description="Current project status.")
    goal_ids: list[str] = Field(default_factory=list, description="Goals this project serves.")


class Task(Entity):
    """A concrete action item, possibly tied to a project or goal."""

    entity_type: EntityType = Field(default=EntityType.TASK, description="Always 'task'.")
    status: str = Field(
        default="pending", description="Task status (pending, in_progress, done, blocked)."
    )
    due_date: datetime | None = Field(default=None, description="When the task is due.")
    assignee_id: str | None = Field(default=None, description="Entity ID of the assigned person.")
    priority: str = Field(
        default="medium", description="Priority level (low, medium, high, urgent)."
    )


class Decision(Entity):
    """A structured representation of an important decision."""

    entity_type: EntityType = Field(default=EntityType.DECISION, description="Always 'decision'.")
    question: str = Field(description="The question that required a decision.")
    alternatives: list[str] = Field(description="The options that were considered.")
    context: str = Field(description="Background context relevant to the decision.")
    constraints: list[str] = Field(
        default_factory=list,
        description="Constraints that influenced the decision.",
    )
    reasoning: str = Field(
        default="", description="The reasoning process that led to the decision."
    )
    decision: str = Field(default="", description="The actual decision that was made.")
    outcome: str | None = Field(
        default=None, description="The observed outcome of the decision, if known."
    )
    decided_at: datetime | None = Field(default=None, description="When the decision was made.")
    status: DecisionStatus = Field(
        default=DecisionStatus.PENDING,
        description="Current decision lifecycle status.",
    )


class Preference(Entity):
    """A user preference or personal policy."""

    entity_type: EntityType = Field(
        default=EntityType.PREFERENCE, description="Always 'preference'."
    )
    domain: str = Field(
        description="What domain this preference applies to (e.g. 'communication', 'tools')."
    )
    value: str = Field(description="The preference value or rule.")


class Constraint(Entity):
    """An external or self-imposed constraint on the user."""

    entity_type: EntityType = Field(
        default=EntityType.CONSTRAINT, description="Always 'constraint'."
    )
    constraint_type: str = Field(
        description="Type of constraint (e.g. 'time', 'budget', 'policy', 'physical')."
    )
    severity: str = Field(
        default="hard", description="Whether this is a 'hard' or 'soft' constraint."
    )


class Commitment(Entity):
    """A promise or obligation the user has made or received."""

    entity_type: EntityType = Field(
        default=EntityType.COMMITMENT, description="Always 'commitment'."
    )
    committed_to: str = Field(description="Who/what the commitment is to (entity ID or free text).")
    due_date: datetime | None = Field(default=None, description="When the commitment is due.")
    status: str = Field(
        default="open", description="Commitment status (open, fulfilled, broken, cancelled)."
    )
