"""
Acceptance Test Suite for Domain-Agnostic Extensible Context Graph Relationships.

Verifies:
1. Context Graph relationship types are open and extensible, not a rigid closed ontology.
2. Recommended canonical relationships (RELATED_TO, INVOLVES, AFFECTS, DEPENDS_ON,
   SUPPORTS, CONFLICTS_WITH, PRECEDES, FOLLOWS, OCCURS_AT, PART_OF, DERIVED_FROM,
   EVIDENCE_FOR, MENTIONED_IN) are distinguished from hard architectural restrictions.
3. Unseen relationships (e.g. 'telemetry_streamed_to', 'calibrated_with', 'powers',
   'cools', 'regulates') can be:
   - stored in SQLite
   - navigated via adjacency & neighbor queries
   - evaluated via temporal validity queries
   - retrieved via context retrieval (BoundedContextGraph)
   - linked to situation discovery
   - exposed in bounded reasoning context for Hermes
   without creating:
   - new relationship classes
   - a semantic ontology engine
   - a graph database
   - source code changes for new relationship types.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import unittest

from personal_intelligence.core.situations.models import SituationPriority
from personal_intelligence.core.world.graph import (
    CanonicalRelationship,
    ContextGraph,
    EntityEdge,
    EntityNode,
    RECOMMENDED_RELATIONSHIP_TYPES,
    validate_and_normalize_relationship_type,
)
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.storage.db import DatabaseManager


class TestDomainAgnosticExtensibleRelationships(unittest.TestCase):

    def setUp(self) -> None:
        self.db = DatabaseManager(":memory:")
        self.db.initialize_schema()
        self.world_model = PersonalWorldModel(db_manager=self.db)
        self.cg = self.world_model.context_graph

    def test_relationship_validation_and_normalization(self) -> None:
        """Verify relationship_type is validated and normalized without closed ontology restrictions."""
        # 1. Standard canonical recommendations
        self.assertEqual(validate_and_normalize_relationship_type("related_to"), "related_to")
        self.assertEqual(validate_and_normalize_relationship_type("DEPENDS_ON"), "depends_on")
        self.assertEqual(validate_and_normalize_relationship_type("  supports  "), "supports")
        self.assertEqual(validate_and_normalize_relationship_type("EVIDENCE_FOR"), "evidence_for")
        self.assertEqual(validate_and_normalize_relationship_type("mentioned_in"), "mentioned_in")

        # 2. Arbitrary unseen relationships with spaces / hyphens
        self.assertEqual(
            validate_and_normalize_relationship_type("Telemetry-Streamed-To"),
            "telemetry_streamed_to",
        )
        self.assertEqual(
            validate_and_normalize_relationship_type("  calibrated with  "),
            "calibrated_with",
        )
        self.assertEqual(
            validate_and_normalize_relationship_type("thermodynamically_regulates"),
            "thermodynamically_regulates",
        )

        # 3. Canonical Enum compatibility
        self.assertEqual(validate_and_normalize_relationship_type(CanonicalRelationship.AFFECTS), "affects")
        self.assertEqual(validate_and_normalize_relationship_type(CanonicalRelationship("INVOLVES")), "involves")

        # 4. CanonicalRelationship dynamic pseudo-member for unseen relationships
        unseen_rel = CanonicalRelationship("telemetry_streamed_to")
        self.assertEqual(unseen_rel.value, "telemetry_streamed_to")
        self.assertEqual(str(unseen_rel), "telemetry_streamed_to")

        # 5. Distinguish recommended canonical types from arbitrary unseen types
        self.assertTrue(CanonicalRelationship.is_recommended("related_to"))
        self.assertTrue(CanonicalRelationship.is_recommended("involves"))
        self.assertTrue(CanonicalRelationship.is_recommended("mentioned_in"))
        self.assertFalse(CanonicalRelationship.is_recommended("telemetry_streamed_to"))
        self.assertIn("depends_on", RECOMMENDED_RELATIONSHIP_TYPES)
        self.assertIn("conflicts_with", RECOMMENDED_RELATIONSHIP_TYPES)

        # 6. Strict validation rules: reject empty, overly long, or dangerous characters
        with self.assertRaises(ValueError):
            validate_and_normalize_relationship_type("")
        with self.assertRaises(ValueError):
            validate_and_normalize_relationship_type("   ")
        with self.assertRaises(ValueError):
            validate_and_normalize_relationship_type("x" * 65)  # Exceeds 64 chars
        with self.assertRaises(ValueError):
            validate_and_normalize_relationship_type("bad*rel$type!")

    def test_unseen_relationships_storage_and_provenance(self) -> None:
        """Verify unseen relationship types are stored in SQLite with full metadata, timestamps, and provenance."""
        drone = self.cg.upsert_entity(id="drone-falcon-1", name="Falcon Drone 1", entity_type="device")
        battery = self.cg.upsert_entity(id="battery-cell-9", name="Solid-State Battery 9", entity_type="device")
        ground = self.cg.upsert_entity(id="station-alpha", name="Ground Control Alpha", entity_type="place")

        t_now = datetime.now(timezone.utc)

        # Store unseen relationships
        edge1 = self.cg.connect(
            source_id=battery.id,
            target_id=drone.id,
            relationship="powers",
            weight=0.95,
            provenance={"source": "telemetry", "confidence": 0.99},
            valid_from=t_now,
        )
        edge2 = self.cg.connect(
            source_id=drone.id,
            target_id=ground.id,
            relationship="telemetry_streamed_to",
            weight=1.0,
            provenance={"source": "radio_link"},
            valid_from=t_now,
        )

        self.assertEqual(edge1.relationship, "powers")
        self.assertEqual(edge2.relationship, "telemetry_streamed_to")

        # Query back from SQLite
        edges = self.cg.get_edges(node_id=drone.id)
        self.assertEqual(len(edges), 2)
        rel_names = {e.relationship for e in edges}
        self.assertEqual(rel_names, {"powers", "telemetry_streamed_to"})

        # Verify edge attributes preserved
        powers_edge = [e for e in edges if e.relationship == "powers"][0]
        self.assertEqual(powers_edge.source_id, battery.id)
        self.assertEqual(powers_edge.target_id, drone.id)
        self.assertEqual(powers_edge.weight, 0.95)
        self.assertEqual(powers_edge.metadata["provenance"]["source"], "telemetry")

    def test_unseen_relationships_adjacency_and_filtering(self) -> None:
        """Verify Context Graph traversal, neighbor queries, and relationship filtering work with unseen types."""
        drone = self.cg.upsert_entity(id="drone-falcon-1", name="Falcon Drone 1", entity_type="device")
        sensor = self.cg.upsert_entity(id="lidar-pod-3", name="LIDAR Pod 3", entity_type="device")
        ground = self.cg.upsert_entity(id="station-alpha", name="Ground Control Alpha", entity_type="place")
        battery = self.cg.upsert_entity(id="battery-cell-9", name="Battery 9", entity_type="device")

        self.cg.connect(battery.id, drone.id, "powers")
        self.cg.connect(sensor.id, drone.id, "calibrated_with")
        self.cg.connect(drone.id, ground.id, "telemetry_streamed_to")

        # 1. Traversal: get all neighbors
        neighbors = self.cg.get_neighbors(drone.id)
        self.assertEqual(len(neighbors), 3)

        # 2. Filter neighbors by unseen relationship
        filtered = self.cg.get_neighbors(drone.id, relationship="calibrated_with")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0][0].id, sensor.id)
        self.assertEqual(filtered[0][1], "calibrated_with")
        self.assertEqual(filtered[0][2].id, drone.id)

        # 3. get_related_entities with unseen relationship filter
        powered_by = self.cg.get_related_entities(drone.id, relationship="powers")
        self.assertEqual(len(powered_by), 1)
        self.assertEqual(powered_by[0].id, battery.id)

        streamed = self.cg.get_related_entities(drone.id, relationship="telemetry_streamed_to")
        self.assertEqual(len(streamed), 1)
        self.assertEqual(streamed[0].id, ground.id)

    def test_unseen_relationships_temporal_queries(self) -> None:
        """Verify temporal validity and what_was_true_at with unseen relationship types."""
        drone = self.cg.upsert_entity(id="drone-falcon-1", name="Falcon Drone 1", entity_type="device")
        cooler = self.cg.upsert_entity(id="cryo-cooler-2", name="Cryo Cooler 2", entity_type="device")

        t0 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)

        # Connect with finite validity
        edge = self.cg.connect(
            source_id=cooler.id,
            target_id=drone.id,
            relationship="cools",
            valid_from=t0,
            valid_to=t1,
        )

        # Active at t0 + 30m
        active_during = self.cg.get_edges(
            node_id=drone.id,
            relationship="cools",
            at_time=datetime(2026, 9, 1, 10, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(len(active_during), 1)

        # Inactive at t2
        active_after = self.cg.get_edges(
            node_id=drone.id,
            relationship="cools",
            at_time=t2,
        )
        self.assertEqual(len(active_after), 0)

        # what_was_true_at evaluation
        truth_at_t0 = self.cg.what_was_true_at(
            target_time=datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc),
            entity_id=drone.id,
        )
        self.assertEqual(truth_at_t0["active_relationships_count"], 1)
        self.assertEqual(truth_at_t0["active_relationships"][0]["relationship"], "cools")

    def test_unseen_relationships_in_situation_discovery_and_context(self) -> None:
        """
        Verify situation discovery can leverage unseen relationships and that
        the BoundedContextGraph renders them cleanly for Hermes reasoning.
        """
        drone = self.cg.upsert_entity(id="drone-falcon-1", name="Falcon Drone 1", entity_type="device")
        battery = self.cg.upsert_entity(id="battery-cell-9", name="Solid-State Battery 9", entity_type="device")
        ground = self.cg.upsert_entity(id="station-alpha", name="Ground Control Alpha", entity_type="place")

        self.cg.connect(battery.id, drone.id, "powers")
        self.cg.connect(drone.id, ground.id, "telemetry_streamed_to")

        # Create situation
        sit = self.world_model.create_situation(
            situation_type="avionics_voltage_drop",
            priority=SituationPriority.HIGH.value,
            context={"drone_id": drone.id, "voltage_v": 18.2},
        )

        # Connect situation using unseen tension relationship
        self.cg.connect(sit.id, drone.id, "threatens")
        self.cg.connect(sit.id, battery.id, "originates_from")

        # Query situation relations via graph
        sits = self.cg.get_related_situations(drone.id)
        self.assertGreaterEqual(len(sits), 1)
        self.assertEqual(sits[0]["id"], sit.id)

        # Context retrieval
        bounded = self.cg.get_context(drone.id, depth=1)
        self.assertEqual(bounded.center_node_id, drone.id)
        rendered_prompt = bounded.to_reasoning_prompt_context()

        # Verify unseen relationships are formatted cleanly without ontology errors
        self.assertIn("--[powers]-->", rendered_prompt)
        self.assertIn("--[telemetry_streamed_to]-->", rendered_prompt)
        self.assertIn("Falcon Drone 1", rendered_prompt)
        self.assertIn("Solid-State Battery 9", rendered_prompt)

    def test_unseen_relationship_end_to_end_acceptance(self) -> None:
        """
        ACCEPTANCE TEST:
        Introduce an unseen relationship type that does not exist anywhere in the current canonical vocabulary.
        The system must be able to:
        create it
        → persist it
        → query it
        → traverse it
        → include it in contextual retrieval
        → expose it to bounded reasoning
        without changing source code.
        Also verify that existing canonical relationships continue working.
        """
        # 1. Verify unseen relationship does NOT exist in recommended vocabulary
        unseen_rel = "synthetically_modulates"
        self.assertFalse(CanonicalRelationship.is_recommended(unseen_rel))
        self.assertNotIn(unseen_rel, RECOMMENDED_RELATIONSHIP_TYPES)

        # 2. Verify canonical relationship DOES exist in recommended vocabulary
        canonical_rel = CanonicalRelationship.SUPPORTS.value
        self.assertTrue(CanonicalRelationship.is_recommended(canonical_rel))

        # 3. Create entities
        emitter = self.cg.upsert_entity(id="emitter-01", name="Quantum Emitter Alpha", entity_type="device")
        sensor = self.cg.upsert_entity(id="sensor-02", name="Resonance Sensor Beta", entity_type="device")
        monitor = self.cg.upsert_entity(id="monitor-03", name="Telemetry Hub Gamma", entity_type="device")

        # 4. Create & persist unseen relationship and canonical relationship
        edge_unseen = self.cg.connect(
            source_id=emitter.id,
            target_id=sensor.id,
            relationship=unseen_rel,
            weight=0.88,
            epistemic_type="observed",
            provenance={"source": "spectrometer", "channel": 4},
        )
        edge_canonical = self.cg.connect(
            source_id=sensor.id,
            target_id=monitor.id,
            relationship=CanonicalRelationship.SUPPORTS,
            weight=1.0,
            epistemic_type="observed",
        )

        self.assertEqual(edge_unseen.relationship, "synthetically_modulates")
        self.assertEqual(edge_canonical.relationship, "supports")

        # 5. Query back from SQLite directly
        queried_edges = self.cg.get_edges(node_id=emitter.id)
        self.assertEqual(len(queried_edges), 1)
        self.assertEqual(queried_edges[0].relationship, "synthetically_modulates")
        self.assertEqual(queried_edges[0].target_id, sensor.id)
        self.assertEqual(queried_edges[0].weight, 0.88)

        # 6. Traverse adjacency
        neighbors = self.cg.get_neighbors(sensor.id)
        rel_set = {n[1] for n in neighbors}
        self.assertIn("synthetically_modulates", rel_set)
        self.assertIn("supports", rel_set)

        related_modulated = self.cg.get_related_entities(sensor.id, relationship="synthetically_modulates")
        self.assertEqual(len(related_modulated), 1)
        self.assertEqual(related_modulated[0].id, emitter.id)

        # 7. Include in contextual retrieval (BoundedContextGraph)
        bounded = self.cg.get_context(sensor.id, depth=1)
        self.assertEqual(bounded.center_node_id, sensor.id)
        self.assertEqual(len(bounded.nodes), 3)

        # 8. Expose to bounded reasoning context
        rendered_prompt = bounded.to_reasoning_prompt_context()
        self.assertIn("--[synthetically_modulates]-->", rendered_prompt)
        self.assertIn("--[supports]-->", rendered_prompt)
        self.assertIn("Quantum Emitter Alpha", rendered_prompt)
        self.assertIn("Resonance Sensor Beta", rendered_prompt)
        self.assertIn("Telemetry Hub Gamma", rendered_prompt)

        # 9. Verify ContextQueryEngine builds BoundedRelevantPersonalContext with unseen relationship
        sit = self.world_model.create_situation(
            situation_type="sensor_calibration_drift",
            priority=SituationPriority.HIGH.value,
            context={"primary_entity_ids": [sensor.id]},
        )
        self.cg.connect(sit.id, sensor.id, CanonicalRelationship.INVOLVES)

        from personal_intelligence.core.context.query_engine import ContextQueryEngine
        query_engine = ContextQueryEngine(context_graph=self.cg, db_manager=self.db)
        bounded_context = query_engine.query_for_situation(sit)
        rel_edges = [r["relationship"] for r in bounded_context.relationships]
        self.assertIn("synthetically_modulates", rel_edges)
        self.assertIn("supports", rel_edges)
        self.assertIn("involves", rel_edges)


if __name__ == "__main__":
    unittest.main()
