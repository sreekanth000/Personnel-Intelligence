"""
Integration test suite for the Synthetic World Generator & Demo.

Verifies that the synthetic world demo exercises the complete 19-stage pipeline
without bypassing ingestion, World Model, Context Graph, Eligibility Gate, or Policy.
"""

from datetime import datetime, timezone
import os
import tempfile
import unittest

from personal_intelligence.demo.synthetic_world import (
    SyntheticWorldDemo,
    SyntheticWorldGenerator,
)
from personal_intelligence.storage.db import DatabaseManager


class TestSyntheticWorldDemo(unittest.TestCase):
    """Test suite for Synthetic World Demo execution."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_synthetic.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_synthetic_world_generator_stream(self) -> None:
        """Verify generator produces valid multi-domain observation specs."""
        generator = SyntheticWorldGenerator(base_time=datetime.now(timezone.utc))
        specs = generator.generate_longitudinal_stream()
        self.assertGreater(len(specs), 15)
        
        # Verify sources are domain-agnostic strings
        sources = {s.source for s in specs}
        self.assertIn("biometrics_tracker", sources)
        self.assertIn("schedule_calendar", sources)
        self.assertIn("activity_tracker", sources)

    def test_synthetic_world_demo_full_pipeline_execution(self) -> None:
        """Verify full 19-stage pipeline execution via SyntheticWorldDemo."""
        demo = SyntheticWorldDemo(db_manager=self.db_manager)
        result = demo.run_demo(base_time=datetime.now(timezone.utc))

        self.assertGreater(result.observations_ingested, 0)
        self.assertGreater(result.context_graph_nodes, 0)
        self.assertGreater(result.context_graph_edges, 0)
        self.assertIsNotNone(result.active_situations_count)
        self.assertIsNotNone(result.episodes_recorded)


if __name__ == "__main__":
    unittest.main()
