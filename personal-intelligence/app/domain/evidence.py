"""Evidence domain model.

Evidence links derived World Model items (Entities, Relationships, Claims,
Events, Goals, Projects, Decisions, Constraints, Preferences) back to source Observations.

Every Evidence item MUST reference a source Observation — free-floating evidence
is strictly prohibited.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import EvidenceType
from app.domain.values import ConfidenceScore, EvidenceSpan, _new_id, _utcnow


class Evidence(BaseModel):
    """Lean evidence record establishing provenance lineage from raw Gmail observations.

    Guarantees full lineage tracing:
    World Model state → derived claim/entity/event/rel → Gmail message → exact evidence span
    """

    id: str = Field(default_factory=_new_id, description="Unique evidence identifier.")
    source_observation_id: str = Field(
        description="ID of the source raw Observation. MUST reference a valid Observation."
    )
    source_message_id: str = Field(
        default="",
        description="Gmail message ID from source observation metadata.",
    )
    source_thread_id: str = Field(
        default="",
        description="Gmail thread ID from source observation metadata.",
    )
    target_id: str = Field(
        description="ID or reference of the target entity, relationship, claim, event, goal, decision, etc."
    )
    target_type: str = Field(
        default="claim",
        description="Type of target object (entity, relationship, claim, event, goal, project, decision, preference, constraint).",
    )
    evidence_type: EvidenceType = Field(
        default=EvidenceType.SUPPORTS,
        description="How this evidence relates to the target item.",
    )
    evidence_span: EvidenceSpan = Field(
        description="Exact text snippet, start_char/offset, end_char/offset, and confidence score.",
    )
    confidence: ConfidenceScore = Field(
        description="Confidence score in this evidence grounding.",
    )
    recorded_at: datetime = Field(
        default_factory=_utcnow,
        description="When this evidence was recorded.",
    )

    @property
    def observation_id(self) -> str:
        """Alias for source_observation_id for backward compatibility."""
        return self.source_observation_id

    @property
    def claim_id(self) -> str:
        """Alias for target_id when target_type is claim."""
        return self.target_id

    @property
    def content(self) -> str:
        """Alias for evidence_span text snippet."""
        return self.evidence_span.text_snippet

    @property
    def start_offset(self) -> int | None:
        """Alias for evidence_span start character offset."""
        return self.evidence_span.start_char

    @property
    def end_offset(self) -> int | None:
        """Alias for evidence_span end character offset."""
        return self.evidence_span.end_char

    @model_validator(mode="before")
    @classmethod
    def _remap_legacy_fields(cls, data: dict[str, Any]) -> dict[str, Any]:
        if isinstance(data, dict):
            if "observation_id" in data and "source_observation_id" not in data:
                data["source_observation_id"] = data["observation_id"]
            if "claim_id" in data and "target_id" not in data:
                data["target_id"] = data["claim_id"]
                data["target_type"] = "claim"
            if "content" in data and "evidence_span" not in data:
                conf = data.get("confidence", ConfidenceScore.from_score(0.9))
                data["evidence_span"] = EvidenceSpan(
                    text_snippet=data["content"],
                    start_char=data.get("start_offset"),
                    end_char=data.get("end_offset"),
                    confidence=conf
                    if isinstance(conf, ConfidenceScore)
                    else ConfidenceScore.model_validate(conf),
                )
        return data

    @model_validator(mode="after")
    def _source_observation_id_must_not_be_empty(self) -> Evidence:
        if not self.source_observation_id.strip():
            msg = "Evidence must reference an observation (source_observation_id cannot be empty)."
            raise ValueError(msg)
        return self
