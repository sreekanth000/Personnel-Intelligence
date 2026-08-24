"""
Unit & Integration Tests for In-Process Local Semantic Vector Search & Hybrid Retrieval.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.embeddings.vector_engine import (
    EMBEDDING_DIMENSION,
    LocalSemanticEmbedder,
    VectorRecord,
    compute_cosine_similarity,
)
from personal_intelligence.core.search.hybrid_engine import HybridSearchEngine
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.situations.models import Situation
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.query.ask import AskPersonalIntelligenceEngine
from personal_intelligence.api.server import DashboardDataService
from personal_intelligence.storage.db import DatabaseManager


class TestLocalSemanticEmbedder(unittest.TestCase):
    """Tests for 384-dimensional dense vector embeddings and cosine math."""

    def setUp(self) -> None:
        self.embedder = LocalSemanticEmbedder(dimension=EMBEDDING_DIMENSION)

    def test_embedding_dimensions_and_normalization(self) -> None:
        text = "Google Security alert: Suspicious sign-in detected"
        vec = self.embedder.embed_text(text)
        self.assertEqual(len(vec), EMBEDDING_DIMENSION)

        # Check L2 unit norm (~1.0)
        norm = sum(x * x for x in vec) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=4)

    def test_semantic_similarity_relative_scoring(self) -> None:
        q_bank = self.embedder.embed_text("SBI BPCL credit card assessment due date")
        doc_bank = self.embedder.embed_text("BankBazaar SBI credit card assessment validity terms")
        doc_job = self.embedder.embed_text("LinkedIn Job Alert: Machine Learning Engineering Lead")

        sim_bank = compute_cosine_similarity(q_bank, doc_bank)
        sim_job = compute_cosine_similarity(q_bank, doc_job)

        # Financial card query must have higher similarity to financial doc than to job alert
        self.assertGreater(sim_bank, sim_job)
        self.assertGreater(sim_bank, 0.3)

    def test_vector_record_blob_serialization(self) -> None:
        vec = self.embedder.embed_text("Test vector serialization")
        rec = VectorRecord(
            id="vec-test-1",
            source_type="event",
            source_id="evt-1",
            content_text="Test vector serialization",
            vector=vec,
            metadata={"source": "gmail"},
        )
        blob = rec.embedding_blob
        self.assertEqual(len(blob), EMBEDDING_DIMENSION * 4)

        unpacked = VectorRecord.from_blob(
            id="vec-test-1",
            source_type="event",
            source_id="evt-1",
            content_text="Test vector serialization",
            blob=blob,
            metadata={"source": "gmail"},
        )
        self.assertEqual(len(unpacked.vector), EMBEDDING_DIMENSION)
        self.assertAlmostEqual(unpacked.vector[0], vec[0], places=5)


class TestHybridSearchEngine(unittest.TestCase):
    """Tests for SQLite vector persistence and Hybrid Dense + Lexical retrieval."""

    def test_indexing_and_hybrid_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_vector.db"
            db = DatabaseManager(db_path=str(db_path))
            es = EventStore(db)
            ss = SituationStore(db)

            # Insert real-world sample events
            es.append(Event(
                id="evt-sec-01",
                source="gmail",
                event_type="email_received",
                payload={"summary": "Google Accounts: Security alert for login from new device"},
            ))
            es.append(Event(
                id="evt-sbi-01",
                source="gmail",
                event_type="email_received",
                payload={"summary": "BankBazaar: SBI BPCL credit card assessment valid until 27/Aug/2026"},
            ))
            es.append(Event(
                id="evt-job-01",
                source="gmail",
                event_type="email_received",
                payload={"summary": "LinkedIn Job Alerts: Head of Data Engineering + ML"},
            ))

            engine = HybridSearchEngine(db_manager=db)
            indexed = engine.sync_all_unindexed()
            self.assertEqual(indexed, 3)

            # Test Dense Search
            dense_hits = engine.search_dense(query="credit card payment deadline", limit=3)
            self.assertTrue(len(dense_hits) > 0)
            self.assertIn("SBI BPCL", dense_hits[0]["content_text"])

            # Test Hybrid Search (RRF)
            hybrid_hits = engine.search_hybrid(query="security account password alert", limit=3)
            self.assertTrue(len(hybrid_hits) > 0)
            self.assertIn("Security alert", hybrid_hits[0]["content_text"])
            self.assertIn("rrf_score", hybrid_hits[0])

            # Test Index Stats
            stats = engine.get_index_stats()
            self.assertEqual(stats["total_vectors"], 3)
            self.assertEqual(stats["dimension"], EMBEDDING_DIMENSION)

    def test_ask_pi_with_semantic_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_ask_vec.db"
            db = DatabaseManager(db_path=str(db_path))
            es = EventStore(db)
            es.append(Event(
                id="evt-bank-01",
                source="gmail",
                event_type="email_received",
                payload={"summary": "INT-ID:VL5537 - SBI BPCL card assessment valid until 27/Aug/2026"},
            ))

            ask_engine = AskPersonalIntelligenceEngine(db_manager=db, event_store=es)
            resp = ask_engine.ask("Tell me about my SBI credit card details")
            self.assertTrue(len(resp.answer) > 0)
            self.assertTrue(len(resp.semantic_search_hits) > 0)
            self.assertIn("SBI BPCL", resp.semantic_search_hits[0]["content_text"])

    def test_dashboard_service_vector_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_ds_vec.db"
            db = DatabaseManager(db_path=str(db_path))
            ds = DashboardDataService(db_manager=db)

            # Test vector status API
            stats = ds.get_vector_search_status()
            self.assertIn("total_vectors", stats)
            self.assertEqual(stats["dimension"], EMBEDDING_DIMENSION)

            # Test hybrid search API
            search_res = ds.execute_hybrid_search(query="security login alert")
            self.assertEqual(search_res["status"], "success")
            self.assertIn("results", search_res)

            ds.bg_scheduler.stop()


if __name__ == "__main__":
    unittest.main()
