"""
Personal Learning Engine.
Discovers empirical personal patterns, behavioral regularities, world rhythms, and interaction preferences
from observations, reasoning episodes, recommendations, user responses, and outcomes.

STRICT RULE: Strictly non-causal associations only (Never claiming causation).
Represents newly discovered patterns as hypotheses first.
Manages 7-stage lifecycle:
  OBSERVED -> HYPOTHESIS -> EMERGING -> SUPPORTED -> ACTIVE -> DECAYING -> INACTIVE (with recovery).
Every learned pattern explicitly references supporting and contradicting reasoning episodes.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from personal_intelligence.core.episodes.models import (
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.events.models import (
    Event,
    ensure_timezone_aware,
)
from personal_intelligence.core.patterns.models import (
    EvidenceObservationType,
    Pattern,
    PatternEvidence,
    PatternStatus,
    PatternType,
)
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.storage.db import DatabaseManager


class LearningEngine:
    """
    Empirical learning engine discovering recurring personal associations without causal claims.
    Tracks supporting and contradictory evidence through a 7-stage promotion lifecycle with recency decay.
    """

    def __init__(
        self,
        pattern_store: Optional[PatternStore] = None,
        db_manager: Optional[DatabaseManager] = None,
        decay_after_days: int = 60,
        inactivate_after_days: int = 120,
    ) -> None:
        self.pattern_store = pattern_store or PatternStore(db_manager=db_manager)
        self.decay_after_days = decay_after_days
        self.inactivate_after_days = inactivate_after_days

    # -------------------------------------------------------------------------
    # Core Pattern Registration & Evidence Tracking
    # -------------------------------------------------------------------------

    def register_candidate_pattern(
        self,
        description: str,
        first_seen: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        initial_status: PatternStatus = PatternStatus.HYPOTHESIS,
        pattern_type: Union[PatternType, str] = PatternType.BEHAVIORAL_PATTERN,
    ) -> Pattern:
        """
        Registers a new candidate association pattern. Enforces non-causal description.
        By default initializes as HYPOTHESIS (hypothesis-first representation).
        """
        now = datetime.now(timezone.utc)
        f_seen = ensure_timezone_aware(first_seen or now, "first_seen")
        p_type_val = pattern_type.value if hasattr(pattern_type, "value") else str(pattern_type).strip().upper()

        # Sanitize description to ensure non-causal phrasing
        clean_desc = self._sanitize_non_causal_phrasing(description)

        meta = dict(metadata or {})
        meta["pattern_type"] = p_type_val
        if "supporting_episodes" not in meta:
            meta["supporting_episodes"] = []
        if "contradicting_episodes" not in meta:
            meta["contradicting_episodes"] = []

        return self.pattern_store.create_pattern(
            description=clean_desc,
            first_seen=f_seen,
            last_seen=f_seen,
            support_count=1,
            contradiction_count=0,
            evidence_strength="weak",
            status=initial_status.value,
            metadata=meta,
            pattern_type=p_type_val,
        )

    def record_evidence(
        self,
        pattern_id: str,
        observation_type: Union[EvidenceObservationType, str],
        observed_at: Optional[datetime] = None,
        episode_id: Optional[str] = None,
        event_ids: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Pattern, PatternEvidence]:
        """
        Records supporting or contradictory evidence for a pattern and evaluates progression/recovery.
        Explicitly tracks episode provenance in pattern metadata and evidence store.
        """
        pattern = self.pattern_store.get_pattern(pattern_id)
        if pattern is None:
            raise ValueError(f"Pattern with id '{pattern_id}' not found.")

        obs_dt = ensure_timezone_aware(observed_at or datetime.now(timezone.utc), "observed_at")
        obs_type = observation_type.value if isinstance(observation_type, EvidenceObservationType) else str(observation_type).strip().upper()

        if obs_type not in (EvidenceObservationType.SUPPORT.value, EvidenceObservationType.CONTRADICTION.value):
            raise ValueError(f"Invalid observation type '{obs_type}'. Must be SUPPORT or CONTRADICTION.")

        # 1. Add evidence record (historical evidence is permanently preserved)
        evidence = self.pattern_store.add_evidence(
            pattern_id=pattern_id,
            observation_type=obs_type,
            observed_at=obs_dt,
            episode_id=episode_id,
            event_ids=event_ids,
            details=details,
        )

        # 2. Update pattern counts, recency, and episode provenance pointers
        if obs_type == EvidenceObservationType.SUPPORT.value:
            pattern.support_count += 1
            if episode_id and episode_id not in pattern.supporting_episodes:
                if "supporting_episodes" not in pattern.metadata:
                    pattern.metadata["supporting_episodes"] = []
                pattern.metadata["supporting_episodes"].append(episode_id)
            if event_ids:
                if "source_observations" not in pattern.metadata:
                    pattern.metadata["source_observations"] = []
                for eid in event_ids:
                    if eid not in pattern.metadata["source_observations"]:
                        pattern.metadata["source_observations"].append(eid)
        else:
            pattern.contradiction_count += 1
            if episode_id and episode_id not in pattern.contradicting_episodes:
                if "contradicting_episodes" not in pattern.metadata:
                    pattern.metadata["contradicting_episodes"] = []
                pattern.metadata["contradicting_episodes"].append(episode_id)
            if event_ids:
                if "contradicting_event_ids" not in pattern.metadata:
                    pattern.metadata["contradicting_event_ids"] = []
                for eid in event_ids:
                    if eid not in pattern.metadata["contradicting_event_ids"]:
                        pattern.metadata["contradicting_event_ids"].append(eid)

        if obs_dt > pattern.last_seen:
            pattern.last_seen = obs_dt
        if obs_dt < pattern.first_seen:
            pattern.first_seen = obs_dt

        # 3. Evaluate lifecycle progression & evidence strength (as of observation time)
        new_status, new_strength = self.evaluate_progression(pattern, as_of=obs_dt)
        pattern.status = new_status.value
        pattern.evidence_strength = new_strength

        # 4. Persist updated pattern
        updated = self.pattern_store.update_pattern(pattern)
        return (updated or pattern, evidence)

    # -------------------------------------------------------------------------
    # 7-Stage Lifecycle Evaluation & Recency Decay
    # -------------------------------------------------------------------------

    def evaluate_progression(
        self,
        pattern: Pattern,
        as_of: Optional[datetime] = None,
        recent_evidence_window_days: float = 14.0,
    ) -> Tuple[PatternStatus, str]:
        """
        Evaluates stage transitions, recency decay, and evidence strength across the 7 stages
        according to strict deterministic V1.2 rules:
          OBSERVED -> HYPOTHESIS -> EMERGING -> SUPPORTED -> ACTIVE -> DECAYING -> INACTIVE.
        """
        now = ensure_timezone_aware(as_of or datetime.now(timezone.utc), "as_of")
        days_since_last_seen = max(0.0, (now - pattern.last_seen).total_seconds() / 86400.0)
        time_span_days = max(0.0, (pattern.last_seen - pattern.first_seen).total_seconds() / 86400.0)

        support = pattern.support_count
        contra = pattern.contradiction_count
        total = support + contra

        if total == 0:
            return PatternStatus.OBSERVED, "weak"

        contra_rate = contra / total if total > 0 else 0.0
        current = pattern.status.upper()

        # 1. Temporal Inactivity: Prolonged silence (>= 120 days) -> INACTIVE
        if days_since_last_seen >= self.inactivate_after_days:
            return PatternStatus.INACTIVE, "weak"

        # 2. High Contradiction Rate (> 50%)
        if contra_rate >= 0.50 and total >= 3:
            if current in (PatternStatus.ACTIVE.value, PatternStatus.SUPPORTED.value, PatternStatus.EMERGING.value, PatternStatus.DECAYING.value):
                return PatternStatus.DECAYING, "weak"
            return PatternStatus.HYPOTHESIS, "weak"

        # 3. Recency Decay Gate: Silence >= 60 days on active/supported pattern -> DECAYING
        if days_since_last_seen >= self.decay_after_days:
            if current in (PatternStatus.ACTIVE.value, PatternStatus.SUPPORTED.value, PatternStatus.EMERGING.value):
                return PatternStatus.DECAYING, "moderate" if contra_rate < 0.20 else "weak"

        # Evidence Strength Calculation
        if support >= 10 and contra_rate < 0.20:
            strength = "strong"
        elif support >= 3 and contra_rate < 0.30:
            strength = "moderate"
        else:
            strength = "weak"

        # 4. Recovery Gates from DECAYING or INACTIVE
        if current == PatternStatus.INACTIVE.value:
            if days_since_last_seen < self.decay_after_days and contra_rate < 0.30:
                if support >= 10 and time_span_days >= 45 and contra_rate < 0.20:
                    return PatternStatus.ACTIVE, "strong"
                if support >= 6 and time_span_days >= 21 and contra_rate < 0.20:
                    return PatternStatus.SUPPORTED, "strong"
                if support >= 3 and time_span_days >= 7 and contra_rate < 0.50:
                    return PatternStatus.EMERGING, "moderate"
                return PatternStatus.HYPOTHESIS, "weak"
            return PatternStatus.INACTIVE, strength

        if current == PatternStatus.DECAYING.value:
            if days_since_last_seen < recent_evidence_window_days and contra_rate < 0.20:
                if support >= 10 and time_span_days >= 45:
                    return PatternStatus.ACTIVE, "strong"
                if support >= 6 and time_span_days >= 21:
                    return PatternStatus.SUPPORTED, "strong"
                if support >= 3 and time_span_days >= 7:
                    return PatternStatus.EMERGING, "moderate"
            return PatternStatus.DECAYING, strength

        # 5. Progressive Promotion Gates (V1.2 Deterministic Rules)
        # ACTIVE: support >= 10, span >= 45 days, contra < 20%, recent evidence within window
        if (
            support >= 10
            and time_span_days >= 45.0
            and contra_rate < 0.20
            and days_since_last_seen <= recent_evidence_window_days
        ):
            return PatternStatus.ACTIVE, "strong"

        # SUPPORTED: support >= 6, span >= 21 days, contra < 20%
        if (
            support >= 6
            and time_span_days >= 21.0
            and contra_rate < 0.20
            and days_since_last_seen < self.decay_after_days
        ):
            return PatternStatus.SUPPORTED, "strong"

        # EMERGING: support >= 3, span >= 7 days, contra < 50%
        if (
            support >= 3
            and time_span_days >= 7.0
            and contra_rate < 0.50
        ):
            return PatternStatus.EMERGING, "moderate"

        # HYPOTHESIS: support >= 1
        if support >= 1:
            return PatternStatus.HYPOTHESIS, "weak"

        # OBSERVED
        return PatternStatus.OBSERVED, "weak"

    def apply_recency_decay(
        self,
        as_of: Optional[datetime] = None,
    ) -> List[Pattern]:
        """
        Sweeps all stored patterns and applies recency-aware temporal decay.
        Demotes stale patterns (ACTIVE/SUPPORTED -> DECAYING -> INACTIVE).
        Does NOT delete historical evidence.
        """
        now = ensure_timezone_aware(as_of or datetime.now(timezone.utc), "as_of")
        all_patterns = self.pattern_store.list_patterns(limit=500)
        updated_patterns: List[Pattern] = []

        for pat in all_patterns:
            orig_status = pat.status
            orig_strength = pat.evidence_strength

            new_status, new_strength = self.evaluate_progression(pat, as_of=now)
            if new_status.value != orig_status or new_strength != orig_strength:
                pat.status = new_status.value
                pat.evidence_strength = new_strength
                persisted = self.pattern_store.update_pattern(pat)
                if persisted:
                    updated_patterns.append(persisted)

        return updated_patterns

    # -------------------------------------------------------------------------
    # 1. World Pattern Discovery
    # -------------------------------------------------------------------------

    def discover_world_patterns(
        self,
        events: List[Event],
        timeline: Optional[Any] = None,
    ) -> List[Pattern]:
        """
        Discovers WORLD PATTERNS from environmental observations, calendar density regularities,
        and temporal rhythms across the user's external environment.
        """
        discovered: List[Pattern] = []
        if not events:
            return discovered

        # 1. Day-of-week meeting density regularities
        day_events: Dict[int, List[Event]] = defaultdict(list)
        for ev in events:
            day_events[ev.event_time.weekday()].append(ev)

        day_names = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
        for weekday, ev_list in day_events.items():
            calendar_evs = [e for e in ev_list if "calendar" in e.source or "meeting" in e.event_type]
            if len(calendar_evs) >= 3:
                day_name = day_names[weekday]
                desc = f"{day_name} frequently exhibit elevated calendar and meeting density."
                pat = self._upsert_pattern(
                    description=desc,
                    pattern_type=PatternType.WORLD_PATTERN,
                    supporting_episodes=[],
                    contradicting_episodes=[],
                    supporting_event_ids=[e.id for e in calendar_evs],
                    first_seen=min(e.event_time for e in calendar_evs),
                    last_seen=max(e.event_time for e in calendar_evs),
                    metadata={
                        "dimension": "weekday_density",
                        "weekday": weekday,
                        "observation_count": len(calendar_evs),
                    },
                )
                discovered.append(pat)

        # 2. Cross-source coordination regularities (e.g. Drive doc changes before Calendar reviews)
        drive_evs = [e for e in events if "drive" in e.source or "document" in e.event_type]
        review_evs = [e for e in events if "calendar" in e.source and "review" in str(e.payload).lower()]

        if len(drive_evs) >= 2 and len(review_evs) >= 1:
            # Check if drive events occur within 48h prior to review events
            co_occurrences = []
            for rev in review_evs:
                prior_drive = [
                    d for d in drive_evs
                    if 0 < (rev.event_time - d.event_time).total_seconds() <= 172800
                ]
                if prior_drive:
                    co_occurrences.extend(prior_drive)

            if len(co_occurrences) >= 2:
                desc = "Calendar review events are frequently preceded by Google Drive document modifications."
                pat = self._upsert_pattern(
                    description=desc,
                    pattern_type=PatternType.WORLD_PATTERN,
                    supporting_episodes=[],
                    contradicting_episodes=[],
                    supporting_event_ids=[e.id for e in co_occurrences],
                    first_seen=min(e.event_time for e in co_occurrences),
                    last_seen=max(e.event_time for e in co_occurrences),
                    metadata={
                        "dimension": "cross_source_coordination",
                        "co_occurrence_count": len(co_occurrences),
                    },
                )
                discovered.append(pat)

        # 3. Project communication bursts (repeated communication events clustered around specific projects)
        project_events: Dict[str, List[Event]] = defaultdict(list)
        for ev in events:
            proj = None
            if isinstance(ev.payload, dict):
                proj = ev.payload.get("project") or ev.payload.get("project_name") or ev.payload.get("topic")
            if not proj and ev.subject_id and ev.subject_id.startswith(("proj_", "project_", "prj_")):
                proj = ev.subject_id
            if proj:
                project_events[str(proj)].append(ev)

        for proj_name, p_evs in project_events.items():
            if len(p_evs) >= 3:
                desc = f"Project '{proj_name}' frequently generates repeated communication bursts."
                pat = self._upsert_pattern(
                    description=desc,
                    pattern_type=PatternType.WORLD_PATTERN,
                    supporting_episodes=[],
                    contradicting_episodes=[],
                    supporting_event_ids=[e.id for e in p_evs],
                    first_seen=min(e.event_time for e in p_evs),
                    last_seen=max(e.event_time for e in p_evs),
                    metadata={
                        "dimension": "project_communication_burst",
                        "project": proj_name,
                        "burst_event_count": len(p_evs),
                    },
                )
                discovered.append(pat)

        return discovered

    # -------------------------------------------------------------------------
    # 2. Behavioral Pattern Discovery
    # -------------------------------------------------------------------------

    def discover_behavioral_patterns(
        self,
        events: List[Event],
        timeline: Optional[Any] = None,
        episodes: Optional[List[ReasoningEpisode]] = None,
    ) -> List[Pattern]:
        """
        Discovers BEHAVIORAL PATTERNS from user habits, sequential activity routines,
        and temporal rhythms (e.g. 'Late meetings are often followed by delayed work').
        """
        discovered: List[Pattern] = []
        if not events:
            return discovered

        ep_list = episodes or []
        sorted_events = sorted(events, key=lambda e: e.event_time)

        # 1. Late meetings followed by delayed work sequence
        # Late meeting: event_time hour >= 17 (5 PM) or 'late_meeting'
        late_meetings = [
            e for e in sorted_events
            if ("meeting" in e.event_type or "calendar" in e.source) and e.event_time.hour >= 17
        ]

        if len(late_meetings) >= 2:
            delayed_work_instances = []
            on_time_work_instances = []

            for m in late_meetings:
                # Look for subsequent activity / work within 4 hours
                subsequent_events = [
                    e for e in sorted_events
                    if 0 < (e.event_time - m.event_time).total_seconds() <= 14400
                ]
                # If subsequent work shows delay, prolonged gap, or delayed task completion
                has_delayed_work = any(
                    "delayed" in str(e.payload).lower() or "overrun" in str(e.payload).lower()
                    or ("task" in e.event_type and (e.event_time - m.event_time).total_seconds() > 3600)
                    for e in subsequent_events
                )
                if has_delayed_work or len(subsequent_events) <= 1:
                    delayed_work_instances.append(m)
                else:
                    on_time_work_instances.append(m)

            if len(delayed_work_instances) >= 2:
                desc = "Late meetings are often followed by delayed work."

                # Find relevant supporting and contradicting episodes
                supp_episodes = [
                    ep.id for ep in ep_list
                    if any("late" in str(getattr(ep, "outcome", {})).lower()
                           or "meeting" in str(getattr(ep, "outcome", {})).lower()
                           or "late" in str(getattr(ep, "hermes_task", "")).lower()
                           or "meeting" in str(getattr(ep, "hermes_task", "")).lower()
                           or "late" in " ".join(getattr(ep, "observations", [])).lower()
                           for _ in [1])
                ]


                pat = self._upsert_pattern(
                    description=desc,
                    pattern_type=PatternType.BEHAVIORAL_PATTERN,
                    supporting_episodes=supp_episodes,
                    contradicting_episodes=[],
                    supporting_event_ids=[e.id for e in delayed_work_instances],
                    contradicting_event_ids=[e.id for e in on_time_work_instances],
                    first_seen=min(e.event_time for e in late_meetings),
                    last_seen=max(e.event_time for e in late_meetings),
                    metadata={
                        "dimension": "late_meeting_sequence",
                        "delayed_instances": len(delayed_work_instances),
                        "on_time_instances": len(on_time_work_instances),
                    },
                )
                discovered.append(pat)

        # 2. Prolonged deep work followed by restorative breaks
        deep_work_events = [
            e for e in sorted_events
            if "deep_work" in e.event_type or ("duration_minutes" in e.payload and float(e.payload.get("duration_minutes", 0)) >= 180)
        ]
        if len(deep_work_events) >= 2:
            desc = "Extended deep work sessions over 3 hours are frequently followed by restorative breaks."
            pat = self._upsert_pattern(
                description=desc,
                pattern_type=PatternType.BEHAVIORAL_PATTERN,
                supporting_episodes=[],
                contradicting_episodes=[],
                supporting_event_ids=[e.id for e in deep_work_events],
                first_seen=min(e.event_time for e in deep_work_events),
                last_seen=max(e.event_time for e in deep_work_events),
                metadata={
                    "dimension": "deep_work_fatigue",
                    "session_count": len(deep_work_events),
                },
            )
            discovered.append(pat)

        # 3. Sleep deficit and subsequent daily activity capacity
        sleep_events = [
            e for e in sorted_events
            if "sleep" in e.event_type or "sleep" in e.source
        ]
        low_sleep_events = [
            e for e in sleep_events
            if float(e.payload.get("duration_minutes", 480)) < 360
        ]
        if len(low_sleep_events) >= 2:
            desc = "Reduced sleep duration is frequently associated with lower afternoon activity capacity."
            pat = self._upsert_pattern(
                description=desc,
                pattern_type=PatternType.BEHAVIORAL_PATTERN,
                supporting_episodes=[],
                contradicting_episodes=[],
                supporting_event_ids=[e.id for e in low_sleep_events],
                first_seen=min(e.event_time for e in low_sleep_events),
                last_seen=max(e.event_time for e in low_sleep_events),
                metadata={
                    "dimension": "sleep_recovery",
                    "low_sleep_count": len(low_sleep_events),
                },
            )
            discovered.append(pat)

        # 4. Recurring commitments completed shortly before deadline (< 2 hours before due_at)
        commitment_events = [
            e for e in sorted_events
            if ("commitment" in e.event_type or "task" in e.event_type or "completed" in str(e.payload).lower())
            and isinstance(e.payload, dict) and e.payload.get("due_at")
        ]
        if len(commitment_events) >= 2:
            short_notice_completions = []
            for ce in commitment_events:
                due_val = ce.payload.get("due_at")
                try:
                    if isinstance(due_val, str):
                        due_dt = datetime.fromisoformat(due_val.replace("Z", "+00:00"))
                    elif isinstance(due_val, datetime):
                        due_dt = due_val
                    else:
                        continue
                    due_dt = ensure_timezone_aware(due_dt, "due_at")
                    time_before_hours = (due_dt - ce.event_time).total_seconds() / 3600.0
                    if 0.0 <= time_before_hours <= 2.5:
                        short_notice_completions.append(ce)
                except Exception:
                    pass

            if len(short_notice_completions) >= 2:
                desc = "A recurring commitment is frequently completed shortly before its deadline."
                pat = self._upsert_pattern(
                    description=desc,
                    pattern_type=PatternType.BEHAVIORAL_PATTERN,
                    supporting_episodes=[],
                    contradicting_episodes=[],
                    supporting_event_ids=[e.id for e in short_notice_completions],
                    first_seen=min(e.event_time for e in short_notice_completions),
                    last_seen=max(e.event_time for e in short_notice_completions),
                    metadata={
                        "dimension": "deadline_completion_timing",
                        "completion_count": len(short_notice_completions),
                    },
                )
                discovered.append(pat)

        return discovered

    # -------------------------------------------------------------------------
    # 3. Interaction Pattern Discovery
    # -------------------------------------------------------------------------

    def discover_interaction_patterns(
        self,
        episodes: List[ReasoningEpisode],
    ) -> List[Pattern]:
        """
        Discovers INTERACTION PATTERNS from longitudinal reasoning episodes,
        recommendation specificity, timing, urgency, user responses, and outcomes.
        Explicitly links both supporting and contradicting reasoning episode IDs.
        """
        discovered_patterns: List[Pattern] = []
        if not episodes:
            return discovered_patterns

        # Filter episodes that have recorded user responses or outcomes
        evaluated_episodes = [
            ep for ep in episodes
            if self._extract_user_response(ep) != RecommendationResult.UNKNOWN.value
        ]
        if len(evaluated_episodes) < 2:
            return discovered_patterns

        # --- 1. Recommendation Specificity Preference ---
        # Specific contextual recommendations vs generic reminders
        specific_eps = [ep for ep in evaluated_episodes if self._is_specific_recommendation(ep)]
        generic_eps = [ep for ep in evaluated_episodes if not self._is_specific_recommendation(ep)]

        if len(specific_eps) >= 2 and len(generic_eps) >= 1:
            spec_pos_eps = [ep for ep in specific_eps if self._is_positive_response(self._extract_user_response(ep))]
            spec_neg_eps = [ep for ep in specific_eps if self._is_negative_response(self._extract_user_response(ep))]
            gen_pos_eps = [ep for ep in generic_eps if self._is_positive_response(self._extract_user_response(ep))]
            gen_neg_eps = [ep for ep in generic_eps if self._is_negative_response(self._extract_user_response(ep))]

            spec_rate = len(spec_pos_eps) / len(specific_eps)
            gen_rate = len(gen_pos_eps) / len(generic_eps)

            if spec_rate >= 0.65 and gen_rate <= 0.40:
                desc = "User appears more responsive to specific contextual recommendations than generic reminders."

                # Supporting: Specific accepted OR generic dismissed
                supporting = [ep.id for ep in spec_pos_eps] + [ep.id for ep in gen_neg_eps]
                # Contradicting: Specific dismissed OR generic accepted
                contradicting = [ep.id for ep in spec_neg_eps] + [ep.id for ep in gen_pos_eps]

                pat = self._upsert_pattern(
                    description=desc,
                    pattern_type=PatternType.INTERACTION_PATTERN,
                    supporting_episodes=supporting,
                    contradicting_episodes=contradicting,
                    first_seen=min(ep.created_at for ep in specific_eps + generic_eps),
                    last_seen=max(ep.created_at for ep in specific_eps + generic_eps),
                    metadata={
                        "dimension": "recommendation_specificity",
                        "specific_acceptance_rate": round(spec_rate, 2),
                        "generic_acceptance_rate": round(gen_rate, 2),
                        "specific_count": len(specific_eps),
                        "generic_count": len(generic_eps),
                    },
                )
                discovered_patterns.append(pat)

        # --- 2. Timing Preferences (Morning vs Evening) ---
        morning_eps = [ep for ep in evaluated_episodes if self._extract_timing_bucket(ep) == "morning"]
        evening_eps = [ep for ep in evaluated_episodes if self._extract_timing_bucket(ep) in ("evening", "night")]

        if len(morning_eps) >= 2:
            morn_pos = [ep for ep in morning_eps if self._is_positive_response(self._extract_user_response(ep))]
            morn_neg = [ep for ep in morning_eps if self._is_negative_response(self._extract_user_response(ep))]
            morn_rate = len(morn_pos) / len(morning_eps)

            if morn_rate >= 0.70:
                if len(evening_eps) >= 1:
                    eve_pos = [ep for ep in evening_eps if self._is_positive_response(self._extract_user_response(ep))]
                    eve_neg = [ep for ep in evening_eps if self._is_negative_response(self._extract_user_response(ep))]
                    eve_rate = len(eve_pos) / len(evening_eps)
                    if morn_rate - eve_rate >= 0.30:
                        desc = "User appears more responsive to recommendations delivered during morning hours than late evening."
                        supporting = [ep.id for ep in morn_pos] + [ep.id for ep in eve_neg]
                        contradicting = [ep.id for ep in morn_neg] + [ep.id for ep in eve_pos]
                    else:
                        desc = "User appears more responsive to recommendations delivered during morning hours."
                        supporting = [ep.id for ep in morn_pos]
                        contradicting = [ep.id for ep in morn_neg]
                else:
                    desc = "User appears more responsive to recommendations delivered during morning hours."
                    supporting = [ep.id for ep in morn_pos]
                    contradicting = [ep.id for ep in morn_neg]

                pat = self._upsert_pattern(
                    description=desc,
                    pattern_type=PatternType.INTERACTION_PATTERN,
                    supporting_episodes=supporting,
                    contradicting_episodes=contradicting,
                    first_seen=min(ep.created_at for ep in morning_eps),
                    last_seen=max(ep.created_at for ep in morning_eps),
                    metadata={
                        "dimension": "timing",
                        "morning_acceptance_rate": round(morn_rate, 2),
                        "morning_count": len(morning_eps),
                    },
                )
                discovered_patterns.append(pat)

        # --- 3. Urgency Alignment ---
        high_urg_eps = [ep for ep in evaluated_episodes if ep.urgency in ("high", "critical")]
        med_urg_eps = [ep for ep in evaluated_episodes if ep.urgency in ("medium", "low")]

        if len(high_urg_eps) >= 2:
            high_pos = [ep for ep in high_urg_eps if self._is_positive_response(self._extract_user_response(ep))]
            high_neg = [ep for ep in high_urg_eps if self._is_negative_response(self._extract_user_response(ep))]
            high_rate = len(high_pos) / len(high_urg_eps)

            if high_rate >= 0.75:
                desc = "Recommendations delivered with high urgency appear associated with higher acceptance rates."
                pat = self._upsert_pattern(
                    description=desc,
                    pattern_type=PatternType.INTERACTION_PATTERN,
                    supporting_episodes=[ep.id for ep in high_pos],
                    contradicting_episodes=[ep.id for ep in high_neg],
                    first_seen=min(ep.created_at for ep in high_urg_eps),
                    last_seen=max(ep.created_at for ep in high_urg_eps),
                    metadata={
                        "dimension": "urgency",
                        "high_urgency_acceptance_rate": round(high_rate, 2),
                        "high_urgency_count": len(high_urg_eps),
                    },
                )
                discovered_patterns.append(pat)

        # --- 4. Context Receptivity (e.g. Busy Context) ---
        busy_eps = [ep for ep in evaluated_episodes if self._extract_context(ep) in ("busy", "deep_work", "meeting")]
        if len(busy_eps) >= 2:
            busy_dismissed = [ep for ep in busy_eps if self._is_negative_response(self._extract_user_response(ep))]
            busy_accepted = [ep for ep in busy_eps if self._is_positive_response(self._extract_user_response(ep))]
            busy_dismiss_rate = len(busy_dismissed) / len(busy_eps)

            if busy_dismiss_rate >= 0.65:
                desc = "Recommendations delivered during busy context appear associated with higher dismissal rates."
                pat = self._upsert_pattern(
                    description=desc,
                    pattern_type=PatternType.INTERACTION_PATTERN,
                    supporting_episodes=[ep.id for ep in busy_dismissed],
                    contradicting_episodes=[ep.id for ep in busy_accepted],
                    first_seen=min(ep.created_at for ep in busy_eps),
                    last_seen=max(ep.created_at for ep in busy_eps),
                    metadata={
                        "dimension": "context",
                        "busy_dismissal_rate": round(busy_dismiss_rate, 2),
                        "busy_count": len(busy_eps),
                    },
                )
                discovered_patterns.append(pat)

        # --- 5. Low-Urgency Interruption Dismissals ---
        low_urg_interrupts = [
            ep for ep in evaluated_episodes
            if ep.urgency in ("low", "medium")
            and (
                (isinstance(ep.intervention_decision, dict) and ep.intervention_decision.get("action") == "INTERRUPT")
                or self._extract_context(ep) in ("busy", "deep_work", "meeting", "focused")
            )
        ]
        if len(low_urg_interrupts) >= 2:
            dismissed = [ep for ep in low_urg_interrupts if self._is_negative_response(self._extract_user_response(ep))]
            accepted = [ep for ep in low_urg_interrupts if self._is_positive_response(self._extract_user_response(ep))]
            dismiss_rate = len(dismissed) / len(low_urg_interrupts)

            if dismiss_rate >= 0.60:
                desc = "User frequently dismisses low-urgency interruptions during focused or busy states."
                pat = self._upsert_pattern(
                    description=desc,
                    pattern_type=PatternType.INTERACTION_PATTERN,
                    supporting_episodes=[ep.id for ep in dismissed],
                    contradicting_episodes=[ep.id for ep in accepted],
                    first_seen=min(ep.created_at for ep in low_urg_interrupts),
                    last_seen=max(ep.created_at for ep in low_urg_interrupts),
                    metadata={
                        "dimension": "low_urgency_dismissal",
                        "dismissal_rate": round(dismiss_rate, 2),
                        "low_urgency_count": len(low_urg_interrupts),
                    },
                )
                discovered_patterns.append(pat)

        return discovered_patterns

    def synthesize_interaction_preferences(
        self,
        episodes: Optional[List[ReasoningEpisode]] = None,
    ) -> Dict[str, Any]:
        """
        Synthesizes empirical interaction preferences answering:
        'How does this person prefer to be helped?'
        without hardcoded rules or predefined assumptions.
        """
        if episodes:
            self.discover_interaction_patterns(episodes)

        all_patterns = self.pattern_store.list_patterns(limit=100)
        interaction_patterns = [
            p for p in all_patterns
            if p.pattern_type == PatternType.INTERACTION_PATTERN.value and p.status in (
                PatternStatus.ACTIVE.value,
                PatternStatus.SUPPORTED.value,
                PatternStatus.EMERGING.value,
                PatternStatus.HYPOTHESIS.value,
            )
        ]

        prefers_specific = any(
            "specific" in p.description.lower() for p in interaction_patterns
        )
        morning_pref = any(
            "morning" in p.description.lower() for p in interaction_patterns
        )
        dismisses_low_urgency = any(
            "low-urgency" in p.description.lower() or "busy" in p.description.lower()
            for p in interaction_patterns
        )
        high_urgency_receptive = any(
            "high urgency" in p.description.lower() for p in interaction_patterns
        )

        timing_pref = "morning" if morning_pref else "any"

        summary_parts = []
        if prefers_specific:
            summary_parts.append("prefers specific actionable recommendations over generic reminders")
        if morning_pref:
            summary_parts.append("is more responsive to morning notifications")
        if dismisses_low_urgency:
            summary_parts.append("frequently dismisses low-urgency interruptions during focused work")
        if high_urgency_receptive:
            summary_parts.append("accepts high-urgency notifications with high responsiveness")

        summary = "User " + ", ".join(summary_parts) + "." if summary_parts else "No clear interaction preferences established yet."

        return {
            "prefers_specific_recommendations": prefers_specific,
            "preferred_timing_window": timing_pref,
            "dismisses_low_urgency_interruptions": dismisses_low_urgency,
            "high_urgency_receptive": high_urgency_receptive,
            "active_interaction_pattern_count": len(interaction_patterns),
            "summary": summary,
        }

    # -------------------------------------------------------------------------
    # Unified Multi-Source Learning Pipeline
    # -------------------------------------------------------------------------

    def learn_patterns(
        self,
        events: Optional[List[Event]] = None,
        episodes: Optional[List[ReasoningEpisode]] = None,
        timeline: Optional[Any] = None,
        as_of: Optional[datetime] = None,
    ) -> Dict[str, List[Pattern]]:
        """
        Unified learning pipeline scanning observations, reasoning episodes,
        recommendations, user responses, and outcomes across World, Behavioral,
        and Interaction domains with recency decay.
        """
        ev_list = events or []
        ep_list = episodes or []
        ref_dt = ensure_timezone_aware(as_of or datetime.now(timezone.utc), "as_of")

        world_pats = self.discover_world_patterns(ev_list, timeline=timeline)
        behavioral_pats = self.discover_behavioral_patterns(ev_list, timeline=timeline, episodes=ep_list)
        recurrence_pats = self.discover_situation_recurrence_patterns(ep_list)
        behavioral_pats.extend(recurrence_pats)
        interaction_pats = self.discover_interaction_patterns(ep_list)
        decayed_pats = self.apply_recency_decay(as_of=ref_dt)

        return {
            "world_patterns": world_pats,
            "behavioral_patterns": behavioral_pats,
            "interaction_patterns": interaction_pats,
            "decayed_patterns": decayed_pats,
        }

    def discover_situation_recurrence_patterns(
        self,
        episodes: List[ReasoningEpisode],
    ) -> List[Pattern]:
        """
        Discovers empirical patterns from repeated situations, outcomes, and user responses.
        Strictly observes recurring correlation without causal claims or modifying historical observations.
        """
        discovered: List[Pattern] = []
        if not episodes:
            return discovered

        by_situation_type: Dict[str, List[ReasoningEpisode]] = defaultdict(list)
        for ep in episodes:
            sit_type = None
            if isinstance(ep.context_snapshot, dict):
                sit_type = ep.context_snapshot.get("category") or ep.context_snapshot.get("situation_type")
            if not sit_type and ep.hermes_task:
                sit_type = ep.hermes_task
            if not sit_type and ep.situation_id:
                sit_type = ep.situation_id
            sit_type = sit_type or "general_situation"
            by_situation_type[str(sit_type)].append(ep)

        for s_type, ep_list in by_situation_type.items():
            if len(ep_list) >= 2:
                desc = f"Repeated situation of type '{s_type}' frequently recurs under similar temporal and contextual conditions."
                clean_desc = self._sanitize_non_causal_phrasing(desc)

                pat = self._upsert_pattern(
                    description=clean_desc,
                    pattern_type=PatternType.BEHAVIORAL_PATTERN,
                    supporting_episodes=[e.id for e in ep_list],
                    first_seen=min(e.created_at for e in ep_list),
                    last_seen=max(e.created_at for e in ep_list),
                    metadata={
                        "dimension": "situation_recurrence",
                        "situation_type": s_type,
                        "recurrence_count": len(ep_list),
                    },
                )
                discovered.append(pat)

        return discovered

    def scan_intervention_preferences(
        self,
        episodes: List[ReasoningEpisode],
    ) -> List[Pattern]:
        """Alias for discover_interaction_patterns for backwards compatibility."""
        return self.discover_interaction_patterns(episodes)

    def scan_episodes_for_associations(
        self,
        episodes: List[ReasoningEpisode],
    ) -> List[Pattern]:
        """Scans episodes for task-level co-occurrences."""
        discovered: List[Pattern] = []
        if not episodes:
            return discovered

        co_occurrences: Dict[str, List[ReasoningEpisode]] = defaultdict(list)
        for ep in episodes:
            key = ep.hermes_task or ep.situation_id or "general"
            co_occurrences[key].append(ep)

        for task_key, group in co_occurrences.items():
            if len(group) >= 2:
                desc = f"Repeated reasoning for {task_key} appears associated with recurring situational context."
                clean_desc = self._sanitize_non_causal_phrasing(desc)

                pat = self._upsert_pattern(
                    description=clean_desc,
                    pattern_type=PatternType.BEHAVIORAL_PATTERN,
                    supporting_episodes=[e.id for e in group],
                    first_seen=group[0].created_at,
                    last_seen=group[-1].created_at,
                    metadata={"source_task": task_key, "initial_episodes": len(group)},
                )
                discovered.append(pat)

        return discovered

    # -------------------------------------------------------------------------
    # Internal Pattern Helpers
    # -------------------------------------------------------------------------

    def _upsert_pattern(
        self,
        description: str,
        pattern_type: PatternType,
        supporting_episodes: Optional[List[str]] = None,
        contradicting_episodes: Optional[List[str]] = None,
        supporting_event_ids: Optional[List[str]] = None,
        contradicting_event_ids: Optional[List[str]] = None,
        first_seen: Optional[datetime] = None,
        last_seen: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        initial_status: PatternStatus = PatternStatus.HYPOTHESIS,
    ) -> Pattern:
        """
        Creates or updates a learned pattern with full episode and event provenance records.
        """
        now = datetime.now(timezone.utc)
        f_seen = ensure_timezone_aware(first_seen or now, "first_seen")
        l_seen = ensure_timezone_aware(last_seen or now, "last_seen")
        p_type_val = pattern_type.value if hasattr(pattern_type, "value") else str(pattern_type).strip().upper()

        clean_desc = self._sanitize_non_causal_phrasing(description)
        existing = [p for p in self.pattern_store.list_patterns(limit=100) if p.description == clean_desc]

        supp_eps = list(supporting_episodes or [])
        contra_eps = list(contradicting_episodes or [])
        supp_ev_ids = list(supporting_event_ids or [])
        contra_ev_ids = list(contradicting_event_ids or [])

        meta = dict(metadata or {})
        meta["pattern_type"] = p_type_val
        meta["supporting_episodes"] = supp_eps
        meta["contradicting_episodes"] = contra_eps

        support_count = max(1, len(supp_eps) if supp_eps else len(supp_ev_ids))
        contra_count = len(contra_eps) if contra_eps else len(contra_ev_ids)

        if existing:
            pat = existing[0]
            pat.support_count = max(pat.support_count, support_count)
            pat.contradiction_count = max(pat.contradiction_count, contra_count)
            pat.last_seen = l_seen
            pat.pattern_type = p_type_val
            pat.metadata.update(meta)

            new_status, new_strength = self.evaluate_progression(pat, as_of=l_seen)
            pat.status = new_status.value
            pat.evidence_strength = new_strength

            updated = self.pattern_store.update_pattern(pat) or pat

            # Record individual supporting evidence items for provenance
            for ep_id in supp_eps:
                self.pattern_store.add_evidence(
                    pattern_id=updated.id,
                    observation_type=EvidenceObservationType.SUPPORT,
                    observed_at=l_seen,
                    episode_id=ep_id,
                    details={"dimension": meta.get("dimension")},
                )
            for ep_id in contra_eps:
                self.pattern_store.add_evidence(
                    pattern_id=updated.id,
                    observation_type=EvidenceObservationType.CONTRADICTION,
                    observed_at=l_seen,
                    episode_id=ep_id,
                    details={"dimension": meta.get("dimension")},
                )
            return updated
        else:
            init_status = initial_status.value if hasattr(initial_status, "value") else str(initial_status)
            pat = self.pattern_store.create_pattern(
                description=clean_desc,
                first_seen=f_seen,
                last_seen=l_seen,
                support_count=support_count,
                contradiction_count=0,
                evidence_strength="moderate" if support_count >= 3 else "weak",
                status=init_status,
                metadata=meta,
                pattern_type=p_type_val,
            )
            # Record evidence records for provenance
            for ep_id in supp_eps:
                self.pattern_store.add_evidence(
                    pattern_id=pat.id,
                    observation_type=EvidenceObservationType.SUPPORT,
                    observed_at=l_seen,
                    episode_id=ep_id,
                    details={"dimension": meta.get("dimension")},
                )
            return pat


    def _extract_user_response(self, ep: ReasoningEpisode) -> str:
        """Extracts normalized user response or outcome state from an episode."""
        if ep.user_response:
            if isinstance(ep.user_response, dict):
                resp = ep.user_response.get("response") or ep.user_response.get("action_taken") or ep.user_response.get("user_feedback")
                if resp:
                    return str(resp).strip().upper()
            elif isinstance(ep.user_response, str):
                return ep.user_response.strip().upper()

        if ep.outcome:
            if isinstance(ep.outcome, dict):
                status = ep.outcome.get("outcome_status") or ep.outcome.get("status")
                if status:
                    return str(status).strip().upper()
                if ep.outcome.get("success") is True:
                    return RecommendationResult.COMPLETED.value
            elif isinstance(ep.outcome, str):
                return ep.outcome.strip().upper()

        return RecommendationResult.UNKNOWN.value

    def _is_positive_response(self, resp: str) -> bool:
        """Returns True if user response reflects positive interaction."""
        norm = resp.upper()
        return norm in (
            RecommendationResult.ACCEPTED.value,
            RecommendationResult.COMPLETED.value,
            RecommendationResult.PARTIALLY_COMPLETED.value,
            "DONE",
            "HELPFUL",
            "YES",
            "CONFIRMED",
        ) or "COMPLETED" in norm or "DONE" in norm or "ACCEPTED" in norm

    def _is_negative_response(self, resp: str) -> bool:
        """Returns True if user response reflects negative or ignored interaction."""
        return resp.upper() in (
            RecommendationResult.DISMISSED.value,
            RecommendationResult.IGNORED.value,
        )

    def _is_specific_recommendation(self, ep: ReasoningEpisode) -> bool:
        """Determines if the recommendation in an episode is specific vs generic."""
        rec = ep.recommendation
        if isinstance(rec, dict):
            if "specificity" in rec:
                return str(rec["specificity"]).lower() == "specific"
            content = str(rec.get("content") or rec.get("action") or "")
        else:
            content = str(rec or "")

        generic_markers = ["check schedule", "take a break", "stay focused", "stay on track", "drink water"]
        content_lower = content.lower()
        if any(marker in content_lower for marker in generic_markers) and len(content) < 45:
            return False
        return len(content) >= 45 or ":" in content or "at" in content

    def _extract_timing_bucket(self, ep: ReasoningEpisode) -> str:
        """Categorizes episode timestamp into daily time bucket."""
        hour = ep.created_at.hour
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 22:
            return "evening"
        else:
            return "night"

    def _extract_context(self, ep: ReasoningEpisode) -> str:
        """Extracts user delivery context from intervention decision or context snapshot."""
        if ep.intervention_decision and isinstance(ep.intervention_decision, dict):
            ctx = ep.intervention_decision.get("user_context")
            if ctx:
                return str(ctx).lower()
        if ep.context_snapshot and isinstance(ep.context_snapshot, dict):
            curr_state = ep.context_snapshot.get("current_state", {})
            if isinstance(curr_state, dict):
                ctx = curr_state.get("user_context") or curr_state.get("current_activity")
                if ctx:
                    return str(ctx).lower()
        return "available"

    def record_supporting_evidence(
        self,
        pattern_id: str,
        observation_id: Optional[str] = None,
        episode_id: Optional[str] = None,
        event_ids: Optional[List[str]] = None,
        observed_at: Optional[datetime] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Pattern, PatternEvidence]:
        """Convenience method to record supporting empirical evidence for a pattern."""
        ev_ids = list(event_ids or [])
        if observation_id and observation_id not in ev_ids:
            ev_ids.append(observation_id)
        return self.record_evidence(
            pattern_id=pattern_id,
            observation_type=EvidenceObservationType.SUPPORT,
            observed_at=observed_at,
            episode_id=episode_id,
            event_ids=ev_ids,
            details=details,
        )

    def record_contradicting_evidence(
        self,
        pattern_id: str,
        observation_id: Optional[str] = None,
        episode_id: Optional[str] = None,
        event_ids: Optional[List[str]] = None,
        observed_at: Optional[datetime] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Pattern, PatternEvidence]:
        """Convenience method to record contradicting empirical evidence for a pattern."""
        ev_ids = list(event_ids or [])
        if observation_id and observation_id not in ev_ids:
            ev_ids.append(observation_id)
        return self.record_evidence(
            pattern_id=pattern_id,
            observation_type=EvidenceObservationType.CONTRADICTION,
            observed_at=observed_at,
            episode_id=episode_id,
            event_ids=ev_ids,
            details=details,
        )

    def discover_state_transition_patterns(
        self,
        state_history: List[Any],
        events: Optional[List[Event]] = None,
    ) -> List[Pattern]:
        """
        Discovers patterns from consecutive state transitions across personal signal dimensions
        (e.g., high workload transitioning to prolonged recovery).
        """
        discovered: List[Pattern] = []
        if not state_history or len(state_history) < 2:
            return discovered

        # Track transitions between high cognitive load and subsequent activity drop
        workload_drop_instances: List[Any] = []
        for i in range(len(state_history) - 1):
            s1 = state_history[i]
            s2 = state_history[i + 1]

            s1_workload = s1.get_value("workload_index") if hasattr(s1, "get_value") else getattr(s1, "workload", 0.0)
            s2_activity = s2.get_value("recent_activity_duration") if hasattr(s2, "get_value") else getattr(s2, "activity_duration", 0.0)

            if s1_workload is not None and s2_activity is not None:
                if float(s1_workload) >= 2.0 and float(s2_activity) < 30.0:
                    workload_drop_instances.append((s1, s2))

        if len(workload_drop_instances) >= 2:
            desc = "Lower activity duration has occurred more frequently following periods containing elevated workload indices."
            f_time = workload_drop_instances[0][0].timestamp if hasattr(workload_drop_instances[0][0], "timestamp") else datetime.now(timezone.utc)
            l_time = workload_drop_instances[-1][1].timestamp if hasattr(workload_drop_instances[-1][1], "timestamp") else datetime.now(timezone.utc)
            pat = self._upsert_pattern(
                description=desc,
                pattern_type=PatternType.BEHAVIORAL_PATTERN,
                supporting_episodes=[],
                contradicting_episodes=[],
                first_seen=f_time,
                last_seen=l_time,
                metadata={
                    "dimension": "state_transition_workload_recovery",
                    "transition_count": len(workload_drop_instances),
                },
            )
            discovered.append(pat)

        return discovered

    def _sanitize_non_causal_phrasing(self, text: str) -> str:
        """
        Enforces non-causal association semantics.
        Replaces causal verbs ('causes', 'leads to', 'results in') with association phrasing.
        """
        phrasing = text.strip()
        causal_replacements = {
            " causes ": " appears associated with ",
            " cause ": " appear associated with ",
            " leads to ": " appears correlated with ",
            " lead to ": " appear correlated with ",
            " results in ": " is frequently followed by ",
            " result in ": " are frequently followed by ",
            " makes ": " coincides with ",
        }
        for causal_word, assoc_word in causal_replacements.items():
            if causal_word in phrasing:
                phrasing = phrasing.replace(causal_word, assoc_word)

        return phrasing


# Backwards compatibility alias
PatternEngine = LearningEngine



