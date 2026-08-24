"""
Generic, domain-agnostic Event model with validation and deterministic hashing.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, Optional, Union
import uuid

from personal_intelligence.core.events.exceptions import EventValidationError


def ensure_timezone_aware(dt: Union[datetime, str], field_name: str = "timestamp") -> datetime:
    """
    Validates and converts a datetime or ISO string to a timezone-aware datetime object.
    Raises EventValidationError if timezone is missing or format is invalid.
    """
    if isinstance(dt, str):
        # Support trailing 'Z' for UTC in ISO strings
        clean_str = dt.replace("Z", "+00:00")
        try:
            parsed_dt = datetime.fromisoformat(clean_str)
        except Exception as e:
            raise EventValidationError(f"{field_name} is not a valid ISO-8601 string: {dt}. Error: {e}")
        if parsed_dt.tzinfo is None or parsed_dt.tzinfo.utcoffset(parsed_dt) is None:
            raise EventValidationError(f"{field_name} string must include timezone offset: {dt}")
        return parsed_dt
    elif isinstance(dt, datetime):
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise EventValidationError(f"{field_name} must be a timezone-aware datetime object (got naive datetime).")
        return dt
    else:
        raise EventValidationError(f"{field_name} must be a datetime object or ISO-8601 string, got {type(dt).__name__}")


def format_iso8601(dt: datetime) -> str:
    """Formats a timezone-aware datetime to standardized UTC ISO-8601 format."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise EventValidationError("Cannot format naive datetime to ISO-8601.")
    return dt.astimezone(timezone.utc).isoformat()



def serialize_payload(payload: Any) -> str:
    """Serializes arbitrary dictionary payload into canonical JSON string."""
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise EventValidationError(f"payload is not JSON-serializable: {e}")


class StandardObservationType:
    """Standard observation categories relevant for longitudinal reasoning."""
    POSSIBLE_COMMITMENT = "possible_commitment"
    UPCOMING_MILESTONE = "upcoming_milestone"
    MEETING_DECISION = "meeting_decision"
    DOCUMENT_CHANGED = "document_changed"
    UNRESOLVED_ACTION = "unresolved_action"
    GOAL_SIGNAL = "goal_signal"
    ROUTINE_CHANGE = "routine_change"
    NOVEL_STATE = "novel_state"
    GENERIC_OBSERVATION = "generic_observation"


def compute_observation_hash(
    timestamp: datetime,
    observation_type: str,
    source: str,
    subject_id: Optional[str],
    structured_data: Dict[str, Any],
) -> str:
    """
    Deterministically computes a SHA-256 hash for an observation based on its
    canonical normalized representation.
    """
    utc_time_iso = timestamp.astimezone(timezone.utc).isoformat()
    payload_json = serialize_payload(structured_data)
    subj = subject_id if subject_id is not None else ""
    canonical_representation = f"{utc_time_iso}|{observation_type.strip()}|{source.strip()}|{subj.strip()}|{payload_json}"
    return hashlib.sha256(canonical_representation.encode("utf-8")).hexdigest()


compute_event_hash = compute_observation_hash


@dataclass
class Observation:
    """
    Normalized observation stored for longitudinal reasoning.
    Does NOT mirror external data sources (Gmail, Drive, Calendar, Meet, filesystem).
    Captures only salient items determined to matter for future reasoning, preserving source provenance.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    observation_type: str = StandardObservationType.GENERIC_OBSERVATION
    source: str = "hermes"
    source_id: Optional[str] = None
    summary: str = ""
    structured_data: Dict[str, Any] = field(default_factory=dict)
    provenance: Optional[Dict[str, Any]] = None
    confidence_category: str = "moderate"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    subject_id: Optional[str] = None
    confidence: float = 1.0
    event_hash: Optional[str] = None

    def __init__(
        self,
        observation_type: Optional[str] = None,
        source: Optional[str] = None,
        structured_data: Optional[Dict[str, Any]] = None,
        timestamp: Optional[Union[datetime, str]] = None,
        summary: Optional[str] = None,
        source_id: Optional[str] = None,
        provenance: Optional[Dict[str, Any]] = None,
        confidence_category: Optional[str] = None,
        created_at: Optional[Union[datetime, str]] = None,
        id: Optional[str] = None,
        subject_id: Optional[str] = None,
        confidence: float = 1.0,
        event_hash: Optional[str] = None,
        # Backward-compatible keyword arguments
        event_type: Optional[str] = None,
        event_time: Optional[Union[datetime, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
        ingested_at: Optional[Union[datetime, str]] = None,
    ) -> None:
        self.id = id or str(uuid.uuid4())
        if observation_type is not None:
            self.observation_type = observation_type
        elif event_type is not None:
            self.observation_type = event_type
        else:
            self.observation_type = StandardObservationType.GENERIC_OBSERVATION

        if source is not None:
            self.source = source
        else:
            self.source = "hermes"

        self.source_id = source_id

        
        data = structured_data if structured_data is not None else (payload if payload is not None else {})
        self.structured_data = data

        # Extract summary from parameter or structured_data payload
        if summary is not None:
            self.summary = summary
        elif "summary" in data and isinstance(data["summary"], str):
            self.summary = data["summary"]
        elif "description" in data and isinstance(data["description"], str):
            self.summary = data["description"]
        elif "title" in data and isinstance(data["title"], str):
            self.summary = data["title"]
        else:
            self.summary = f"{self.observation_type} from {self.source}"

        self.provenance = provenance
        self.subject_id = subject_id
        self.confidence = float(confidence)

        if confidence_category is not None:
            self.confidence_category = confidence_category
        elif self.confidence >= 0.9:
            self.confidence_category = "high"
        elif self.confidence >= 0.7:
            self.confidence_category = "moderate"
        else:
            self.confidence_category = "low"

        ts_raw = timestamp or event_time or datetime.now(timezone.utc)
        self.timestamp = ensure_timezone_aware(ts_raw, "timestamp")

        cr_raw = created_at or ingested_at or datetime.now(timezone.utc)
        self.created_at = ensure_timezone_aware(cr_raw, "created_at")

        self.event_hash = event_hash
        self.validate()

        if not self.event_hash:
            self.event_hash = compute_observation_hash(
                timestamp=self.timestamp,
                observation_type=self.observation_type,
                source=self.source,
                subject_id=self.subject_id,
                structured_data=self.structured_data,
            )

    @property
    def event_time(self) -> datetime:
        """Alias for timestamp."""
        return self.timestamp

    @event_time.setter
    def event_time(self, val: Union[datetime, str]) -> None:
        self.timestamp = ensure_timezone_aware(val, "timestamp")

    @property
    def event_type(self) -> str:
        """Alias for observation_type."""
        return self.observation_type

    @event_type.setter
    def event_type(self, val: str) -> None:
        self.observation_type = val

    @property
    def payload(self) -> Dict[str, Any]:
        """Alias for structured_data."""
        return self.structured_data

    @payload.setter
    def payload(self, val: Dict[str, Any]) -> None:
        self.structured_data = val

    @property
    def ingested_at(self) -> datetime:
        """Alias for created_at."""
        return self.created_at

    @ingested_at.setter
    def ingested_at(self, val: Union[datetime, str]) -> None:
        self.created_at = ensure_timezone_aware(val, "created_at")

    def validate(self) -> None:
        """
        Performs strict validation on all observation fields.
        Raises EventValidationError if any validation fails.
        """
        if not self.id or not isinstance(self.id, str) or not self.id.strip():
            raise EventValidationError("Observation id must be a non-empty string.")

        if not self.observation_type or not isinstance(self.observation_type, str) or not self.observation_type.strip():
            raise EventValidationError("observation_type must be a non-empty string.")

        if not self.source or not isinstance(self.source, str) or not self.source.strip():
            raise EventValidationError("source must be a non-empty string.")

        if self.subject_id is not None and not isinstance(self.subject_id, str):
            raise EventValidationError(f"subject_id must be a string or None, got {type(self.subject_id).__name__}.")

        if self.source_id is not None and not isinstance(self.source_id, str):
            raise EventValidationError(f"source_id must be a string or None, got {type(self.source_id).__name__}.")

        if self.provenance is not None and not isinstance(self.provenance, dict):
            raise EventValidationError(f"provenance must be a dictionary or None, got {type(self.provenance).__name__}.")

        self.timestamp = ensure_timezone_aware(self.timestamp, "timestamp")
        self.created_at = ensure_timezone_aware(self.created_at, "created_at")

        if not isinstance(self.structured_data, dict):
            raise EventValidationError(f"structured_data must be a dictionary, got {type(self.structured_data).__name__}.")
        serialize_payload(self.structured_data)

        if not isinstance(self.confidence, (int, float)):
            raise EventValidationError(f"confidence must be a float between 0.0 and 1.0, got {type(self.confidence).__name__}.")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise EventValidationError(f"confidence must be between 0.0 and 1.0, got {self.confidence}.")

        if self.event_hash is not None:
            if not isinstance(self.event_hash, str) or not self.event_hash.strip():
                raise EventValidationError("event_hash must be a non-empty string when provided.")

    def to_dict(self) -> Dict[str, Any]:
        """Converts Observation into a serializable dictionary."""
        return {
            "id": self.id,
            "timestamp": format_iso8601(self.timestamp),
            "event_time": format_iso8601(self.timestamp),
            "created_at": format_iso8601(self.created_at),
            "ingested_at": format_iso8601(self.created_at),
            "observation_type": self.observation_type,
            "event_type": self.observation_type,
            "source": self.source,
            "source_id": self.source_id,
            "summary": self.summary,
            "structured_data": self.structured_data,
            "payload": self.structured_data,
            "provenance": self.provenance,
            "confidence_category": self.confidence_category,
            "confidence": self.confidence,
            "subject_id": self.subject_id,
            "event_hash": self.event_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Observation":
        """Creates and validates an Observation instance from a dictionary."""
        if not isinstance(data, dict):
            raise EventValidationError(f"Expected dict to construct Observation, got {type(data).__name__}")

        obs_type = data.get("observation_type") or data.get("event_type")
        if not obs_type:
            raise EventValidationError("Missing required field 'observation_type' or 'event_type' in observation data.")

        ts_raw = data.get("timestamp") or data.get("event_time")
        if not ts_raw:
            raise EventValidationError("Missing required field 'timestamp' or 'event_time' in observation data.")

        if "source" not in data:
            raise EventValidationError("Missing required field 'source' in observation data.")

        payload = data.get("structured_data") if "structured_data" in data else data.get("payload", {})
        if not isinstance(payload, dict):
            raise EventValidationError(f"payload/structured_data must be a dictionary, got {type(payload).__name__}")

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            observation_type=obs_type,
            source=data["source"],
            structured_data=payload,
            timestamp=ensure_timezone_aware(ts_raw, "timestamp"),
            summary=data.get("summary"),
            source_id=data.get("source_id"),
            provenance=data.get("provenance"),
            confidence_category=data.get("confidence_category"),
            created_at=ensure_timezone_aware(data.get("created_at") or data.get("ingested_at", datetime.now(timezone.utc)), "created_at"),
            subject_id=data.get("subject_id"),
            confidence=data.get("confidence", 1.0),
            event_hash=data.get("event_hash"),
        )


# Alias Event to Observation for seamless domain transition
Event = Observation


@dataclass
class ObservationBatch:
    """A collection of normalized observations received together."""
    observations: list = field(default_factory=list)
    batch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __init__(
        self,
        observations: Optional[list] = None,
        events: Optional[list] = None,
        batch_id: Optional[str] = None,
        received_at: Optional[datetime] = None,
    ) -> None:
        self.observations = observations if observations is not None else (events if events is not None else [])
        self.batch_id = batch_id or str(uuid.uuid4())
        self.received_at = received_at or datetime.now(timezone.utc)

    @property
    def events(self) -> list:
        return self.observations

    @events.setter
    def events(self, val: list) -> None:
        self.observations = val


EventBatch = ObservationBatch



