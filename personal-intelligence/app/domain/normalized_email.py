"""Normalized Email Observation domain model.

Represents a noise-filtered, structured email observation ready for GPT-4.1 extraction.
Crucially, the original raw Observation is NEVER deleted or modified.
The raw observation and normalized observation are stored separately.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.values import _new_id, _utcnow


class NormalizedEmailObservation(BaseModel):
    """A clean, noise-filtered representation of an email message.

    Strips quoted reply chains, signatures, HTML markup, and redundant whitespace
    so that downstream LLM extraction (GPT-4.1) receives high-signal content.

    Maintains linkage to the original raw Observation via raw_observation_id.
    """

    id: str = Field(
        default_factory=_new_id, description="Unique normalized observation identifier."
    )
    raw_observation_id: str = Field(description="ID of the original immutable raw Observation.")
    message_id: str = Field(description="Gmail native message ID.")
    thread_id: str = Field(description="Gmail native thread ID.")
    sender: str = Field(default="", description="Sender email address / header.")
    recipients: list[str] = Field(
        default_factory=list, description="Primary recipient email addresses."
    )
    cc: list[str] = Field(default_factory=list, description="CC recipient email addresses.")
    subject: str = Field(default="", description="Cleaned email subject line.")
    timestamp: datetime = Field(
        default_factory=_utcnow,
        description="Message sent / received timestamp.",
    )
    body: str = Field(
        default="",
        description="Clean, main email body text (noise-filtered, HTML-stripped).",
    )
    quoted_reply: str | None = Field(
        default=None,
        description="Separated quoted reply chain text, if detected.",
    )
    signature: str | None = Field(
        default=None,
        description="Separated sign-off or email signature, if detected.",
    )
    attachments_metadata: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Preserved attachment metadata dicts (filename, mime_type, size_bytes, attachment_id).",
    )
    content_hash: str = Field(
        description="SHA-256 hash of the normalized body content.",
    )
    normalized_at: datetime = Field(
        default_factory=_utcnow,
        description="Timestamp when normalization was performed.",
    )
