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

import logging
import re
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

# Valid source identifier format (generic alphanumeric, underscores, hyphens, dots)
SOURCE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{2,64}$")

# Backwards-compatibility reference of common standard observation sources
ALLOWED_OBSERVATION_SOURCES = frozenset({
    "gmail", "drive", "calendar", "meet", "filesystem", "hermes", "user",
    "whatsapp", "whoop", "slack", "jira", "hevy", "linear", "github", "healthkit",
})

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
    source_type: Optional[str] = None
    schema_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "observation_type": self.observation_type,
            "timestamp": self.timestamp,
            "summary": self.summary,
            "evidence": self.evidence,
            "provenance": self.provenance,
            "status": self.status,
            "schema_version": self.schema_version,
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
    source_type: Optional[str] = None,
    observed_at: Optional[Union[datetime, str]] = None,
    entity_refs: Optional[List[str]] = None,
    schema_version: str = "1.0",
    db_manager: Optional[DatabaseManager] = None,
    event_store: Optional[EventStore] = None,
    # Compatibility aliases
    occurred_at: Optional[Union[datetime, str]] = None,
    source_reference: Optional[str] = None,
) -> Event:
    """
    Records a normalized, source-backed observation in the Personal Intelligence local event_log.

    Enforces data minimization by storing concise summaries and salient evidence,
    retaining provenance sufficient for Hermes to retrieve original information if needed.

    Args:
        source: External system source identifier (e.g. 'whatsapp', 'gmail', 'slack', 'whoop', 'calendar', 'drive', 'jira', 'filesystem', 'hermes', 'user').
        source_id: Unique record/document/message/event identifier in the originating system.
        timestamp: Time the observation occurred in the external world (datetime or ISO 8601 string).
        observation_type: Normalized category (e.g. 'email_received', 'deadline_detected', 'document_changed', 'calendar_event', 'action_item_detected').
        summary: Concise derived description.
        evidence: Salient extracted facts/attributes (NOT raw multi-megabyte payloads).
        provenance: Retrieval coordinates (tool name, query, file path, ID) allowing Hermes to re-query the source.
        subject_id: Subject of the observation (defaults to 'user').
        confidence: Normalized confidence [0.0, 1.0].
        source_type: Optional generic category ('communication', 'calendar', 'document', 'activity', 'financial', 'health', 'system', 'user').
        observed_at: Time when the observation was ingested into PI (defaults to now UTC).
        entity_refs: Optional list of related entity IDs / references.
        schema_version: Schema contract version (default '1.0').
        db_manager: Optional DatabaseManager instance.
        event_store: Optional EventStore instance.

    Returns:
        The persisted normalized Event record.
    """
    # 1. Validate source
    if not source or not isinstance(source, str) or not source.strip():
        raise EventValidationError("source must be a non-empty string identifier.")
    norm_source = source.strip().lower()
    if not SOURCE_IDENTIFIER_PATTERN.match(norm_source):
        raise EventValidationError(
            f"Invalid source identifier '{source}'. Source must be an alphanumeric identifier (2-64 chars)."
        )

    # 2. Validate source_id / source_reference
    sid_raw = source_id or source_reference
    if not sid_raw or not isinstance(sid_raw, str) or not sid_raw.strip():
        raise EventValidationError("source_id must be a non-empty string identifier.")
    norm_source_id = sid_raw.strip()

    # 3. Validate timestamp / occurred_at
    ts_val = timestamp if timestamp is not None else occurred_at
    if ts_val is None:
        raise EventValidationError("timestamp or occurred_at must be provided.")
    aware_timestamp = ensure_timezone_aware(ts_val, "timestamp")

    # Validate observed_at
    aware_observed_at = ensure_timezone_aware(observed_at or datetime.now(timezone.utc), "observed_at")

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
    if entity_refs:
        payload["entity_refs"] = list(entity_refs)
    if source_type:
        payload["source_type"] = source_type
    if schema_version:
        payload["schema_version"] = schema_version
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
        source_type=source_type,
        source_id=norm_source_id,
        summary=norm_summary,
        structured_data=payload,
        provenance=provenance,
        confidence_category=confidence_cat,
        timestamp=aware_timestamp,
        created_at=aware_observed_at,
        subject_id=subject_id or "user",
        entity_refs=entity_refs or [],
        confidence=confidence,
        schema_version=schema_version,
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


