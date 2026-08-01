from core.pipeline import AsyncQueueEventBus, PipelineComponent, PipelineEvent
from core.db import DuckDBWorldModelStore, ChromaVectorStore
from core.models import Entity, Relationship, EntityType, Provenance, OriginType
import uuid


class GraphEntityBuilder(PipelineComponent):
    def __init__(
        self,
        bus: AsyncQueueEventBus,
        db: DuckDBWorldModelStore,
        vector_store: ChromaVectorStore = None,
    ):
        super().__init__(bus)
        self.db = db
        self.vector_store = vector_store

    async def process(self, event: PipelineEvent) -> None:
        """Takes the AI extraction payload and upserts nodes/edges into DuckDB and Chroma."""
        payload = event.raw_data
        base_entity_dict = payload.get("base_entity", {})
        extraction = payload.get("extraction", {})

        # 1. Upsert the base Document/Email/Meeting Entity
        base_entity = Entity(**base_entity_dict)
        if "summary" in extraction:
            base_entity.properties["summary"] = extraction["summary"]

        if "topics" in extraction:
            base_entity.properties["topics"] = extraction["topics"]

        # Keep readiness metadata on the calendar item itself.  The proactive
        # agent reads these extracted facts; it does not need SRM- or topic-
        # specific rules in its code.
        event_context = extraction.get("event_context", {})
        for key in (
            "organization",
            "event_category",
            "requires_preparation",
            "preparation_requirements",
        ):
            if event_context.get(key) is not None:
                base_entity.properties[key] = event_context[key]

        extracted_entities = extraction.get("entities", [])
        for ent in extracted_entities:
            if ent.get("entity_type") in ("Event", "Meeting", "Session", "Workshop"):
                if ent.get("properties", {}).get("event_category"):
                    base_entity.properties["event_category"] = ent.get(
                        "properties"
                    ).get("event_category")
                if ent.get("properties", {}).get("organization"):
                    base_entity.properties["organization"] = ent.get("properties").get(
                        "organization"
                    )

        if self.db:
            await self.db.upsert_entity(base_entity)

        # Index in Chroma with local embeddings automatically!
        if self.vector_store:
            await self.vector_store.index_entity(base_entity)

        subject_raw = (
            base_entity.properties.get("title")
            or base_entity.properties.get("subject")
            or "Unknown"
        )
        subject_safe = subject_raw.encode("ascii", "ignore").decode("ascii")
        print(f"[GraphBuilder] Upserted Base {base_entity.type.value}: {subject_safe}")

        # Trigger immediate evaluation
        await self.bus.publish(
            "entity_built",
            PipelineEvent(
                source="GraphBuilder",
                event_type="CREATED",
                raw_data={"entity_id": base_entity.id},
            ),
        )

        # 2. Upsert extracted Sub-Entities (People, Tasks, Organizations)
        extracted_entities = extraction.get("entities", [])
        entity_name_to_id_map = {}

        base_name = (
            base_entity.properties.get("name")
            or base_entity.properties.get("subject")
            or base_entity.properties.get("title")
        )
        if base_name:
            entity_name_to_id_map[base_name] = base_entity.id
        entity_name_to_id_map["Base_Document"] = base_entity.id

        base_url = (
            base_entity.provenance.source_url
            if getattr(base_entity, "provenance", None)
            else None
        )
        base_model = (
            getattr(base_entity.provenance, "extraction_model", None)
            if getattr(base_entity, "provenance", None)
            else None
        )
        base_native_id = (
            getattr(base_entity.provenance, "source_item_id", None)
            if getattr(base_entity, "provenance", None)
            else None
        )
        inherited_item_id = base_native_id if base_native_id else base_entity.id

        for ext_ent in extracted_entities:
            name = ext_ent.get("name")
            ent_type_str = ext_ent.get("entity_type", "Knowledge")
            existing = (
                await self.db.find_entity_by_name(name, entity_type=ent_type_str)
                if name and self.db
                else None
            )
            sub_id = existing.id if existing else str(uuid.uuid4())
            try:
                prov = Provenance(
                    source_connector="AzureOpenAIExtractor",
                    source_item_id=inherited_item_id,
                    supporting_text=ext_ent.get("supporting_text"),
                    origin_type=OriginType.INFERRED,
                    source_url=base_url,
                    extraction_model=base_model or "gpt-4o",
                )

                new_props = {"name": ext_ent.get("name")} | ext_ent.get(
                    "properties", {}
                )
                new_aliases = [ext_ent.get("name")] if ext_ent.get("name") else []
                new_identifiers = ext_ent.get("identifiers", {})

                if existing:
                    merged_props = {**existing.properties, **new_props}
                    merged_aliases = list(set(existing.aliases + new_aliases))
                    merged_identifiers = {**existing.identifiers, **new_identifiers}
                    sub_entity = Entity(
                        id=sub_id,
                        type=EntityType(ent_type_str),
                        properties=merged_props,
                        aliases=merged_aliases,
                        identifiers=merged_identifiers,
                        source=existing.source,
                        confidence=max(
                            existing.confidence, ext_ent.get("confidence", 1.0)
                        ),
                        valid_from=existing.valid_from or ext_ent.get("valid_from"),
                        valid_to=existing.valid_to or ext_ent.get("valid_to"),
                        occurred_at=existing.occurred_at or ext_ent.get("occurred_at"),
                        timezone=existing.timezone or ext_ent.get("timezone"),
                        recurrence=existing.recurrence or ext_ent.get("recurrence"),
                        provenance=prov,
                    )
                else:
                    sub_entity = Entity(
                        id=sub_id,
                        type=EntityType(ent_type_str),
                        properties=new_props,
                        aliases=new_aliases,
                        identifiers=new_identifiers,
                        source=f"Inferred_from_{base_entity.id}",
                        confidence=ext_ent.get("confidence", 1.0),
                        valid_from=ext_ent.get("valid_from"),
                        valid_to=ext_ent.get("valid_to"),
                        occurred_at=ext_ent.get("occurred_at"),
                        timezone=ext_ent.get("timezone"),
                        recurrence=ext_ent.get("recurrence"),
                        provenance=prov,
                    )
                await self.db.upsert_entity(sub_entity)
                entity_name_to_id_map[ext_ent.get("name")] = sub_id

                rel = Relationship(
                    target_entity_id=sub_id, relationship_type="MENTIONS"
                )
                await self.db.upsert_relationship(base_entity.id, rel)
            except ValueError as e:
                print(
                    f"[GraphBuilder] Invalid entity type in payload for {base_entity.id}: {ext_ent}. Error: {e}"
                )

        # 3. Upsert complex relationships
        relationships = extraction.get("relationships", [])
        for rel_data in relationships:
            src_name = rel_data.get("source_entity_name")
            tgt_name = rel_data.get("target_entity_name")
            rel_type = rel_data.get("relationship_type", "RELATED_TO")

            src_id = entity_name_to_id_map.get(src_name)
            tgt_id = entity_name_to_id_map.get(tgt_name)

            if src_id and tgt_id:
                rel_prov = Provenance(
                    source_connector="AzureOpenAIExtractor",
                    source_item_id=inherited_item_id,
                    supporting_text=rel_data.get("supporting_text"),
                    origin_type=OriginType.INFERRED,
                    source_url=base_url,
                    extraction_model=base_model or "gpt-4o",
                )
                rel = Relationship(
                    target_entity_id=tgt_id,
                    relationship_type=rel_type,
                    confidence=rel_data.get("confidence", 1.0),
                    valid_from=rel_data.get("valid_from"),
                    valid_to=rel_data.get("valid_to"),
                    provenance=rel_prov,
                )
                await self.db.upsert_relationship(src_id, rel)
                print(
                    f"[GraphBuilder] Created edge: {src_name} -[{rel_type}]-> {tgt_name}"
                )
