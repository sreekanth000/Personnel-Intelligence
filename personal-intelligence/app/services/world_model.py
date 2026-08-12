"""Personal World Model Service.

Provides unified persistence operations across DuckDB (relational/structured)
and Kuzu (graph database) for entities, relationships, claims, and temporal snapshots.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import TYPE_CHECKING, Any

from app.config.logging import get_logger
from app.domain.claims import Claim
from app.domain.values import _utcnow
from app.domain.world_state import StateChange, SynthesizedCurrentState, WorldState
from app.domain.entities import Entity, Relationship, Event, Goal, Project, Task, Decision, Preference, Constraint, Commitment

if TYPE_CHECKING:
    from app.domain.enums import EntityType
    from app.persistence.duckdb_store import DuckDBStore
    from app.persistence.kuzu_store import KuzuStore

logger = get_logger(__name__)


def _parse_claim(data_json: str) -> Claim:
    return Claim.model_validate_json(data_json)



def _parse_entity(data_json: str) -> Entity:
    data = json.loads(data_json)
    etype = str(data.get("entity_type", "")).lower()
    
    try:
        if etype == "event": return Event.model_validate(data)
        elif etype == "goal": return Goal.model_validate(data)
        elif etype == "project": return Project.model_validate(data)
        elif etype == "task": return Task.model_validate(data)
        elif etype == "decision": return Decision.model_validate(data)
        elif etype == "preference": return Preference.model_validate(data)
        elif etype == "constraint": return Constraint.model_validate(data)
        elif etype == "commitment": return Commitment.model_validate(data)
    except Exception as e:
        logger.warning("world_model.parse_entity_fallback", entity_id=data.get("id"), type=etype, error=str(e))
        
    return Entity.model_validate(data)


def _parse_relationship(data_json: str) -> Relationship:
    return Relationship.model_validate_json(data_json)


def _parse_state_change(data_json: str) -> StateChange:
    return StateChange.model_validate_json(data_json)


class BaseWorldModelService(ABC):
    """Abstract interface for personal world model persistence."""

    @abstractmethod
    async def save_entity(self, entity: Entity) -> None:
        """Save or update an entity in the world model."""

    @abstractmethod
    async def get_entity(self, entity_id: str) -> Entity | None:
        """Retrieve an entity by ID."""

    @abstractmethod
    async def save_relationship(self, relationship: Relationship) -> None:
        """Save a relationship (graph edge) in the world model."""

    @abstractmethod
    async def save_claim(self, claim: Claim) -> None:
        """Save a claim in the world model."""

    @abstractmethod
    async def get_current_state(self) -> WorldState:
        """Get the current point-in-time WorldState snapshot."""


class WorldModelService(BaseWorldModelService):
    """Unified service bridging DuckDB and Kuzu graph database."""

    def __init__(
        self, duckdb_store: DuckDBStore | None = None, kuzu_store: KuzuStore | None = None
    ) -> None:
        from app.config.settings import get_settings
        from app.persistence.duckdb_store import DuckDBStore
        from app.persistence.kuzu_store import KuzuStore

        if duckdb_store is None:
            duckdb_store = DuckDBStore(get_settings().duckdb_path)

        if kuzu_store is None:
            kuzu_store = KuzuStore(get_settings().kuzu_path)

        if duckdb_store is not None:
            duckdb_store.init_schema()
        if kuzu_store is not None:
            kuzu_store.init_schema()

        self._duckdb = duckdb_store
        self._kuzu = kuzu_store
        self._unresolved_conflicts: list[dict[str, Any]] = []

    async def save_entity(self, entity: Entity) -> None:
        """Persist entity to DuckDB, and Kuzu."""
        if self._duckdb:
            data_json = entity.model_dump_json()
            with self._duckdb.get_connection() as conn:
                conn.execute(
                    """INSERT INTO entities (id, type, data) VALUES (?, ?, ?)
                       ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, type = EXCLUDED.type""",
                    (entity.id, str(entity.entity_type), data_json)
                )
            
        if self._kuzu:
            name = getattr(entity, "name", entity.id)
            with self._kuzu.get_connection() as conn:
                conn.execute(
                    "MERGE (e:Entity {id: $id}) ON MATCH SET e.type = $type, e.name = $name ON CREATE SET e.type = $type, e.name = $name",
                    {"id": entity.id, "type": str(entity.entity_type), "name": name}
                )

        logger.info("world_model.save_entity", entity_id=entity.id, type=entity.entity_type)

    async def get_entity(self, entity_id: str) -> Entity | None:
        """Fetch entity by ID."""
        if not self._duckdb:
            return None
        with self._duckdb.get_connection() as conn:
            result = conn.execute("SELECT data FROM entities WHERE id = ?", (entity_id,)).fetchone()
            if result and result[0]:
                return _parse_entity(result[0])
        return None

    async def get_all_entities(self) -> list[Entity]:
        """Fetch all entities."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection() as conn:
            results = conn.execute("SELECT data FROM entities").fetchall()
            return [_parse_entity(row[0]) for row in results if row[0]]

    async def get_all_relationships(self) -> list[Relationship]:
        """Fetch all relationships."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection() as conn:
            results = conn.execute("SELECT data FROM relationships").fetchall()
            return [_parse_relationship(row[0]) for row in results if row[0]]

    async def save_relationship(self, relationship: Relationship) -> None:
        """Persist relationship edge."""
        if self._duckdb:
            data_json = relationship.model_dump_json()
            with self._duckdb.get_connection() as conn:
                conn.execute(
                    """INSERT INTO relationships (id, subject, predicate, object, data) VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, subject = EXCLUDED.subject, predicate = EXCLUDED.predicate, object = EXCLUDED.object""",
                    (relationship.id, relationship.subject, str(relationship.predicate), relationship.object, data_json)
                )
            
        if self._kuzu:
            with self._kuzu.get_connection() as conn:
                # We must ensure the source and target nodes exist first
                conn.execute(
                    """
                    MERGE (s:Entity {id: $subject})
                    MERGE (o:Entity {id: $object})
                    MERGE (s)-[r:Edge {id: $id}]->(o)
                    ON MATCH SET r.predicate = $predicate
                    ON CREATE SET r.predicate = $predicate
                    """,
                    {
                        "subject": relationship.subject, 
                        "object": relationship.object, 
                        "id": relationship.id, 
                        "predicate": str(relationship.predicate)
                    }
                )

        logger.info(
            "world_model.save_relationship",
            rel_id=relationship.id,
            source=relationship.source_entity_id,
            target=relationship.target_entity_id,
        )

    async def save_claim(self, claim: Claim) -> None:
        """Persist claim into DuckDB."""
        if self._duckdb:
            data_json = claim.model_dump_json()
            with self._duckdb.get_connection() as conn:
                conn.execute(
                    """INSERT INTO claims (id, subject, predicate, value, status, data) VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT (id) DO UPDATE SET
                           subject = EXCLUDED.subject,
                           predicate = EXCLUDED.predicate,
                           value = EXCLUDED.value,
                           status = EXCLUDED.status,
                           data = EXCLUDED.data""",
                    (
                        claim.id,
                        claim.subject,
                        str(claim.predicate),
                        str(claim.value),
                        str(claim.status),
                        data_json,
                    ),
                )
        logger.info("world_model.save_claim", claim_id=claim.id, status=claim.status)

    async def get_claim(self, claim_id: str) -> Claim | None:
        """Retrieve a claim by ID."""
        if not self._duckdb:
            return None
        with self._duckdb.get_connection(read_only=True) as conn:
            result = conn.execute("SELECT data FROM claims WHERE id = ?", (claim_id,)).fetchone()
            if result and result[0]:
                return _parse_claim(result[0])
        return None

    async def get_all_claims(self) -> list[Claim]:
        """Fetch all claims from DuckDB."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection(read_only=True) as conn:
            results = conn.execute("SELECT data FROM claims").fetchall()
            return [_parse_claim(row[0]) for row in results if row[0]]

    async def get_claims_for_entity(self, entity_id: str) -> list[Claim]:
        """Retrieve claims associated with given entity_id as subject or value."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection(read_only=True) as conn:
            results = conn.execute(
                "SELECT data FROM claims WHERE subject = ? OR value = ?",
                (entity_id, entity_id),
            ).fetchall()
            return [_parse_claim(row[0]) for row in results if row[0]]

    async def get_claims_by_status(self, status: str) -> list[Claim]:
        """Retrieve claims matching status."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection(read_only=True) as conn:
            results = conn.execute(
                "SELECT data FROM claims WHERE LOWER(status) = ?",
                (str(status).lower(),),
            ).fetchall()
            return [_parse_claim(row[0]) for row in results if row[0]]

    async def record_state_change(self, change: StateChange) -> None:
        """Record state change entry."""
        if not self._duckdb:
            return
        data_json = change.model_dump_json()
        with self._duckdb.get_connection() as conn:
            conn.execute(
                """INSERT INTO state_changes (id, entity_id, observation_id, data) VALUES (?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data""",
                (change.id, change.entity_id or "", change.observation_id or "", data_json)
            )

    async def get_state_changes(self) -> list[StateChange]:
        """Return historical log of state changes."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection() as conn:
            results = conn.execute("SELECT data FROM state_changes ORDER BY created_at ASC").fetchall()
            return [_parse_state_change(row[0]) for row in results if row[0]]

    async def get_entities_by_type(self, entity_type: str | EntityType) -> list[Entity]:
        """Retrieve all entities matching given EntityType."""
        target_type = str(entity_type).lower()
        if not self._duckdb:
            return []
        with self._duckdb.get_connection() as conn:
            results = conn.execute("SELECT data FROM entities WHERE LOWER(type) = ?", (target_type,)).fetchall()
            return [_parse_entity(row[0]) for row in results if row[0]]

    async def get_relationships_for_entity(self, entity_id: str) -> list[Relationship]:
        """Retrieve all active relationships involving entity_id as subject or object."""
        if not self._duckdb:
            return []
        with self._duckdb.get_connection() as conn:
            results = conn.execute(
                "SELECT data FROM relationships WHERE subject = ? OR object = ?", 
                (entity_id, entity_id)
            ).fetchall()
            rels = [_parse_relationship(row[0]) for row in results if row[0]]
            return [r for r in rels if r.validity.is_open_ended]

    async def get_timeline_for_entity(self, entity_id: str) -> list[dict[str, Any]]:
        """Construct temporal timeline of events and state changes for entity_id."""
        timeline: list[dict[str, Any]] = []
        
        state_changes = await self.get_state_changes()
        for sc in state_changes:
            if sc.entity_id == entity_id:
                timeline.append(
                    {
                        "timestamp": sc.changed_at.isoformat(),
                        "type": "state_change",
                        "description": sc.description,
                        "outcome": sc.outcome,
                    }
                )

        entities = await self.get_all_entities()
        for entity in entities:
            if str(entity.entity_type).lower() == "event":
                attendees = getattr(entity, "attendees", [])
                if entity.id == entity_id or entity_id in attendees:
                    starts = getattr(entity, "starts_at", entity.created_at)
                    timeline.append(
                        {
                            "timestamp": starts.isoformat()
                            if hasattr(starts, "isoformat")
                            else str(starts),
                            "type": "event",
                            "name": entity.name,
                            "description": entity.description,
                        }
                    )

        timeline.sort(key=lambda item: str(item.get("timestamp", "")))
        return timeline

    async def get_current_state(self) -> WorldState:
        """Generate current point-in-time WorldState snapshot."""
        entities = await self.get_all_entities()
        rels = await self.get_all_relationships()
        recent_changes = (await self.get_state_changes())[-10:]
        
        active_entity_ids = [e.id for e in entities]
        active_rel_ids = [r.id for r in rels if r.validity.is_open_ended]
        recent_sc_ids = [sc.id for sc in recent_changes]

        return WorldState(
            timestamp=_utcnow(),
            active_entity_ids=active_entity_ids,
            active_relationship_ids=active_rel_ids,
            recent_changes=recent_sc_ids,
        )

    async def get_synthesized_current_state(self) -> SynthesizedCurrentState:
        """Synthesize current state deterministically from structured World Model data (No LLM)."""
        people_entities = await self.get_entities_by_type("person")
        people_ids = {p.id for p in people_entities}

        all_rels = await self.get_all_relationships()
        active_people_rels = [
            r
            for r in all_rels
            if r.validity.is_open_ended and (r.subject in people_ids or r.object in people_ids)
        ]

        active_projects = await self.get_entities_by_type("project")
        active_goals = await self.get_entities_by_type("goal")
        recent_decisions = await self.get_entities_by_type("decision")
        recent_events = await self.get_entities_by_type("event")
        important_constraints = await self.get_entities_by_type("constraint")
        recent_state_changes = (await self.get_state_changes())[-10:]

        return SynthesizedCurrentState(
            timestamp=_utcnow(),
            active_people_relationships=active_people_rels,
            active_projects=active_projects,
            active_goals=active_goals,
            recent_decisions=recent_decisions,
            recent_events=recent_events,
            important_constraints=important_constraints,
            recent_state_changes=recent_state_changes,
            unresolved_conflicts=list(self._unresolved_conflicts),
        )

    async def apply_user_correction(
        self,
        target_id: str,
        target_type: str,
        action: str,
        reason: str,
        new_subject: str | None = None,
        new_predicate: str | None = None,
        new_object: str | None = None,
    ) -> tuple[str, str]:
        import uuid

        from app.domain.entities import Relationship
        from app.domain.enums import ReconciliationOutcome
        from app.domain.values import ConfidenceScore
        from app.domain.world_state import StateChange

        if target_type == "relationship":
            # Need to get relationship from DuckDB
            rels = await self.get_all_relationships()
            target = next((r for r in rels if r.id == target_id), None)
            if not target:
                raise ValueError("Target relationship not found")

            obs_id = f"obs_correction_{uuid.uuid4()}"

            if action == "confirm":
                target.confidence = ConfidenceScore(
                    score=1.0, category="high", reasoning="User confirmed"
                )
                target.properties["status"] = "CONFIRMED"
                await self.save_relationship(target)
                await self.record_state_change(
                    StateChange(
                        observation_id=obs_id,
                        outcome=ReconciliationOutcome.CONFIRM,
                        description=f"User manually confirmed relationship: {target.subject} {target.predicate} {target.object}",
                        previous_value=None,
                        new_value=None,
                    )
                )
                return target.id, obs_id

            elif action == "reject":
                target.validity.valid_to = _utcnow()
                target.properties["status"] = "CONFLICT"
                await self.save_relationship(target)
                await self.record_state_change(
                    StateChange(
                        observation_id=obs_id,
                        outcome=ReconciliationOutcome.CONFLICT,
                        description=f"User manually rejected relationship: {target.subject} {target.predicate} {target.object}",
                    )
                )
                return target.id, obs_id

            elif action == "outdate":
                target.validity.valid_to = _utcnow()
                target.properties["status"] = "HISTORICAL"
                await self.save_relationship(target)
                await self.record_state_change(
                    StateChange(
                        observation_id=obs_id,
                        outcome=ReconciliationOutcome.UPDATE,
                        description="User manually marked relationship as outdated.",
                    )
                )
                return target.id, obs_id

            elif action == "correct":
                target.validity.valid_to = _utcnow()
                target.properties["status"] = "HISTORICAL"
                await self.save_relationship(target)

                new_rel = Relationship(
                    subject=new_subject or target.subject,
                    predicate=new_predicate or target.predicate,
                    object=new_object or target.object,
                    confidence=ConfidenceScore(
                        score=1.0, category="high", reasoning="User corrected manually"
                    ),
                )
                await self.save_relationship(new_rel)

                await self.record_state_change(
                    StateChange(
                        observation_id=obs_id,
                        outcome=ReconciliationOutcome.UPDATE,
                        description=f"User manually corrected relationship from {target.subject} {target.predicate} {target.object} to {new_rel.subject} {new_rel.predicate} {new_rel.object}",
                        previous_value=target.id,
                        new_value=new_rel.id,
                    )
                )
                return new_rel.id, obs_id

        raise NotImplementedError("Correction for this target type is not yet implemented")
