"""Claim domain model.

A Claim is a structured proposition derived from one or more Observations.
Claims are NOT automatically truth — they have a lifecycle:

    proposed → supported / contested → confirmed / withdrawn

Claims accumulate evidence over time. Contradictory evidence moves a
claim to 'contested' status rather than silently overwriting it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import ClaimStatus
from app.domain.values import (
    ConfidenceScore,
    EvidenceSpan,
    Provenance,
    TemporalReference,
    _new_id,
    _utcnow,
)


class Claim(BaseModel):
    """A structured proposition about the user's world.

    Claims are the intermediary between raw Observations and the
    Personal World Model. They make the system's beliefs explicit
    and auditable.

    A Claim is NOT an Observation or a Fact — it has a status lifecycle
    and confidence that can change as new evidence arrives.
    """

    id: str = Field(default_factory=_new_id, description="Unique claim identifier.")
    subject: str = Field(
        description="What the claim is about (e.g. entity ID, topic, or free-text subject)."
    )
    predicate: str = Field(
        description="The property or relationship being asserted (e.g. 'works_at', 'lives_in')."
    )
    value: str = Field(description="The asserted value (e.g. 'Google', 'San Francisco').")
    status: ClaimStatus = Field(
        default=ClaimStatus.PROPOSED,
        description="Current lifecycle state of this claim.",
    )
    confidence: ConfidenceScore = Field(
        description="How confident the system is in this claim.",
    )
    evidence_spans: list[EvidenceSpan] = Field(
        default_factory=list,
        description="Text spans grounding this claim in source observations.",
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence items that support or contest this claim.",
    )
    temporal: TemporalReference | None = Field(
        default=None,
        description="Optional temporal reference associated with this claim.",
    )
    first_observed_at: datetime = Field(
        default_factory=_utcnow,
        description="When this claim was first derived.",
    )
    last_evaluated_at: datetime = Field(
        default_factory=_utcnow,
        description="When this claim's status was last updated.",
    )
    provenance: Provenance = Field(
        default_factory=Provenance,
        description="How this claim was derived.",
    )
