"""
Hermes-Mediated Capability Source Pollers for Personal Intelligence.

All external app access (Gmail, Google Calendar, Slack, WhatsApp, etc.) flows
EXCLUSIVELY through the host Hermes Agent runtime.

Guarantees:
- Zero direct third-party SDKs or OAuth token handling in Personal Intelligence.
- Declarative capability requests to Hermes.
- Safe read-only bounds enforced by OperationSafetyGuard.
- Graceful handling when Hermes runtime or capabilities are unavailable.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from personal_intelligence.core.events.models import Event
from personal_intelligence.hermes_bridge.calendar_adapter import (
    CalendarCapabilityRequest,
    GoogleCalendarCapabilityAdapter,
)
from personal_intelligence.hermes_bridge.client import HermesClient, HermesRuntimeBridge
from personal_intelligence.hermes_bridge.gmail_adapter import (
    GmailCapabilityAdapter,
    GmailCapabilityRequest,
)
from personal_intelligence.scheduler.daemon import SourcePoller

logger = logging.getLogger(__name__)


class HermesGmailPoller(SourcePoller):
    """
    Polls Gmail messages exclusively through the Hermes Agent runtime.
    """

    name = "hermes_gmail"

    def __init__(
        self,
        hermes_client: Optional[HermesClient] = None,
        bridge: Optional[HermesRuntimeBridge] = None,
        gmail_adapter: Optional[GmailCapabilityAdapter] = None,
        query: str = "is:unread",
        max_results: int = 10,
    ) -> None:
        self.client = hermes_client or HermesClient()
        self.bridge = bridge or (self.client.bridge if hasattr(self.client, "bridge") else HermesRuntimeBridge())
        self.adapter = gmail_adapter or GmailCapabilityAdapter(bridge=self.bridge)
        self.query = query
        self.max_results = max_results
        self._seen_message_ids = set()

    def poll(self) -> List[Event]:
        """Requests recent Gmail messages from Hermes and converts to PI Events."""
        request = GmailCapabilityRequest(
            query=self.query,
            max_results=self.max_results,
            read_only=True,
        )

        try:
            result = self.adapter.execute_query(request)
        except Exception as e:
            logger.debug(f"Hermes Gmail inquiry note: {e}")
            return []

        if result.status != "success":
            logger.debug(f"Hermes Gmail status: {result.status} ({result.error or 'no error details'})")
            return []

        events: List[Event] = []
        for i, ref in enumerate(result.message_references):
            if ref in self._seen_message_ids:
                continue
            self._seen_message_ids.add(ref)

            summary = result.safe_summaries[i] if i < len(result.safe_summaries) else f"Email: {ref}"
            finding = result.findings[i] if i < len(result.findings) else ""

            events.append(Event(
                event_type="email_received",
                source="gmail",
                source_id=ref,
                timestamp=datetime.now(timezone.utc),
                structured_data={
                    "message_id": ref,
                    "summary": summary,
                    "finding": finding,
                    "provenance": "hermes_gmail_capability",
                },
                summary=summary,
                confidence=1.0,
            ))

        return events


class HermesCalendarPoller(SourcePoller):
    """
    Polls Google Calendar events exclusively through the Hermes Agent runtime.
    """

    name = "hermes_calendar"

    def __init__(
        self,
        hermes_client: Optional[HermesClient] = None,
        bridge: Optional[HermesRuntimeBridge] = None,
        calendar_adapter: Optional[GoogleCalendarCapabilityAdapter] = None,
        lookahead_days: int = 7,
    ) -> None:
        self.client = hermes_client or HermesClient()
        self.bridge = bridge or (self.client.bridge if hasattr(self.client, "bridge") else HermesRuntimeBridge())
        self.adapter = calendar_adapter or GoogleCalendarCapabilityAdapter(bridge=self.bridge)
        self.lookahead_days = lookahead_days
        self._seen_event_ids = set()

    def poll(self) -> List[Event]:
        """Requests upcoming calendar schedule from Hermes and converts to PI Events."""
        request = CalendarCapabilityRequest(
            time_range_days=self.lookahead_days,
            read_only=True,
        )

        try:
            result = self.adapter.execute_query(request)
        except Exception as e:
            logger.debug(f"Hermes Calendar inquiry note: {e}")
            return []

        if result.status != "success":
            logger.debug(f"Hermes Calendar status: {result.status} ({result.error or 'no error details'})")
            return []

        events: List[Event] = []
        for cal_event in result.events:
            if cal_event.id in self._seen_event_ids:
                continue
            self._seen_event_ids.add(cal_event.id)

            events.append(Event(
                event_type="calendar_event_upcoming",
                source="google_calendar",
                source_id=cal_event.id,
                timestamp=datetime.now(timezone.utc),
                structured_data={
                    "event_id": cal_event.id,
                    "title": cal_event.summary,
                    "start": cal_event.start_time,
                    "end": cal_event.end_time,
                    "duration_minutes": cal_event.duration_minutes,
                    "attendees": cal_event.attendees,
                    "location": cal_event.location,
                    "is_busy": cal_event.is_busy,
                    "provenance": "hermes_calendar_capability",
                },
                summary=f"Calendar: {cal_event.summary} ({cal_event.start_time})",
                confidence=1.0,
            ))

        return events


class HermesGenericPoller(SourcePoller):
    """
    Generic poller that requests observations across any Hermes tool (Slack, WhatsApp, etc.).
    """

    def __init__(
        self,
        capability_name: str,
        tool_name: str,
        tool_parameters: Optional[Dict[str, Any]] = None,
        event_type: str = "generic_observation",
        hermes_client: Optional[HermesClient] = None,
    ) -> None:
        self.name = f"hermes_{capability_name}"
        self.capability_name = capability_name
        self.tool_name = tool_name
        self.tool_parameters = tool_parameters or {}
        self.event_type = event_type
        self.client = hermes_client or HermesClient()

    def poll(self) -> List[Event]:
        """Invokes Hermes tool in read-only mode and captures structured observations."""
        try:
            tool_res = self.client.execute_tool(
                tool_name=self.tool_name,
                parameters=self.tool_parameters,
            )
        except Exception as e:
            logger.debug(f"Hermes tool {self.tool_name} inquiry note: {e}")
            return []

        if not tool_res or getattr(tool_res, "is_error", False):
            return []

        data = tool_res.data if hasattr(tool_res, "data") else tool_res
        if not data:
            return []

        # If data is a serialized JSON string, attempt decoding
        if isinstance(data, str) and (data.strip().startswith("{") or data.strip().startswith("[")):
            try:
                import json
                data = json.loads(data)
            except Exception:
                pass

        items = data if isinstance(data, list) else [data]
        events: List[Event] = []
        for item in items:
            summary = ""
            if isinstance(item, dict):
                summary = item.get("summary") or item.get("text") or item.get("title") or str(item)[:100]
            else:
                summary = str(item)[:100]

            events.append(Event(
                event_type=self.event_type,
                source=self.capability_name,
                timestamp=datetime.now(timezone.utc),
                structured_data=item if isinstance(item, dict) else {"content": item},
                summary=f"{self.capability_name.capitalize()}: {summary}",
                confidence=1.0,
            ))

        return events
