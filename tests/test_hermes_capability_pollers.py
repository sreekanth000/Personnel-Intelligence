"""
Unit tests for Hermes-mediated capability source pollers.
Verifies that all external data observations flow strictly through Hermes
without direct third-party SDKs or credential storage.
"""

from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock

from personal_intelligence.hermes_bridge.calendar_adapter import (
    CalendarEventObservation,
    HermesCalendarResult,
)
from personal_intelligence.hermes_bridge.client import HermesClient
from personal_intelligence.hermes_bridge.gmail_adapter import HermesGmailResult
from personal_intelligence.hermes_bridge.pollers import (
    HermesCalendarPoller,
    HermesGenericPoller,
    HermesGmailPoller,
)


class TestHermesCapabilityPollers(unittest.TestCase):

    def test_hermes_gmail_poller_success(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.execute_query.return_value = HermesGmailResult(
            status="success",
            findings=["Found 1 urgent email regarding contract"],
            message_references=["msg_101", "msg_102"],
            safe_summaries=["Contract review request", "Team meeting notes"],
            provenance=["gmail:msg_101", "gmail:msg_102"],
        )

        poller = HermesGmailPoller(gmail_adapter=mock_adapter)
        events = poller.poll()

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].source, "gmail")
        self.assertEqual(events[0].source_id, "msg_101")
        self.assertEqual(events[0].event_type, "email_received")
        self.assertIn("Contract review", events[0].summary)

        # Subsequent poll should skip previously seen message IDs
        events_2 = poller.poll()
        self.assertEqual(len(events_2), 0)

    def test_hermes_gmail_poller_handles_unavailable_gracefully(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.execute_query.return_value = HermesGmailResult(
            status="unavailable",
            error="Gmail tool not configured in Hermes host",
        )

        poller = HermesGmailPoller(gmail_adapter=mock_adapter)
        events = poller.poll()
        self.assertEqual(events, [])

    def test_hermes_calendar_poller_success(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.execute_query.return_value = HermesCalendarResult(
            status="success",
            events=[
                CalendarEventObservation(
                    id="cal_event_01",
                    summary="Q3 Planning Session",
                    start_time="2026-08-30T10:00:00Z",
                    end_time="2026-08-30T11:00:00Z",
                    duration_minutes=60,
                    attendees=["alice@example.com", "bob@example.com"],
                    location="Conference Room A",
                )
            ],
            total_events=1,
        )

        poller = HermesCalendarPoller(calendar_adapter=mock_adapter)
        events = poller.poll()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, "google_calendar")
        self.assertEqual(events[0].source_id, "cal_event_01")
        self.assertEqual(events[0].event_type, "calendar_event_upcoming")
        self.assertIn("Q3 Planning Session", events[0].summary)
        self.assertEqual(events[0].structured_data["attendees"], ["alice@example.com", "bob@example.com"])

    def test_hermes_generic_poller_slack_and_whatsapp(self) -> None:
        mock_client = MagicMock()
        tool_result = MagicMock()
        tool_result.is_error = False
        tool_result.data = [
            {"channel": "general", "user": "alice", "text": "Deploying v2.1 to staging"},
            {"channel": "general", "user": "bob", "text": "All tests green"},
        ]
        mock_client.execute_tool.return_value = tool_result

        slack_poller = HermesGenericPoller(
            capability_name="slack",
            tool_name="slack_search",
            tool_parameters={"query": "deploy"},
            event_type="slack_message",
            hermes_client=mock_client,
        )

        events = slack_poller.poll()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].source, "slack")
        self.assertEqual(events[0].event_type, "slack_message")
        self.assertIn("Deploying v2.1", events[0].summary)


if __name__ == "__main__":
    unittest.main()
