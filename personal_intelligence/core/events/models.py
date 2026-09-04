"""
Generic, domain-agnostic Event and Observation models with strict validation and deterministic hashing.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Union
import uuid

from personal_intelligence.core.events.exceptions import EventValidationError


def ensure_timezone_aware(dt: Union[datetime, str], field_name: str = "timestamp") -> datetime:
    """
    Validates and converts a datetime or ISO string to a timezone-aware UTC/offset datetime object.
    Raises EventValidationError if timezone offset is missing or format is invalid.
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
    """Serializes arbitrary dictionary payload into canonical deterministic JSON string."""
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
    subj = subject_id.strip() if subject_id is not None else ""
    canonical_representation = (
        f"{utc_time_iso}|{observation_type.strip()}|{source.strip()}|{subj}|{payload_json}"
    )
    return hashlib.sha256(canonical_representation.encode("utf-8")).hexdigest()


compute_event_hash = compute_observation_hash


class Observation:
    """
    Normalized source-backed observation stored for longitudinal reasoning.
    Does NOT mirror raw external payloads. Captures salient items determined to
    matter for future reasoning while retaining tool retrieval provenance.
    """

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
        source_type: Optional[str] = None,
        entity_refs: Optional[List[str]] = None,
        schema_version: Optional[str] = "1.0",
        # Backward-compatible & alias keyword arguments
        observation_id: Optional[str] = None,
        event_type: Optional[str] = None,
        event_time: Optional[Union[datetime, str]] = None,
        occurred_at: Optional[Union[datetime, str]] = None,
        observed_at: Optional[Union[datetime, str]] = None,
        ingested_at: Optional[Union[datetime, str]] = None,
        source_reference: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> None:
        self.id = id or observation_id or str(uuid.uuid4())
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

        self.source_type = source_type
        self.source_id = source_id or source_reference

        data = structured_data if structured_data is not None else (payload if payload is not None else {})
        self.structured_data = data

        if summary is not None:
            self.summary = summary
        elif isinstance(data, dict) and isinstance(data.get("summary"), str):
            self.summary = data["summary"]
        elif isinstance(data, dict) and isinstance(data.get("description"), str):
            self.summary = data["description"]
        elif isinstance(data, dict) and isinstance(data.get("title"), str):
            self.summary = data["title"]
        else:
            self.summary = f"{self.observation_type} from {self.source}"

        self.provenance = provenance
        self.subject_id = subject_id
        self.entity_refs = list(entity_refs) if entity_refs is not None else []
        self.confidence = float(confidence)
        self.schema_version = schema_version or "1.0"

        if confidence_category is not None:
            self.confidence_category = confidence_category
        elif self.confidence >= 0.9:
            self.confidence_category = "high"
        elif self.confidence >= 0.7:
            self.confidence_category = "moderate"
        else:
            self.confidence_category = "low"

        ts_raw = timestamp or event_time or occurred_at or datetime.now(timezone.utc)
        self.timestamp = ensure_timezone_aware(ts_raw, "timestamp")

        cr_raw = created_at or ingested_at or observed_at or datetime.now(timezone.utc)
        self.created_at = ensure_timezone_aware(cr_raw, "created_at")

        self.event_hash = event_hash or idempotency_key
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
    def observation_id(self) -> str:
        """Alias for id."""
        return self.id

    @property
    def occurred_at(self) -> datetime:
        """Alias for timestamp."""
        return self.timestamp

    @property
    def event_time(self) -> datetime:
        """Alias for timestamp."""
        return self.timestamp

    @event_time.setter
    def event_time(self, val: Union[datetime, str]) -> None:
        self.timestamp = ensure_timezone_aware(val, "timestamp")

    @property
    def observed_at(self) -> datetime:
        """Alias for created_at."""
        return self.created_at

    @property
    def ingested_at(self) -> datetime:
        """Alias for created_at."""
        return self.created_at

    @ingested_at.setter
    def ingested_at(self, val: Union[datetime, str]) -> None:
        self.created_at = ensure_timezone_aware(val, "created_at")

    @property
    def source_reference(self) -> Optional[str]:
        """Alias for source_id."""
        return self.source_id

    @source_reference.setter
    def source_reference(self, val: Optional[str]) -> None:
        self.source_id = val

    @property
    def idempotency_key(self) -> Optional[str]:
        """Alias for event_hash."""
        return self.event_hash

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
            "observation_id": self.id,
            "timestamp": format_iso8601(self.timestamp),
            "event_time": format_iso8601(self.timestamp),
            "occurred_at": format_iso8601(self.timestamp),
            "created_at": format_iso8601(self.created_at),
            "ingested_at": format_iso8601(self.created_at),
            "observed_at": format_iso8601(self.created_at),
            "observation_type": self.observation_type,
            "event_type": self.observation_type,
            "source": self.source,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_reference": self.source_id,
            "summary": self.summary,
            "structured_data": self.structured_data,
            "payload": self.structured_data,
            "provenance": self.provenance,
            "confidence_category": self.confidence_category,
            "confidence": self.confidence,
            "subject_id": self.subject_id,
            "entity_refs": self.entity_refs,
            "event_hash": self.event_hash,
            "idempotency_key": self.event_hash,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Observation":
        """Creates and validates an Observation instance from a dictionary."""
        if not isinstance(data, dict):
            raise EventValidationError(f"Expected dict to construct Observation, got {type(data).__name__}")

        obs_type = data.get("observation_type") or data.get("event_type")
        if not obs_type:
            raise EventValidationError("Missing required field 'observation_type' or 'event_type' in observation data.")

        ts_raw = data.get("timestamp") or data.get("event_time") or data.get("occurred_at")
        if not ts_raw:
            raise EventValidationError("Missing required field 'timestamp' or 'event_time' in observation data.")

        cr_raw = data.get("created_at") or data.get("ingested_at") or data.get("observed_at")
        src = data.get("source", "hermes")
        sid = data.get("source_id") or data.get("source_reference")
        stype = data.get("source_type")
        sdata = data.get("structured_data") if "structured_data" in data else data.get("payload", {})
        prov = data.get("provenance")
        conf = data.get("confidence", 1.0)
        subj = data.get("subject_id")
        erefs = data.get("entity_refs") or []
        e_id = data.get("id") or data.get("observation_id")
        ehash = data.get("event_hash") or data.get("idempotency_key")
        summ = data.get("summary")
        conf_cat = data.get("confidence_category")
        sver = data.get("schema_version", "1.0")

        return cls(
            id=e_id,
            observation_type=obs_type,
            source=src,
            source_type=stype,
            source_id=sid,
            summary=summ,
            structured_data=sdata,
            provenance=prov,
            confidence_category=conf_cat,
            timestamp=ts_raw,
            created_at=cr_raw,
            confidence=conf,
            subject_id=subj,
            entity_refs=erefs,
            event_hash=ehash,
            schema_version=sver,
        )


# Canonical alias for compatibility
Event = Observation


class ObservationBatch:
    """A collection of normalized observations received together."""

    def __init__(
        self,
        observations: Optional[List[Observation]] = None,
        events: Optional[List[Observation]] = None,
        batch_id: Optional[str] = None,
        received_at: Optional[datetime] = None,
    ) -> None:
        self.observations = observations if observations is not None else (events if events is not None else [])
        self.batch_id = batch_id or str(uuid.uuid4())
        self.received_at = ensure_timezone_aware(received_at or datetime.now(timezone.utc), "received_at")

    @property
    def events(self) -> List[Observation]:
        return self.observations

    @events.setter
    def events(self, val: List[Observation]) -> None:
        self.observations = val


EventBatch = ObservationBatch



