"""WorldState and StateChange domain models.

WorldState is a temporal snapshot of the user's personal world model
at a given point in time. It aggregates active entities, relationships,
claims, and the user's current cognitive context.

StateChange records how a reconciliation event modified the world state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import ReconciliationOutcome
from app.domain.values import Provenance, _new_id, _utcnow


class StateChange(BaseModel):
    """A record of a single change to the world state.

    Created during reconciliation to maintain a full audit trail.
    Every state change references the observation that triggered it
    and describes what happened.
    """

    id: str = Field(default_factory=_new_id, description="Unique state change identifier.")
    observation_id: str = Field(description="The observation that triggered this state change.")
    entity_id: str | None = Field(
        default=None,
        description="The entity that was affected, if applicable.",
    )
    claim_id: str | None = Field(
        default=None,
        description="The claim that was affected, if applicable.",
    )
    outcome: ReconciliationOutcome = Field(description="What happened during reconciliation.")
    description: str = Field(description="Human-readable description of the change.")
    previous_value: str | None = Field(
        default=None,
        description="The value before the change, if applicable.",
    )
    new_value: str | None = Field(
        default=None,
        description="The value after the change, if applicable.",
    )
    changed_at: datetime = Field(
        default_factory=_utcnow,
        description="When this change occurred.",
    )
    provenance: Provenance = Field(
        default_factory=Provenance,
        description="How this change was derived.",
    )


class WorldState(BaseModel):
    """A temporal snapshot of the personal world model.

    WorldState is always associated with a point-in-time. The system
    can reconstruct the user's world model at any past moment by
    replaying StateChanges up to that timestamp.

    This model captures the *current* state — the set of active
    entity IDs, relationship IDs, and claim IDs that are valid right now.
    """

    id: str = Field(default_factory=_new_id, description="Unique state snapshot identifier.")
    timestamp: datetime = Field(
        default_factory=_utcnow,
        description="The point in time this state represents.",
    )
    active_entity_ids: list[str] = Field(
        default_factory=list,
        description="Entity IDs that are active at this point in time.",
    )
    active_relationship_ids: list[str] = Field(
        default_factory=list,
        description="Relationship IDs that are valid at this point in time.",
    )
    active_claim_ids: list[str] = Field(
        default_factory=list,
        description="Claim IDs that are in supported or confirmed status.",
    )
    pending_claim_ids: list[str] = Field(
        default_factory=list,
        description="Claim IDs that are proposed but not yet supported/contested.",
    )
    recent_changes: list[str] = Field(
        default_factory=list,
        description="StateChange IDs from the most recent reconciliation cycle.",
    )


class SynthesizedCurrentState(BaseModel):
    """Deterministic snapshot synthesizing current active world state.

    Constructed strictly from structured World Model data without LLM generation.
    """

    timestamp: datetime = Field(default_factory=_utcnow, description="Snapshot timestamp.")
    active_people_relationships: list[Any] = Field(
        default_factory=list,
        description="Currently active relationships involving person entities.",
    )
    active_projects: list[Any] = Field(
        default_factory=list,
        description="Currently active projects.",
    )
    active_goals: list[Any] = Field(
        default_factory=list,
        description="Currently active goals.",
    )
    recent_decisions: list[Any] = Field(
        default_factory=list,
        description="Recently made or pending decisions.",
    )
    recent_events: list[Any] = Field(
        default_factory=list,
        description="Recent or upcoming events.",
    )
    important_constraints: list[Any] = Field(
        default_factory=list,
        description="Active constraints influencing decision context.",
    )
    recent_state_changes: list[StateChange] = Field(
        default_factory=list,
        description="Recent historical StateChange records.",
    )
    unresolved_conflicts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Conflicting relationships or claims flagged for review.",
    )
