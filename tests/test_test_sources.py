"""
Unit tests for /pi test_sources and Hermes Google Workspace capability readiness.
"""

import os
import tempfile
import unittest

from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
from personal_intelligence.storage.db import DatabaseManager


class TestSourcesDiagnostic(unittest.TestCase):
    """
    Test suite for /pi test_sources and Google Workspace capability readiness.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_sources.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.event_store = EventStore(db_manager=self.db_manager)
        self.command_handler = PersonalIntelligenceCommandHandler(
            db_manager=self.db_manager,
            event_store=self.event_store,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sources_payload_structure(self) -> None:
        sources = self.command_handler.get_test_sources_payload()
        self.assertEqual(len(sources), 7)

        source_names = [s["source"] for s in sources]
        self.assertIn("Gmail", source_names)
        self.assertIn("Google Calendar", source_names)
        self.assertIn("Google Drive", source_names)
        self.assertIn("Google Meet", source_names)
        self.assertIn("Filesystem", source_names)
        self.assertIn("Web Search", source_names)
        self.assertIn("Hermes Reasoning", source_names)

        for s in sources:
            self.assertIn("status", s)
            self.assertIn("last_successful_access", s)
            self.assertIn("capability_availability", s)
            self.assertIn("READ_ONLY", s["capability_availability"])

    def test_command_output_no_content_dump(self) -> None:
        # Ingest a private email payload
        private_event = Event(
            id="evt-private-email-01",
            source="gmail",
            event_type="email_received",
            payload={"subject": "Confidential salary review details", "sender": "hr@company.com"},
        )
        self.event_store.append(private_event)

        output = self.command_handler.handle_test_sources()
        self.assertIn("Diagnostic (/pi test_sources)", output)
        self.assertIn("Gmail", output)
        self.assertIn("Google Calendar", output)
        self.assertIn("Google Drive", output)
        self.assertIn("Google Meet", output)
        self.assertIn("Filesystem", output)
        self.assertIn("Web Search", output)
        self.assertIn("Hermes Reasoning", output)

        # Guarantees zero leakage of private email payload
        self.assertNotIn("Confidential salary review details", output)
        self.assertNotIn("hr@company.com", output)

    def test_dispatcher_invocation(self) -> None:
        out1 = self.command_handler.execute("/pi test_sources")
        self.assertIn("Diagnostic (/pi test_sources)", out1)

        out2 = self.command_handler.execute("/pi sources")
        self.assertIn("Diagnostic (/pi test_sources)", out2)


if __name__ == "__main__":
    unittest.main()
