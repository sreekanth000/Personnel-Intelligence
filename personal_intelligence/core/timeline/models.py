"""
Timeline models representing chronological history, intervals, and aggregate summaries.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional
import uuid

from personal_intelligence.core.events.models import Event, format_iso8601


class TimelineEntryType(str, Enum):
    """Categorization of entries in the unified timeline."""
    EVENT = "event"
    INTERVAL = "interval"
    STATE_TRANSITION = "state_transition"
    INTERVENTION = "intervention"
    DECISION = "decision"
    MILESTONE = "milestone"


@dataclass
class TimelineEntry:
    """An individual entry or anchor placed on the personal timeline."""
    entry_type: TimelineEntryType
    timestamp: datetime
    title: str
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    end_timestamp: Optional[datetime] = None
    description: Optional[str] = None
    associated_event_ids: List[str] = field(default_factory=list)
    associated_goal_ids: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TimelineInterval:
    """A bounded time interval representing an activity, phase, or continuous episode."""
    interval_type: str
    start_time: datetime
    end_time: Optional[datetime] = None
    interval_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    summary: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Timeline:
    """
    Chronologically ordered container of Events.
    Provides compact context representations for Hermes and deterministic aggregations.
    """

    def __init__(
        self,
        events: Optional[List[Event]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        query_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Guarantee strict chronological ordering by event_time, then ingested_at
        raw_events = events or []
        self.events: List[Event] = sorted(
            raw_events,
            key=lambda e: (e.event_time, e.ingested_at),
        )
        self.start_time = start_time
        self.end_time = end_time
        self.query_metadata = query_metadata or {}

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)

    def __getitem__(self, index: int) -> Event:
        return self.events[index]

    @property
    def is_empty(self) -> bool:
        """Returns True if timeline contains no events."""
        return len(self.events) == 0

    @property
    def first_event(self) -> Optional[Event]:
        """Returns the chronologically earliest event in this timeline slice."""
        return self.events[0] if self.events else None

    @property
    def last_event(self) -> Optional[Event]:
        """Returns the chronologically latest event in this timeline slice."""
        return self.events[-1] if self.events else None

    def to_compact_dict(self) -> Dict[str, Any]:
        """
        Produces a token-efficient dictionary representation suitable for Hermes context injection.
        """
        return {
            "start_time": format_iso8601(self.start_time) if self.start_time else (format_iso8601(self.first_event.event_time) if self.first_event else None),
            "end_time": format_iso8601(self.end_time) if self.end_time else (format_iso8601(self.last_event.event_time) if self.last_event else None),
            "total_events": len(self.events),
            "query_metadata": self.query_metadata,
            "events": [
                {
                    "id": e.id,
                    "time": format_iso8601(e.event_time),
                    "type": e.event_type,
                    "source": e.source,
                    "subject": e.subject_id,
                    "payload": e.payload,
                    "confidence": e.confidence,
                }
                for e in self.events
            ],
        }

    def to_compact_text(self, max_events: Optional[int] = None) -> str:
        """
        Produces a dense, tabular chronological text format for LLM prompts.
        """
        if self.is_empty:
            return "[Empty Timeline]"

        lines = []
        events_to_render = self.events if max_events is None else self.events[:max_events]
        for e in events_to_render:
            iso_time = format_iso8601(e.event_time)
            lines.append(f"[{iso_time}] ({e.event_type}) src={e.source} subj={e.subject_id} | {e.payload}")

        if max_events is not None and len(self.events) > max_events:
            lines.append(f"... and {len(self.events) - max_events} more events.")

        return "\n".join(lines)

    def summarize_raw(self) -> Dict[str, Any]:
        """
        Performs deterministic, statistical aggregation only over the timeline events.
        Produces zero natural-language summary.
        """
        total = len(self.events)
        if total == 0:
            return {
                "total_events": 0,
                "time_span": {
                    "start": None,
                    "end": None,
                    "duration_seconds": 0.0,
                },
                "event_types": {},
                "sources": {},
                "subjects": {},
                "hourly_distribution": {},
                "confidence_stats": {
                    "min": 0.0,
                    "max": 0.0,
                    "mean": 0.0,
                },
            }

        first_dt = self.events[0].event_time
        last_dt = self.events[-1].event_time
        duration_seconds = max(0.0, (last_dt - first_dt).total_seconds())

        type_counts = Counter(e.event_type for e in self.events)
        source_counts = Counter(e.source for e in self.events)
        subject_counts = Counter(e.subject_id or "unknown" for e in self.events)

        # Hourly bins in UTC
        hourly_bins = Counter()
        confidences = []
        for e in self.events:
            utc_dt = e.event_time.astimezone(timezone.utc)
            bin_key = utc_dt.strftime("%Y-%m-%dT%H:00:00+00:00")
            hourly_bins[bin_key] += 1
            confidences.append(e.confidence)

        min_conf = min(confidences)
        max_conf = max(confidences)
        mean_conf = round(sum(confidences) / total, 4)

        return {
            "total_events": total,
            "time_span": {
                "start": format_iso8601(first_dt),
                "end": format_iso8601(last_dt),
                "duration_seconds": duration_seconds,
            },
            "event_types": dict(type_counts.most_common()),
            "sources": dict(source_counts.most_common()),
            "subjects": dict(subject_counts.most_common()),
            "hourly_distribution": dict(sorted(hourly_bins.items())),
            "confidence_stats": {
                "min": min_conf,
                "max": max_conf,
                "mean": mean_conf,
            },
        }
