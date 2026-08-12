"""Domain models for the Gmail -> Personal World Model ingestion pipeline.

Includes CandidateRelationshipResult and IngestionReport.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.entities import Relationship


class CandidateRelationshipResult(BaseModel):
    """Evaluation result for a candidate relationship during pipeline execution."""

    relationship: Relationship = Field(description="The evaluated relationship candidate.")
    status: str = Field(
        description="Candidate status: NEW, CONFIRM, UPDATE, CONFLICT, or UNCERTAIN.",
    )
    reason: str = Field(description="Rationale for the candidate classification.")
    evidence_snippet: str = Field(default="", description="Exact evidence snippet text.")
    subject_entity_name: str = Field(default="", description="Name of subject entity.")
    object_entity_name: str = Field(default="", description="Name of object entity.")


class IngestionReport(BaseModel):
    """Complete summary report returned by the Gmail -> Personal World Model ingestion pipeline."""

    raw_observation_id: str = Field(description="ID of the raw Observation.")
    message_id: str = Field(default="", description="Gmail message ID.")
    thread_id: str = Field(default="", description="Gmail thread ID.")
    sender: str = Field(default="", description="Sender email address.")
    subject: str = Field(default="", description="Email subject line.")

    entities_processed: int = Field(default=0, description="Total entities extracted.")
    entities_resolved: int = Field(default=0, description="Entities matched to existing entities.")
    entities_new: int = Field(default=0, description="New entities created.")
    entities_requiring_review: int = Field(
        default=0, description="Entities flagged for human review."
    )

    relationships_candidate_count: int = Field(
        default=0, description="Total relationship candidates."
    )
    relationships_by_status: dict[str, int] = Field(
        default_factory=dict,
        description="Counts of relationships grouped by status (NEW, CONFIRM, UPDATE, CONFLICT, UNCERTAIN).",
    )
    candidate_relationship_results: list[CandidateRelationshipResult] = Field(
        default_factory=list,
        description="Detailed evaluation results for every relationship candidate.",
    )

    evidence_records_created: int = Field(
        default=0, description="Number of evidence records created."
    )
    success: bool = Field(
        default=True, description="Whether the ingestion pipeline ran successfully."
    )
