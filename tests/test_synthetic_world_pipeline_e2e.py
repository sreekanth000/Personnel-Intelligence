"""
End-to-End Test Suite for Single Synthetic World Demo Command.

Verifies the complete 15-stage execution:
1. reset demo state
2. generate synthetic world
3. ingest all observations
4. construct Personal World Model
5. construct Context Graph
6. construct timeline/state
7. run novelty analysis
8. discover situations
9. calculate evidence strength
10. invoke Hermes reasoning only when eligible
11. validate structured output
12. apply InterventionPolicy
13. persist reasoning episode
14. update learned patterns
15. expose all results to the existing UI

Guarantees:
- All summary fields are non-zero (except errors == 0).
- Formatting contains exact required field names.
- Reset demo state leaves clean tables.
- Deterministic reproducibility with seed.
"""

import os
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.demo.synthetic_hermes import (
    SyntheticHermesMode,
    SyntheticHermesRuntime,
)
from personal_intelligence.demo.synthetic_world import (
    SyntheticWorldDemo,
    SyntheticWorldPipelineSummary,
)
from personal_intelligence.storage.db import DatabaseManager


class TestSyntheticWorldPipelineE2E(unittest.TestCase):
    """End-to-end integration tests for the Synthetic World Demo pipeline."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_e2e_synthetic.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_full_pipeline_e2e_execution(self) -> None:
        """Verify complete 15-stage pipeline execution produces non-zero summary with zero errors."""
        runtime = SyntheticHermesRuntime(mode=SyntheticHermesMode.REALISTIC_SEMANTIC, seed=42)
        demo = SyntheticWorldDemo(db_manager=self.db_manager, hermes_runtime=runtime)

        summary: SyntheticWorldPipelineSummary = demo.run_end_to_end_pipeline(
            days=30,
            seed=42,
            reset_state=True,
            hermes_mode=SyntheticHermesMode.REALISTIC_SEMANTIC,
        )

        # Validate summary fields
        self.assertGreater(summary.events_ingested, 100, "Should ingest >100 multi-day events")
        self.assertGreater(summary.entities_created, 50, "Should create >50 entity nodes in graph")
        self.assertGreater(summary.relationships_created, 100, "Should create >100 edges in graph")
        self.assertGreater(summary.situations_discovered, 0, "Should discover at least 1 situation")
        self.assertGreater(summary.hermes_calls, 0, "Should invoke Hermes reasoning")
        self.assertGreater(summary.recommendations, 0, "Should generate recommendations")
        self.assertGreater(summary.interventions, 0, "Should record intervention decisions")
        self.assertGreater(summary.patterns_learned, 0, "Should learn empirical patterns")
        self.assertEqual(summary.errors, 0, "Should complete with 0 errors")

    def test_summary_formatted_output_contains_all_required_labels(self) -> None:
        """Verify summary output text includes all exact labels specified in the requirement."""
        summary = SyntheticWorldPipelineSummary(
            events_ingested=169,
            entities_created=190,
            relationships_created=594,
            situations_discovered=2,
            hermes_calls=2,
            recommendations=2,
            interventions=2,
            patterns_learned=6,
            errors=0,
        )
        formatted = summary.to_formatted_summary()

        required_labels = [
            "events ingested",
            "entities created",
            "relationships created",
            "situations discovered",
            "Hermes calls",
            "recommendations",
            "interventions",
            "patterns learned",
            "errors",
        ]
        for label in required_labels:
            self.assertIn(label, formatted, f"Formatted summary must contain '{label}'")

    def test_reset_demo_state_clears_tables(self) -> None:
        """Verify reset_demo_state clears all pipeline tables to pristine state."""
        runtime = SyntheticHermesRuntime(mode=SyntheticHermesMode.DETERMINISTIC, seed=42)
        demo = SyntheticWorldDemo(db_manager=self.db_manager, hermes_runtime=runtime)

        # Run pipeline to populate tables
        summary = demo.run_end_to_end_pipeline(days=30, seed=42, reset_state=False)
        self.assertGreater(summary.events_ingested, 0)

        # Reset state
        demo.reset_demo_state()

        # Verify tables are completely empty
        conn = self.db_manager.get_connection()
        try:
            for table in [
                "event_log",
                "entity_nodes",
                "entity_edges",
                "situations",
                "reasoning_episodes",
                "intervention_decisions",
                "patterns",
            ]:
                cursor = conn.cursor()
                cursor.execute(f"SELECT COUNT(*) FROM {table};")
                count = cursor.fetchone()[0]
                self.assertEqual(count, 0, f"Table '{table}' should be empty after reset")
        finally:
            conn.close()

    def test_pipeline_deterministic_reproducibility(self) -> None:
        """Verify pipeline execution is reproducible given the same seed."""
        runtime1 = SyntheticHermesRuntime(mode=SyntheticHermesMode.DETERMINISTIC, seed=99)
        demo1 = SyntheticWorldDemo(db_manager=self.db_manager, hermes_runtime=runtime1)
        summary1 = demo1.run_end_to_end_pipeline(days=30, seed=99, reset_state=True)

        # Re-run with same seed
        summary2 = demo1.run_end_to_end_pipeline(days=30, seed=99, reset_state=True)

        self.assertEqual(summary1.events_ingested, summary2.events_ingested)
        self.assertEqual(summary1.entities_created, summary2.entities_created)
        self.assertEqual(summary1.relationships_created, summary2.relationships_created)
        self.assertEqual(summary1.situations_discovered, summary2.situations_discovered)
        self.assertEqual(summary1.hermes_calls, summary2.hermes_calls)


if __name__ == "__main__":
    unittest.main()
