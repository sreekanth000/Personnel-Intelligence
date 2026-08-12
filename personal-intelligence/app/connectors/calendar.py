"""Google Calendar Connector.

Fetches raw event observations from Google Calendar API or local calendar stores
and normalizes them into standard Observation domain objects.

Feeds directly into the evidence recording and deterministic reconciliation pipeline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from googleapiclient.discovery import build

from app.config.logging import get_logger
from app.connectors.base import BaseConnector
from app.connectors.gmail_auth import GmailAuthService
from app.domain.enums import ObservationSource
from app.domain.observations import Observation

logger = get_logger(__name__)


def format_calendar_event_as_text(event: dict[str, Any]) -> str:
    """Format Google Calendar event payload into clean structured observation text."""
    summary = event.get("summary") or "Untitled Event"
    description = event.get("description") or ""
    location = event.get("location") or "Unspecified Location"

    start_data = event.get("start", {})
    end_data = event.get("end", {})
    start_str = start_data.get("dateTime") or start_data.get("date") or "TBD"
    end_str = end_data.get("dateTime") or end_data.get("date") or "TBD"

    organizer = event.get("organizer", {}).get("email") or event.get("organizer", {}).get("displayName") or "Unknown"

    attendees_list: list[str] = []
    for att in event.get("attendees", []):
        att_email = att.get("email")
        att_name = att.get("displayName")
        if att_name and att_email:
            attendees_list.append(f"{att_name} <{att_email}>")
        elif att_email:
            attendees_list.append(att_email)
        elif att_name:
            attendees_list.append(att_name)

    attendees_str = ", ".join(attendees_list) if attendees_list else "None specified"

    text_blocks = [
        f"Event Title: {summary}",
        f"Organizer: {organizer}",
        f"Start Time: {start_str}",
        f"End Time: {end_str}",
        f"Location: {location}",
        f"Attendees: {attendees_str}",
    ]
    if description.strip():
        text_blocks.append(f"\nDescription:\n{description.strip()}")

    return "\n".join(text_blocks)


class GoogleCalendarConnector(BaseConnector):
    """Connector for fetching calendar events from Google Calendar API."""

    def __init__(
        self,
        auth_service: GmailAuthService | None = None,
        service: Any | None = None,
    ) -> None:
        self._auth_service = auth_service or GmailAuthService()
        self._service = service

    @property
    def name(self) -> str:
        """Return connector name."""
        return "google_calendar"

    def is_authenticated(self) -> bool:
        """Return True if OAuth credentials exist and are valid."""
        if self._service is not None:
            return True
        creds = self._auth_service.load_credentials()
        return creds is not None and creds.valid

    def get_service(self) -> Any:
        """Return authorized Google Calendar API service instance."""
        if self._service is not None:
            return self._service

        creds = self._auth_service.load_credentials()
        if not creds or not creds.valid:
            msg = "Google Calendar authentication is required. Run authentication setup first."
            raise RuntimeError(msg)

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def event_to_observation(self, event: dict[str, Any]) -> Observation:
        """Convert a Google Calendar API event resource into an Observation."""
        event_id = event.get("id", "")
        summary = event.get("summary") or "Untitled Event"
        updated_at = event.get("updated") or datetime.now(UTC).isoformat()
        body_text = format_calendar_event_as_text(event)

        start_time = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end_time = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")

        return Observation(
            source=ObservationSource.GOOGLE_CALENDAR,
            source_identifier=f"calendar:{event_id}",
            content=body_text,
            metadata={
                "calendar_event_id": event_id,
                "summary": summary,
                "start_time": start_time,
                "end_time": end_time,
                "location": event.get("location"),
                "organizer": event.get("organizer", {}).get("email"),
                "raw_metadata": event,
            },
            timestamp=updated_at,
        )

    async def fetch_observations(
        self,
        since: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[Observation]:
        """Fetch calendar events from primary Google Calendar as Observation objects."""
        if not self.is_authenticated():
            msg = "Google Calendar authentication is required. Run authentication setup first."
            raise RuntimeError(msg)

        service = self.get_service()

        time_min = since
        if not time_min:
            # Default to fetching events from 30 days ago to future
            time_min = (datetime.now(UTC) - timedelta(days=30)).isoformat()

        logger.info("calendar_connector.fetch_started", limit=limit, time_min=time_min)

        try:
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=time_min,
                    maxResults=limit,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            items = events_result.get("items", [])

            for item in items:
                obs = self.event_to_observation(item)
                yield obs

            logger.info("calendar_connector.fetch_complete", count=len(items))

        except Exception as e:
            logger.error("calendar_connector.fetch_error", error=str(e))
            raise
