"""Evidence Engine implementation for Gmail-derived extraction.

Manages evidence linkage between raw Observations and derived World Model objects.
Guarantees full provenance lineage tracing:

    World Model State → derived claim/entity/event/relationship → Gmail message → exact evidence span

Does NOT duplicate full email bodies into derived records.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from app.config.logging import get_logger
from app.domain.enums import EvidenceType
from app.domain.evidence import Evidence
from app.domain.values import ConfidenceScore, EvidenceSpan

if TYPE_CHECKING:
    from app.services.extraction import StructuredExtraction
    from app.persistence.duckdb_store import DuckDBStore

logger = get_logger(__name__)


def _parse_evidence(data_json: str) -> Evidence:
    return Evidence.model_validate_json(data_json)


class BaseEvidenceService(ABC):
    """Abstract interface for evidence recording and querying."""

    @abstractmethod
    async def record_evidence(
        self,
        observation_id: str,
        target_id: str | None = None,
        evidence_type: EvidenceType = EvidenceType.SUPPORTS,
        evidence_span: EvidenceSpan | None = None,
        confidence: ConfidenceScore | None = None,
        source_message_id: str = "",
        source_thread_id: str = "",
        target_type: str = "claim",
        content: str | None = None,
        claim_id: str | None = None,
    ) -> Evidence:
        """Record evidence linking an observation to a derived target item."""

    @abstractmethod
    async def get_evidence_for_entity(self, entity_id: str) -> list[Evidence]:
        """Fetch all evidence items associated with an entity."""

    @abstractmethod
    async def get_evidence_for_relationship(self, relationship_id: str) -> list[Evidence]:
        """Fetch all evidence items associated with a relationship."""

    @abstractmethod
    async def get_evidence_for_claim(self, claim_id: str) -> list[Evidence]:
        """Fetch all evidence items associated with a claim."""

    @abstractmethod
    async def get_evidence_for_event(self, event_id: str) -> list[Evidence]:
        """Fetch all evidence items associated with an event."""


class EvidenceService(BaseEvidenceService):
    """Production Evidence Engine implementation."""

    def __init__(self, duckdb_store: DuckDBStore | None = None) -> None:
        if duckdb_store is None:
            from app.config.settings import get_settings
            from app.persistence.duckdb_store import DuckDBStore

            duckdb_store = DuckDBStore(get_settings().duckdb_path)

        if duckdb_store is not None:
            duckdb_store.init_schema()

        self._duckdb = duckdb_store

    async def record_evidence(
        self,
        observation_id: str,
        target_id: str | None = None,
        evidence_type: EvidenceType = EvidenceType.SUPPORTS,
        evidence_span: EvidenceSpan | None = None,
        confidence: ConfidenceScore | None = None,
        source_message_id: str = "",
        source_thread_id: str = "",
        target_type: str = "claim",
        content: str | None = None,
        claim_id: str | None = None,
    ) -> Evidence:
        """Record a lean evidence item establishing provenance lineage."""
        effective_target_id = target_id or claim_id or ""
        if not effective_target_id:
            msg = "record_evidence requires target_id or claim_id."
            raise ValueError(msg)

        if evidence_span is None:
            text = content or ""
            conf = confidence or ConfidenceScore.from_score(0.9)
            evidence_span = EvidenceSpan(text_snippet=text, confidence=conf)

        if confidence is None:
            confidence = evidence_span.confidence

        ev = Evidence(
            source_observation_id=observation_id,
            source_message_id=source_message_id,
            source_thread_id=source_thread_id,
            target_id=effective_target_id,
            target_type=target_type,
            evidence_type=evidence_type,
            evidence_span=evidence_span,
            confidence=confidence,
        )

        if self._duckdb:
            data_json = ev.model_dump_json()
            with self._duckdb.get_connection() as conn:
                conn.execute(
                    """INSERT INTO evidence (id, target_id, target_type, data) VALUES (?, ?, ?, ?)
                       ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data""",
                    (ev.id, effective_target_id, target_type, data_json)
                )

        logger.info(
            "evidence_engine.recorded",
            evidence_id=ev.id,
            target_id=target_id,
            target_type=target_type,
            source_observation_id=observation_id,
            source_message_id=source_message_id,
        )
        return ev

    async def record_extraction_result(
        self,
        extraction: StructuredExtraction,
        source_message_id: str = "",
        source_thread_id: str = "",
    ) -> list[Evidence]:
        """Batch record evidence items for all extracted items in a StructuredExtraction payload."""
        obs_id = extraction.source_observation_id
        recorded: list[Evidence] = []

        # 1. Entities
        for ent in extraction.entities:
            span = EvidenceSpan(text_snippet=ent.name, confidence=ent.confidence)
            ev = await self.record_evidence(
                observation_id=obs_id,
                target_id=ent.id,
                target_type="entity",
                evidence_span=span,
                confidence=ent.confidence,
                source_message_id=source_message_id,
                source_thread_id=source_thread_id,
            )
            recorded.append(ev)

        # 2. Relationships
        for rel in extraction.relationships:
            span = rel.evidence_span or EvidenceSpan(
                text_snippet=f"{rel.subject} {rel.predicate} {rel.object}",
                confidence=rel.confidence,
            )
            ev = await self.record_evidence(
                observation_id=obs_id,
                target_id=rel.id,
                target_type="relationship",
                evidence_span=span,
                confidence=rel.confidence,
                source_message_id=source_message_id,
                source_thread_id=source_thread_id,
            )
            recorded.append(ev)

        # 3. Claims
        for claim in extraction.claims:
            for span in claim.evidence_spans:
                ev = await self.record_evidence(
                    observation_id=obs_id,
                    target_id=claim.id,
                    target_type="claim",
                    evidence_span=span,
                    confidence=claim.confidence,
                    source_message_id=source_message_id,
                    source_thread_id=source_thread_id,
                )
                recorded.append(ev)

        # 4. Events
        for evt in extraction.events:
            span = EvidenceSpan(text_snippet=evt.name, confidence=evt.confidence)
            ev = await self.record_evidence(
                observation_id=obs_id,
                target_id=evt.id,
                target_type="event",
                evidence_span=span,
                confidence=evt.confidence,
                source_message_id=source_message_id,
                source_thread_id=source_thread_id,
            )
            recorded.append(ev)

        # 5. Goals, Projects, Decisions, Constraints, Preferences
        sub_lists: list[tuple[list[Any], str]] = [
            (list(extraction.goals), "goal"),
            (list(extraction.projects), "project"),
            (list(extraction.decisions), "decision"),
            (list(extraction.constraints), "constraint"),
            (list(extraction.preferences), "preference"),
        ]
        for sub_list, item_type in sub_lists:
            for item in sub_list:
                item_name = str(getattr(item, "name", str(item)))
                span = EvidenceSpan(text_snippet=item_name, confidence=item.confidence)
                ev = await self.record_evidence(
                    observation_id=obs_id,
                    target_id=item.id,
                    target_type=item_type,
                    evidence_span=span,
                    confidence=item.confidence,
                    source_message_id=source_message_id,
                    source_thread_id=source_thread_id,
                )
                recorded.append(ev)

        return recorded

    async def get_evidence_for_entity(self, entity_id: str) -> list[Evidence]:
        """Fetch all evidence items associated with an entity."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection() as conn:
            results = conn.execute("SELECT data FROM evidence WHERE target_id = ?", (entity_id,)).fetchall()
            return [_parse_evidence(row[0]) for row in results if row[0]]

    async def get_evidence_for_relationship(self, relationship_id: str) -> list[Evidence]:
        """Fetch all evidence items associated with a relationship."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection() as conn:
            results = conn.execute("SELECT data FROM evidence WHERE target_id = ?", (relationship_id,)).fetchall()
            return [_parse_evidence(row[0]) for row in results if row[0]]

    async def get_evidence_for_claim(self, claim_id: str) -> list[Evidence]:
        """Fetch all evidence items associated with a claim."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection() as conn:
            results = conn.execute("SELECT data FROM evidence WHERE target_id = ?", (claim_id,)).fetchall()
            return [_parse_evidence(row[0]) for row in results if row[0]]

    async def get_evidence_for_event(self, event_id: str) -> list[Evidence]:
        """Fetch all evidence items associated with an event."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection() as conn:
            results = conn.execute("SELECT data FROM evidence WHERE target_id = ?", (event_id,)).fetchall()
            return [_parse_evidence(row[0]) for row in results if row[0]]

    async def get_all_evidence(self) -> list[Evidence]:
        """Fetch all evidence items."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection() as conn:
            results = conn.execute("SELECT data FROM evidence").fetchall()
            return [_parse_evidence(row[0]) for row in results if row[0]]
