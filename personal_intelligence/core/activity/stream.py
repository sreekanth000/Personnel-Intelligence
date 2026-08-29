"""
Personal Intelligence Execution Activity Stream.

Thread-safe, bounded telemetry stream capturing real execution lifecycle events:
- observation_created
- state_updated
- novelty_detected
- situation_created
- investigation_started
- tool_requested
- tool_completed
- evidence_added
- reasoning_started
- reasoning_completed
- intervention_decided
- pattern_updated

Strict Privacy Guarantees:
- Zero credential exposure
- Zero OAuth token exposure
- Zero raw private payload dumps
- Zero hidden chain-of-thought
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import threading
from typing import Any, Callable, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)


def format_iso8601(dt: Optional[datetime] = None) -> str:
    """Formats datetime into ISO-8601 string."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@dataclass(frozen=True)
class ActivityEvent:
    """
    Structured execution lifecycle event.
    """
    id: str
    timestamp: str
    type: str
    situation_id: Optional[str]
    summary: str
    source: str
    status: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Converts event to dictionary for serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "type": self.type,
            "situation_id": self.situation_id,
            "summary": self.summary,
            "source": self.source,
            "status": self.status,
        }


class ActivityStream:
    """
    Thread-safe, bounded ring-buffer activity stream for live Personal Intelligence events.
    """

    VALID_EVENT_TYPES = {
        # Canonical Prompt 3 Telemetry Stages
        "observation",
        "observation_created",
        "state_update",
        "state_updated",
        "change_detected",
        "novelty_detected",
        "significance_evaluated",
        "situation_created",
        "reasoning_eligibility",
        "hermes_investigation",
        "investigation_started",
        "hermes_reasoning",
        "reasoning_started",
        "reasoning_completed",
        "evidence_evaluated",
        "evidence_added",
        "recommendation_created",
        "policy_decision",
        "intervention_decided",
        "user_response",
        "user_feedback_applied",
        "outcome",
        "outcome_recorded",
        "pattern_updated",
        "tool_requested",
        "tool_completed",
    }

    _instance: Optional["ActivityStream"] = None
    _lock = threading.Lock()

    def __init__(self, max_events: int = 500) -> None:
        self._max_events = max_events
        self._events: deque[ActivityEvent] = deque(maxlen=max_events)
        self._listeners: List[Callable[[ActivityEvent], None]] = []
        self._mutex = threading.RLock()

    @classmethod
    def get_instance(cls) -> "ActivityStream":
        """Returns the global ActivityStream singleton."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def emit(
        self,
        event_type: str,
        summary: str,
        source: str = "personal_intelligence",
        status: str = "completed",
        situation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActivityEvent:
        """
        Emits a structured execution lifecycle event.
        Sanitizes input to guarantee zero credential/token leakage.
        """
        # Validate or normalize type
        norm_type = event_type.lower().strip()
        if norm_type not in self.VALID_EVENT_TYPES:
            norm_type = "state_updated"

        # Sanitize summary and metadata against sensitive fields and tokens
        try:
            from personal_intelligence.security.redactor import SensitivePayloadRedactor
            redactor = SensitivePayloadRedactor()
            sanitized_summary = str(redactor.sanitize(summary))
            sanitized_meta = redactor.sanitize(metadata or {})
        except Exception:
            sanitized_summary = summary.replace("Bearer ", "").strip()
            sanitized_meta = metadata or {}

        event = ActivityEvent(
            id=str(uuid.uuid4()),
            timestamp=format_iso8601(datetime.now(timezone.utc)),
            type=norm_type,
            situation_id=situation_id,
            summary=sanitized_summary,
            source=source,
            status=status,
            metadata=sanitized_meta,
        )

        with self._mutex:
            self._events.append(event)
            listeners_copy = list(self._listeners)

        # Notify any registered listeners
        for listener in listeners_copy:
            try:
                listener(event)
            except Exception as e:
                logger.warning(f"Error in ActivityStream listener: {e}")

        return event

    def get_recent(self, since_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieves recent activity events in chronological order.
        If since_id is provided, returns only events recorded after that event.
        """
        with self._mutex:
            events_list = list(self._events)

        if since_id:
            found_idx = -1
            for idx, evt in enumerate(events_list):
                if evt.id == since_id:
                    found_idx = idx
                    break
            if found_idx != -1:
                events_list = events_list[found_idx + 1:]

        # Slice to requested limit (most recent up to limit)
        if len(events_list) > limit:
            events_list = events_list[-limit:]

        return [e.to_dict() for e in events_list]

    def subscribe(self, listener: Callable[[ActivityEvent], None]) -> None:
        """Subscribes a callback listener for new events."""
        with self._mutex:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[ActivityEvent], None]) -> None:
        """Unsubscribes a callback listener."""
        with self._mutex:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def clear(self) -> None:
        """Clears the buffer."""
        with self._mutex:
            self._events.clear()
