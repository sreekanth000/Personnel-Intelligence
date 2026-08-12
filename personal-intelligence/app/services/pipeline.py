"""Gmail -> Personal World Model End-to-End Ingestion Pipeline.

Executes:
1. Raw Gmail Observation ingestion
2. HTML & noise normalization (GmailNormalizer)
3. GPT-4.1 structured extraction (GPT41Extractor)
4. Evidence recording with character offsets (EvidenceService)
5. Entity Resolution (EntityResolver)
6. Relationship Candidate Validation (Entities, Predicate, Evidence, Confidence, Existing check)
7. Candidate classification: NEW, CONFIRM, UPDATE, CONFLICT, UNCERTAIN
8. World Model state persistence & IngestionReport generation

Does NOT blindly persist relationships — every candidate undergoes rigorous 6-step validation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config.logging import get_logger
from app.connectors.gmail_normalizer import GmailNormalizer
from app.domain.entities import Entity, Relationship
from app.domain.enums import ObservationSource, RelationshipType
from app.domain.pipeline import CandidateRelationshipResult, IngestionReport
from app.services.entity_resolution import EntityResolver
from app.services.evidence import EvidenceService
from app.services.extraction import GPT41Extractor
from app.services.reconciliation import ReconciliationEngine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.domain.observations import Observation
    from app.services.world_model import WorldModelService

logger = get_logger(__name__)


class GmailPipelineService:
    """End-to-end pipeline processing Gmail emails into Personal World Model state."""

    def __init__(
        self,
        extractor: GPT41Extractor | None = None,
        evidence_service: EvidenceService | None = None,
        entity_resolver: EntityResolver | None = None,
        world_model_service: WorldModelService | None = None,
        normalizer: GmailNormalizer | None = None,
        reconciliation_engine: ReconciliationEngine | None = None,
    ) -> None:
        self._extractor = extractor or GPT41Extractor()
        self._evidence_service = evidence_service or EvidenceService()
        self._entity_resolver = entity_resolver or EntityResolver()
        self._world_model = world_model_service
        self._normalizer = normalizer or GmailNormalizer()
        self._reconciliation_engine = reconciliation_engine or ReconciliationEngine(
            world_model_service=world_model_service
        )

    async def process_observation(
        self,
        raw_observation: Observation,
        existing_entities: Sequence[Entity] = (),
        existing_relationships: Sequence[Relationship] = (),
    ) -> IngestionReport:
        """Process any raw Observation (Gmail, Google Calendar, Google Drive, Local Notes) into the World Model."""
        if raw_observation.source == ObservationSource.GMAIL:
            return await self.process_gmail_observation(
                raw_observation=raw_observation,
                existing_entities=existing_entities,
                existing_relationships=existing_relationships,
            )

        logger.info(
            "pipeline.start_multi_source",
            raw_observation_id=raw_observation.id,
            source=raw_observation.source,
            identifier=raw_observation.source_identifier,
        )

        # 1. Extraction directly from multi-source observation content
        extraction = await self._extractor.extract_from_observation(raw_observation)

        # 2. Evidence Recording
        evidence_records = await self._evidence_service.record_extraction_result(
            extraction=extraction,
            source_message_id=raw_observation.source_identifier,
            source_thread_id=raw_observation.metadata.get("calendar_event_id") or raw_observation.metadata.get("drive_file_id") or "",
        )

        # 3. Entity Resolution
        resolved_entities_map: dict[str, Entity] = {}
        active_entities = list(existing_entities)
        entities_processed = len(extraction.entities)
        entities_resolved = 0
        entities_new = 0
        entities_requiring_review = 0

        organizer = raw_observation.metadata.get("organizer") or raw_observation.metadata.get("author") or ""
        participants = [organizer] if organizer else []

        for ext_entity in extraction.entities:
            resolution = self._entity_resolver.resolve_entity(
                extracted_entity=ext_entity,
                existing_entities=active_entities,
                thread_participants=participants,
            )
            if resolution.requires_review:
                entities_requiring_review += 1
                resolved_entities_map[ext_entity.id] = ext_entity
                resolved_entities_map[ext_entity.name] = ext_entity
            elif resolution.matched_entity is not None:
                entities_resolved += 1
                resolved_entities_map[ext_entity.id] = resolution.matched_entity
                resolved_entities_map[ext_entity.name] = resolution.matched_entity
            else:
                entities_new += 1
                active_entities.append(ext_entity)
                resolved_entities_map[ext_entity.id] = ext_entity
                resolved_entities_map[ext_entity.name] = ext_entity

                if self._world_model is not None:
                    await self._world_model.save_entity(ext_entity)

        # 4. Relationship Validation & ReconciliationEngine
        known_relationships = list(existing_relationships)
        candidate_results: list[CandidateRelationshipResult] = []
        relationships_by_status: dict[str, int] = {
            "NEW": 0,
            "CONFIRM": 0,
            "UPDATE": 0,
            "CONFLICT": 0,
            "UNCERTAIN": 0,
        }

        for rel_candidate in extraction.relationships:
            result = await self._validate_and_classify_relationship(
                candidate=rel_candidate,
                resolved_entities_map=resolved_entities_map,
                existing_relationships=known_relationships,
            )
            candidate_results.append(result)
            relationships_by_status[result.status] += 1

            if result.status in ("NEW", "UPDATE") and self._world_model is not None:
                await self._world_model.save_relationship(result.relationship)
                known_relationships.append(result.relationship)

        # 5. Claim Reconciliation & Persistence
        if extraction.claims and self._world_model is not None:
            known_claims = await self._world_model.get_all_claims()
            for claim in extraction.claims:
                await self._reconciliation_engine.reconcile_claim(
                    candidate=claim,
                    existing_claims=known_claims,
                )
                await self._world_model.save_claim(claim)
                known_claims.append(claim)
                if self._evidence_service is not None:
                    await self._evidence_service.record_evidence(
                        target_id=claim.id,
                        target_type="claim",
                        source_observation_id=raw_observation.id,
                        source_message_id=raw_observation.source_identifier,
                        spans=claim.evidence_spans,
                    )

        report = IngestionReport(
            raw_observation_id=raw_observation.id,
            message_id=raw_observation.source_identifier,
            thread_id=raw_observation.source_identifier,
            sender=organizer,
            subject=raw_observation.metadata.get("summary") or raw_observation.metadata.get("filename") or "Observation",
            entities_processed=entities_processed,
            entities_resolved=entities_resolved,
            entities_new=entities_new,
            entities_requiring_review=entities_requiring_review,
            relationships_candidate_count=len(extraction.relationships),
            relationships_by_status=relationships_by_status,
            candidate_relationship_results=candidate_results,
            evidence_records_created=len(evidence_records),
            success=True,
        )

        logger.info(
            "pipeline.complete_multi_source",
            raw_observation_id=report.raw_observation_id,
            source=raw_observation.source,
            new_rel=relationships_by_status["NEW"],
        )
        return report

    async def process_gmail_observation(
        self,
        raw_observation: Observation,
        existing_entities: Sequence[Entity] = (),
        existing_relationships: Sequence[Relationship] = (),
    ) -> IngestionReport:
        """Process a raw Gmail Observation into the Personal World Model.

        Args:
            raw_observation: Raw Gmail observation.
            existing_entities: Current active entities in World Model.
            existing_relationships: Current active relationships in World Model.

        Returns:
            IngestionReport summarizing complete pipeline execution.
        """
        logger.info(
            "pipeline.start",
            raw_observation_id=raw_observation.id,
            source=raw_observation.source,
        )

        # -------------------------------------------------------------------
        # Step 1 & 2: Normalization
        # -------------------------------------------------------------------
        norm_obs = self._normalizer.normalize_observation(raw_observation)
        logger.info(
            "pipeline.normalized",
            raw_observation_id=norm_obs.raw_observation_id,
            message_id=norm_obs.message_id,
            body_length=len(norm_obs.body),
        )

        # -------------------------------------------------------------------
        # Step 3: GPT-4.1 Extraction
        # -------------------------------------------------------------------
        extraction = await self._extractor.extract_from_normalized_email(norm_obs)
        logger.info(
            "pipeline.extracted",
            entities_count=len(extraction.entities),
            relationships_count=len(extraction.relationships),
            claims_count=len(extraction.claims),
        )

        # -------------------------------------------------------------------
        # Step 4: Evidence Recording
        # -------------------------------------------------------------------
        evidence_records = await self._evidence_service.record_extraction_result(
            extraction=extraction,
            source_message_id=norm_obs.message_id,
            source_thread_id=norm_obs.thread_id,
        )

        # -------------------------------------------------------------------
        # Step 5: Entity Resolution
        # -------------------------------------------------------------------
        resolved_entities_map: dict[str, Entity] = {}  # temp_id/name -> resolved entity
        active_entities = list(existing_entities)

        entities_processed = len(extraction.entities)
        entities_resolved = 0
        entities_new = 0
        entities_requiring_review = 0

        thread_participants = [norm_obs.sender, *norm_obs.recipients, *norm_obs.cc]

        for ext_entity in extraction.entities:
            resolution = self._entity_resolver.resolve_entity(
                extracted_entity=ext_entity,
                existing_entities=active_entities,
                thread_participants=thread_participants,
            )

            if resolution.requires_review:
                entities_requiring_review += 1
                resolved_entities_map[ext_entity.id] = ext_entity
                resolved_entities_map[ext_entity.name] = ext_entity
            elif resolution.matched_entity is not None:
                entities_resolved += 1
                resolved_entities_map[ext_entity.id] = resolution.matched_entity
                resolved_entities_map[ext_entity.name] = resolution.matched_entity
            else:
                entities_new += 1
                active_entities.append(ext_entity)
                resolved_entities_map[ext_entity.id] = ext_entity
                resolved_entities_map[ext_entity.name] = ext_entity

                if self._world_model is not None:
                    await self._world_model.save_entity(ext_entity)

        # -------------------------------------------------------------------
        # Step 6 & 7: Relationship Validation & Candidate Classification
        # -------------------------------------------------------------------
        known_relationships = list(existing_relationships)
        candidate_results: list[CandidateRelationshipResult] = []
        relationships_by_status: dict[str, int] = {
            "NEW": 0,
            "CONFIRM": 0,
            "UPDATE": 0,
            "CONFLICT": 0,
            "UNCERTAIN": 0,
        }

        for rel_candidate in extraction.relationships:
            result = await self._validate_and_classify_relationship(
                candidate=rel_candidate,
                resolved_entities_map=resolved_entities_map,
                existing_relationships=known_relationships,
            )
            candidate_results.append(result)
            relationships_by_status[result.status] += 1

            # Persist valid NEW / UPDATE relationships to World Model
            if result.status in ("NEW", "UPDATE") and self._world_model is not None:
                await self._world_model.save_relationship(result.relationship)
                known_relationships.append(result.relationship)

        # -------------------------------------------------------------------
        # Step 7b: Reconcile & Persist Claims via ReconciliationEngine
        # -------------------------------------------------------------------
        if extraction.claims and self._world_model is not None:
            known_claims = await self._world_model.get_all_claims()
            for claim in extraction.claims:
                rec_claim_record = await self._reconciliation_engine.reconcile_claim(
                    candidate=claim,
                    existing_claims=known_claims,
                )
                await self._world_model.save_claim(claim)
                known_claims.append(claim)
                if self._evidence_service is not None:
                    await self._evidence_service.record_evidence(
                        target_id=claim.id,
                        target_type="claim",
                        source_observation_id=norm_obs.raw_observation_id,
                        source_message_id=norm_obs.message_id,
                        spans=claim.evidence_spans,
                    )

        # -------------------------------------------------------------------
        # Step 8: Build Ingestion Report
        # -------------------------------------------------------------------
        report = IngestionReport(
            raw_observation_id=norm_obs.raw_observation_id,
            message_id=norm_obs.message_id,
            thread_id=norm_obs.thread_id,
            sender=norm_obs.sender,
            subject=norm_obs.subject,
            entities_processed=entities_processed,
            entities_resolved=entities_resolved,
            entities_new=entities_new,
            entities_requiring_review=entities_requiring_review,
            relationships_candidate_count=len(extraction.relationships),
            relationships_by_status=relationships_by_status,
            candidate_relationship_results=candidate_results,
            evidence_records_created=len(evidence_records),
            success=True,
        )

        logger.info(
            "pipeline.complete",
            raw_observation_id=report.raw_observation_id,
            new_rel=relationships_by_status["NEW"],
            confirm_rel=relationships_by_status["CONFIRM"],
            uncertain_rel=relationships_by_status["UNCERTAIN"],
        )
        return report

    async def _validate_and_classify_relationship(
        self,
        candidate: Relationship,
        resolved_entities_map: dict[str, Entity],
        existing_relationships: Sequence[Relationship],
    ) -> CandidateRelationshipResult:
        """Run candidate relationship through entity/predicate checks and delegate reconciliation to ReconciliationEngine."""
        subject_name = candidate.subject
        object_name = candidate.object
        evidence_str = candidate.evidence_span.text_snippet if candidate.evidence_span else ""

        # 1. Validate entities
        subj_entity = resolved_entities_map.get(candidate.subject) or resolved_entities_map.get(
            subject_name
        )
        obj_entity = resolved_entities_map.get(candidate.object) or resolved_entities_map.get(
            object_name
        )

        if not subj_entity or not obj_entity:
            return CandidateRelationshipResult(
                relationship=candidate,
                status="UNCERTAIN",
                reason=f"Failed entity validation: Subject ('{subject_name}') or Object ('{object_name}') could not be resolved.",
                evidence_snippet=evidence_str,
                subject_entity_name=subject_name,
                object_entity_name=object_name,
            )

        resolved_subj_id = subj_entity.id
        resolved_obj_id = obj_entity.id

        # 2. Validate predicate
        valid_predicates = [p.value for p in RelationshipType]
        pred_str = str(candidate.predicate).lower()
        if pred_str not in valid_predicates and pred_str not in [
            p.name.lower() for p in RelationshipType
        ]:
            return CandidateRelationshipResult(
                relationship=candidate,
                status="UNCERTAIN",
                reason=f"Failed predicate validation: '{candidate.predicate}' is not a recognized RelationshipType.",
                evidence_snippet=evidence_str,
                subject_entity_name=subj_entity.name,
                object_entity_name=obj_entity.name,
            )

        # 3. Validate evidence grounding
        if not candidate.evidence_span or not candidate.evidence_span.text_snippet.strip():
            return CandidateRelationshipResult(
                relationship=candidate,
                status="UNCERTAIN",
                reason="Failed evidence validation: Missing text snippet in evidence_span.",
                evidence_snippet="",
                subject_entity_name=subj_entity.name,
                object_entity_name=obj_entity.name,
            )

        # Build updated relationship with resolved entity IDs
        validated_relationship = Relationship(
            id=candidate.id,
            subject=resolved_subj_id,
            predicate=candidate.predicate,
            object=resolved_obj_id,
            confidence=candidate.confidence,
            evidence_span=candidate.evidence_span,
            source_observation_id=candidate.source_observation_id,
            validity=candidate.validity,
            provenance=candidate.provenance,
        )

        # 4. Delegate to ReconciliationEngine for deterministic lifecycle & temporal guarantees
        rec_record = await self._reconciliation_engine.reconcile_relationship(
            candidate=validated_relationship,
            existing_relationships=existing_relationships,
            evidence=candidate.evidence_span,
        )

        outcome_val = str(rec_record.outcome.value).upper()
        if outcome_val == "NOVEL":
            status = "NEW"
        elif outcome_val == "CONFIRM":
            status = "CONFIRM"
        elif outcome_val in ("UPDATE", "REFINE"):
            status = "UPDATE"
            # Crucial temporal guarantee: Close previous relationship validity interval on UPDATE
            if rec_record.closed_previous_relationship_id and self._world_model is not None:
                for ex_rel in existing_relationships:
                    if ex_rel.id == rec_record.closed_previous_relationship_id:
                        ex_rel.validity.valid_to = rec_record.timestamp
                        await self._world_model.save_relationship(ex_rel)
                        break
        elif outcome_val == "CONFLICT":
            status = "CONFLICT"
        else:
            status = "UNCERTAIN"

        return CandidateRelationshipResult(
            relationship=validated_relationship,
            status=status,
            reason=rec_record.reconciliation_reason,
            evidence_snippet=evidence_str,
            subject_entity_name=subj_entity.name,
            object_entity_name=obj_entity.name,
        )
