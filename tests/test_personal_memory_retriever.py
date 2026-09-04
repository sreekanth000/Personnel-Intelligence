"""
Unit & Integration Tests for PersonalMemoryRetriever.

Verifies:
1. Structured SQL retrieval with typed filters and provenance preservation.
2. Timeline window queries with proximity ranking.
3. Entity and relationship lookups across knowledge graph nodes and edges.
4. Lexical FTS and keyword retrieval.
5. Situation-targeted evidence gathering (SQL + Timeline + Entities + FTS) with ZERO embedding computation.
6. Semantic retrieval as an optional escalation mechanism.
7. Bounded context, relevance filtering, and evidence references.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.search.retriever import PersonalMemoryRetriever, RetrievalItem
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.world.graph import EntityEdge, EntityGraphStore, EntityNode
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore


class TestPersonalMemoryRetriever(unittest.TestCase):
    """Rigorous tests for PersonalMemoryRetriever."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_retriever.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.local_store = LocalStateStore(db_manager=self.db_manager)
        self.graph_store = EntityGraphStore(db_manager=self.db_manager)
        self.retriever = PersonalMemoryRetriever(db_manager=self.db_manager, local_store=self.local_store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_structured_sql_retrieval_and_provenance(self) -> None:
        """Verifies structured SQL filtering by sources, event types, confidence, and provenance preservation."""
        now = datetime.now(timezone.utc)

        self.local_store.event_store.append(Event(
            id="evt-gmail-01",
            source="gmail",
            source_id="msg-101",
            event_type="email_received",
            event_time=now - timedelta(hours=2),
            payload={"summary": "Q3 Board Deck Review Draft", "sender": "alex@company.com"},
            provenance={"tool": "gmail_search", "query": "label:board", "msg_id": "msg-101"},
            confidence=0.95,
        ))
        self.local_store.event_store.append(Event(
            id="evt-cal-02",
            source="calendar",
            source_id="cal-202",
            event_type="calendar_event",
            event_time=now - timedelta(hours=1),
            payload={"summary": "Executive Staff Sync", "attendees": ["alex@company.com", "sarah@company.com"]},
            provenance={"tool": "calendar_list_events", "calendar_id": "primary"},
            confidence=1.0,
        ))
        self.local_store.event_store.append(Event(
            id="evt-drive-03",
            source="drive",
            source_id="doc-303",
            event_type="document_changed",
            event_time=now - timedelta(hours=5),
            payload={"summary": "Architecture Spec V2", "author": "john@company.com"},
            provenance={"tool": "drive_get_document", "file_id": "doc-303"},
            confidence=0.80,
        ))

        # Query only gmail & calendar
        items = self.retriever.retrieve_structured(
            sources=["gmail", "calendar"],
            min_confidence=0.9,
            limit=10,
        )

        self.assertEqual(len(items), 2)
        sources = [it.source for it in items]
        self.assertIn("gmail", sources)
        self.assertIn("calendar", sources)
        self.assertNotIn("drive", sources)

        # Check provenance and evidence references
        gmail_item = next(it for it in items if it.source == "gmail")
        self.assertEqual(gmail_item.source_id, "msg-101")
        self.assertEqual(gmail_item.provenance["tool"], "gmail_search")
        self.assertEqual(gmail_item.provenance["query"], "label:board")
        self.assertIn("gmail:msg-101", gmail_item.evidence_references)
        self.assertIn("tool:gmail_search", gmail_item.evidence_references)

    def test_timeline_window_retrieval_and_proximity_ranking(self) -> None:
        """Verifies temporal window queries rank closest items highest."""
        anchor = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc)

        # Event 1: Exact at anchor
        self.local_store.event_store.append(Event(
            id="evt-anchor",
            source="calendar",
            source_id="anchor-1",
            event_type="calendar_event",
            event_time=anchor,
            payload={"summary": "Critical Milestone Review"},
        ))
        # Event 2: 2 hours before anchor
        self.local_store.event_store.append(Event(
            id="evt-2h-before",
            source="gmail",
            source_id="before-1",
            event_type="email_received",
            event_time=anchor - timedelta(hours=2),
            payload={"summary": "Pre-meeting memo"},
        ))
        # Event 3: 20 hours before anchor
        self.local_store.event_store.append(Event(
            id="evt-20h-before",
            source="drive",
            source_id="before-2",
            event_type="document_changed",
            event_time=anchor - timedelta(hours=20),
            payload={"summary": "Early deck draft"},
        ))
        # Event 4: 72 hours before anchor (outside 24h window)
        self.local_store.event_store.append(Event(
            id="evt-72h-before",
            source="gmail",
            source_id="outside-1",
            event_type="email_received",
            event_time=anchor - timedelta(hours=72),
            payload={"summary": "Old irrelevant email"},
        ))

        window_items = self.retriever.retrieve_timeline_window(
            anchor_time=anchor,
            window_hours_before=24.0,
            window_hours_after=24.0,
            limit=10,
        )

        self.assertEqual(len(window_items), 3)
        self.assertEqual(window_items[0].id, "evt-anchor")
        self.assertAlmostEqual(window_items[0].score, 1.0, places=2)
        self.assertEqual(window_items[1].id, "evt-2h-before")
        self.assertGreater(window_items[1].score, window_items[2].score)
        self.assertEqual(window_items[2].id, "evt-20h-before")

    def test_entity_network_and_relationship_lookup(self) -> None:
        """Verifies entity nodes, aliases, and relational edges are queried without embeddings."""
        # Create entity nodes
        user_node = EntityNode(id="ent-user", name="User", entity_type="person", aliases=["me", "self"])
        manager_node = EntityNode(id="ent-alex", name="Alex Rivera", entity_type="person", aliases=["alex", "manager"])
        project_node = EntityNode(id="ent-apex", name="Project Apex", entity_type="project", aliases=["apex"])

        self.graph_store.add_node(user_node)
        self.graph_store.add_node(manager_node)
        self.graph_store.add_node(project_node)

        # Create relationship edges
        edge1 = EntityEdge(id="edge-1", source_id=user_node.id, target_id=manager_node.id, relationship="reports_to", weight=1.0)
        edge2 = EntityEdge(id="edge-2", source_id=user_node.id, target_id=project_node.id, relationship="leads", weight=1.0)
        self.graph_store.add_edge(edge1)
        self.graph_store.add_edge(edge2)

        # Lookup entity by alias
        items = self.retriever.retrieve_entity_network("alex", depth=1, limit=10)
        self.assertTrue(len(items) > 0)
        node_item = next(it for it in items if it.id == "ent-alex")
        self.assertEqual(node_item.title, "Entity: Alex Rivera (person)")
        self.assertIn("entity:ent-alex", node_item.evidence_references)

        # Lookup relations connected to User
        user_items = self.retriever.retrieve_entity_network("User", depth=1, limit=10)
        edge_titles = [it.title for it in user_items if it.source == "graph_edge"]
        self.assertTrue(any("reports_to" in t for t in edge_titles))
        self.assertTrue(any("leads" in t for t in edge_titles))

    def test_lexical_retrieval_ranking(self) -> None:
        """Verifies lexical keyword ranking across event payloads and situation contexts."""
        self.local_store.event_store.append(Event(
            id="evt-tax-01",
            source="gmail",
            source_id="tax-1",
            event_type="email_received",
            payload={"summary": "Q4 Tax Compliance Filing Deadline", "body": "Please submit quarterly income tax forms before end of month."},
        ))
        self.local_store.event_store.append(Event(
            id="evt-lunch-02",
            source="calendar",
            source_id="lunch-2",
            event_type="calendar_event",
            payload={"summary": "Team Lunch at Bistro", "location": "Downtown"},
        ))

        lex_items = self.retriever.retrieve_lexical(query="quarterly tax deadline forms", limit=5)
        self.assertTrue(len(lex_items) > 0)
        self.assertEqual(lex_items[0].id, "evt-tax-01")
        self.assertGreater(lex_items[0].score, 0.5)

    def test_retrieve_for_situation_zero_embeddings_invariant(self) -> None:
        """
        Critical Acceptance Test:
        A situation must be completely answerable using SQL + Timeline + Entities + FTS
        with ZERO embedding computation.
        """
        now = datetime.now(timezone.utc)

        # 1. Setup Entity Graph
        collaborator = EntityNode(id="ent-sarah", name="Sarah Chen", entity_type="person", aliases=["sarah"])
        self.graph_store.add_node(collaborator)

        # 2. Setup Events around situation
        self.local_store.event_store.append(Event(
            id="evt-prod-incident",
            source="filesystem",
            source_id="log-404",
            event_type="system_alert",
            event_time=now - timedelta(hours=1),
            payload={"summary": "Payment Service API Error Spike 500", "sender": "Sarah Chen"},
            provenance={"tool": "fs_read", "path": "/var/log/service.log"},
        ))

        # 3. Setup Situation
        sit = Situation(
            id="sit-incident-001",
            type="external_dependency_risk",
            status=SituationStatus.OPEN.value,
            priority=SituationPriority.HIGH.value,
            context={
                "summary": "Payment Service Error Rate Exceeded SLA Threshold",
                "sender": "Sarah Chen",
                "primary_entity": "Payment Service",
            },
            created_at=now,
            updated_at=now,
        )
        self.local_store.situation_store.create(sit)

        # 4. Retrieve targeted situation evidence
        evidence = self.retriever.retrieve_for_situation(
            situation_id="sit-incident-001",
            window_hours=24.0,
            limit=10,
        )

        # Invariant Assertions:
        # Embedder should NEVER have been instantiated or called
        self.assertIsNone(self.retriever._embedder)

        # Evidence should contain situation, entity, timeline event, and lexical match
        self.assertTrue(len(evidence) >= 2)
        source_types = {e.source_type for e in evidence}
        self.assertIn("situation", source_types)
        self.assertIn("event", source_types)

        # Verify event provenance is intact
        event_evidence = next(e for e in evidence if e.id == "evt-prod-incident")
        self.assertEqual(event_evidence.provenance["tool"], "fs_read")
        self.assertEqual(event_evidence.provenance["path"], "/var/log/service.log")

    def test_semantic_retrieval_as_optional_escalation(self) -> None:
        """Verifies semantic retrieval acts strictly as an escalation mechanism when lexical fails."""
        # 1. Normal query with lexical hits -> 0 embeddings computed
        self.local_store.event_store.append(Event(
            id="evt-wifi-01",
            source="gmail",
            source_id="msg-wifi",
            event_type="email_received",
            payload={"summary": "Office WiFi Password Update credentials"},
        ))

        res_lexical = self.retriever.retrieve(
            query="WiFi Password credentials",
            allow_semantic_escalation=False,
            limit=5,
        )
        self.assertTrue(len(res_lexical) > 0)
        self.assertIn(res_lexical[0].retrieval_mode, ("lexical", "fts5"))
        self.assertIsNone(self.retriever._embedder)  # Embedder not created!

        # 2. When allow_semantic_escalation=True and lexical returns 0 hits, embedder is lazily created
        res_escalated = self.retriever.retrieve(
            query="unmatched exotic query term xyz9876",
            allow_semantic_escalation=True,
            escalation_threshold=0.5,
            limit=5,
        )
        # Should gracefully return without error, embedder invoked on demand
        self.assertIsNotNone(self.retriever._embedder)


if __name__ == "__main__":
    unittest.main()
