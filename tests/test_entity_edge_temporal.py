"""
Unit tests for Temporal Entity Edges (Blueprint §7).
"""

from datetime import datetime, timedelta, timezone
import unittest

from personal_intelligence.core.world.graph import EntityEdge, EntityGraphStore, EntityNode
from personal_intelligence.storage.db import DatabaseManager


class TestEntityEdgeTemporal(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseManager(db_path=":memory:")
        self.db.initialize_schema()
        self.graph = EntityGraphStore(db_manager=self.db)
        self.base_time = datetime(2026, 8, 29, 10, 0, 0, tzinfo=timezone.utc)

    def test_edge_temporal_fields_and_serialization(self) -> None:
        """Verify valid_from, valid_to, and status fields."""
        edge = EntityEdge(
            source_id="person_1",
            target_id="project_alpha",
            relationship="leads",
            valid_from=self.base_time,
            valid_to=self.base_time + timedelta(days=90),
            status="active",
        )
        d = edge.to_dict()
        self.assertEqual(d["status"], "active")
        self.assertIsNotNone(d["valid_from"])
        self.assertIsNotNone(d["valid_to"])

        restored = EntityEdge.from_dict(d)
        self.assertEqual(restored.relationship, "leads")
        self.assertEqual(restored.status, "active")
        self.assertEqual(restored.valid_from, self.base_time)

    def test_get_neighbors_filters_active_by_default(self) -> None:
        """Verify get_neighbors filters out ended relationships unless requested."""
        n1 = self.graph.add_node(EntityNode(name="Alice", entity_type="person"))
        n2 = self.graph.add_node(EntityNode(name="Project Alpha", entity_type="project"))
        n3 = self.graph.add_node(EntityNode(name="Project Beta", entity_type="project"))

        # Active edge to Alpha
        e1 = self.graph.add_edge(EntityEdge(
            source_id=n1.id,
            target_id=n2.id,
            relationship="leads",
            status="active",
        ))
        # Ended edge to Beta
        e2 = self.graph.add_edge(EntityEdge(
            source_id=n1.id,
            target_id=n3.id,
            relationship="contributed_to",
            status="ended",
            valid_to=self.base_time,
        ))

        # Default query (active only)
        neighbors = self.graph.get_neighbors(n1.id, depth=1, include_ended=False)
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0][2].id, n2.id)

        # Include ended
        all_neighbors = self.graph.get_neighbors(n1.id, depth=1, include_ended=True)
        self.assertEqual(len(all_neighbors), 2)

    def test_end_edge_operation(self) -> None:
        """Verify end_edge updates status to ended and sets valid_to."""
        n1 = self.graph.add_node(EntityNode(name="Bob", entity_type="person"))
        n2 = self.graph.add_node(EntityNode(name="Team Gamma", entity_type="team"))

        e = self.graph.add_edge(EntityEdge(
            source_id=n1.id,
            target_id=n2.id,
            relationship="member_of",
            status="active",
        ))

        success = self.graph.end_edge(e.id)
        self.assertTrue(success)

        # Query should no longer return it as active
        active = self.graph.get_neighbors(n1.id, depth=1, include_ended=False)
        self.assertEqual(len(active), 0)

        # But it remains historically
        all_edges = self.graph.get_neighbors(n1.id, depth=1, include_ended=True)
        self.assertEqual(len(all_edges), 1)


if __name__ == "__main__":
    unittest.main()
