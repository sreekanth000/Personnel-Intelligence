"""AskRequest and AskResponse domain models for the GPT-4.1 reasoning layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain.context import ContextPackage


class AskRequest(BaseModel):
    """User question request submitted to POST /api/v1/ask."""

    question: str = Field(description="User natural language question.")
    purpose: str = Field(
        default="user_query",
        description="Declared purpose for context retrieval.",
    )


class AskResponse(BaseModel):
    """Response returned by POST /api/v1/ask carrying answer, supporting context, evidence, and clear provenance lineage."""

    answer: str = Field(description="Synthesized answer produced by GPT-4.1 reasoning layer.")
    supporting_context: ContextPackage = Field(
        description="The filtered ContextPackage supplied to GPT-4.1.",
    )
    evidence: list[Any] = Field(
        default_factory=list,
        description="Supporting evidence items grounding the answer.",
    )
    provenance_lineage: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Clear provenance lineage mapping statements to source observations and confidence scores.",
    )
    uncertainties: list[str] = Field(
        default_factory=list,
        description="Explicit uncertainties, missing information, or ambiguous aspects identified.",
    )
