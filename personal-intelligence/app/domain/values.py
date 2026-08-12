"""Value objects shared across the domain model.

These are immutable building blocks used by Observations, Claims,
Entities, and Evidence to express provenance, temporal ranges,
temporal references, evidence spans, and calibrated confidence.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field
from typing import Any

from app.domain.enums import ConfidenceCategory, TemporalAspect


def _new_id() -> str:
    """Generate a new domain object identifier."""
    return str(uuid4())


def _utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Provenance — tracks where a derived object came from
# ---------------------------------------------------------------------------


class Provenance(BaseModel):
    """Records how a derived domain object was produced.

    Every Claim, Entity, Relationship, and Evidence carries provenance
    so that the system never loses track of *why* something exists.
    """

    source_observation_ids: list[str] = Field(
        default_factory=list,
        description="Observation IDs that contributed to this derivation.",
    )
    derivation_method: str = Field(
        default="unknown",
        description="How the object was derived (e.g. 'llm_extraction', 'user_input', 'rule_engine').",
    )
    derived_at: datetime = Field(
        default_factory=_utcnow,
        description="When the derivation occurred.",
    )
    derived_by: str = Field(
        default="system",
        description="Which component produced this derivation.",
    )
    model_id: str | None = Field(
        default=None,
        description="If an LLM was used, which model produced the extraction.",
    )


# ---------------------------------------------------------------------------
# Temporal range & reference — validity intervals and temporal aspects
# ---------------------------------------------------------------------------


class TemporalRange(BaseModel):
    """A time interval expressing when a piece of state is valid."""

    valid_from: datetime | None = Field(
        default=None,
        description="Start of the validity period (inclusive).",
    )
    valid_to: datetime | None = Field(
        default=None,
        description="End of the validity period (inclusive). None means still valid.",
    )

    @property
    def is_open_ended(self) -> bool:
        """Return True if this range has no end date (still active)."""
        return self.valid_to is None

    def contains(self, point: datetime) -> bool:
        """Return True if the given timestamp falls within this range."""
        if self.valid_from is not None and point < self.valid_from:
            return False
        return not (self.valid_to is not None and point > self.valid_to)


class TemporalReference(BaseModel):
    """Temporal aspect and reference for facts, events, and relationships.

    Supports aspects: before, after, during, since, until, current, unknown.
    """

    aspect: TemporalAspect = Field(
        default=TemporalAspect.UNKNOWN,
        description="Temporal aspect operator (before, after, during, since, until, current, unknown).",
    )
    point_in_time: datetime | None = Field(
        default=None,
        description="Resolved timestamp if applicable.",
    )
    relative_text: str | None = Field(
        default=None,
        description="Textual temporal phrase from source (e.g. 'next Tuesday', 'since Q2').",
    )
    range: TemporalRange | None = Field(
        default=None,
        description="Resolved temporal range if applicable.",
    )


# ---------------------------------------------------------------------------
# Confidence score — numeric with qualitative category
# ---------------------------------------------------------------------------


class ConfidenceScore(BaseModel):
    """A calibrated confidence value with an explicit qualitative label."""

    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Numeric confidence in [0.0, 1.0].",
    )
    category: ConfidenceCategory = Field(
        description="Qualitative label derived from the score.",
    )

    @classmethod
    def from_score(cls, score: float) -> ConfidenceScore:
        """Create a ConfidenceScore with the category auto-derived from the score."""
        if score < 0.2:
            cat = ConfidenceCategory.VERY_LOW
        elif score < 0.4:
            cat = ConfidenceCategory.LOW
        elif score < 0.6:
            cat = ConfidenceCategory.MEDIUM
        elif score < 0.8:
            cat = ConfidenceCategory.HIGH
        else:
            cat = ConfidenceCategory.VERY_HIGH
        return cls(score=score, category=cat)


# ---------------------------------------------------------------------------
# Evidence Span — excerpt from source observation
# ---------------------------------------------------------------------------


class EvidenceSpan(BaseModel):
    """Exact text span excerpt from a source observation supporting an extraction."""

    text_snippet: str = Field(
        default="",
        description="Exact text excerpt from the observation body/content.",
    )
    start_char: int | None = Field(
        default=None,
        ge=0,
        description="Start character offset in observation content.",
    )
    end_char: int | None = Field(
        default=None,
        ge=0,
        description="End character offset in observation content.",
    )
    confidence: ConfidenceScore = Field(
        default_factory=lambda: ConfidenceScore(score=0.8, category="high"),
        description="Confidence score in the excerpt grounding.",
    )

    model_config = {"populate_by_name": True}

    @classmethod
    def model_validate(cls, obj: Any, **kwargs) -> "EvidenceSpan":  # type: ignore[override]
        if isinstance(obj, dict):
            # Accept 'quote' as alias for text_snippet
            if "quote" in obj and "text_snippet" not in obj:
                obj = dict(obj)
                obj["text_snippet"] = obj.pop("quote")
            # Accept 'text' as alias
            if "text" in obj and "text_snippet" not in obj:
                obj = dict(obj)
                obj["text_snippet"] = obj.pop("text")
            # Coerce bare float/int confidence
            if "confidence" in obj and isinstance(obj["confidence"], (int, float)):
                score = float(obj["confidence"])
                cat = "very_high" if score >= 0.8 else ("high" if score >= 0.6 else "medium")
                obj = dict(obj)
                obj["confidence"] = {"score": score, "category": cat}
        return super().model_validate(obj, **kwargs)
