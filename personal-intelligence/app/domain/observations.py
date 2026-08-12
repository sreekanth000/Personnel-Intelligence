"""Observation domain model.

An Observation is something actually observed from a source.
It is NOT automatically a fact, NOT a claim, and NOT truth.

Observations are the raw, immutable inputs to the intelligence pipeline.
They are never modified after creation — only new observations are added.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import ObservationSource
from app.domain.values import _new_id, _utcnow


class Observation(BaseModel):
    """A raw observation captured from a source.

    Observations are immutable records of something that was seen.
    They carry the raw content and enough metadata to trace their origin,
    but they make no truth claims.

    The pipeline processes Observations into Claims via extraction.
    """

    id: str = Field(default_factory=_new_id, description="Unique observation identifier.")
    source: ObservationSource = Field(description="Where this observation came from.")
    source_identifier: str = Field(
        description="Native identifier from the source system (e.g. message ID, file path)."
    )
    observed_at: datetime = Field(
        default_factory=_utcnow,
        description="When the observation was captured.",
    )
    content: str = Field(description="Raw textual content of the observation.")
    content_type: str = Field(
        default="text/plain",
        description="MIME type of the content (e.g. 'text/plain', 'text/html').",
    )
    content_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of the observation content for integrity verification.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific metadata (e.g. sender, recipients, subject, thread_id, labels, headers).",
    )
