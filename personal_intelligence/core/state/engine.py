"""
Deterministic StateEngine for extracting and updating Personal State Representations.
Derived purely from TimelineEngine, EventStore, and GoalStore without LLMs, embeddings, or ML.

Domain-Neutral Design
---------------------
StateEngine computes deterministic representations from whatever personal signals are
available in the event log. It imposes NO architectural assumptions about the domain of
those signals. Any of the following signal types (and others not yet imagined) are treated
uniformly:

    - Communication signals   (email, messages, meeting notes)
    - Calendar / schedule     (events, deadlines, availability)
    - Document signals        (edits, reviews, approvals)
    - Productivity signals    (tasks, focus blocks, output)
    - Routine signals         (sleep, exercise, travel — as optional custom extractors)
    - Biometric signals       (optional, registered via register_extractor())
    - Financial signals       (optional, registered via register_extractor())
    - Any future domain

Built-in feature dimensions computed from a generic event stream:
    1. time_of_day              — fractional hour + temporal bucket (clock)
    2. recent_context_signal    — most-recent observable context value from any event
    3. active_signal_type       — most-recent observation type from any event
    4. event_density            — observation arrival rate over last 60 minutes
    5. recent_activity_duration — continuous-event-type span duration in minutes
    6. routine_deviation        — short-term vs 24h density divergence metric
    7. goal_pressure            — weighted active goal count and priority
    8. commitment_load          — count of open commitment-type observations in 24h
    9. communication_activity   — count of communication-source observations in 24h

Biometric features (sleep quality, heart rate, HRV, etc.) must be registered as optional
custom extractors via register_extractor(), not baked into built-in dimensions.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from personal_intelligence.core.events.models import ensure_timezone_aware
from personal_intelligence.core.goals.models import GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.state.models import StateFeature, StateRepresentation
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.timeline.models import Timeline


# Event types that indicate a potential open commitment in any domain
_COMMITMENT_SIGNAL_TYPES = frozenset({
    "email_received", "possible_commitment", "unresolved_action",
    "calendar_event", "upcoming_milestone", "conflicting_commitments",
    "document_changed", "meeting_decision", "goal_signal",
    "action_item", "task_created", "deadline_detected",
})

# Source names that indicate communication-domain observations
_COMMUNICATION_SOURCES = frozenset({"gmail", "meet", "calendar", "chat", "slack", "email"})


class StateEngine:
    """
    Deterministic engine that computes the multi-dimensional StateRepresentation
    of the user from underlying event logs and active goals.

    Fully domain-neutral: operates on any personal signal present in the event log.
    Biometric and domain-specific signals are supported as optional registered extractors.
    """

    def __init__(
        self,
        timeline_engine: TimelineEngine,
        goal_store: Optional[GoalStore] = None,
    ) -> None:
        self.timeline_engine = timeline_engine
        self.goal_store = goal_store
        self._custom_extractors: Dict[str, Callable[[Timeline, Optional[GoalStore], datetime], StateFeature]] = {}

    def register_extractor(
        self,
        name: str,
        extractor_fn: Callable[[Timeline, Optional[GoalStore], datetime], StateFeature],
    ) -> None:
        """
        Registers a custom feature extractor for extensible state dimension generation.

        Use this to add domain-specific signals such as:
            - biometric signals (sleep_quality, heart_rate_variability)
            - financial signals (spending_rate, budget_pressure)
            - travel signals   (transit_status, trip_duration)
            - any other personal domain

        The extractor_fn receives (timeline_24h, goal_store, reference_time) and must
        return a single StateFeature with a unique name.
        """
        if not callable(extractor_fn):
            raise ValueError("extractor_fn must be callable.")
        self._custom_extractors[name] = extractor_fn

    def compute_current_state(
        self,
        reference_time: Optional[datetime] = None,
        subject_id: Optional[str] = None,
    ) -> StateRepresentation:
        """
        Computes the complete, deterministic StateRepresentation as of reference_time.

        Built-in dimensions (9 total) are computed from whatever observations exist in
        the event log — no specific signal domain is assumed or required.

        Optional domain-specific extractors are evaluated after built-ins.
        """
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        # Fetch recent timeline context (last 24 hours for broad context)
        timeline_24h = self.timeline_engine.get_last_n_hours(24, reference_time=ref_dt, subject_id=subject_id)
        # Fetch last 1 hour for high-resolution density calculations
        timeline_1h = self.timeline_engine.get_last_n_minutes(60, reference_time=ref_dt, subject_id=subject_id)

        rep = StateRepresentation(timestamp=ref_dt)

        # 1. time_of_day — always computable from clock
        rep.set_feature(*self._extract_time_of_day(ref_dt))

        # 2. recent_context_signal — most-recent context key from any event
        rep.set_feature(*self._extract_recent_context_signal(timeline_24h, ref_dt))

        # 3. active_signal_type — most-recent observation type from any event
        rep.set_feature(*self._extract_active_signal_type(timeline_24h, ref_dt))

        # 4. event_density — observation rate over last 60 minutes
        rep.set_feature(*self._extract_event_density(timeline_1h, ref_dt))

        # 5. recent_activity_duration — continuous span of current signal type
        rep.set_feature(*self._extract_activity_duration(timeline_24h, ref_dt))

        # 6. routine_deviation — density divergence metric
        rep.set_feature(*self._extract_routine_deviation(timeline_24h, timeline_1h, ref_dt))

        # 7. goal_pressure — weighted active goal count and priority
        rep.set_feature(*self._extract_goal_pressure(ref_dt))

        # 8. commitment_load — open commitment-type observations in 24h
        rep.set_feature(*self._extract_commitment_load(timeline_24h, ref_dt))

        # 9. communication_activity — communication-source observations in 24h
        rep.set_feature(*self._extract_communication_activity(timeline_24h, ref_dt))

        # 10+. Optional domain-specific custom extractors
        for custom_name, extractor in self._custom_extractors.items():
            feat = extractor(timeline_24h, self.goal_store, ref_dt)
            rep.features[feat.name] = feat

        return rep

    def rebuild_state(
        self,
        as_of: Optional[datetime] = None,
        subject_id: Optional[str] = None,
    ) -> StateRepresentation:
        """
        Deterministically recalculates and rebuilds the complete StateRepresentation
        from the underlying event log after event deletions, source purges, or retention pruning.
        Guarantees zero stale state retention.
        """
        return self.compute_current_state(reference_time=as_of, subject_id=subject_id)

    # -------------------------------------------------------------------------
    # Built-in Deterministic Extractors (Domain-Neutral)
    # -------------------------------------------------------------------------

    def _extract_time_of_day(self, ref_dt: datetime) -> tuple:
        """Computes fractional hour and temporal day bucket from the system clock."""
        local_dt = ref_dt.astimezone(timezone.utc)
        hour_frac = local_dt.hour + (local_dt.minute / 60.0) + (local_dt.second / 3600.0)
        hour_val = round(hour_frac, 2)

        if 5.0 <= hour_val < 12.0:
            bucket = "morning"
        elif 12.0 <= hour_val < 17.0:
            bucket = "afternoon"
        elif 17.0 <= hour_val < 21.0:
            bucket = "evening"
        else:
            bucket = "night"

        return (
            "time_of_day",
            {"hour": hour_val, "bucket": bucket},
            "clock",
            ref_dt,
            1.0,
            {"hour_fraction": hour_val, "bucket": bucket},
        )

    def _extract_recent_context_signal(self, timeline: Timeline, ref_dt: datetime) -> tuple:
        """
        Extracts the most-recent context value from any timeline event.

        Scans the most-recent event for any of these generic context keys:
            context, topic, project, status, location, place, room, city, app, domain

        Domain-neutral: does NOT reference GPS or device-specific event types.
        Any observation that carries any of these keys contributes to this dimension.
        """
        context_keys = ("context", "topic", "project", "status", "location",
                        "place", "room", "city", "app", "domain")
        context_value = "unknown"
        signal_time = ref_dt
        confidence = 0.5
        source = "default_fallback"

        for evt in reversed(timeline.events):
            for key in context_keys:
                if key in evt.payload:
                    context_value = str(evt.payload[key])
                    signal_time = evt.event_time
                    confidence = evt.confidence
                    source = f"event:{evt.id}"
                    break
            else:
                continue
            break

        return (
            "recent_context_signal",
            context_value,
            source,
            signal_time,
            confidence,
            {"context_key_value": context_value},
        )

    def _extract_active_signal_type(self, timeline: Timeline, ref_dt: datetime) -> tuple:
        """
        Extracts the most-recent observation type from timeline events.

        Scans backwards for explicit activity/signal descriptors in event payloads,
        or uses the event_type field of the most recent event as fallback.
        Falls back to 'idle' when the timeline is empty.

        Domain-neutral: works equally for calendar, document, communication, or any
        other observation type stored in the event log.
        """
        if timeline.is_empty:
            return (
                "active_signal_type",
                "idle",
                "default_fallback",
                ref_dt,
                0.5,
                {"signal_type": "idle"},
            )

        activity_keys = ("activity", "signal_type", "app", "action", "task")
        for evt in reversed(timeline.events):
            for key in activity_keys:
                if key in evt.payload and evt.payload[key]:
                    act_val = str(evt.payload[key])
                    return (
                        "active_signal_type",
                        act_val,
                        f"event:{evt.id}",
                        evt.event_time,
                        evt.confidence,
                        {"signal_type": act_val},
                    )

        latest = timeline.events[-1]
        signal_type = latest.payload.get("activity") or latest.payload.get("signal_type") or latest.event_type
        confidence = latest.confidence
        source = f"event:{latest.id}"

        return (
            "active_signal_type",
            str(signal_type),
            source,
            latest.event_time,
            confidence,
            {"signal_type": str(signal_type)},
        )

    def _extract_event_density(self, timeline_1h: Timeline, ref_dt: datetime) -> tuple:
        """Calculates observation arrival rate (events/minute) over the last 60 minutes."""
        count = len(timeline_1h)
        density_per_min = round(count / 60.0, 3)
        return (
            "event_density",
            density_per_min,
            "timeline_last_60m",
            ref_dt,
            1.0,
            {"events_in_last_hour": count, "rate_per_minute": density_per_min},
        )

    def _extract_activity_duration(self, timeline: Timeline, ref_dt: datetime) -> tuple:
        """
        Calculates duration in minutes of the current continuous signal-type episode.

        Walks back the timeline counting contiguous events sharing the same signal type.
        Domain-neutral: works for any event type in the observation log.
        """
        if timeline.is_empty:
            return (
                "recent_activity_duration",
                0.0,
                "timeline_activity_span",
                ref_dt,
                1.0,
                {"duration_minutes": 0.0},
            )

        latest = timeline.events[-1]
        curr_type = latest.payload.get("activity") or latest.payload.get("signal_type") or latest.event_type

        first_contiguous_time = latest.event_time
        for evt in reversed(timeline.events):
            sig = evt.payload.get("activity") or evt.payload.get("signal_type") or evt.event_type
            if sig == curr_type:
                first_contiguous_time = evt.event_time
            else:
                break

        payload_dur = 0.0
        if "duration_minutes" in latest.payload:
            try:
                payload_dur = float(latest.payload.get("duration_minutes", 0.0))
            except (ValueError, TypeError):
                payload_dur = 0.0

        duration_sec = max(0.0, (ref_dt - first_contiguous_time).total_seconds())
        duration_min = max(payload_dur, round(duration_sec / 60.0, 1))

        return (
            "recent_activity_duration",
            duration_min,
            "timeline_activity_span",
            ref_dt,
            1.0,
            {"duration_minutes": duration_min, "activity": curr_type},
        )

    def _extract_routine_deviation(
        self,
        timeline_24h: Timeline,
        timeline_1h: Timeline,
        ref_dt: datetime,
    ) -> tuple:
        """
        Computes a deterministic baseline divergence metric in [0.0, 1.0].
        Compares short-term (1h) observation density against the 24h average observation rate.

        Domain-neutral: works with any mix of observation types.
        A score near 0.0 = activity in line with recent baseline.
        A score near 1.0 = significant deviation from baseline (unusually high or low).
        """
        if len(timeline_24h) == 0:
            return (
                "routine_deviation",
                0.0,
                "heuristic_density_divergence",
                ref_dt,
                0.5,
                {"deviation_score": 0.0, "reason": "no_prior_events"},
            )

        avg_per_hour = max(0.1, len(timeline_24h) / 24.0)
        recent_in_1h = len(timeline_1h)

        ratio = recent_in_1h / avg_per_hour
        if ratio >= 1.0:
            deviation = min(1.0, round((ratio - 1.0) / 4.0, 3))
        else:
            deviation = min(1.0, round(1.0 - ratio, 3))

        return (
            "routine_deviation",
            deviation,
            "heuristic_density_divergence",
            ref_dt,
            0.85,
            {"recent_1h_count": recent_in_1h, "avg_per_hour": round(avg_per_hour, 2), "ratio": round(ratio, 2)},
        )

    def _extract_goal_pressure(self, ref_dt: datetime) -> tuple:
        """Calculates weighted goal pressure score from active goals in GoalStore."""
        if not self.goal_store:
            return (
                "goal_pressure",
                {"active_goal_count": 0, "pressure_score": 0.0},
                "goal_store_none",
                ref_dt,
                1.0,
                {},
            )

        active_goals = self.goal_store.list_active_goals()
        weights = {
            GoalPriority.CRITICAL.value: 3.0,
            GoalPriority.HIGH.value: 2.0,
            GoalPriority.MEDIUM.value: 1.0,
            GoalPriority.LOW.value: 0.5,
            GoalPriority.BACKGROUND.value: 0.2,
        }

        total_score = 0.0
        critical_count = 0
        for g in active_goals:
            p_val = g.priority.lower() if isinstance(g.priority, str) else g.priority.value
            weight = weights.get(p_val, 1.0)
            total_score += weight
            if p_val == GoalPriority.CRITICAL.value:
                critical_count += 1

        val = {
            "active_goal_count": len(active_goals),
            "pressure_score": round(total_score, 2),
            "critical_goal_count": critical_count,
        }

        return (
            "goal_pressure",
            val,
            "goal_store",
            ref_dt,
            1.0,
            {"active_goals": [g.name for g in active_goals]},
        )

    def _extract_commitment_load(self, timeline_24h: Timeline, ref_dt: datetime) -> tuple:
        """
        Counts observations in the last 24h whose event_type indicates an open commitment.

        Domain-neutral: counts across all commitment-type observations regardless of source
        domain (calendar, email, documents, tasks, etc.).

        High commitment_load indicates the user may have many pending items to address.
        """
        commitment_count = sum(
            1 for evt in timeline_24h.events
            if evt.event_type in _COMMITMENT_SIGNAL_TYPES
            or evt.payload.get("observation_type") in _COMMITMENT_SIGNAL_TYPES
        )

        return (
            "commitment_load",
            commitment_count,
            "timeline_commitment_scan",
            ref_dt,
            1.0,
            {"commitment_observation_count": commitment_count, "window_hours": 24},
        )

    def _extract_communication_activity(self, timeline_24h: Timeline, ref_dt: datetime) -> tuple:
        """
        Counts observations in the last 24h sourced from communication domains.

        Domain-neutral: counts across email (gmail), video (meet), calendar, messaging,
        or any future communication source added to the observation layer.

        High communication_activity indicates active interpersonal engagement.
        """
        comm_count = sum(
            1 for evt in timeline_24h.events
            if evt.source in _COMMUNICATION_SOURCES
        )

        return (
            "communication_activity",
            comm_count,
            "timeline_communication_scan",
            ref_dt,
            1.0,
            {"communication_observation_count": comm_count, "window_hours": 24},
        )



