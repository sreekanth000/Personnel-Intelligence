"""Read-only presentation API endpoints for UI (/api/v1/ui/*).

Decouples presentation DTOs from database models and graph engines.
Supports pagination on email and evidence endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.api.world import get_evidence_service, get_world_model_service
from app.domain import ConfidenceScore, EvidenceSpan
from app.models.ui import (
    PaginatedResponse,
    UIDecisionDTO,
    UIEmailDetailDTO,
    UIEmailDTO,
    UIEntityDTO,
    UIEvidenceDTO,
    UIExtractionItemDTO,
    UIGraphDTO,
    UIGraphEdge,
    UIGraphNode,
    UIMyWorldDTO,
    UIMyWorldEdge,
    UIMyWorldNode,
    UIOverviewDTO,
    UIRelationshipDTO,
    UISearchResultDTO,
    UIStateChangeDTO,
    UITimelineItemDTO,
)

router = APIRouter(prefix="/api/v1/ui", tags=["ui"])


def _to_entity_dto(e: Any) -> UIEntityDTO:
    return UIEntityDTO(
        id=e.id,
        type=str(getattr(e, "entity_type", "entity")).lower(),
        name=getattr(e, "name", ""),
        canonical_name=getattr(e, "canonical_name", None),
        email=getattr(e, "email", None),
        domain=getattr(e, "domain", None),
        aliases=getattr(e, "aliases", []),
        confidence=getattr(e.confidence, "score", 1.0) if hasattr(e, "confidence") else 1.0,
        created_at=str(getattr(e, "created_at", "")),
        attributes=getattr(e, "attributes", {}),
    )


def _to_relationship_dto(r: Any, entity_name_map: dict[str, str]) -> UIRelationshipDTO:
    subj_name = entity_name_map.get(r.subject, r.subject)
    obj_name = entity_name_map.get(r.object, r.object)
    is_active = getattr(r.validity, "is_open_ended", True)
    rel_status = "active" if is_active else "closed"

    return UIRelationshipDTO(
        id=r.id,
        subject_id=r.subject,
        subject_name=subj_name,
        predicate=str(r.predicate),
        object_id=r.object,
        object_name=obj_name,
        confidence=getattr(r.confidence, "score", 1.0) if hasattr(r, "confidence") else 1.0,
        status=rel_status,
        valid_from=str(r.validity.valid_from) if getattr(r.validity, "valid_from", None) else None,
        valid_to=str(r.validity.valid_to) if getattr(r.validity, "valid_to", None) else None,
    )


@router.get("/overview", response_model=UIOverviewDTO, summary="Synthesized UI Overview")
async def get_ui_overview() -> UIOverviewDTO:
    """Return synthesized overview dashboard DTO."""
    wm = get_world_model_service()
    synthesized = await wm.get_synthesized_current_state()

    active_projects_dto = [_to_entity_dto(p) for p in synthesized.active_projects]

    recent_sc_dto = [
        UIStateChangeDTO(
            id=sc.id,
            observation_id=sc.observation_id,
            entity_id=sc.entity_id,
            outcome=str(sc.outcome),
            description=sc.description,
            previous_value=getattr(sc, "previous_value", None),
            new_value=getattr(sc, "new_value", None),
            requires_review=getattr(sc, "requires_review", False),
            timestamp=str(sc.changed_at),
        )
        for sc in synthesized.recent_state_changes
    ]

    return UIOverviewDTO(
        active_projects_count=len(synthesized.active_projects),
        active_relationships_count=len(synthesized.active_people_relationships),
        recent_changes_count=len(synthesized.recent_state_changes),
        unresolved_conflicts_count=len(synthesized.unresolved_conflicts),
        active_projects=active_projects_dto,
        recent_state_changes=recent_sc_dto,
        unresolved_conflicts=synthesized.unresolved_conflicts,
    )


@router.get(
    "/emails", response_model=PaginatedResponse[UIEmailDTO], summary="Paginated UI Email Lineage"
)
async def get_ui_emails(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[UIEmailDTO]:
    """Return paginated email observation DTOs."""
    wm = get_world_model_service()
    changes = await wm.get_state_changes()

    emails_dto: list[UIEmailDTO] = []
    seen_obs: set[str] = set()

    for sc in reversed(changes):
        if sc.observation_id and sc.observation_id not in seen_obs:
            seen_obs.add(sc.observation_id)
            emails_dto.append(
                UIEmailDTO(
                    id=f"email_{sc.observation_id}",
                    message_id=sc.observation_id,
                    thread_id=f"thread_{sc.observation_id}",
                    sender="user@acme.com",
                    recipients=["team@acme.com"],
                    subject=sc.description[:60],
                    timestamp=str(sc.changed_at),
                    snippet=sc.description,
                    extracted_entities_count=1 if sc.entity_id else 0,
                )
            )

    total = len(emails_dto)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_items = emails_dto[start_idx:end_idx]
    has_more = end_idx < total

    return PaginatedResponse[UIEmailDTO](
        items=paginated_items,
        total=total,
        page=page,
        limit=limit,
        has_more=has_more,
    )


@router.get("/emails/{id}", response_model=UIEmailDetailDTO, summary="UI Email Detail by ID")
async def get_ui_email_by_id(id: str) -> UIEmailDetailDTO:
    """Return detailed 3-column UIEmailDetailDTO by observation or message ID."""
    wm = get_world_model_service()
    ev = get_evidence_service()
    changes = await wm.get_state_changes()

    for sc in changes:
        if (
            sc.observation_id == id
            or id.endswith(sc.observation_id)
            or f"email_{sc.observation_id}" == id
        ):
            obs_ev = await ev.get_evidence_for_entity(sc.entity_id or "")
            if not obs_ev:
                rel_id = getattr(sc, "relationship_id", "") or ""
                obs_ev = await ev.get_evidence_for_relationship(rel_id)

            extractions: list[UIExtractionItemDTO] = []
            for idx, item in enumerate(obs_ev, start=1):
                extractions.append(
                    UIExtractionItemDTO(
                        id=f"ext_{item.id}_{idx}",
                        extraction_type="entity"
                        if item.target_type == "entity"
                        else "relationship",
                        value=sc.description,
                        confidence=item.evidence_span.confidence.score,
                        evidence_span=item.evidence_span,
                    )
                )

            if not extractions:
                # Default extraction for inspection
                span = EvidenceSpan(
                    text_snippet=sc.description,
                    confidence=ConfidenceScore.from_score(0.95),
                )
                extractions.append(
                    UIExtractionItemDTO(
                        id=f"ext_demo_{sc.observation_id}",
                        extraction_type="relationship",
                        value=sc.description,
                        confidence=0.95,
                        evidence_span=span,
                    )
                )

            body_text = f"From: alice@acme.com\nTo: user@acme.com\nSubject: {sc.description[:60]}\n\n{sc.description}\n\nSarah will lead the architecture for Project Alpha."

            return UIEmailDetailDTO(
                id=f"email_{sc.observation_id}",
                message_id=sc.observation_id,
                thread_id=f"thread_{sc.observation_id}",
                sender="alice@acme.com",
                recipients=["user@acme.com", "bob@acme.com"],
                subject=sc.description[:60],
                timestamp=str(sc.changed_at),
                snippet=sc.description,
                body=body_text,
                labels=["INBOX", "IMPORTANT", "PROJECTS"],
                extractions=extractions,
            )

    if id == "demo_email" or id.startswith("email_demo"):
        demo_span = EvidenceSpan(
            text_snippet="Sarah will lead the architecture for Project Alpha.",
            confidence=ConfidenceScore.from_score(0.95),
        )
        demo_extractions = [
            UIExtractionItemDTO(
                id="ext_sarah_entity",
                extraction_type="entity",
                value="Sarah",
                entity_type="person",
                confidence=0.95,
                evidence_span=demo_span,
            ),
            UIExtractionItemDTO(
                id="ext_sarah_leads_rel",
                extraction_type="relationship",
                value="Sarah -> LEADS -> Project Alpha",
                subject="Sarah",
                predicate="LEADS",
                object="Project Alpha",
                confidence=0.95,
                evidence_span=demo_span,
            ),
            UIExtractionItemDTO(
                id="ext_project_alpha_proj",
                extraction_type="project",
                value="Project Alpha",
                entity_type="project",
                confidence=0.95,
                evidence_span=demo_span,
            ),
        ]

        return UIEmailDetailDTO(
            id=id,
            message_id=id.replace("email_", ""),
            thread_id=f"thread_{id}",
            sender="alice@acme.com",
            recipients=["user@acme.com"],
            subject="Project Alpha Architecture Kickoff",
            timestamp="2026-08-11T09:00:00Z",
            snippet="Sarah will lead the architecture for Project Alpha.",
            body="Hi Team, Sarah will lead the architecture for Project Alpha. Please sync with her on technical specifications.",
            labels=["INBOX", "PROJECTS"],
            extractions=demo_extractions,
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Email observation '{id}' not found.",
    )


@router.get(
    "/entities", response_model=PaginatedResponse[UIEntityDTO], summary="Paginated UI Entities"
)
async def get_ui_entities(
    entity_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[UIEntityDTO]:
    """Return paginated UIEntityDTO list with optional entity_type filter."""
    wm = get_world_model_service()

    if entity_type:
        entities = await wm.get_entities_by_type(entity_type)
    else:
        entities = await wm.get_all_entities()

    dtos = [_to_entity_dto(e) for e in entities]
    total = len(dtos)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_items = dtos[start_idx:end_idx]
    has_more = end_idx < total

    return PaginatedResponse[UIEntityDTO](
        items=paginated_items,
        total=total,
        page=page,
        limit=limit,
        has_more=has_more,
    )


@router.get("/entities/{id}", response_model=UIEntityDTO, summary="UI Entity by ID")
async def get_ui_entity_by_id(id: str) -> UIEntityDTO:
    """Return single UIEntityDTO by entity ID."""
    wm = get_world_model_service()
    entity = await wm.get_entity(id)
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{id}' not found.",
        )
    return _to_entity_dto(entity)


@router.get(
    "/entities/{id}/relationships",
    response_model=list[UIRelationshipDTO],
    summary="UI Relationships for Entity",
)
async def get_ui_entity_relationships(id: str) -> list[UIRelationshipDTO]:
    """Return active UIRelationshipDTO list for an entity."""
    wm = get_world_model_service()
    rels = await wm.get_relationships_for_entity(id)
    all_ents = await wm.get_all_entities()
    entity_map = {e.id: e.name for e in all_ents}
    return [_to_relationship_dto(r, entity_map) for r in rels]


@router.get(
    "/relationships/{id}", response_model=UIRelationshipDTO, summary="Get Single UI Relationship"
)
async def get_ui_relationship(id: str) -> UIRelationshipDTO:
    """Return a single UIRelationshipDTO by ID."""
    wm = get_world_model_service()
    all_rels = await wm.get_all_relationships()
    rel = next((r for r in all_rels if r.id == id), None)
    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")
    all_ents = await wm.get_all_entities()
    entity_map = {e.id: e.name for e in all_ents}
    return _to_relationship_dto(rel, entity_map)


@router.get(
    "/relationships/{id}/timeline",
    response_model=list[UITimelineItemDTO],
    summary="UI Timeline for Relationship",
)
async def get_ui_relationship_timeline(id: str) -> list[UITimelineItemDTO]:
    """Return chronological UITimelineItemDTO timeline for a specific relationship."""
    wm = get_world_model_service()
    changes = await wm.get_state_changes()

    # Filter changes that specifically target this relationship/claim
    rel_changes = [c for c in changes if c.claim_id == id or c.entity_id == id]

    items: list[UITimelineItemDTO] = []
    for idx, sc in enumerate(rel_changes, start=1):
        items.append(
            UITimelineItemDTO(
                id=f"tl_rel_{id}_{idx}",
                timestamp=str(sc.changed_at),
                type="state_change",
                title=f"Reconciliation: {sc.outcome}",
                description=sc.description,
                outcome=str(sc.outcome),
                requires_review=getattr(sc, "requires_review", False),
            )
        )
    return items


@router.get(
    "/relationships",
    response_model=PaginatedResponse[UIRelationshipDTO],
    summary="Paginated UI Relationships",
)
async def get_ui_relationships(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[UIRelationshipDTO]:
    """Return paginated UIRelationshipDTO list (representing claims in the graph)."""
    wm = get_world_model_service()
    rels = await wm.get_all_relationships()

    all_ents = await wm.get_all_entities()
    entity_map = {e.id: e.name for e in all_ents}
    dtos = [_to_relationship_dto(r, entity_map) for r in rels]

    total = len(dtos)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_items = dtos[start_idx:end_idx]
    has_more = end_idx < total

    return PaginatedResponse[UIRelationshipDTO](
        items=paginated_items,
        total=total,
        page=page,
        limit=limit,
        has_more=has_more,
    )


@router.get(
    "/entities/{id}/timeline",
    response_model=list[UITimelineItemDTO],
    summary="UI Timeline for Entity",
)
async def get_ui_entity_timeline(id: str) -> list[UITimelineItemDTO]:
    """Return chronological UITimelineItemDTO timeline for an entity."""
    wm = get_world_model_service()
    raw_timeline = await wm.get_timeline_for_entity(id)

    items: list[UITimelineItemDTO] = []
    for idx, raw in enumerate(raw_timeline, start=1):
        items.append(
            UITimelineItemDTO(
                id=f"tl_ent_{id}_{idx}",
                timestamp=str(raw.get("timestamp", "")),
                type=str(raw.get("type", "state_change")),
                title=str(raw.get("description", "State Update")),
                description=str(raw.get("description", "")),
                outcome=raw.get("outcome"),
                requires_review=bool(raw.get("requires_review", False)),
            )
        )
    return items


@router.get("/graph", response_model=UIGraphDTO, summary="Small UIGraphDTO Payload")
async def get_ui_graph(
    entity_ids: list[str] | None = Query(default=None),
    depth: int = Query(default=1, ge=0, le=3),
) -> UIGraphDTO:
    """Return presentation-optimized graph payload with neighborhood filtering."""
    wm = get_world_model_service()
    ev = get_evidence_service()

    all_ents = await wm.get_all_entities()
    all_entities = {e.id: e for e in all_ents}
    all_rels = await wm.get_all_relationships()

    if not entity_ids:
        # Default load: projects, goals, and decisions to keep it focused
        entity_ids = [
            e.id
            for e in all_entities.values()
            if getattr(e, "entity_type", "") in ("project", "goal", "decision", "person")
        ]
        # Fallback if empty
        if not entity_ids and all_entities:
            entity_ids = list(all_entities.keys())[:10]

    visited_nodes: set[str] = set()
    visited_edges: set[str] = set()
    current_frontier = set(entity_ids)

    for _ in range(depth):
        next_frontier = set()
        for node_id in current_frontier:
            if node_id in visited_nodes:
                continue
            visited_nodes.add(node_id)
            for r in all_rels:
                if r.id in visited_edges:
                    continue
                if r.subject == node_id:
                    visited_edges.add(r.id)
                    next_frontier.add(r.object)
                elif r.object == node_id:
                    visited_edges.add(r.id)
                    next_frontier.add(r.subject)
        current_frontier = next_frontier

    visited_nodes.update(current_frontier)

    nodes: list[UIGraphNode] = [
        UIGraphNode(
            id=e.id,
            type=str(getattr(e, "entity_type", "entity")).lower(),
            label=getattr(e, "name", e.id),
            metadata={
                "email": getattr(e, "email", None),
                "domain": getattr(e, "domain", None),
                "confidence": getattr(e.confidence, "score", 1.0)
                if hasattr(e, "confidence")
                else 1.0,
            },
        )
        for e in all_entities.values()
        if e.id in visited_nodes
    ]

    edges: list[UIGraphEdge] = []
    for r in all_rels:
        if r.id not in visited_edges:
            # Also include edges between any two visited nodes even if they weren't traversed
            if r.subject in visited_nodes and r.object in visited_nodes:
                visited_edges.add(r.id)
            else:
                continue

        rel_ev = await ev.get_evidence_for_relationship(r.id)
        is_active = getattr(r.validity, "is_open_ended", True)
        rel_status = "active" if is_active else "closed"

        edges.append(
            UIGraphEdge(
                id=r.id,
                source=r.subject,
                target=r.object,
                relationship_type=str(r.predicate),
                confidence=getattr(r.confidence, "score", 1.0) if hasattr(r, "confidence") else 1.0,
                status=rel_status,
                evidence_count=len(rel_ev),
                valid_from=str(r.validity.valid_from)
                if getattr(r.validity, "valid_from", None)
                else None,
                valid_to=str(r.validity.valid_to)
                if getattr(r.validity, "valid_to", None)
                else None,
            )
        )

    return UIGraphDTO(nodes=nodes, edges=edges)


@router.get("/timeline", response_model=list[UITimelineItemDTO], summary="UI Global Timeline")
async def get_ui_timeline() -> list[UITimelineItemDTO]:
    """Return global audit trail as UITimelineItemDTO list."""
    wm = get_world_model_service()
    changes = await wm.get_state_changes()

    return [
        UITimelineItemDTO(
            id=f"tl_{sc.id}",
            timestamp=str(sc.changed_at),
            type="state_change",
            title=f"Reconciliation: {sc.outcome}",
            description=sc.description,
            outcome=str(sc.outcome),
            requires_review=getattr(sc, "requires_review", False),
        )
        for sc in changes
    ]


@router.get(
    "/evidence/{id}",
    response_model=PaginatedResponse[UIEvidenceDTO],
    summary="Paginated UI Evidence by Target ID",
)
async def get_ui_evidence_by_target_id(
    id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[UIEvidenceDTO]:
    """Return paginated evidence DTOs supporting a specific entity/relationship ID."""
    ev = get_evidence_service()
    records = await ev.get_evidence_for_entity(id)
    if not records:
        records = await ev.get_evidence_for_relationship(id)

    dtos = [
        UIEvidenceDTO(
            id=rec.id,
            observation_id=rec.observation_id,
            source_message_id=rec.source_message_id,
            target_id=rec.target_id,
            target_type=rec.target_type,
            text_snippet=rec.evidence_span.text_snippet,
            confidence=rec.evidence_span.confidence.score,
            recorded_at=str(rec.recorded_at),
        )
        for rec in records
    ]

    total = len(dtos)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_items = dtos[start_idx:end_idx]
    has_more = end_idx < total

    return PaginatedResponse[UIEvidenceDTO](
        items=paginated_items,
        total=total,
        page=page,
        limit=limit,
        has_more=has_more,
    )


@router.get("/decisions", response_model=list[UIDecisionDTO], summary="UI Decision Memory Records")
async def get_ui_decisions() -> list[UIDecisionDTO]:
    """Return UIDecisionDTO list of decision memory records."""
    wm = get_world_model_service()
    decisions = await wm.get_entities_by_type("decision")

    return [
        UIDecisionDTO(
            id=d.id,
            name=d.name,
            question=getattr(d, "question", None),
            decision=getattr(d, "decision", None),
            alternatives=getattr(d, "alternatives", []),
            context=getattr(d, "context", None),
            status=str(getattr(d, "status", "MADE")),
            confidence=getattr(d.confidence, "score", 1.0) if hasattr(d, "confidence") else 1.0,
            created_at=str(d.created_at),
        )
        for d in decisions
    ]


@router.get("/changes", response_model=list[UIStateChangeDTO], summary="UI State Changes Audit Log")
async def get_ui_changes() -> list[UIStateChangeDTO]:
    """Return UIStateChangeDTO list of state change records."""
    wm = get_world_model_service()
    changes = await wm.get_state_changes()

    return [
        UIStateChangeDTO(
            id=sc.id,
            observation_id=sc.observation_id,
            entity_id=sc.entity_id,
            outcome=str(sc.outcome),
            description=sc.description,
            previous_value=getattr(sc, "previous_value", None),
            new_value=getattr(sc, "new_value", None),
            requires_review=getattr(sc, "requires_review", False),
            timestamp=str(sc.changed_at),
        )
        for sc in changes
    ]


@router.get(
    "/search", response_model=list[UISearchResultDTO], summary="Global Relationship-Aware Search"
)
async def global_search(q: str = Query(..., min_length=1)) -> list[UISearchResultDTO]:
    """Search across entities, relationships, emails, and history."""
    query = q.lower()
    wm = get_world_model_service()
    ev = get_evidence_service()

    results: list[UISearchResultDTO] = []

    all_ents = await wm.get_all_entities()
    all_entities = {e.id: e for e in all_ents}
    all_rels = await wm.get_all_relationships()

    # 1. Search Entities
    matched_entity_ids = set()
    for e in all_entities.values():
        if query in e.name.lower() or (e.description and query in e.description.lower()):
            matched_entity_ids.add(e.id)
            results.append(
                UISearchResultDTO(
                    id=e.id,
                    result_type="entity",
                    subtype=str(e.entity_type).lower(),
                    title=e.name,
                    current_status=str(getattr(e, "status", "ACTIVE")).upper(),
                    timestamp=e.created_at.isoformat() if e.created_at else None,
                    confidence=getattr(e.confidence, "score", 1.0)
                    if getattr(e, "confidence", None)
                    else None,
                    evidence_count=0,
                )
            )

    # 2. Search Relationships
    for r in all_rels:
        r_type = str(r.predicate)
        subject_name = all_entities[r.subject].name if r.subject in all_entities else r.subject
        object_name = all_entities[r.object].name if r.object in all_entities else r.object
        full_text = f"{subject_name} {r_type} {object_name}".lower()

        is_match = query in full_text
        is_connected = r.subject in matched_entity_ids or r.object in matched_entity_ids

        r_valid_from = getattr(r.validity, "valid_from", None) if getattr(r, "validity", None) else None

        if is_match or is_connected:
            results.append(
                UISearchResultDTO(
                    id=r.id,
                    result_type="relationship",
                    subtype=r_type,
                    title=f"{subject_name} → {r_type} → {object_name}",
                    current_status=str(getattr(r, "status", "ACTIVE")),
                    timestamp=r_valid_from.isoformat() if r_valid_from and hasattr(r_valid_from, "isoformat") else None,
                    confidence=None,
                    evidence_count=0,
                )
            )

    # 3. Search Timeline / State Changes
    changes = await wm.get_state_changes()
    for c in changes:
        is_match = query in c.description.lower()
        is_connected = c.entity_id in matched_entity_ids

        if is_match or is_connected:
            results.append(
                UISearchResultDTO(
                    id=c.id,
                    result_type="timeline_event",
                    subtype=str(c.outcome).lower(),
                    title=c.description,
                    current_status=None,
                    timestamp=c.changed_at.isoformat() if c.changed_at else None,
                    confidence=None,
                    evidence_count=0,
                )
            )

    # 4. Search Evidence (Emails)
    all_evidence = await ev.get_all_evidence() if hasattr(ev, "get_all_evidence") else []
    for e in all_evidence:
        text = e.evidence_span.text_snippet
        is_match = query in text.lower()

        is_connected = False
        if e.target_type == "claim":
            if any(res.id == e.target_id and res.result_type == "relationship" for res in results):
                is_connected = True

        if is_match or is_connected:
            results.append(
                UISearchResultDTO(
                    id=e.source_message_id or e.id,
                    result_type="email",
                    subtype="email",
                    title="Evidence from Email",
                    current_status=None,
                    timestamp=e.recorded_at.isoformat() if e.recorded_at else None,
                    confidence=getattr(e.confidence, "score", 1.0),
                    evidence_count=1,
                    snippet=text,
                )
            )

    seen = set()
    unique_results = []

    type_priority = {"entity": 0, "relationship": 1, "timeline_event": 2, "email": 3}
    results.sort(key=lambda x: type_priority.get(x.result_type, 99))

    for r in results:
        uid = f"{r.result_type}_{r.id}"
        if uid not in seen:
            seen.add(uid)
            unique_results.append(r)

    return unique_results[:100]


@router.get("/my-world", response_model=UIMyWorldDTO, summary="Get Curated Canvas for My World")
async def get_my_world() -> UIMyWorldDTO:
    """Returns a highly curated graph payload for the My World visual canvas."""
    wm = get_world_model_service()

    nodes: list[UIMyWorldNode] = []
    edges: list[UIMyWorldEdge] = []

    def determine_epistemic_state(status: str, confidence: float, valid_until: str | None) -> str:
        if status == "HISTORICAL" or valid_until is not None:
            return "HISTORICAL"
        if status == "CONFLICT":
            return "CONFLICTING"
        if status == "UNCERTAIN" or confidence < 0.6:
            return "UNCERTAIN"
        if confidence == 1.0:
            return "USER_CONFIRMED"
        if confidence >= 0.8:
            return "OBSERVED"
        return "INFERRED"

    # We only want to plot active or high priority entities to prevent clutter
    plotted_entities = set()

    all_ents = await wm.get_all_entities()
    for e in all_ents:
        e_status = str(getattr(e, "status", "ACTIVE"))
        if e_status != "ACTIVE":
            continue

        conf = getattr(e.confidence, "score", 0.9)
        e_state = determine_epistemic_state(e_status, conf, None)

        # Mapping generic EntityType to our specific UI categories
        cat = str(e.entity_type).lower()
        if cat not in ["person", "project", "organization", "goal", "decision"]:
            continue

        nodes.append(
            UIMyWorldNode(
                id=e.id,
                label=e.name,
                category=cat
                + "s",  # e.g., "people", "projects" (for "person" it'll be "persons", let's fix below)
                epistemic_state=e_state,
                confidence=conf,
            )
        )
        plotted_entities.add(e.id)

    # Fix 'persons' to 'people'
    for n in nodes:
        if n.category == "persons":
            n.category = "people"

    # Include relationships between plotted entities
    all_rels = await wm.get_all_relationships()
    for r in all_rels:
        if r.subject in plotted_entities and r.object in plotted_entities:
            conf = getattr(r.confidence, "score", 0.9)
            valid_to = getattr(r.validity, "valid_to", None) if getattr(r, "validity", None) else None
            valid_until = str(valid_to) if valid_to else None
            r_status = str(getattr(r, "status", "ACTIVE"))
            r_state = determine_epistemic_state(r_status, conf, valid_until)

            edges.append(
                UIMyWorldEdge(
                    id=r.id,
                    source=r.subject,
                    target=r.object,
                    label=str(r.predicate),
                    epistemic_state=r_state,
                    confidence=conf,
                )
            )

    return UIMyWorldDTO(nodes=nodes, edges=edges)
