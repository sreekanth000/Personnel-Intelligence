"""
Hermes External Observation Scheduler & Connector Normalizer for Personal Intelligence.

Implements the Prompt 4 architectural boundary:
Hermes Scheduler -> Hermes Connector -> Connector Normalizer -> PI record_observation()
-> EventStore -> World Model -> Context Graph -> PI evaluation.

Guarantees:
- External observation acquisition is owned and scheduled by Hermes.
- Jobs run even when the Hive UI is closed (headless background runner).
- Safe failure handling for source errors, auth errors, and malformed results.
- Authentication remains strictly Hermes-owned; PI never stores OAuth credentials.
- Purely feeds into PI's record_observation(); PI evaluates local state independently.
"""

from datetime import datetime, timezone
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import uuid

from personal_intelligence.core.events.exceptions import DuplicateEventError
from personal_intelligence.core.events.models import (
    Event,
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.events.store import EventStore

logger = logging.getLogger(__name__)


class ConnectorNormalizer:
    """
    Normalizes raw connector payloads from Hermes into standard, source-backed
    Personal Intelligence observation records.
    Safely rejects or sanitizes malformed results.
    """

    @staticmethod
    def normalize_gmail_observation(raw_message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Normalizes a raw Gmail message payload into standard observation format.
        Returns None if the payload is fatally malformed.
        """
        if not isinstance(raw_message, dict):
            return None

        msg_id = raw_message.get("id") or raw_message.get("message_id")
        if not msg_id or not str(msg_id).strip():
            return None

        # Clean timestamp
        raw_ts = raw_message.get("date") or raw_message.get("timestamp") or raw_message.get("internalDate")
        try:
            ts = ensure_timezone_aware(raw_ts or datetime.now(timezone.utc), "gmail_timestamp")
        except Exception:
            ts = datetime.now(timezone.utc)

        subject = raw_message.get("subject") or raw_message.get("snippet") or "Email message"
        sender = raw_message.get("from") or raw_message.get("sender") or "unknown"
        body_preview = raw_message.get("snippet") or raw_message.get("body") or ""

        summary = f"Email from {sender}: {subject}"

        return {
            "source": "gmail",
            "source_id": str(msg_id).strip(),
            "timestamp": format_iso8601(ts),
            "observation_type": "email_received",
            "summary": summary[:250],
            "evidence": {
                "message_id": str(msg_id).strip(),
                "subject": subject,
                "from": sender,
                "snippet": str(body_preview)[:500],
                "summary": summary,
            },
            "provenance": {
                "tool": "hermes_gmail_connector",
                "source": "gmail",
                "source_id": str(msg_id).strip(),
                "fetched_at": format_iso8601(datetime.now(timezone.utc)),
            },
            "source_type": "connector",
            "confidence": 1.0,
        }

    @staticmethod
    def normalize_calendar_observation(raw_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Normalizes a raw Google Calendar event payload into standard observation format.
        Returns None if the payload is fatally malformed.
        """
        if not isinstance(raw_event, dict):
            return None

        event_id = raw_event.get("id") or raw_event.get("event_id")
        if not event_id or not str(event_id).strip():
            return None

        # Extract start time
        start_data = raw_event.get("start")
        raw_start = start_data.get("dateTime", start_data.get("date")) if isinstance(start_data, dict) else (raw_event.get("start_time") or raw_event.get("timestamp"))
        try:
            ts = ensure_timezone_aware(raw_start or datetime.now(timezone.utc), "cal_timestamp")
        except Exception:
            ts = datetime.now(timezone.utc)

        summary = raw_event.get("summary") or raw_event.get("title") or "Calendar Event"
        attendees = raw_event.get("attendees") or []
        location = raw_event.get("location") or ""
        full_summary = f"Calendar: {summary}"

        return {
            "source": "google_calendar",
            "source_id": str(event_id).strip(),
            "timestamp": format_iso8601(ts),
            "observation_type": "calendar_event",
            "summary": full_summary,
            "evidence": {
                "event_id": str(event_id).strip(),
                "title": summary,
                "start": format_iso8601(ts),
                "location": location,
                "attendee_count": len(attendees) if isinstance(attendees, list) else 0,
                "summary": full_summary,
            },
            "provenance": {
                "tool": "hermes_calendar_connector",
                "source": "google_calendar",
                "source_id": str(event_id).strip(),
                "fetched_at": format_iso8601(datetime.now(timezone.utc)),
            },
            "source_type": "connector",
            "confidence": 1.0,
        }


class HermesObservationScheduler:
    """
    Hermes-owned observation scheduler.
    Orchestrates recurring observation sweeps for external sources (Gmail, Calendar).
    Operates headlessly even when the user-facing Hive UI is closed.
    Delegates all storage, state, and evaluation to Personal Intelligence.
    """

    def __init__(
        self,
        pi_interface: Optional[Any] = None,
        event_store: Optional[EventStore] = None,
        gmail_connector_fn: Optional[Callable[[], Any]] = None,
        calendar_connector_fn: Optional[Callable[[], Any]] = None,
        poll_interval_seconds: int = 900,  # 15 minutes default
    ) -> None:
        self.pi_interface = pi_interface
        self.event_store = event_store or (pi_interface.event_store if hasattr(pi_interface, "event_store") else EventStore())
        self.gmail_connector_fn = gmail_connector_fn
        self.calendar_connector_fn = calendar_connector_fn
        self.poll_interval_seconds = poll_interval_seconds

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._telemetry: Dict[str, Any] = {
            "gmail_last_run": None,
            "gmail_status": "initialized",
            "calendar_last_run": None,
            "calendar_status": "initialized",
            "observations_ingested": 0,
            "duplicates_skipped": 0,
            "auth_failures": 0,
            "errors": 0,
        }

    # -------------------------------------------------------------------------
    # Observation Acquisition Routines
    # -------------------------------------------------------------------------

    def sweep_gmail(self) -> Dict[str, Any]:
        """
        Executes a scheduled sweep of Gmail via the Hermes Gmail Connector.
        Handles auth failure, network errors, and malformed data safely.
        """
        now_str = format_iso8601(datetime.now(timezone.utc))
        self._telemetry["gmail_last_run"] = now_str

        if not self.gmail_connector_fn:
            self._telemetry["gmail_status"] = "connector_not_configured"
            return {"status": "skipped", "reason": "No Gmail connector configured in Hermes"}

        try:
            raw_result = self.gmail_connector_fn()
        except PermissionError as pe:
            logger.warning("Hermes Gmail auth required: %s", pe)
            self._telemetry["gmail_status"] = "auth_required"
            self._telemetry["auth_failures"] += 1
            return {"status": "auth_required", "error": str(pe)}
        except Exception as ex:
            logger.error("Hermes Gmail observation failure: %s", ex)
            self._telemetry["gmail_status"] = "error"
            self._telemetry["errors"] += 1
            return {"status": "source_error", "error": str(ex)}

        # Check connector result status
        if isinstance(raw_result, dict) and raw_result.get("status") in ("auth_required", "unauthorized"):
            self._telemetry["gmail_status"] = "auth_required"
            self._telemetry["auth_failures"] += 1
            return {"status": "auth_required", "error": raw_result.get("error", "Authentication required")}

        # Extract items
        items = raw_result if isinstance(raw_result, list) else (raw_result.get("items", []) if isinstance(raw_result, dict) else [])

        ingested = 0
        duplicates = 0
        for item in items:
            norm = ConnectorNormalizer.normalize_gmail_observation(item)
            if not norm:
                continue  # Malformed item safely dropped

            status = self._deliver_observation_to_pi(norm)
            if status == "accepted":
                ingested += 1
            elif status == "duplicate":
                duplicates += 1

        self._telemetry["gmail_status"] = "success"
        self._telemetry["observations_ingested"] += ingested
        self._telemetry["duplicates_skipped"] += duplicates

        return {
            "status": "success",
            "source": "gmail",
            "ingested_count": ingested,
            "duplicates_count": duplicates,
            "timestamp": now_str,
        }

    def sweep_calendar(self) -> Dict[str, Any]:
        """
        Executes a scheduled sweep of Google Calendar via the Hermes Calendar Connector.
        Handles auth failure, network errors, and malformed data safely.
        """
        now_str = format_iso8601(datetime.now(timezone.utc))
        self._telemetry["calendar_last_run"] = now_str

        if not self.calendar_connector_fn:
            self._telemetry["calendar_status"] = "connector_not_configured"
            return {"status": "skipped", "reason": "No Calendar connector configured in Hermes"}

        try:
            raw_result = self.calendar_connector_fn()
        except PermissionError as pe:
            logger.warning("Hermes Calendar auth required: %s", pe)
            self._telemetry["calendar_status"] = "auth_required"
            self._telemetry["auth_failures"] += 1
            return {"status": "auth_required", "error": str(pe)}
        except Exception as ex:
            logger.error("Hermes Calendar observation failure: %s", ex)
            self._telemetry["calendar_status"] = "error"
            self._telemetry["errors"] += 1
            return {"status": "source_error", "error": str(ex)}

        # Check connector result status
        if isinstance(raw_result, dict) and raw_result.get("status") in ("auth_required", "unauthorized"):
            self._telemetry["calendar_status"] = "auth_required"
            self._telemetry["auth_failures"] += 1
            return {"status": "auth_required", "error": raw_result.get("error", "Authentication required")}

        items = raw_result if isinstance(raw_result, list) else (raw_result.get("items", []) if isinstance(raw_result, dict) else [])

        ingested = 0
        duplicates = 0
        for item in items:
            norm = ConnectorNormalizer.normalize_calendar_observation(item)
            if not norm:
                continue  # Malformed item safely dropped

            status = self._deliver_observation_to_pi(norm)
            if status == "accepted":
                ingested += 1
            elif status == "duplicate":
                duplicates += 1

        self._telemetry["calendar_status"] = "success"
        self._telemetry["observations_ingested"] += ingested
        self._telemetry["duplicates_skipped"] += duplicates

        return {
            "status": "success",
            "source": "google_calendar",
            "ingested_count": ingested,
            "duplicates_count": duplicates,
            "timestamp": now_str,
        }

    # -------------------------------------------------------------------------
    # Observation Delivery to PI
    # -------------------------------------------------------------------------

    def _deliver_observation_to_pi(self, observation: Dict[str, Any]) -> str:
        """
        Delivers a normalized observation to Personal Intelligence.
        Uses pi_interface.record_observation() if available, else directly EventStore.append().
        Enforces duplicate prevention.
        """
        try:
            if self.pi_interface and hasattr(self.pi_interface, "record_observation"):
                self.pi_interface.record_observation(
                    source=observation["source"],
                    source_id=observation["source_id"],
                    timestamp=observation["timestamp"],
                    observation_type=observation["observation_type"],
                    summary=observation["summary"],
                    evidence=observation.get("evidence"),
                    provenance=observation.get("provenance"),
                    confidence=observation.get("confidence", 1.0),
                    source_type=observation.get("source_type", "connector"),
                )
                return "accepted"
            else:
                # Direct EventStore delivery
                event = Event(
                    id=str(uuid.uuid4()),
                    source=observation["source"],
                    source_id=observation["source_id"],
                    event_type=observation["observation_type"],
                    payload=observation.get("evidence") or {"summary": observation["summary"]},
                    provenance=observation.get("provenance"),
                    event_time=observation["timestamp"],
                )
                self.event_store.append(event)
                return "accepted"
        except DuplicateEventError:
            logger.debug("Duplicate observation ignored for %s:%s", observation["source"], observation["source_id"])
            return "duplicate"
        except Exception as ex:
            if "UNIQUE constraint failed" in str(ex) or "duplicate" in str(ex).lower():
                return "duplicate"
            logger.warning("Observation ingestion exception: %s", ex)
            return "error"

    # -------------------------------------------------------------------------
    # Headless Scheduler Lifecycle (Runs when Hive UI is closed)
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """Starts the Hermes observation scheduler daemon."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="HermesObservationScheduler",
        )
        self._thread.start()
        logger.info("Hermes Observation Scheduler started (Interval: %ds)", self.poll_interval_seconds)

    def stop(self) -> None:
        """Stops the Hermes observation scheduler cleanly."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Hermes Observation Scheduler stopped.")

    def run_all_now(self) -> Dict[str, Any]:
        """Executes one immediate observation sweep across all configured sources."""
        gmail_res = self.sweep_gmail()
        cal_res = self.sweep_calendar()
        return {
            "gmail": gmail_res,
            "calendar": cal_res,
            "telemetry": dict(self._telemetry),
        }

    def _run_loop(self) -> None:
        """Continuous headless polling loop independent of Hive UI."""
        while self._running and not self._stop_event.is_set():
            try:
                self.sweep_gmail()
                self.sweep_calendar()
            except Exception as ex:
                logger.error("Hermes scheduler loop error: %s", ex)

            self._stop_event.wait(timeout=self.poll_interval_seconds)

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns structured metrics and status."""
        return {
            "is_running": self._running,
            "poll_interval_seconds": self.poll_interval_seconds,
            **self._telemetry,
        }
