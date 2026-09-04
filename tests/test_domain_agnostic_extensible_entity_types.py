"""
Acceptance Test Suite for Domain-Agnostic Extensible Entity Types.

Verifies:
1. Personal Intelligence has NO permanently fixed entity taxonomy or domain classes.
2. Recommended canonical types are distinguished from hard architectural restrictions.
3. Unseen entity types (e.g. 'submersible_vehicle', 'hydrothermal_vent', 'benthic_sensor_array')
   can be:
   - validated and normalized
   - ingested via observations
   - persisted in SQLite
   - linked via generic relationships
   - traversed via ContextGraph
   - discovered in Situations
   - retrieved via ContextQueryEngine
   - formatted into BoundedReasoningContext
   without creating:
   - a new agent
   - a new connector inside PI
   - a new database
   - a new reasoning pipeline
   - a new entity class (No HealthEntity, FinanceEntity, etc.).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
import unittest

from personal_intelligence.core.context.query_engine import ContextQueryEngine
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.situations.models import Situation, SituationPriority
from personal_intelligence.core.state.entity_store import EntityState, EntityStateStore
from personal_intelligence.core.world.graph import (
    CanonicalEntityType,
    CanonicalRelationship,
    ContextGraph,
    EntityEdge,
    EntityNode,
    RECOMMENDED_ENTITY_TYPES,
    validate_and_normalize_entity_type,
)
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.storage.db import DatabaseManager


class TestDomainAgnosticExtensibleEntityTypes(unittest.TestCase):

    def setUp(self) -> None:
        self.db = DatabaseManager(":memory:")
        self.db.initialize_schema()
        self.world_model = PersonalWorldModel(db_manager=self.db)
        self.context_graph = self.world_model.context_graph
        self.query_engine = ContextQueryEngine(
            db_manager=self.db,
            context_graph=self.context_graph,
            goal_store=self.world_model.goal_store,
            situation_store=self.world_model.situation_store,
            event_store=self.world_model.event_store,
        )

    def test_entity_type_validation_and_normalization(self) -> None:
        """Verify entity_type is safely validated and normalized without closed taxonomy restrictions."""
        # 1. Standard cases
        self.assertEqual(validate_and_normalize_entity_type("person"), "person")
        self.assertEqual(validate_and_normalize_entity_type("PROJECT"), "project")
        self.assertEqual(validate_and_normalize_entity_type("  THING  "), "thing")
        self.assertEqual(validate_and_normalize_entity_type("TOPIC"), "topic")

        # 2. Arbitrary unseen domain types with spaces/hyphens
        self.assertEqual(
            validate_and_normalize_entity_type("Hydrothermal Vent"),
            "hydrothermal_vent",
        )
        self.assertEqual(
            validate_and_normalize_entity_type("benthic-sensor-array"),
            "benthic-sensor-array",
        )
        self.assertEqual(
            validate_and_normalize_entity_type("microbial.culture/strain_a"),
            "microbial.culture/strain_a",
        )

        # 3. Canonical Enum compatibility
        self.assertEqual(validate_and_normalize_entity_type(CanonicalEntityType.PERSON), "person")
        self.assertEqual(validate_and_normalize_entity_type(CanonicalEntityType("THING")), "thing")

        # 4. CanonicalEntityType dynamic pseudo-member for unseen types
        unseen_member = CanonicalEntityType("submersible_vehicle")
        self.assertEqual(unseen_member.value, "submersible_vehicle")
        self.assertEqual(str(unseen_member), "submersible_vehicle")

        # 5. Distinguish recommended types from arbitrary unseen types
        self.assertTrue(CanonicalEntityType.is_recommended("person"))
        self.assertTrue(CanonicalEntityType.is_recommended("thing"))
        self.assertTrue(CanonicalEntityType.is_recommended("topic"))
        self.assertFalse(CanonicalEntityType.is_recommended("submersible_vehicle"))
        self.assertIn("person", RECOMMENDED_ENTITY_TYPES)
        self.assertIn("project", RECOMMENDED_ENTITY_TYPES)

        # 6. Strict validation rules: reject empty, overly long, or dangerous characters
        with self.assertRaises(ValueError):
            validate_and_normalize_entity_type("")
        with self.assertRaises(ValueError):
            validate_and_normalize_entity_type("   ")
        with self.assertRaises(ValueError):
            validate_and_normalize_entity_type("x" * 65)  # Exceeds 64 chars
        with self.assertRaises(ValueError):
            validate_and_normalize_entity_type("bad*entity$type!")

    def test_unseen_domain_ingestion_and_persistence(self) -> None:
        """
        Verify an observation from an unseen domain (Oceanographic Telemetry)
        creates and persists unseen entities without new classes.
        """
        obs_event = Event(
            source="deep_sea_telemetry",
            event_type="thermal_spike_detected",
            timestamp=datetime.now(timezone.utc),
            summary="Thermal plume spike detected at Vent Alpha-9",
            structured_data={
                "vent_id": "vent-alpha-9",
                "temperature_c": 382.5,
                "entities": [
                    {
                        "id": "vent-alpha-9",
                        "name": "Alpha 9 Hydrothermal Vent",
                        "entity_type": "hydrothermal_vent",
                        "metadata": {"depth_meters": 2400, "tectonic_plate": "Juan de Fuca"},
                    },
                    {
                        "id": "sensor-deep-3",
                        "name": "Benthic Sensor Array 3",
                        "entity_type": "benthic_sensor_array",
                        "metadata": {"firmware": "v4.1.2"},
                    },
                ],
            },
        )

        # Ingest through world model
        ingested = self.world_model.record_observation(obs_event)
        self.assertEqual(ingested.id, obs_event.id)

        # Verify unseen entity nodes exist and are persisted in SQLite
        vent_node = self.context_graph.get_node("vent-alpha-9")
        self.assertIsNotNone(vent_node)
        self.assertEqual(vent_node.name, "Alpha 9 Hydrothermal Vent")
        self.assertEqual(vent_node.entity_type, "hydrothermal_vent")

        sensor_node = self.context_graph.get_node("sensor-deep-3")
        self.assertIsNotNone(sensor_node)
        self.assertEqual(sensor_node.name, "Benthic Sensor Array 3")
        self.assertEqual(sensor_node.entity_type, "benthic_sensor_array")

        # Verify query by unseen entity_type
        vents = self.context_graph.find_nodes_by_type("hydrothermal_vent")
        self.assertEqual(len(vents), 1)
        self.assertEqual(vents[0].id, "vent-alpha-9")

    def test_unseen_domain_relationships_and_traversal(self) -> None:
        """Verify unseen domain entities can be interconnected and traversed using generic primitives."""
        cg = self.context_graph

        # Create nodes of unforeseen types
        sub = cg.upsert_entity(id="sub-nautilus", name="Nautilus Submersible", entity_type="submersible_vehicle")
        vent = cg.upsert_entity(id="vent-alpha-9", name="Alpha 9 Vent", entity_type="hydrothermal_vent")
        sample = cg.upsert_entity(id="sample-bio-42", name="Microbial Extremophile 42", entity_type="microbial_culture")

        # Connect with generic relationships
        cg.connect(sub.id, vent.id, CanonicalRelationship.LOCATED_AT)
        cg.connect(sample.id, vent.id, CanonicalRelationship.DERIVED_FROM)
        cg.connect(sub.id, sample.id, CanonicalRelationship.INVOLVES)

        # Neighbors
        sub_neighbors = cg.get_neighbors(sub.id)
        self.assertEqual(len(sub_neighbors), 2)

        # Related entities
        related_to_vent = cg.get_related_entities(vent.id)
        related_names = [r.name for r in related_to_vent]
        self.assertIn("Nautilus Submersible", related_names)
        self.assertIn("Microbial Extremophile 42", related_names)

        # Bounded context graph
        bounded = cg.get_context(vent.id, depth=1)
        self.assertEqual(bounded.center_node_id, vent.id)
        self.assertEqual(len(bounded.nodes), 3)

    def test_unseen_domain_situation_discovery(self) -> None:
        """Verify Situations can be formed and linked around unseen domain entities."""
        wm = self.world_model
        cg = self.context_graph

        vent = cg.upsert_entity(id="vent-alpha-9", name="Alpha 9 Vent", entity_type="hydrothermal_vent")
        sensor = cg.upsert_entity(id="sensor-deep-3", name="Sensor Array 3", entity_type="benthic_sensor_array")
        cg.connect(sensor.id, vent.id, CanonicalRelationship.DEPENDS_ON)

        # Create generic situation
        situation = wm.create_situation(
            situation_type="sensor_overheat_risk",
            priority=SituationPriority.HIGH.value,
            context={
                "vent_id": vent.id,
                "sensor_id": sensor.id,
                "observed_temp_c": 395.0,
                "summary": "Sensor array temperature exceeding operational limits near Alpha 9 Vent",
            },
        )
        self.assertIsNotNone(situation)

        # Connect situation to entities in graph
        cg.connect(situation.id, vent.id, CanonicalRelationship.INVOLVES)
        cg.connect(situation.id, sensor.id, CanonicalRelationship.AFFECTS)

        # Query related situations via ContextGraph
        sits_for_vent = cg.get_related_situations(vent.id)
        self.assertGreaterEqual(len(sits_for_vent), 1)
        self.assertEqual(sits_for_vent[0]["id"], situation.id)

    def test_unseen_domain_in_bounded_reasoning_context(self) -> None:
        """
        Verify unseen domain entities are properly discovered and formatted
        into bounded reasoning context for Hermes LLM reasoning.
        """
        cg = self.context_graph
        sub = cg.upsert_entity(id="sub-nautilus", name="Nautilus Submersible", entity_type="submersible_vehicle")
        chamber = cg.upsert_entity(id="decomp-1", name="Primary Decompression Chamber", entity_type="decompression_chamber")
        cg.connect(sub.id, chamber.id, CanonicalRelationship.DEPENDS_ON)

        # 1. Context query engine matches unseen entity name in user query
        personal_context = self.query_engine.find_relevant_context_for_query(
            "What is the status of Nautilus Submersible and its decompression chamber?"
        )
        matched_ids = [e["id"] for e in personal_context.relevant_entities]
        self.assertIn(sub.id, matched_ids)

        # 2. Bounded Context formatting
        bounded = cg.get_context(sub.id, depth=1)
        rendered_prompt = bounded.to_reasoning_prompt_context()

        self.assertIn("Nautilus Submersible [submersible_vehicle]", rendered_prompt)
        self.assertIn("Primary Decompression Chamber [decompression_chamber]", rendered_prompt)
        self.assertIn("depends_on", rendered_prompt)

    def test_entity_state_store_accepts_unseen_types(self) -> None:
        """Verify EntityStateStore accepts and normalizes arbitrary entity types."""
        store = EntityStateStore(db_manager=self.db)
        state = EntityState(
            entity_id="cryo-tank-7",
            entity_type="Cryogenic Fluid Reservoir",
            state={"fill_level_percent": 94.2, "psi": 120.0},
        )
        # Should normalize to "cryogenic_fluid_reservoir"
        self.assertEqual(state.entity_type, "cryogenic_fluid_reservoir")

        store.upsert(state)
        retrieved = store.get("cryo-tank-7")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.entity_type, "cryogenic_fluid_reservoir")
        self.assertEqual(retrieved.state["fill_level_percent"], 94.2)

    def test_unseen_entity_domain_end_to_end_acceptance(self) -> None:
        """
        ACCEPTANCE TEST:
        Create an unseen domain with entity types that are not in the recommended vocabulary.
        The system must:
        ingest
        → persist
        → relate
        → retrieve
        → use in situation discovery
        → expose through bounded context
        without modifying PI source code.
        """
        # Unseen domain entity types (not in recommended core)
        unseen_type_1 = "fusion_reactor"
        unseen_type_2 = "plasma_containment_field"
        self.assertFalse(CanonicalEntityType.is_recommended(unseen_type_1))
        self.assertFalse(CanonicalEntityType.is_recommended(unseen_type_2))

        # 1. Ingest observation mentioning unseen domain entity
        obs = Event(
            source="sensor_telemetry",
            source_id="fusion-metric-882",
            event_type="core_temperature_fluctuation",
            payload={"reactor_id": "tokamak-alpha", "temperature_kelvin": 1.5e7},
            timestamp=datetime.now(timezone.utc),
        )
        saved_obs = self.world_model.event_store.append(obs)

        # 2. Persist unseen domain entities in ContextGraph
        reactor = self.context_graph.upsert_entity(
            id="tokamak-alpha",
            name="Tokamak Core Alpha",
            entity_type=unseen_type_1,
            metadata={"peak_output_mw": 500},
        )
        field = self.context_graph.upsert_entity(
            id="field-gamma",
            name="Toroidal Magnetic Barrier",
            entity_type=unseen_type_2,
            metadata={"strength_tesla": 12.5},
        )
        self.assertEqual(reactor.entity_type, "fusion_reactor")
        self.assertEqual(field.entity_type, "plasma_containment_field")

        # 3. Relate entities using extensible relationships
        edge = self.context_graph.connect(
            source_id=field.id,
            target_id=reactor.id,
            relationship="contains_and_stabilizes",
            weight=1.0,
            epistemic_type="observed",
        )
        self.assertEqual(edge.relationship, "contains_and_stabilizes")

        # 4. Retrieve back from SQLite
        retrieved_reactor = self.context_graph.get_node("tokamak-alpha")
        self.assertIsNotNone(retrieved_reactor)
        self.assertEqual(retrieved_reactor.entity_type, "fusion_reactor")

        # 5. Use in situation discovery
        sit = self.world_model.create_situation(
            situation_type="containment_field_instability",
            priority=SituationPriority.HIGH.value,
            context={"primary_entity_ids": [reactor.id, field.id], "evidence_event_ids": [saved_obs.id]},
        )
        self.context_graph.connect(sit.id, field.id, CanonicalRelationship.INVOLVES)
        self.context_graph.connect(sit.id, reactor.id, CanonicalRelationship.AFFECTS)

        related_sits = self.context_graph.get_related_situations(reactor.id)
        self.assertEqual(len(related_sits), 1)
        self.assertEqual(related_sits[0]["id"], sit.id)

        # 6. Expose through bounded context query
        bounded_context = self.query_engine.query_for_situation(sit)
        entity_types_in_context = {e["entity_type"] for e in bounded_context.relevant_entities}
        self.assertIn("fusion_reactor", entity_types_in_context)
        self.assertIn("plasma_containment_field", entity_types_in_context)

        # Verify BoundedContextGraph prompt rendering
        bounded_graph = self.context_graph.get_context(reactor.id, depth=1)
        rendered = bounded_graph.to_reasoning_prompt_context()
        self.assertIn("Tokamak Core Alpha [fusion_reactor]", rendered)
        self.assertIn("Toroidal Magnetic Barrier [plasma_containment_field]", rendered)
        self.assertIn("contains_and_stabilizes", rendered)


if __name__ == "__main__":
    unittest.main()
