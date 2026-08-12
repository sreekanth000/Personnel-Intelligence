"""Extraction Quality API router.

Provides endpoints for monitoring GPT-4.1 extraction metrics and sampling extraction records.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.world import get_evidence_service, get_world_model_service

router = APIRouter(prefix="/extraction", tags=["Extraction"])


class ExtractionMetricsDTO(BaseModel):
    emails_processed: int
    entities_extracted: int
    relationships_extracted: int
    claims_extracted: int
    events_extracted: int
    extraction_failures: int
    low_confidence_extractions: int
    unresolved_entities: int
    unresolved_relationships: int
    conflicting_relationships: int
    pending_confirmations: int


class ExtractionSampleDTO(BaseModel):
    id: str
    email_snippet: str
    extraction_subject: str
    extraction_predicate: str
    extraction_object: str
    confidence: float
    final_wm_status: str
    review_status: str = "pending"


@router.get("/metrics", response_model=ExtractionMetricsDTO, summary="Get Extraction Metrics")
async def get_extraction_metrics() -> ExtractionMetricsDTO:
    """Return quality metrics for the extraction pipeline."""
    wm = get_world_model_service()
    ev = get_evidence_service()

    changes = await wm.get_state_changes()

    # Calculate emails processed from unique observations in state changes
    processed_emails = len({c.observation_id for c in changes})

    entities = await wm.get_all_entities()
    relationships = await wm.get_all_relationships()

    entities_extracted = len(entities)
    relationships_extracted = len(relationships)
    claims_extracted = relationships_extracted  # In this context, relations are claims
    events_extracted = sum(
        1 for e in entities if str(getattr(e, "entity_type", "")).lower() == "event"
    )

    # Extraction failures and unresolved are estimated/mocked for now as they aren't persisted
    extraction_failures = 0
    unresolved_entities = 0
    unresolved_relationships = 0

    # Calculate confidence issues from evidence
    low_confidence = 0
    all_evidence = await ev.get_all_evidence()
    for e in all_evidence:
        if getattr(e.confidence, "score", 1.0) < 0.7:
            low_confidence += 1

    conflicting = sum(1 for c in changes if str(c.outcome).upper() == "CONFLICT")
    pending = sum(1 for c in changes if getattr(c, "requires_review", False))

    return ExtractionMetricsDTO(
        emails_processed=processed_emails,
        entities_extracted=entities_extracted,
        relationships_extracted=relationships_extracted,
        claims_extracted=claims_extracted,
        events_extracted=events_extracted,
        extraction_failures=extraction_failures,
        low_confidence_extractions=low_confidence,
        unresolved_entities=unresolved_entities,
        unresolved_relationships=unresolved_relationships,
        conflicting_relationships=conflicting,
        pending_confirmations=pending,
    )


@router.get("/samples", response_model=list[ExtractionSampleDTO], summary="Get Sample Extractions")
async def get_extraction_samples() -> list[ExtractionSampleDTO]:
    """Return a sample of extraction records for manual review."""
    wm = get_world_model_service()
    ev = get_evidence_service()

    samples: list[ExtractionSampleDTO] = []

    all_evidence = await ev.get_all_evidence()
    all_relationships = await wm.get_all_relationships()
    all_entities = await wm.get_all_entities()
    entity_map = {e.id: getattr(e, "name", e.id) for e in all_entities}

    # Take up to 50 evidence records as samples
    for evidence in list(all_evidence)[:50]:
        target_id = evidence.target_id

        # Determine if target is relationship or entity
        rel = next((r for r in all_relationships if r.id == target_id), None)

        if rel:
            subject_name = entity_map.get(rel.subject, rel.subject)
            object_name = entity_map.get(rel.object, rel.object)

            samples.append(
                ExtractionSampleDTO(
                    id=evidence.id,
                    email_snippet=evidence.evidence_span.text_snippet,
                    extraction_subject=subject_name,
                    extraction_predicate=str(rel.predicate),
                    extraction_object=object_name,
                    confidence=getattr(evidence.confidence, "score", 1.0),
                    final_wm_status="active",
                    review_status="pending",
                )
            )

    return samples
