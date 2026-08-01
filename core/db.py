import os
import json
import asyncio
import duckdb
from abc import ABC, abstractmethod
from typing import List, Optional
import chromadb
from core.models import Entity, Relationship, Provenance, EntityType


class WorldModelStore(ABC):
    @abstractmethod
    async def upsert_entity(self, entity: Entity) -> None:
        pass

    @abstractmethod
    async def get_entity(self, entity_id: str) -> Optional[Entity]:
        pass

    @abstractmethod
    async def delete_entity(self, entity_id: str) -> None:
        pass

    @abstractmethod
    async def upsert_relationship(
        self, source_id: str, relationship: Relationship
    ) -> None:
        pass


class VectorSearchIndex(ABC):
    @abstractmethod
    async def index_entity(self, entity: Entity) -> None:
        pass

    @abstractmethod
    async def search(self, query_text: str, top_k: int = 10) -> List[Entity]:
        pass


class ChromaVectorStore(VectorSearchIndex):
    def __init__(self, persist_directory: str = "./chroma_db"):
        try:
            self.client = chromadb.PersistentClient(path=persist_directory)
            self.collection = self.client.get_or_create_collection(
                name="world_model_entities"
            )
            print(
                f"[ChromaDB] Initialized vector store at {persist_directory} using local embeddings."
            )
        except Exception as e:
            print(f"[ChromaDB] Failed to initialize: {e}")
            self.client = None
            self.collection = None

    async def index_entity(self, entity: Entity) -> None:
        if not self.collection:
            return

        loop = asyncio.get_running_loop()

        def _add():
            metadata = {
                "type": entity.type.value,
                "source": entity.source,
                "title": entity.properties.get("title")
                or entity.properties.get("name")
                or "Untitled",
            }
            # The document to be embedded
            document = json.dumps(entity.properties)

            for k, v in entity.properties.items():
                if isinstance(v, str):
                    metadata[k] = v[:500]

            self.collection.upsert(
                ids=[entity.id], documents=[document], metadatas=[metadata]
            )

        try:
            await loop.run_in_executor(None, _add)
        except Exception as e:
            print(f"[ChromaDB] Error indexing entity {entity.id}: {e}")

    async def search(self, query_text: str, top_k: int = 10) -> List[Entity]:
        if not self.collection:
            return []

        loop = asyncio.get_running_loop()

        def _query():
            return self.collection.query(query_texts=[query_text], n_results=top_k)

        try:
            results = await loop.run_in_executor(None, _query)
            entities = []

            if results and results.get("ids") and len(results["ids"]) > 0:
                for i in range(len(results["ids"][0])):
                    ent_id = results["ids"][0][i]
                    meta = (
                        results["metadatas"][0][i] if results.get("metadatas") else {}
                    )
                    properties = {
                        key: value
                        for key, value in meta.items()
                        if key not in {"type", "source"}
                    }
                    e = Entity(
                        id=ent_id,
                        type=meta.get("type", "Knowledge"),
                        source=meta.get("source", "ChromaDB"),
                        properties=properties or {"title": "Unknown"},
                    )
                    entities.append(e)
            return entities

        except Exception as e:
            print(f"[ChromaDB] Error searching: {e}")
            return []


class DuckDBWorldModelStore(WorldModelStore):
    def __init__(self, db_path: str = "world_model.duckdb"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return duckdb.connect(self.db_path)

    def _init_db(self):
        print(f"[DuckDB] Initializing database at {self.db_path}...")
        with self._get_connection() as conn:
            # Create entities table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id VARCHAR PRIMARY KEY,
                type VARCHAR,
                status VARCHAR,
                properties JSON,
                source VARCHAR,
                confidence DOUBLE,
                updated_time TIMESTAMP,
                valid_from TIMESTAMP,
                valid_to TIMESTAMP,
                observed_at TIMESTAMP,
                occurred_at TIMESTAMP,
                last_confirmed_at TIMESTAMP,
                timezone VARCHAR,
                recurrence VARCHAR,
                provenance JSON,
                aliases JSON,
                canonical_id VARCHAR,
                identifiers JSON
            )
            """)

            # Create relationships table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                source_id VARCHAR,
                target_id VARCHAR,
                type VARCHAR,
                properties JSON,
                confidence DOUBLE,
                valid_from TIMESTAMP,
                valid_to TIMESTAMP,
                observed_at TIMESTAMP,
                occurred_at TIMESTAMP,
                last_confirmed_at TIMESTAMP,
                timezone VARCHAR,
                recurrence VARCHAR,
                provenance JSON,
                PRIMARY KEY (source_id, target_id, type)
            )
            """)

            # Evidence Tables
            conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_evidence (
                entity_id VARCHAR,
                source_connector VARCHAR,
                source_item_id VARCHAR,
                supporting_text VARCHAR,
                origin_type VARCHAR,
                extraction_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS relationship_evidence (
                source_id VARCHAR,
                target_id VARCHAR,
                type VARCHAR,
                source_connector VARCHAR,
                source_item_id VARCHAR,
                supporting_text VARCHAR,
                origin_type VARCHAR,
                extraction_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Migrations for existing databases
            migrations = [
                "ALTER TABLE entities ADD COLUMN status VARCHAR",
                "ALTER TABLE entities ADD COLUMN aliases JSON",
                "ALTER TABLE entities ADD COLUMN canonical_id VARCHAR",
                "ALTER TABLE entities ADD COLUMN identifiers JSON",
                "ALTER TABLE entities ADD COLUMN valid_from TIMESTAMP",
                "ALTER TABLE entities ADD COLUMN valid_to TIMESTAMP",
                "ALTER TABLE entities ADD COLUMN observed_at TIMESTAMP",
                "ALTER TABLE entities ADD COLUMN occurred_at TIMESTAMP",
                "ALTER TABLE entities ADD COLUMN last_confirmed_at TIMESTAMP",
                "ALTER TABLE entities ADD COLUMN timezone VARCHAR",
                "ALTER TABLE entities ADD COLUMN recurrence VARCHAR",
                "ALTER TABLE entities ADD COLUMN provenance JSON",
                "ALTER TABLE relationships ADD COLUMN valid_from TIMESTAMP",
                "ALTER TABLE relationships ADD COLUMN valid_to TIMESTAMP",
                "ALTER TABLE relationships ADD COLUMN observed_at TIMESTAMP",
                "ALTER TABLE relationships ADD COLUMN occurred_at TIMESTAMP",
                "ALTER TABLE relationships ADD COLUMN last_confirmed_at TIMESTAMP",
                "ALTER TABLE relationships ADD COLUMN timezone VARCHAR",
                "ALTER TABLE relationships ADD COLUMN recurrence VARCHAR",
                "ALTER TABLE relationships ADD COLUMN provenance JSON",
            ]
            for mig in migrations:
                try:
                    conn.execute(mig)
                except Exception:
                    pass

            try:
                conn.execute(
                    "UPDATE entities SET status = 'Active' WHERE status IS NULL"
                )
            except Exception:
                pass

    async def close(self):
        pass

    def _row_to_entity(self, conn, row) -> Entity:
        def safe_json(val, default):
            if isinstance(val, str):
                val = val.strip()
                if not val:
                    return default
                try:
                    return json.loads(val)
                except:
                    return default
            return val or default

        props = safe_json(row[3], {})
        aliases = safe_json(row[15], [])
        identifiers = safe_json(row[17], {})
        prov_data = safe_json(row[14], {})
        prov = Provenance(**prov_data) if prov_data else Provenance()

        return Entity(
            id=row[0],
            type=EntityType(row[1]),
            status=row[2] or "Active",
            properties=props,
            source=row[4] or "Unknown",
            confidence=row[5] or 1.0,
            updated_time=row[6],
            valid_from=row[7],
            valid_to=row[8],
            observed_at=row[9],
            occurred_at=row[10],
            last_confirmed_at=row[11],
            timezone=row[12],
            recurrence=row[13],
            provenance=prov,
            aliases=aliases,
            canonical_id=row[16],
            identifiers=identifiers,
        )

    async def upsert_entity(self, entity: Entity) -> None:
        loop = asyncio.get_running_loop()

        def _upsert():
            props_json = json.dumps(entity.properties)
            prov_json = (
                entity.provenance.model_dump_json()
                if hasattr(entity.provenance, "model_dump_json")
                else json.dumps(entity.provenance)
            )
            aliases_json = json.dumps(entity.aliases)
            identifiers_json = json.dumps(entity.identifiers)

            def _dt_str(dt):
                if dt is None:
                    return None
                return dt.isoformat() if hasattr(dt, "isoformat") else dt

            with self._get_connection() as conn:
                conn.execute(
                    """
                INSERT INTO entities (
                    id, type, status, properties, source, confidence, updated_time,
                    valid_from, valid_to, observed_at, occurred_at, last_confirmed_at, timezone, recurrence, provenance,
                    aliases, canonical_id, identifiers
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    type = EXCLUDED.type,
                    status = EXCLUDED.status,
                    properties = EXCLUDED.properties,
                    source = EXCLUDED.source,
                    confidence = EXCLUDED.confidence,
                    updated_time = EXCLUDED.updated_time,
                    valid_from = EXCLUDED.valid_from,
                    valid_to = EXCLUDED.valid_to,
                    observed_at = EXCLUDED.observed_at,
                    occurred_at = EXCLUDED.occurred_at,
                    last_confirmed_at = EXCLUDED.last_confirmed_at,
                    timezone = EXCLUDED.timezone,
                    recurrence = EXCLUDED.recurrence,
                    provenance = EXCLUDED.provenance,
                    aliases = EXCLUDED.aliases,
                    canonical_id = EXCLUDED.canonical_id,
                    identifiers = EXCLUDED.identifiers
                """,
                    (
                        entity.id,
                        entity.type.value,
                        entity.status,
                        props_json,
                        entity.source,
                        entity.confidence,
                        _dt_str(entity.updated_time),
                        _dt_str(entity.valid_from),
                        _dt_str(entity.valid_to),
                        _dt_str(entity.observed_at),
                        _dt_str(entity.occurred_at),
                        _dt_str(entity.last_confirmed_at),
                        entity.timezone,
                        entity.recurrence,
                        prov_json,
                        aliases_json,
                        entity.canonical_id,
                        identifiers_json,
                    ),
                )

                if entity.provenance:
                    orig_type = (
                        entity.provenance.origin_type.value
                        if hasattr(entity.provenance.origin_type, "value")
                        else entity.provenance.origin_type
                    )
                    conn.execute(
                        """
                    INSERT INTO entity_evidence (entity_id, source_connector, source_item_id, supporting_text, origin_type)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                        (
                            entity.id,
                            entity.provenance.source_connector,
                            entity.provenance.source_item_id,
                            entity.provenance.supporting_text,
                            orig_type,
                        ),
                    )

        try:
            await loop.run_in_executor(None, _upsert)
        except Exception as e:
            print(f"[DuckDB] Error upserting entity {entity.id}: {e}")

    async def upsert_relationship(
        self, source_id: str, relationship: Relationship
    ) -> None:
        loop = asyncio.get_running_loop()

        def _upsert():
            props_json = json.dumps(relationship.properties)
            prov_json = (
                relationship.provenance.model_dump_json()
                if hasattr(relationship.provenance, "model_dump_json")
                else json.dumps(relationship.provenance)
            )
            rel_type = relationship.relationship_type.upper().replace(" ", "_")

            def _dt_str(dt):
                if dt is None:
                    return None
                return dt.isoformat() if hasattr(dt, "isoformat") else dt

            with self._get_connection() as conn:
                conn.execute(
                    """
                INSERT INTO relationships (
                    source_id, target_id, type, properties, confidence,
                    valid_from, valid_to, observed_at, occurred_at, last_confirmed_at, timezone, recurrence, provenance
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (source_id, target_id, type) DO UPDATE SET
                    properties = EXCLUDED.properties,
                    confidence = EXCLUDED.confidence,
                    valid_from = EXCLUDED.valid_from,
                    valid_to = EXCLUDED.valid_to,
                    observed_at = EXCLUDED.observed_at,
                    occurred_at = EXCLUDED.occurred_at,
                    last_confirmed_at = EXCLUDED.last_confirmed_at,
                    timezone = EXCLUDED.timezone,
                    recurrence = EXCLUDED.recurrence,
                    provenance = EXCLUDED.provenance
                """,
                    (
                        source_id,
                        relationship.target_entity_id,
                        rel_type,
                        props_json,
                        relationship.confidence,
                        _dt_str(relationship.valid_from),
                        _dt_str(relationship.valid_to),
                        _dt_str(relationship.observed_at),
                        _dt_str(relationship.occurred_at),
                        _dt_str(relationship.last_confirmed_at),
                        relationship.timezone,
                        relationship.recurrence,
                        prov_json,
                    ),
                )

                if relationship.provenance:
                    orig_type = (
                        relationship.provenance.origin_type.value
                        if hasattr(relationship.provenance.origin_type, "value")
                        else relationship.provenance.origin_type
                    )
                    conn.execute(
                        """
                    INSERT INTO relationship_evidence (source_id, target_id, type, source_connector, source_item_id, supporting_text, origin_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            source_id,
                            relationship.target_entity_id,
                            rel_type,
                            relationship.provenance.source_connector,
                            relationship.provenance.source_item_id,
                            relationship.provenance.supporting_text,
                            orig_type,
                        ),
                    )

        try:
            await loop.run_in_executor(None, _upsert)
        except Exception as e:
            print(f"[DuckDB] Error upserting relationship from {source_id}: {e}")

    async def merge_entities(self, canonical_id: str, merge_id: str) -> None:
        loop = asyncio.get_running_loop()

        def _merge():
            with self._get_connection() as conn:
                # 1. Re-point relationships where source_id = merge_id
                conn.execute(
                    """
                INSERT INTO relationships (source_id, target_id, type, properties, confidence, valid_from, valid_to, observed_at, occurred_at, last_confirmed_at, timezone, recurrence, provenance)
                SELECT ?, target_id, type, properties, confidence, valid_from, valid_to, observed_at, occurred_at, last_confirmed_at, timezone, recurrence, provenance
                FROM relationships WHERE source_id = ?
                ON CONFLICT DO NOTHING;
                """,
                    (canonical_id, merge_id),
                )

                # 2. Re-point relationships where target_id = merge_id
                conn.execute(
                    """
                INSERT INTO relationships (source_id, target_id, type, properties, confidence, valid_from, valid_to, observed_at, occurred_at, last_confirmed_at, timezone, recurrence, provenance)
                SELECT source_id, ?, type, properties, confidence, valid_from, valid_to, observed_at, occurred_at, last_confirmed_at, timezone, recurrence, provenance
                FROM relationships WHERE target_id = ?
                ON CONFLICT DO NOTHING;
                """,
                    (canonical_id, merge_id),
                )

                # 3. Clean up old relationships
                conn.execute(
                    "DELETE FROM relationships WHERE source_id = ? OR target_id = ?",
                    (merge_id, merge_id),
                )

                # 4. Mark merged entity as merged and point to canonical
                conn.execute(
                    "UPDATE entities SET canonical_id = ?, status = 'Merged' WHERE id = ?",
                    (canonical_id, merge_id),
                )

        try:
            await loop.run_in_executor(None, _merge)
        except Exception as e:
            print(f"[DuckDB] Error merging entity {merge_id} into {canonical_id}: {e}")

    async def get_entity(self, entity_id: str) -> Optional[Entity]:
        loop = asyncio.get_running_loop()

        def _get():
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT id, type, status, properties, source, confidence, updated_time, valid_from, valid_to, observed_at, occurred_at, last_confirmed_at, timezone, recurrence, provenance, aliases, canonical_id, identifiers FROM entities WHERE id = ?",
                    (entity_id,),
                ).fetchone()
                if row:
                    return self._row_to_entity(conn, row)
                return None

        return await loop.run_in_executor(None, _get)

    async def find_entity_by_name(
        self, name: str, entity_type: str = None
    ) -> Optional[Entity]:
        if not name:
            return None
        loop = asyncio.get_running_loop()

        def _find():
            with self._get_connection() as conn:
                query = "SELECT id, type, status, properties, source, confidence, updated_time, valid_from, valid_to, observed_at, occurred_at, last_confirmed_at, timezone, recurrence, provenance, aliases, canonical_id, identifiers FROM entities WHERE (properties->>'$.name' = ? OR aliases::JSON::VARCHAR LIKE ?) AND (status IS NULL OR status != 'Merged')"
                params = [name, f'%"{name}"%']
                if entity_type:
                    query += " AND type = ?"
                    params.append(entity_type)

                row = conn.execute(query, params).fetchone()
                if row:
                    return self._row_to_entity(conn, row)
                return None

        return await loop.run_in_executor(None, _find)

    async def delete_entity(self, entity_id: str) -> None:
        loop = asyncio.get_running_loop()

        def _delete():
            with self._get_connection() as conn:
                conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
                conn.execute(
                    "DELETE FROM relationships WHERE source_id = ? OR target_id = ?",
                    (entity_id, entity_id),
                )

        await loop.run_in_executor(None, _delete)


class MockWorldModelStore(WorldModelStore):
    def __init__(self):
        self.entities = {}
        self.relationships = {}

    async def upsert_entity(self, entity: Entity) -> None:
        self.entities[entity.id] = entity
        print(f"[MockDB] Upserted Entity: {entity.type} ({entity.id})")

    async def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self.entities.get(entity_id)

    async def delete_entity(self, entity_id: str) -> None:
        if entity_id in self.entities:
            self.entities[entity_id].status = "Deleted"

    async def upsert_relationship(
        self, source_id: str, relationship: Relationship
    ) -> None:
        if source_id not in self.relationships:
            self.relationships[source_id] = []
        self.relationships[source_id].append(relationship)
        print(
            f"[MockDB] Upserted Relationship: {source_id} -> {relationship.relationship_type} -> {relationship.target_entity_id}"
        )
