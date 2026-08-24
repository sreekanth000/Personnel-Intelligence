"""
Observation workflow mechanism for Personal Intelligence.

Provides a normalized observation ingestion interface without continuously mirroring
external data stores (Gmail, Google Drive, Google Calendar, Google Meet, filesystem).

When Hermes encounters potentially relevant personal information during tool execution,
Personal Intelligence records a normalized observation preserving:
- source (gmail, drive, calendar, meet, filesystem, hermes, user)
- source_id (unique identifier in external system)
- timestamp (when event/observation occurred)
- observation_type (semantic category)
- summary (concise derived description)
- evidence (salient extracted facts/attributes)
- provenance (retrieval coordinates for Hermes to re-fetch original data on demand)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json

import logging
from typing import Any, Dict, List, Optional, Union
import uuid

from personal_intelligence.core.events.exceptions import EventValidationError
from personal_intelligence.core.events.models import (
    Event,
    ensure_timezone_aware,
)
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)

ALLOWED_OBSERVATION_SOURCES = {
    "gmail",
    "drive",
    "calendar",
    "meet",
    "filesystem",
    "hermes",
    "user",
}

# Maximum allowed summary length to prevent massive raw dumps
MAX_SUMMARY_LENGTH = 1000
# Maximum allowed evidence payload size in bytes
MAX_EVIDENCE_SIZE_BYTES = 32768


@dataclass
class ObservationResult:
    """Result of an observation recording operation."""
    event_id: str
    source: str
    source_id: str
    observation_type: str
    timestamp: str
    summary: str
    evidence: Any
    provenance: Dict[str, Any]
    status: str = "recorded"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "source_id": self.source_id,
            "observation_type": self.observation_type,
            "timestamp": self.timestamp,
            "summary": self.summary,
            "evidence": self.evidence,
            "provenance": self.provenance,
            "status": self.status,
        }


def record_observation(
    source: str,
    source_id: str,
    timestamp: Union[datetime, str],
    observation_type: str,
    summary: str,
    evidence: Optional[Union[Dict[str, Any], List[Any], str]] = None,
    provenance: Optional[Dict[str, Any]] = None,
    subject_id: Optional[str] = "user",
    confidence: float = 1.0,
    db_manager: Optional[DatabaseManager] = None,
    event_store: Optional[EventStore] = None,
) -> Event:
    """
    Records a normalized observation in the Personal Intelligence local event_log.

    Enforces data minimization by storing concise summaries and salient evidence,
    retaining provenance sufficient for Hermes to retrieve original information if needed.

    Args:
        source: External system source ('gmail', 'drive', 'calendar', 'meet', 'filesystem', 'hermes', 'user').
        source_id: Unique record/document/message/event identifier in the originating system.
        timestamp: Time the observation occurred (datetime or ISO 8601 string).
        observation_type: Normalized category (e.g. 'email_received', 'deadline_detected', 'document_changed', 'calendar_event', 'action_item_detected').
        summary: Concise derived description (e.g. 'Email indicates a possible deadline.').
        evidence: Salient extracted facts/attributes (NOT raw multi-megabyte payloads).
        provenance: Retrieval coordinates (tool name, query, file path, ID) allowing Hermes to re-query the source.
        subject_id: Subject of the observation (defaults to 'user').
        confidence: Normalized confidence [0.0, 1.0].
        db_manager: Optional DatabaseManager instance.
        event_store: Optional EventStore instance.

    Returns:
        The persisted normalized Event record.
    """
    # 1. Validate source
    if not source or not isinstance(source, str) or not source.strip():
        raise EventValidationError("source must be a non-empty string.")
    norm_source = source.strip().lower()
    if norm_source not in ALLOWED_OBSERVATION_SOURCES:
        raise EventValidationError(
            f"Invalid source '{source}'. Allowed sources: {sorted(list(ALLOWED_OBSERVATION_SOURCES))}"
        )

    # 2. Validate source_id
    if not source_id or not isinstance(source_id, str) or not source_id.strip():
        raise EventValidationError("source_id must be a non-empty string identifier.")
    norm_source_id = source_id.strip()

    # 3. Validate timestamp
    aware_timestamp = ensure_timezone_aware(timestamp, "timestamp")

    # 4. Validate observation_type
    if not observation_type or not isinstance(observation_type, str) or not observation_type.strip():
        raise EventValidationError("observation_type must be a non-empty string.")
    norm_obs_type = observation_type.strip().lower()

    # 5. Validate summary
    if not summary or not isinstance(summary, str) or not summary.strip():
        raise EventValidationError("summary must be a non-empty concise description.")
    norm_summary = summary.strip()
    if len(norm_summary) > MAX_SUMMARY_LENGTH:
        norm_summary = norm_summary[:MAX_SUMMARY_LENGTH] + "..."

    # 6. Validate evidence and sanitize against raw bloat
    if evidence is None:
        norm_evidence: Any = {}
    elif isinstance(evidence, (dict, list, str, int, float, bool)):
        evidence_str = json.dumps(evidence, ensure_ascii=False)
        if len(evidence_str.encode("utf-8")) > MAX_EVIDENCE_SIZE_BYTES:
            raise EventValidationError(
                f"Evidence payload exceeds size limit ({MAX_EVIDENCE_SIZE_BYTES} bytes). "
                "Do not store raw multi-megabyte external content. Store extracted salient facts only."
            )
        norm_evidence = evidence
    else:
        raise EventValidationError(f"evidence must be a dict, list, or string, got {type(evidence).__name__}")

    # 7. Validate provenance
    if provenance is None or not isinstance(provenance, dict) or not provenance:
        raise EventValidationError(
            "provenance must be a non-empty dict containing origin tool and retrieval parameters "
            "sufficient for Hermes to re-query the source."
        )

    # Construct normalized payload
    payload: Dict[str, Any] = {
        "summary": norm_summary,
        "evidence": norm_evidence,
    }
    if isinstance(norm_evidence, dict):
        for k, v in norm_evidence.items():
            if k not in payload:
                payload[k] = v

    # Calculate confidence category
    if confidence >= 0.9:
        confidence_cat = "high"
    elif confidence >= 0.7:
        confidence_cat = "moderate"
    else:
        confidence_cat = "low"

    # Instantiate normalized Observation
    observation = Event(
        id=str(uuid.uuid4()),
        observation_type=norm_obs_type,
        source=norm_source,
        source_id=norm_source_id,
        summary=norm_summary,
        structured_data=payload,
        provenance=provenance,
        confidence_category=confidence_cat,
        timestamp=aware_timestamp,
        created_at=datetime.now(timezone.utc),
        subject_id=subject_id or "user",
        confidence=confidence,
    )

    from personal_intelligence.core.events.exceptions import DuplicateEventError

    store = event_store or EventStore(db_manager=db_manager or DatabaseManager())
    try:
        saved_observation = store.append(observation)
        return saved_observation

    except DuplicateEventError:
        # If identical observation already exists, retrieve existing event or return instance cleanly
        logger.info("Observation '%s' with hash '%s' already recorded. Duplicate prevented.", observation.id, observation.event_hash)
        existing = store.get_by_hash(observation.event_hash)
        return existing or observation


