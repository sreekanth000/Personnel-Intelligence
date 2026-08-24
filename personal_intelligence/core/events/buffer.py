"""
Interface for staging and buffering incoming personal events before timeline integration.
"""

from typing import List, Optional
from personal_intelligence.core.events.models import Event, EventBatch


class EventBuffer:
    """
    In-memory / staging queue for ingesting arbitrary events
    prior to reconciliation into the state and timeline.
    """

    def __init__(self, capacity: int = 1000) -> None:
        self.capacity = capacity
        self._buffer: List[Event] = []

    def push(self, event: Event) -> None:
        """Add an event to the ingestion buffer."""
        self._buffer.append(event)

    def push_batch(self, batch: EventBatch) -> None:
        """Add a batch of events to the ingestion buffer."""
        self._buffer.extend(batch.events)

    def drain(self, limit: Optional[int] = None) -> List[Event]:
        """Drain events from the buffer for downstream processing."""
        if limit is None or limit >= len(self._buffer):
            drained = self._buffer
            self._buffer = []
            return drained
        drained = self._buffer[:limit]
        self._buffer = self._buffer[limit:]
        return drained

    def size(self) -> int:
        """Return current number of buffered events."""
        return len(self._buffer)
