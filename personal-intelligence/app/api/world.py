"""Personal World Model Query API endpoints.

Provides read-only query access to the Personal World Model graph, entities,
relationships, temporal timeline, evidence lineage, changes audit log, and synthesized current state.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.connectors.gmail_filter import GmailFilterConfig
from app.domain.entities import Entity, Relationship
from app.domain.enums import EntityType
from app.domain.evidence import Evidence
from app.domain.world_state import StateChange, SynthesizedCurrentState
from app.services.entity_resolution import EntityResolver
from app.services.evidence import EvidenceService
from app.services.pipeline import GmailPipelineService
from app.services.world_model import WorldModelService

router = APIRouter(prefix="/world", tags=["world-model"])

# Singleton service instances for application lifecycle
_world_model_service: WorldModelService | None = None
_evidence_service: EvidenceService | None = None


def get_world_model_service() -> WorldModelService:
    """Dependency injector for WorldModelService."""
    global _world_model_service
    if _world_model_service is None:
        from app.main import _app_state
        duckdb = _app_state.duckdb if _app_state else None
        kuzu = _app_state.kuzu if _app_state else None
        _world_model_service = WorldModelService(duckdb_store=duckdb, kuzu_store=kuzu)
    return _world_model_service


def get_evidence_service() -> EvidenceService:
    """Dependency injector for EvidenceService."""
    global _evidence_service
    if _evidence_service is None:
        from app.main import _app_state
        duckdb = _app_state.duckdb if _app_state else None
        _evidence_service = EvidenceService(duckdb_store=duckdb)
    return _evidence_service


def set_world_model_service(service: WorldModelService) -> None:
    """Set global WorldModelService instance for testing / app lifecycle."""
    global _world_model_service
    _world_model_service = service


def set_evidence_service(service: EvidenceService) -> None:
    """Set global EvidenceService instance for testing / app lifecycle."""
    global _evidence_service
    _evidence_service = service


# ---------------------------------------------------------------------------
# 1. Entity query endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/entities/{entity_id}",
    response_model=Entity,
    summary="Get entity by ID",
)
async def get_entity_by_id(entity_id: str) -> Entity:
    """Retrieve a single entity by its unique identifier."""
    wm = get_world_model_service()
    entity = await wm.get_entity(entity_id)
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found in Personal World Model.",
        )
    return entity


@router.get(
    "/entities/{entity_id}/relationships",
    response_model=list[Relationship],
    summary="Get active relationships for an entity",
)
async def get_entity_relationships(entity_id: str) -> list[Relationship]:
    """Retrieve all active graph relationships where entity_id is subject or object."""
    wm = get_world_model_service()
    entity = await wm.get_entity(entity_id)
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found in Personal World Model.",
        )
    return await wm.get_relationships_for_entity(entity_id)


@router.get(
    "/entities/{entity_id}/timeline",
    response_model=list[dict[str, Any]],
    summary="Get temporal timeline for an entity",
)
async def get_entity_timeline(entity_id: str) -> list[dict[str, Any]]:
    """Retrieve temporal timeline of state changes and events associated with entity_id."""
    wm = get_world_model_service()
    entity = await wm.get_entity(entity_id)
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found in Personal World Model.",
        )
    return await wm.get_timeline_for_entity(entity_id)


@router.get(
    "/entities/{entity_id}/evidence",
    response_model=list[Evidence],
    summary="Get supporting evidence for an entity",
)
async def get_entity_evidence(entity_id: str) -> list[Evidence]:
    """Retrieve all evidence records and text snippets supporting entity_id."""
    wm = get_world_model_service()
    entity = await wm.get_entity(entity_id)
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found in Personal World Model.",
        )
    ev_svc = get_evidence_service()
    return await ev_svc.get_evidence_for_entity(entity_id)


# ---------------------------------------------------------------------------
# 2. Typed Entity collection endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/people",
    response_model=list[Entity],
    summary="List all Person entities",
)
async def list_people() -> list[Entity]:
    """Retrieve all entities of type PERSON."""
    wm = get_world_model_service()
    return await wm.get_entities_by_type(EntityType.PERSON)


@router.get(
    "/organizations",
    response_model=list[Entity],
    summary="List all Organization entities",
)
async def list_organizations() -> list[Entity]:
    """Retrieve all entities of type ORGANIZATION."""
    wm = get_world_model_service()
    return await wm.get_entities_by_type(EntityType.ORGANIZATION)


@router.get(
    "/projects",
    response_model=list[Entity],
    summary="List all Project entities",
)
async def list_projects() -> list[Entity]:
    """Retrieve all entities of type PROJECT."""
    wm = get_world_model_service()
    return await wm.get_entities_by_type(EntityType.PROJECT)


@router.get(
    "/goals",
    response_model=list[Entity],
    summary="List all Goal entities",
)
async def list_goals() -> list[Entity]:
    """Retrieve all entities of type GOAL."""
    wm = get_world_model_service()
    return await wm.get_entities_by_type(EntityType.GOAL)


@router.get(
    "/decisions",
    response_model=list[Entity],
    summary="List all Decision entities",
)
async def list_decisions() -> list[Entity]:
    """Retrieve all entities of type DECISION."""
    wm = get_world_model_service()
    return await wm.get_entities_by_type(EntityType.DECISION)


# ---------------------------------------------------------------------------
# 3. State & History query endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/current-state",
    response_model=SynthesizedCurrentState,
    summary="Synthesize current personal world state",
)
async def get_current_state() -> SynthesizedCurrentState:
    """Synthesize point-in-time state from structured World Model data (No LLM generation).

    Aggregates active people relationships, projects, goals, recent decisions, events,
    constraints, state changes, and unresolved conflicts.
    """
    wm = get_world_model_service()
    return await wm.get_synthesized_current_state()


class CorrectionRequest(BaseModel):
    action: str  # "confirm", "correct", "reject", "outdate"
    reason: str
    new_subject: str | None = None
    new_predicate: str | None = None
    new_object: str | None = None


@router.post(
    "/corrections/relationship/{relationship_id}",
    response_model=dict[str, str],
    summary="Submit manual correction for a relationship",
)
async def submit_relationship_correction(
    relationship_id: str, request: CorrectionRequest
) -> dict[str, str]:
    """Process a user correction workflow for a given relationship.

    Actions:
    - confirm: Upgrades confidence to 1.0.
    - reject: Marks as conflict and invalidates.
    - outdate: Deprecates and marks as historical.
    - correct: Deprecates old and creates a new modified relationship.
    """
    wm = get_world_model_service()

    if request.action not in ["confirm", "correct", "reject", "outdate"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid correction action.",
        )

    try:
        new_target_id, observation_id = await wm.apply_user_correction(
            target_id=relationship_id,
            target_type="relationship",
            action=request.action,
            reason=request.reason,
            new_subject=request.new_subject,
            new_predicate=request.new_predicate,
            new_object=request.new_object,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # We could also hook into EvidenceService to explicitly attach the user correction evidence
    ev_svc = get_evidence_service()
    from app.domain.enums import EvidenceType
    from app.domain.values import ConfidenceScore, EvidenceSpan

    ev_type = EvidenceType.SUPPORTS
    if request.action == "reject":
        ev_type = EvidenceType.CONTRADICTS
    elif request.action == "outdate":
        ev_type = EvidenceType.QUALIFIES

    # Add evidence linking the new observation to the affected target
    # In a fully wired system, we would also persist the user Observation via an ObservationService.
    # For now, we simulate the manual observation linking directly in Evidence.
    await ev_svc.record_evidence(
        observation_id=observation_id,
        target_id=new_target_id,
        target_type="relationship",
        evidence_type=ev_type,
        confidence=ConfidenceScore.from_score(1.0),
        evidence_span=EvidenceSpan(
            text_snippet=request.reason, confidence=ConfidenceScore.from_score(1.0)
        ),
    )

    return {"status": "success", "new_target_id": new_target_id, "observation_id": observation_id}


@router.get(
    "/changes",
    response_model=list[StateChange],
    summary="Get historical state changes log",
)
async def list_state_changes() -> list[StateChange]:
    """Retrieve complete audit log of StateChange records produced by reconciliation."""
    wm = get_world_model_service()
    return await wm.get_state_changes()


@router.get(
    "/filter-config",
    response_model=GmailFilterConfig,
    summary="Get Gmail sync filter configuration",
)
async def get_filter_config() -> GmailFilterConfig:
    """Retrieve current Gmail folder, label, sender, and subject filtering configuration."""
    from app.connectors.gmail_filter import GmailFilterService

    filter_service = GmailFilterService()
    return filter_service.config


@router.post(
    "/filter-config",
    response_model=GmailFilterConfig,
    summary="Update Gmail sync filter configuration",
)
async def update_filter_config(config: GmailFilterConfig) -> GmailFilterConfig:
    """Update and persist Gmail folder, label, sender, and subject filtering rules."""
    from app.connectors.gmail_filter import GmailFilterService

    filter_service = GmailFilterService()
    filter_service.save_config(config)
    return filter_service.config


@router.post("/ingest-gmail", summary="Ingest real Gmail emails")
async def ingest_gmail_emails(
    limit: int = 50,
) -> dict[str, Any]:
    """Fetch real Gmail emails and process them through the extraction pipeline.

    Requires:
    - Gmail OAuth credentials (run scripts/gmail_auth_only.py first)
    - OpenAI API key (set PI_OPENAI_API_KEY in .env)

    Args:
        limit: Maximum number of emails to fetch and process.

    Returns:
        Summary of ingestion results including entity and relationship counts.
    """
    from app.config.settings import get_settings
    from app.connectors.gmail import GmailConnector
    from app.domain.observations import Observation
    from app.services.extraction import GPT41Extractor

    settings = get_settings()

    # Validate Azure OpenAI config
    if not settings.azure_ai_api_key or not settings.azure_ai_endpoint:
        return {
            "status": "error",
            "message": "Azure OpenAI not configured. Set PI_AZURE_AI_API_KEY and PI_AZURE_AI_ENDPOINT in .env file.",
        }

    # Validate Gmail auth
    try:
        connector = GmailConnector()
        if not connector.is_authenticated():
            return {
                "status": "error",
                "message": "Gmail not authenticated. Run scripts/gmail_auth_only.py first.",
            }
    except Exception as e:
        return {"status": "error", "message": f"Gmail connector error: {e}"}

    # Initialize pipeline
    wm = get_world_model_service()
    ev = get_evidence_service()
    er = EntityResolver()
    extractor = GPT41Extractor(
        azure_endpoint=settings.azure_ai_endpoint,
        api_key=settings.azure_ai_api_key,
        deployment=settings.azure_openai_deployment,
        api_version=settings.azure_ai_api_version,
    )

    pipeline = GmailPipelineService(
        extractor=extractor,
        evidence_service=ev,
        entity_resolver=er,
        world_model_service=wm,
    )

    # Fetch real Gmail emails
    try:
        obs_iterator = connector.fetch_observations(limit=limit)
        observations: list[Observation] = []
        async for obs in obs_iterator:
            observations.append(obs)
    except Exception as e:
        return {"status": "error", "message": f"Failed to fetch Gmail emails: {e}"}

    # Process each email through the pipeline
    success_count = 0
    error_count = 0
    errors: list[str] = []

    all_ents = await wm.get_all_entities()
    all_rels = await wm.get_all_relationships()

    for obs in observations:
        try:
            await pipeline.process_gmail_observation(
                raw_observation=obs,
                existing_entities=all_ents,
                existing_relationships=all_rels,
            )
            success_count += 1
        except Exception as e:
            error_count += 1
            errors.append(f"{obs.id}: {e}")

    # Re-fetch for final counts
    final_ents = await wm.get_all_entities()
    final_rels = await wm.get_all_relationships()

    return {
        "status": "success",
        "message": f"Processed {success_count}/{len(observations)} emails",
        "emails_fetched": len(observations),
        "emails_processed": success_count,
        "emails_failed": error_count,
        "total_entities": len(final_ents),
        "total_relationships": len(final_rels),
        "errors": errors[:10] if errors else [],
    }

