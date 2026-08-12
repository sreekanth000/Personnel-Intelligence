"""Reconciliation domain models.

Provides ReconciliationRecord carrying previous_state, new_state, evidence,
timestamp, reconciliation_reason, outcome, and user confirmation flags.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import ReconciliationOutcome
from app.domain.evidence import Evidence
from app.domain.observations import Observation
from app.domain.values import EvidenceSpan, _new_id, _utcnow


class ReconciliationRecord(BaseModel):
    """Auditable record of reconciling an extracted relationship or claim against existing World Model state."""

    id: str = Field(default_factory=_new_id, description="Unique reconciliation record identifier.")
    outcome: ReconciliationOutcome = Field(
        description="Reconciliation outcome: NOVEL, CONFIRM, REFINE, UPDATE, CONFLICT, UNCERTAIN."
    )
    previous_state: dict[str, Any] | None = Field(
        default=None,
        description="Previous relationship or claim state dictionary if existing state was found.",
    )
    new_state: dict[str, Any] = Field(
        description="New relationship or claim state dictionary derived from extraction.",
    )
    evidence: Evidence | EvidenceSpan | Observation | None = Field(
        default=None,
        description="Evidence grounding this reconciliation step.",
    )
    timestamp: datetime = Field(
        default_factory=_utcnow,
        description="Timestamp when reconciliation occurred.",
    )
    reconciliation_reason: str = Field(
        description="Deterministic reasoning explaining the outcome.",
    )
    requires_user_confirmation: bool = Field(
        default=False,
        description="True if the outcome is ambiguous or conflicting and requires human confirmation.",
    )
    closed_previous_relationship_id: str | None = Field(
        default=None,
        description="If UPDATE occurred, ID of the previous relationship whose validity interval was closed.",
    )

    @property
    def observation_id(self) -> str:
        """Helper property extracting observation ID from evidence if present."""
        if self.evidence is not None:
            if hasattr(self.evidence, "id"):
                return str(self.evidence.id)
            if hasattr(self.evidence, "source_observation_id"):
                return str(self.evidence.source_observation_id)
        return ""

    @property
    def claim_id(self) -> str:
        """Helper property extracting claim ID from new_state if present."""
        if self.new_state:
            return str(self.new_state.get("id", ""))
        return ""

    @property
    def relationship_id(self) -> str:
        """Helper property extracting relationship ID from new_state if present."""
        if self.new_state:
            return str(self.new_state.get("id", ""))
        return ""
