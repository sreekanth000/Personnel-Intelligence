"""
Generic Event Ingestion Service for validating, normalizing, and storing incoming personal events.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple
import uuid

from personal_intelligence.core.events.exceptions import (
    DuplicateEventError,
    EventValidationError,
)
from personal_intelligence.core.events.models import (
    Event,
    ensure_timezone_aware,
)
from personal_intelligence.core.events.store import EventStore


class IngestionStatus(str, Enum):
    """Possible outcomes of an event ingestion request."""
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass
class IngestionResult:
    """Structured response returned by the ingestion service."""
    status: IngestionStatus
    event_id: Optional[str] = None
    event_hash: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result into serializable dictionary."""
        d = {
            "status": self.status.value,
            "event_id": self.event_id,
        }
        if self.event_hash is not None:
            d["event_hash"] = self.event_hash
        if self.error is not None:
            d["error"] = self.error
        if self.message is not None:
            d["message"] = self.message
        return d


class EventIngestionService:
    """
    Ingests and normalizes arbitrary domain-agnostic events into the EventStore.
    Enforces contract validation, timestamp normalization, and duplicate safety.
    """

    def __init__(self, event_store: Optional[EventStore] = None) -> None:
        self.event_store = event_store or EventStore()

    def parse_and_validate_payload(self, raw_data: Any) -> Tuple[Optional[Event], Optional[str]]:
        """
        Parses raw dict input adhering to the API contract and constructs an Event instance.
        Returns (event, None) on success or (None, error_message) on validation failure.
        """
        if not isinstance(raw_data, dict):
            return None, f"Request body must be a JSON object, got {type(raw_data).__name__}."

        # Extract fields supporting API contract (and aliases)
        raw_event_id = raw_data.get("event_id") or raw_data.get("id")
        raw_timestamp = raw_data.get("timestamp") or raw_data.get("event_time")
        raw_type = raw_data.get("type") or raw_data.get("event_type")
        raw_source = raw_data.get("source")
        raw_subject = raw_data.get("subject", raw_data.get("subject_id", "user"))
        raw_payload = raw_data.get("payload")
        raw_confidence = raw_data.get("confidence", 1.0)

        # 1. Validate required fields presence
        if raw_timestamp is None:
            return None, "Missing required field: 'timestamp'."
        if not raw_type or not isinstance(raw_type, str) or not raw_type.strip():
            return None, "Missing or invalid required field: 'type' (must be non-empty string)."
        if not raw_source or not isinstance(raw_source, str) or not raw_source.strip():
            return None, "Missing or invalid required field: 'source' (must be non-empty string)."
        if raw_payload is None or not isinstance(raw_payload, dict):
            return None, "Missing or invalid required field: 'payload' (must be a JSON dictionary)."

        # 2. Normalize and validate timestamp
        try:
            event_time = ensure_timezone_aware(raw_timestamp, "timestamp")
        except EventValidationError as e:
            return None, str(e)
        except Exception as e:
            return None, f"Invalid timestamp: {e}"

        # 3. Validate subject
        if raw_subject is not None and not isinstance(raw_subject, str):
            return None, f"'subject' must be a string or None, got {type(raw_subject).__name__}."

        # 4. Validate confidence
        try:
            confidence = float(raw_confidence)
            if confidence < 0.0 or confidence > 1.0:
                return None, f"'confidence' must be between 0.0 and 1.0, got {confidence}."
        except (ValueError, TypeError):
            return None, f"'confidence' must be numeric, got {raw_confidence}."

        # 5. Normalize event_id and optional metadata
        event_id = str(raw_event_id) if raw_event_id and str(raw_event_id).strip() else str(uuid.uuid4())
        raw_prov = raw_data.get("provenance")
        raw_source_id = raw_data.get("source_id") or raw_data.get("source_reference")
        raw_source_type = raw_data.get("source_type")
        raw_entity_refs = raw_data.get("entity_refs")
        raw_summary = raw_data.get("summary")
        raw_schema_version = raw_data.get("schema_version", "1.0")
        raw_created_at = raw_data.get("created_at") or raw_data.get("ingested_at") or raw_data.get("observed_at")

        try:
            event = Event(
                id=event_id,
                event_type=raw_type.strip(),
                source=raw_source.strip(),
                subject_id=raw_subject.strip() if raw_subject else "user",
                payload=raw_payload,
                event_time=event_time,
                confidence=confidence,
                provenance=raw_prov,
                source_id=raw_source_id,
                source_type=raw_source_type,
                entity_refs=raw_entity_refs,
                summary=raw_summary,
                schema_version=raw_schema_version,
                created_at=raw_created_at,
            )
            return event, None
        except EventValidationError as e:
            return None, str(e)
        except Exception as e:
            return None, f"Event creation failed: {e}"

    def ingest_event(self, raw_data: Any) -> IngestionResult:
        """
        Ingests a single event into the system.
        Handles validation, duplicate detection, and storage.
        """
        event, error = self.parse_and_validate_payload(raw_data)
        if error is not None:
            # Extract raw event_id if present for reference
            event_id = None
            if isinstance(raw_data, dict):
                event_id = raw_data.get("event_id") or raw_data.get("id")
            return IngestionResult(
                status=IngestionStatus.REJECTED,
                event_id=str(event_id) if event_id else None,
                error=error,
            )

        assert event is not None

        try:
            self.event_store.append(event)
            return IngestionResult(
                status=IngestionStatus.ACCEPTED,
                event_id=event.id,
                event_hash=event.event_hash,
                message="Event accepted and stored.",
            )
        except DuplicateEventError as e:
            return IngestionResult(
                status=IngestionStatus.DUPLICATE,
                event_id=event.id,
                event_hash=event.event_hash,
                message=f"Duplicate event detected: hash '{e.event_hash}' already recorded.",
            )
        except Exception as e:
            return IngestionResult(
                status=IngestionStatus.REJECTED,
                event_id=event.id,
                event_hash=event.event_hash,
                error=f"Storage error: {e}",
            )
