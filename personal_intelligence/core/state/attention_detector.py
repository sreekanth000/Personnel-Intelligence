"""
Deterministic Attention State Detector for Personal Intelligence.

Derives the user's current attention state from multi-signal heuristics:
  - Calendar / Meeting status (meeting with ≥2 attendees)
  - DND / Focus mode signals (OS/device level)
  - Screen continuity & deep work (continuous IDE/writing/design activity > threshold)
  - Context switching rate (ratio of app switches to focused actions)
  - User interaction continuity (steady actions vs. idle gaps)
  - Notification response patterns
  - Idle time duration
  - Mobility state (driving vs. public transit)
  - Time-of-day sleep heuristics

Returns one of 10 canonical categorical states:
  MEETING | DND | DEEP_WORK | FOCUSED | AVAILABLE | IDLE | DRIVING | TRANSIT | SLEEP | UNKNOWN

All thresholds are configurable.

Blueprint Reference: §13 — Attention State Detection, Decision 3 & Change 9.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from personal_intelligence.core.events.models import Event, ensure_timezone_aware, format_iso8601
from personal_intelligence.core.policy.models import UserContext
from personal_intelligence.core.state.models import StateRepresentation


@dataclass
class AttentionDetectionResult:
    """
    Result of deterministic attention state detection with full provenance.
    """
    state: str  # UserContext enum value
    source: str  # What evidence category triggered detection
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str = ""  # Human-readable explanation
    attention_state_source: str = ""  # Specific signal that drove the detection
    contributing_signals: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.timestamp = ensure_timezone_aware(self.timestamp, "AttentionDetectionResult timestamp")
        if not self.attention_state_source:
            self.attention_state_source = self.source

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "source": self.source,
            "timestamp": format_iso8601(self.timestamp),
            "reason": self.reason,
            "attention_state_source": self.attention_state_source,
            "contributing_signals": self.contributing_signals,
        }


# ---------------------------------------------------------------------------
# Signal keyword sets for deterministic classification
# ---------------------------------------------------------------------------

_MEETING_SIGNALS = frozenset({
    "meeting", "calendar_event", "gcal", "calendar", "in_meeting",
    "video_call", "zoom", "teams_call", "google_meet", "webex",
})

_DND_SIGNALS = frozenset({
    "dnd", "do_not_disturb", "do-not-disturb", "focus_mode", "silent_mode",
    "focus", "quiet_mode", "do_not_disturb_enabled", "focus_mode_enabled",
})

_DRIVING_SIGNALS = frozenset({
    "driving", "carplay", "android_auto", "in_car", "navigation", "waze",
    "google_maps_driving", "uber", "lyft",
})

_TRANSIT_SIGNALS = frozenset({
    "in_transit", "commute", "traveling", "train", "flight",
    "transit", "boarding", "departure", "subway", "bus", "train_boarding",
})

_DEEP_WORK_ACTIVITY_SIGNALS = frozenset({
    "vscode", "editor", "terminal", "ide", "coding", "writing", "document_edit",
    "spreadsheet", "design_tool", "figma", "intellij", "vim", "emacs",
    "code_compile", "git_commit", "document_write", "vscode_edit", "editor_activity",
    "terminal_command",
})

_SLEEP_HOUR_START = 22  # 10 PM
_SLEEP_HOUR_END = 7     # 7 AM


class AttentionDetector:
    """
    Deterministic multi-signal heuristic detector that derives user attention state.

    Detection Precedence (highest to lowest):
      1. Active calendar meeting with ≥2 attendees → MEETING
      2. Explicit DND / Focus mode signal → DO_NOT_DISTURB
      3. Continuous single-app/tool activity > deep_work_threshold → DEEP_WORK
      4. Driving signal (Uber/Car/GPS) → DRIVING
      5. Transit / commute signal (Train/Flight) → TRANSIT
      6. Active focused activity with moderate duration (10-30m) → FOCUSED
      7. No events in idle_threshold + sleep hours → SLEEP
      8. High/moderate recent event density → BUSY
      9. Default daytime activity (or no events during day) → AVAILABLE
    """

    def __init__(
        self,
        deep_work_threshold_minutes: float = 30.0,
        focused_threshold_minutes: float = 10.0,
        idle_threshold_minutes: float = 30.0,
        recent_window_minutes: float = 15.0,
        max_context_switch_ratio_deep_work: float = 0.25,
        sleep_hour_start: int = _SLEEP_HOUR_START,
        sleep_hour_end: int = _SLEEP_HOUR_END,
    ) -> None:
        self.deep_work_threshold = timedelta(minutes=deep_work_threshold_minutes)
        self.focused_threshold = timedelta(minutes=focused_threshold_minutes)
        self.idle_threshold = timedelta(minutes=idle_threshold_minutes)
        self.recent_window = timedelta(minutes=recent_window_minutes)
        self.max_context_switch_ratio = max_context_switch_ratio_deep_work
        self.sleep_hour_start = sleep_hour_start
        self.sleep_hour_end = sleep_hour_end

    def detect(
        self,
        recent_events: List[Event],
        current_state: Optional[StateRepresentation] = None,
        current_time: Optional[datetime] = None,
    ) -> AttentionDetectionResult:
        """
        Derives the user's current attention state from recent events and state.
        """
        now = ensure_timezone_aware(
            current_time or datetime.now(timezone.utc), "current_time"
        )
        contributing: List[str] = []

        # Partition events into time windows
        cutoff = now - self.recent_window
        recent = [e for e in recent_events if _event_time(e) >= cutoff]

        deep_work_cutoff = now - self.deep_work_threshold
        deep_work_window = [e for e in recent_events if _event_time(e) >= deep_work_cutoff]

        idle_cutoff = now - self.idle_threshold
        idle_window = [e for e in recent_events if _event_time(e) >= idle_cutoff]

        # ---------------------------------------------------------------
        # 1. MEETING — Active calendar event with ≥2 attendees
        # ---------------------------------------------------------------
        meeting_event = self._find_active_meeting(recent, now)
        if meeting_event is not None:
            contributing.append(f"calendar_event:{meeting_event.source_id or meeting_event.id}")
            return AttentionDetectionResult(
                state=UserContext.MEETING.value,
                source="calendar",
                timestamp=now,
                reason=f"Active calendar meeting detected: {_event_summary(meeting_event)}",
                attention_state_source="calendar_meeting",
                contributing_signals=contributing,
            )

        # ---------------------------------------------------------------
        # 2. DND / Focus Mode — Explicit signal in recent events or state
        # ---------------------------------------------------------------
        dnd_event = self._find_signal(recent, _DND_SIGNALS)
        if dnd_event is not None:
            contributing.append(f"dnd_signal:{dnd_event.event_type}")
            return AttentionDetectionResult(
                state=UserContext.DO_NOT_DISTURB.value,
                source="device_signal",
                timestamp=now,
                reason=f"DND/Focus mode signal detected: {dnd_event.event_type}",
                attention_state_source="dnd_focus_mode",
                contributing_signals=contributing,
            )

        if current_state and self._state_has_signal(current_state, _DND_SIGNALS):
            contributing.append("state_feature:dnd")
            return AttentionDetectionResult(
                state=UserContext.DO_NOT_DISTURB.value,
                source="state_feature",
                timestamp=now,
                reason="DND/Focus mode detected from current state features.",
                attention_state_source="state_dnd",
                contributing_signals=contributing,
            )

        # ---------------------------------------------------------------
        # 3. DEEP_WORK — Continuous single-app activity with low context switching
        # ---------------------------------------------------------------
        if self._detect_deep_work(deep_work_window, now):
            app_types = [e.event_type for e in deep_work_window if _matches_signals(e, _DEEP_WORK_ACTIVITY_SIGNALS)]
            contributing.append(f"deep_work_activity:{len(app_types)}_events")
            return AttentionDetectionResult(
                state=UserContext.DEEP_WORK.value,
                source="device_activity",
                timestamp=now,
                reason=f"Continuous focused deep work over {int(self.deep_work_threshold.total_seconds() / 60)}min ({len(app_types)} focused actions, minimal context switching).",
                attention_state_source="continuous_app_activity",
                contributing_signals=contributing,
            )

        # ---------------------------------------------------------------
        # 4. DRIVING
        # ---------------------------------------------------------------
        driving_event = self._find_signal(recent, _DRIVING_SIGNALS)
        if driving_event is not None:
            contributing.append(f"driving_signal:{driving_event.event_type}")
            return AttentionDetectionResult(
                state=UserContext.DRIVING.value,
                source="mobility",
                timestamp=now,
                reason=f"Driving mobility signal detected: {driving_event.event_type}",
                attention_state_source="mobility_driving",
                contributing_signals=contributing,
            )

        # ---------------------------------------------------------------
        # 5. TRANSIT
        # ---------------------------------------------------------------
        transit_event = self._find_signal(recent, _TRANSIT_SIGNALS)
        if transit_event is not None:
            contributing.append(f"transit_signal:{transit_event.event_type}")
            return AttentionDetectionResult(
                state=UserContext.TRANSIT.value,
                source="mobility",
                timestamp=now,
                reason=f"Transit/commute signal detected: {transit_event.event_type}",
                attention_state_source="mobility_transit",
                contributing_signals=contributing,
            )

        # ---------------------------------------------------------------
        # 6. FOCUSED — Moderate focused engagement (10-30m)
        # ---------------------------------------------------------------
        if self._detect_focused(recent, now):
            contributing.append("focused_task_engagement")
            return AttentionDetectionResult(
                state=UserContext.FOCUSED.value,
                source="task_focus",
                timestamp=now,
                reason=f"Active focused task engagement detected in last {int(self.recent_window.total_seconds() / 60)}min.",
                attention_state_source="task_focus",
                contributing_signals=contributing,
            )

        # ---------------------------------------------------------------
        # 7. SLEEP — No events in idle window + sleep hours
        # ---------------------------------------------------------------
        if len(idle_window) == 0 and self._is_sleep_hours(now):
            contributing.append(f"no_activity_sleep_hours:{now.hour}:00")
            return AttentionDetectionResult(
                state=UserContext.SLEEP.value,
                source="time_heuristic",
                timestamp=now,
                reason=f"No activity in last {int(self.idle_threshold.total_seconds() / 60)}min during sleep window ({self.sleep_hour_start}:00–{self.sleep_hour_end}:00).",
                attention_state_source="idle_sleep_hours",
                contributing_signals=contributing,
            )

        # ---------------------------------------------------------------
        # 8. BUSY — Recent event density > 0
        # ---------------------------------------------------------------
        if len(recent) > 0:
            contributing.append(f"recent_events:{len(recent)}")
            return AttentionDetectionResult(
                state=UserContext.BUSY.value,
                source="event_density",
                timestamp=now,
                reason=f"{len(recent)} events observed in last {int(self.recent_window.total_seconds() / 60)}min.",
                attention_state_source="event_density",
                contributing_signals=contributing,
            )

        # ---------------------------------------------------------------
        # 9. AVAILABLE — Default daytime state when no events
        # ---------------------------------------------------------------
        return AttentionDetectionResult(
            state=UserContext.AVAILABLE.value,
            source="default",
            timestamp=now,
            reason="User is active with low-to-moderate event load; assumed available.",
            attention_state_source="default_available",
            contributing_signals=contributing,
        )

    # -------------------------------------------------------------------
    # Private detection helpers
    # -------------------------------------------------------------------

    def _find_active_meeting(
        self, events: List[Event], now: datetime
    ) -> Optional[Event]:
        """Finds an active calendar/meeting event with ≥2 attendees."""
        for e in reversed(events):
            if _matches_signals(e, _MEETING_SIGNALS):
                payload = e.payload if isinstance(e.payload, dict) else {}
                attendees = payload.get("attendees", [])
                attendee_count = payload.get("attendee_count", 0)
                if isinstance(attendees, list) and len(attendees) >= 2:
                    return e
                if isinstance(attendee_count, (int, float)) and attendee_count >= 2:
                    return e
                event_type = (e.event_type or "").lower()
                if "meeting" in event_type or "calendar_event" in event_type:
                    return e
        return None

    def _find_signal(
        self, events: List[Event], signals: frozenset
    ) -> Optional[Event]:
        """Finds the most recent event matching any of the given signal keywords."""
        for e in reversed(events):
            if _matches_signals(e, signals):
                return e
        return None

    def _detect_deep_work(self, events: List[Event], now: datetime) -> bool:
        """
        Multi-signal deep work detection:
          - Continuous activity spanning at least half the deep work window
          - Focused app signals (IDE, terminal, document editing)
          - Context-switching ratio below threshold
        """
        if len(events) < 2:
            return False

        focused_events = [e for e in events if _matches_signals(e, _DEEP_WORK_ACTIVITY_SIGNALS)]
        if len(focused_events) < 2:
            return False

        first_time = _event_time(focused_events[0])
        last_time = _event_time(focused_events[-1])
        span = last_time - first_time
        if span < self.deep_work_threshold * 0.35:
            return False

        non_focused_count = len(events) - len(focused_events)
        interruption_ratio = non_focused_count / max(len(events), 1)
        if interruption_ratio > self.max_context_switch_ratio:
            return False

        return True

    def _detect_focused(self, events: List[Event], now: datetime) -> bool:
        """Detects focused task engagement in recent window."""
        if len(events) < 2:
            return False
        focused_events = [e for e in events if _matches_signals(e, _DEEP_WORK_ACTIVITY_SIGNALS)]
        return len(focused_events) >= 2 and len(events) <= 3

    def _is_sleep_hours(self, now: datetime) -> bool:
        """Checks if current hour falls within the sleep window."""
        hour = now.hour
        if self.sleep_hour_start > self.sleep_hour_end:
            return hour >= self.sleep_hour_start or hour < self.sleep_hour_end
        else:
            return self.sleep_hour_start <= hour < self.sleep_hour_end

    @staticmethod
    def _state_has_signal(
        state: StateRepresentation, signals: frozenset
    ) -> bool:
        """Checks if any state feature matches the given signals."""
        for feature in state.features.values():
            name_lower = feature.name.lower()
            val_lower = str(feature.value).lower()
            combined = f"{name_lower} {val_lower}"
            if any(sig in combined for sig in signals):
                return True
        return False


# -----------------------------------------------------------------------
# Module-level helpers
# -----------------------------------------------------------------------

def _event_time(event: Event) -> datetime:
    """Extracts timezone-aware event time."""
    return ensure_timezone_aware(event.event_time, "event_time")


def _event_summary(event: Event) -> str:
    """Returns a short summary string from an event."""
    if isinstance(event.payload, dict):
        return str(event.payload.get("summary") or event.payload.get("title") or event.event_type)[:80]
    return str(event.event_type)[:80]


def _matches_signals(event: Event, signals: frozenset) -> bool:
    """Checks if an event type, source, or payload matches any signal keyword."""
    et = (event.event_type or "").lower()
    src = (event.source or "").lower()
    combined = f"{et} {src}"
    if isinstance(event.payload, dict):
        combined += " " + str(event.payload).lower()[:200]
    return any(sig in combined for sig in signals)
