"""Entity Resolution domain models.

Provides EntityResolutionResult carrying resolution outcome, matched entity,
candidate entities, match reason, confidence, and human review flags.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.entities import Entity
from app.domain.values import ConfidenceScore


class EntityResolutionResult(BaseModel):
    """Result of attempting to resolve an extracted entity against existing World Model state."""

    matched_entity: Entity | None = Field(
        default=None,
        description="The resolved existing entity, or None if ambiguous or new.",
    )
    candidate_entities: list[Entity] = Field(
        default_factory=list,
        description="Potential matching existing entities evaluated during resolution.",
    )
    match_reason: str = Field(
        default="",
        description="Deterministic rule or rationale for the resolution decision.",
    )
    confidence: ConfidenceScore = Field(
        description="Calibrated confidence score in the resolution decision.",
    )
    requires_review: bool = Field(
        default=False,
        description="Flag indicating if the resolution is ambiguous and requires human review.",
    )
