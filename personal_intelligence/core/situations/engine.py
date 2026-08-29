"""
Personal Intelligence Situation Engine.

Synthesizes:
- Current State (commitments, upcoming events, open issues, recent activity, goals, active situations)
- Recent Observations
- Timeline
- Active Goals
- Known Patterns
- Emerging Hypotheses

Produces candidate situations across generic categories:
- possible forgotten commitment
- upcoming preparation need
- schedule conflict
- unresolved issue
- unusual change (unusual_state / prolonged_activity)
- goal risk
- opportunity
- information gap
- novel situation

Does NOT notify the user.
Does NOT take actions.
Does NOT call external APIs directly.
Marks `information_required = True` and specifies `investigation_target` when Hermes investigation is needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Set, Union
import uuid

from personal_intelligence.core.events.models import Event, ensure_timezone_aware, format_iso8601
from personal_intelligence.core.goals.engine import GoalEngine
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.novelty.models import NoveltyResult, OverallNoveltyLevel
from personal_intelligence.core.patterns.models import Pattern
from personal_intelligence.core.situations.models import (
    Situation,
    SituationEvaluation,
    SituationPriority,
    SituationStatus,
    StandardSituationCategory,
)
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.core.world.models import (
    Commitment,
    CommitmentStatus,
    CurrentState,
    IssueSeverity,
    IssueStatus,
    OpenIssue,
    UpcomingEvent,
)

logger = logging.getLogger(__name__)


class SituationEngine:
    """
    Synthesizes personal intelligence signals into structured candidate situations.
    
    Architecture:
    SituationEngine
        |
        +-- Generic Candidate Generators (9 standard candidate patterns)
        |     ├── goal_risk (enriched by GoalEngine)
        |     ├── unresolved_action_item_before_milestone
        |     ├── conflicting_commitments
        |     ├── prolonged_inactivity_on_priority
        |     ├── unusual_change
        |     ├── information_gap
        |     ├── external_dependency_risk
        |     ├── opportunity
        |     └── novel_pattern
        |
        +-- Novelty Detection
        |
        +-- Cross-domain state analysis
        |
        +-- New Situation Discovery (produces NOVEL_SITUATION for unfamiliar combinations)
    """

    def __init__(
        self,
        prolonged_activity_threshold_minutes: float = 120.0,
        routine_deviation_threshold: float = 0.50,
        novelty_threshold: float = 0.65,
        goal_engine: Optional[GoalEngine] = None,
    ) -> None:
        self.prolonged_activity_threshold = prolonged_activity_threshold_minutes
        self.routine_deviation_threshold = routine_deviation_threshold
        self.novelty_threshold = novelty_threshold
        self.goal_engine = goal_engine


    def evaluate(
        self,
        current_state: Union[CurrentState, StateRepresentation],
        timeline: Optional[Timeline] = None,
        goals: Optional[List[Goal]] = None,
        recent_observations: Optional[List[Event]] = None,
        known_patterns: Optional[List[Pattern]] = None,
        emerging_hypotheses: Optional[List[Pattern]] = None,
        novelty_result: Optional[NoveltyResult] = None,
        reference_time: Optional[datetime] = None,
    ) -> SituationEvaluation:
        """
        Executes the 4-stage SituationEngine synthesis:
        1. Generic Candidate Generators (standard categories)
        2. Novelty Detection
        3. Cross-Domain State Analysis
        4. New Situation Discovery (NOVEL_SITUATION for emergent combinations)
        """
        ref_dt = ensure_timezone_aware(
            reference_time or (
                current_state.timestamp if hasattr(current_state, "timestamp") and current_state.timestamp
                else datetime.now(timezone.utc)
            ),
            "reference_time",
        )

        active_goals = goals or []
        obs_list = recent_observations or (timeline.events if timeline else [])
        patterns = known_patterns or []
        hypotheses = emerging_hypotheses or []

        candidates: List[Situation] = []
        ignored_signals: List[Dict[str, Any]] = []
        all_evidence: Set[str] = set()

        # =========================================================================
        # Stage 1: Generic Candidate Generators
        # =========================================================================

        # 1.1 Goal Risk Generator
        candidates.extend(self._generate_goal_risks(current_state, active_goals, obs_list, novelty_result, ref_dt))

        # 1.2 Unresolved Action Items Before Milestone
        candidates.extend(self._generate_possible_forgotten_commitments(current_state, obs_list, ref_dt))
        candidates.extend(self._generate_upcoming_preparation_needs(current_state, obs_list, active_goals, ref_dt))
        candidates.extend(self._generate_unresolved_issues(current_state, ref_dt))

        # 1.3 Conflicting Commitments
        candidates.extend(self._generate_schedule_conflicts(current_state, timeline, ref_dt))

        # 1.4 Prolonged Inactivity on Priority / Prolonged Activity
        candidates.extend(self._generate_prolonged_activity(current_state, timeline, ref_dt))

        # 1.5 Unusual Change
        candidates.extend(self._generate_unusual_changes(current_state, obs_list, novelty_result, ref_dt))

        # 1.6 Information Gap
        candidates.extend(self._generate_information_gaps(obs_list, ref_dt))

        # 1.7 External Dependency Risk
        candidates.extend(self._generate_external_dependency_risks(current_state, obs_list, active_goals, ref_dt))

        # 1.8 Opportunity
        candidates.extend(self._generate_opportunities(current_state, active_goals, patterns, ref_dt))

        # 1.9 Novel Pattern
        candidates.extend(self._generate_novel_patterns(patterns, hypotheses, ref_dt))

        # =========================================================================
        # Stage 2, 3 & 4: Novelty Detection, Cross-Domain Analysis & New Discovery
        # =========================================================================
        detected_categories = {c.type for c in candidates}
        discovered_novel_sits = self._discover_new_situations(
            current_state=current_state,
            observations=obs_list,
            novelty_result=novelty_result,
            goals=active_goals,
            existing_candidate_categories=detected_categories,
            ref_dt=ref_dt,
        )
        candidates.extend(discovered_novel_sits)

        # Consolidate evidence
        for c in candidates:
            for ev in c.evidence:
                all_evidence.add(str(ev))

        return SituationEvaluation(
            candidate_situations=candidates,
            ignored_signals=ignored_signals,
            evidence=list(all_evidence),
            timestamp=ref_dt,
        )


    # -------------------------------------------------------------------------
    # 1. Possible Forgotten Commitment Generator
    # -------------------------------------------------------------------------

    def _generate_possible_forgotten_commitments(
        self,
        current_state: Any,
        observations: List[Event],
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []
        commitments: List[Commitment] = []

        if isinstance(current_state, CurrentState):
            commitments = current_state.current_commitments
        elif hasattr(current_state, "get_value"):
            raw_commits = current_state.get_value("commitments", [])
            commitments = [Commitment.from_dict(c) if isinstance(c, dict) else c for c in raw_commits]

        for commit in commitments:
            if commit.status not in {CommitmentStatus.PENDING.value, CommitmentStatus.IN_PROGRESS.value}:
                continue

            is_overdue = commit.due_at and commit.due_at < ref_dt
            is_approaching = commit.due_at and (commit.due_at - ref_dt) <= timedelta(hours=24)
            is_stale_promise = (ref_dt - commit.created_at) >= timedelta(days=3)

            if is_overdue or is_approaching or is_stale_promise:
                evidence = [commit.id]
                if commit.provenance and commit.provenance.source_observation_id:
                    evidence.append(commit.provenance.source_observation_id)

                priority = SituationPriority.HIGH.value if is_overdue else SituationPriority.MEDIUM.value
                novelty = 0.4 if is_overdue else 0.2

                situations.append(
                    Situation(
                        id=f"sit_forgotten_commit_{uuid.uuid4().hex[:8]}",
                        type="possible_forgotten_commitment",
                        priority=priority,
                        novelty=novelty,
                        status=SituationStatus.OPEN.value,
                        information_required=True,
                        investigation_target=f"Check Gmail/Drive to see if deliverable for commitment '{commit.description}' was already sent or completed.",
                        context={
                            "category": "possible_forgotten_commitment",
                            "commitment_id": commit.id,
                            "description": commit.description,
                            "due_at": format_iso8601(commit.due_at) if commit.due_at else None,
                            "is_overdue": bool(is_overdue),
                            "origin_source": commit.provenance.origin_source if commit.provenance else None,
                        },
                        evidence=evidence,
                        created_at=ref_dt,
                        updated_at=ref_dt,
                    )
                )

        return situations

    # -------------------------------------------------------------------------
    # 2. Upcoming Preparation Need Generator
    # -------------------------------------------------------------------------

    def _generate_upcoming_preparation_needs(
        self,
        current_state: Any,
        observations: List[Event],
        goals: List[Goal],
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []
        upcoming_events: List[UpcomingEvent] = []

        if isinstance(current_state, CurrentState):
            upcoming_events = current_state.upcoming_events

        for evt in upcoming_events:
            time_until = evt.start_time - ref_dt
            if timedelta(0) <= time_until <= timedelta(hours=36):
                title_lower = evt.title.lower()
                is_major_event = any(k in title_lower for k in ["review", "presentation", "executive", "interview", "demo", "board", "quarterly", "arch"])

                prep_doc_found = any(
                    "document_changed" in obs.event_type and any(k in obs.payload.get("summary", "").lower() for k in title_lower.split() if len(k) > 3)
                    for obs in observations
                )

                if is_major_event and not prep_doc_found:
                    evidence = [evt.event_id]
                    if evt.source_observation_id:
                        evidence.append(evt.source_observation_id)

                    matching_goals = [
                        g.id for g in goals
                        if any(k in g.name.lower() for k in title_lower.split() if len(k) > 3)
                    ]

                    situations.append(
                        Situation(
                            id=f"sit_prep_need_{uuid.uuid4().hex[:8]}",
                            type="upcoming_preparation_need",
                            priority=SituationPriority.HIGH.value if time_until <= timedelta(hours=18) else SituationPriority.MEDIUM.value,
                            novelty=0.35,
                            status=SituationStatus.OPEN.value,
                            information_required=True,
                            investigation_target=f"Check Google Drive and filesystem for meeting slides, agenda, or preparation notes for '{evt.title}'.",
                            context={
                                "category": "upcoming_preparation_need",
                                "event_id": evt.event_id,
                                "title": evt.title,
                                "start_time": format_iso8601(evt.start_time),
                                "hours_until": round(time_until.total_seconds() / 3600, 1),
                            },
                            evidence=evidence,
                            related_goals=matching_goals,
                            created_at=ref_dt,
                            updated_at=ref_dt,
                        )
                    )

        return situations

    # -------------------------------------------------------------------------
    # 3. Schedule Conflict Generator
    # -------------------------------------------------------------------------

    def _generate_schedule_conflicts(
        self,
        current_state: Any,
        timeline: Optional[Timeline],
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []
        events: List[UpcomingEvent] = []

        if isinstance(current_state, CurrentState):
            events = [e for e in current_state.upcoming_events if e.start_time >= ref_dt]
        elif timeline and timeline.events:
            for ev in timeline.events:
                if ev.source == "calendar" or "calendar" in ev.event_type:
                    payload = ev.payload if isinstance(ev.payload, dict) else {}
                    evidence = payload.get("evidence", {}) if isinstance(payload.get("evidence"), dict) else payload
                    title = evidence.get("event_title") or evidence.get("title") or payload.get("summary") or "Meeting"
                    start_str = evidence.get("start_time") or format_iso8601(ev.event_time)
                    try:
                        start_dt = ensure_timezone_aware(start_str, "start_time")
                    except Exception:
                        start_dt = ev.event_time
                    events.append(UpcomingEvent(event_id=ev.id, title=title, start_time=start_dt))

        events_sorted = sorted(events, key=lambda x: x.start_time)

        for i in range(len(events_sorted) - 1):
            e1 = events_sorted[i]
            e2 = events_sorted[i + 1]

            e1_end = e1.end_time or (e1.start_time + timedelta(hours=1))
            if e2.start_time < e1_end:
                situations.append(
                    Situation(
                        id=f"sit_conflict_{uuid.uuid4().hex[:8]}",
                        type="schedule_conflict",
                        priority=SituationPriority.HIGH.value,
                        novelty=0.45,
                        status=SituationStatus.OPEN.value,
                        information_required=False,
                        context={
                            "category": "schedule_conflict",
                            "conflict_type": "temporal_overlap",
                            "event_1": {"id": e1.event_id, "title": e1.title, "start": format_iso8601(e1.start_time)},
                            "event_2": {"id": e2.event_id, "title": e2.title, "start": format_iso8601(e2.start_time)},
                        },
                        evidence=[e1.event_id, e2.event_id],
                        created_at=ref_dt,
                        updated_at=ref_dt,
                    )
                )

        return situations

    # -------------------------------------------------------------------------
    # 4. Unresolved Issue Generator
    # -------------------------------------------------------------------------

    def _generate_unresolved_issues(
        self,
        current_state: Any,
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []
        issues: List[OpenIssue] = []

        if isinstance(current_state, CurrentState):
            issues = current_state.open_issues

        for iss in issues:
            if iss.status in {IssueStatus.OPEN.value, IssueStatus.INVESTIGATING.value}:
                is_high_severity = iss.severity in {IssueSeverity.CRITICAL.value, IssueSeverity.HIGH.value}
                is_prolonged = (ref_dt - iss.created_at) >= timedelta(hours=12)

                if is_high_severity or is_prolonged:
                    evidence = [iss.id] + list(iss.source_observation_ids)
                    situations.append(
                        Situation(
                            id=f"sit_unresolved_issue_{uuid.uuid4().hex[:8]}",
                            type="unresolved_issue",
                            priority=SituationPriority.HIGH.value if is_high_severity else SituationPriority.MEDIUM.value,
                            novelty=0.50 if is_high_severity else 0.25,
                            status=SituationStatus.OPEN.value,
                            information_required=True,
                            investigation_target=f"Investigate system logs and communications regarding unresolved blocker '{iss.title}'.",
                            context={
                                "category": "unresolved_issue",
                                "issue_id": iss.id,
                                "title": iss.title,
                                "severity": iss.severity,
                                "description": iss.description,
                                "age_hours": round((ref_dt - iss.created_at).total_seconds() / 3600, 1),
                            },
                            evidence=evidence,
                            created_at=ref_dt,
                            updated_at=ref_dt,
                        )
                    )

        return situations

    # -------------------------------------------------------------------------
    # 5. Unusual Change & Prolonged Activity Generators
    # -------------------------------------------------------------------------

    def _generate_unusual_changes(
        self,
        current_state: Any,
        observations: List[Event],
        novelty_result: Optional[Any],
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []

        # If novelty result is present and indicates statistical anomaly
        if novelty_result:
            is_anomalous = False
            explanation = ""
            novelty_score = 0.5
            anom_evidence = [obs.id for obs in observations[-5:]] if observations else []
            if hasattr(novelty_result, "overall_level"):
                if novelty_result.overall_level in {
                    OverallNoveltyLevel.HIGHLY_UNUSUAL.value,
                    OverallNoveltyLevel.UNUSUAL.value,
                    OverallNoveltyLevel.NOVEL_COMBINATION.value,
                    OverallNoveltyLevel.SLIGHTLY_UNUSUAL.value,
                    "HIGHLY_UNUSUAL",
                    "UNUSUAL",
                    "NOVEL_COMBINATION",
                    "SLIGHTLY_UNUSUAL",
                }:
                    is_anomalous = True
                    novelty_score = 0.90 if "NOVEL" in str(novelty_result.overall_level) else (0.85 if "HIGH" in str(novelty_result.overall_level) else 0.65)
                    explanation = novelty_result.to_compact_summary() if hasattr(novelty_result, "to_compact_summary") else str(novelty_result)


            elif hasattr(novelty_result, "score"):
                if float(novelty_result.score) >= 0.50:
                    is_anomalous = True
                    novelty_score = float(novelty_result.score)
                    explanation = getattr(novelty_result, "explanation", "")

            if is_anomalous:
                priority = SituationPriority.HIGH.value if novelty_score >= 0.70 else SituationPriority.MEDIUM.value
                situations.append(
                    Situation(
                        id=f"sit_unusual_state_{uuid.uuid4().hex[:8]}",
                        type="unusual_state",
                        priority=priority,
                        novelty=novelty_score,
                        status=SituationStatus.OPEN.value,
                        context={
                            "category": "unusual_change",
                            "novelty_score": novelty_score,
                            "explanation": explanation,
                        },
                        evidence=anom_evidence,
                        created_at=ref_dt,
                        updated_at=ref_dt,
                    )
                )

        # Check for routine deviations in state features
        computed_feats = {}
        if isinstance(current_state, CurrentState):
            computed_feats = current_state.computed_features
        elif hasattr(current_state, "features"):
            computed_feats = {k: v.value for k, v in current_state.features.items()}
        elif hasattr(current_state, "get_value"):
            rd = current_state.get_value("routine_deviation")
            if rd is not None:
                computed_feats["routine_deviation"] = rd

        routine_dev = computed_feats.get("routine_deviation", 0.0)
        unusual_obs = [
            obs for obs in observations
            if obs.event_type in {"unusual_state", "routine_change", "anomaly_detected"}
        ]

        if (routine_dev >= self.routine_deviation_threshold or unusual_obs) and not situations:
            evidence = [o.id for o in unusual_obs]
            novelty = max(0.5, float(routine_dev))

            situations.append(
                Situation(
                    id=f"sit_unusual_change_{uuid.uuid4().hex[:8]}",
                    type="unusual_change",
                    priority=SituationPriority.MEDIUM.value,
                    novelty=novelty,
                    status=SituationStatus.OPEN.value,
                    information_required=False,
                    context={
                        "category": "unusual_change",
                        "routine_deviation": routine_dev,
                        "unusual_observations_count": len(unusual_obs),
                    },
                    evidence=evidence,
                    created_at=ref_dt,
                    updated_at=ref_dt,
                )
            )

        return situations

    def _generate_prolonged_activity(
        self,
        current_state: Any,
        timeline: Optional[Timeline],
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []
        computed_feats = {}
        if isinstance(current_state, CurrentState):
            computed_feats = current_state.computed_features
        elif hasattr(current_state, "features"):
            computed_feats = {k: v.value for k, v in current_state.features.items()}
        elif hasattr(current_state, "get_value"):
            dur = current_state.get_value("recent_activity_duration")
            if dur is not None:
                computed_feats["recent_activity_duration"] = dur

        dur = computed_feats.get("recent_activity_duration", 0.0)
        if isinstance(dur, (int, float)) and dur >= self.prolonged_activity_threshold:
            evidence = []
            if timeline and timeline.events:
                evidence = [e.id for e in timeline.events[-3:]]

            situations.append(
                Situation(
                    id=f"sit_prolonged_{uuid.uuid4().hex[:8]}",
                    type="prolonged_activity",
                    priority=SituationPriority.MEDIUM.value,
                    novelty=0.25,
                    status=SituationStatus.OPEN.value,
                    context={
                        "category": "prolonged_activity",
                        "duration_minutes": float(dur),
                        "threshold_minutes": self.prolonged_activity_threshold,
                    },
                    evidence=evidence,
                    created_at=ref_dt,
                    updated_at=ref_dt,
                )
            )

        return situations

    # -------------------------------------------------------------------------
    # 6. Goal Risk Generator
    # -------------------------------------------------------------------------

    def _generate_goal_risks(
        self,
        current_state: Any,
        goals: List[Goal],
        observations: List[Event],
        novelty_result: Optional[NoveltyResult],
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []
        active_goals = [g for g in goals if g.status == GoalStatus.ACTIVE.value]

        if not active_goals:
            return []

        open_issues = current_state.open_issues if isinstance(current_state, CurrentState) else []
        critical_issues = [i for i in open_issues if i.severity in {IssueSeverity.CRITICAL.value, IssueSeverity.HIGH.value}]

        computed_feats = {}
        if isinstance(current_state, CurrentState):
            computed_feats = current_state.computed_features
        elif hasattr(current_state, "features"):
            computed_feats = {k: v.value for k, v in current_state.features.items()}
        elif hasattr(current_state, "get_value"):
            dur = current_state.get_value("recent_activity_duration")
            if dur is not None:
                computed_feats["recent_activity_duration"] = dur

        sleep_mins = computed_feats.get("recent_activity_duration", 480.0)
        has_sleep_deficit = isinstance(sleep_mins, (int, float)) and sleep_mins < 300.0

        for goal in active_goals:
            if goal.priority in {GoalPriority.CRITICAL.value, GoalPriority.HIGH.value}:
                risk_factors = []
                evidence = [goal.id]

                if critical_issues:
                    risk_factors.append(f"Blocked by {len(critical_issues)} high-severity issue(s)")
                    evidence.extend([i.id for i in critical_issues])

                if has_sleep_deficit and any(k in goal.name.lower() for k in ["run", "workout", "marathon", "training", "fitness"]):
                    risk_factors.append("Acute sleep deficit conflicts with high-intensity training goal")

                # Leverage GoalEngine if available
                if self.goal_engine:
                    dep_info = self.goal_engine.check_dependencies(goal, active_goals)
                    if dep_info.get("is_blocked"):
                        risk_factors.append(f"Unmet dependencies: {', '.join(dep_info['unmet_dependencies'])}")
                        evidence.extend(dep_info["unmet_dependencies"])

                    if goal.deadline and goal.deadline < ref_dt:
                        risk_factors.append(f"Goal is overdue past deadline ({format_iso8601(goal.deadline)})")

                if risk_factors:
                    situations.append(
                        Situation(
                            id=f"sit_goal_risk_{uuid.uuid4().hex[:8]}",
                            type="goal_risk",
                            priority=SituationPriority.HIGH.value,
                            novelty=0.65,
                            status=SituationStatus.OPEN.value,
                            information_required=False,
                            context={
                                "category": "goal_risk",
                                "goal_id": goal.id,
                                "goal_name": goal.name,
                                "risk_factors": risk_factors,
                            },
                            evidence=evidence,
                            related_goals=[goal.id],
                            created_at=ref_dt,
                            updated_at=ref_dt,
                        )
                    )

        return situations

    # -------------------------------------------------------------------------
    # 7. Opportunity Generator
    # -------------------------------------------------------------------------

    def _generate_opportunities(
        self,
        current_state: Any,
        goals: List[Goal],
        patterns: List[Pattern],
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []
        active_goals = [g for g in goals if g.status == GoalStatus.ACTIVE.value]

        if not active_goals:
            return []

        focus_patterns = [p for p in patterns if "focus" in p.description.lower() or "morning" in p.description.lower()]

        upcoming_events = current_state.upcoming_events if isinstance(current_state, CurrentState) else []
        has_morning_meeting = any(
            evt.start_time.hour < 12 and evt.start_time.date() > ref_dt.date()
            for evt in upcoming_events
        )

        if focus_patterns and not has_morning_meeting:
            top_goal = active_goals[0]
            pat = focus_patterns[0]
            situations.append(
                Situation(
                    id=f"sit_opportunity_{uuid.uuid4().hex[:8]}",
                    type="opportunity",
                    priority=SituationPriority.LOW.value,
                    novelty=0.20,
                    status=SituationStatus.OPEN.value,
                    information_required=False,
                    context={
                        "category": "opportunity",
                        "opportunity_type": "open_morning_deep_work",
                        "aligned_goal": top_goal.name,
                        "supporting_pattern": pat.description,
                    },
                    evidence=[top_goal.id, pat.id],
                    related_goals=[top_goal.id],
                    created_at=ref_dt,
                    updated_at=ref_dt,
                )
            )

        return situations

    # -------------------------------------------------------------------------
    # 8. Information Gap Generator
    # -------------------------------------------------------------------------

    def _generate_information_gaps(
        self,
        observations: List[Event],
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []

        for obs in observations[-15:]:
            payload = obs.payload if isinstance(obs.payload, dict) else {}
            evidence_data = payload.get("evidence", {}) if isinstance(payload.get("evidence"), dict) else {}
            summary = payload.get("summary", "")

            referenced_doc = evidence_data.get("referenced_document") or evidence_data.get("attachment")
            missing_details = evidence_data.get("missing_context") or "missing" in summary.lower()

            if referenced_doc or missing_details:
                target_str = (
                    f"Retrieve referenced document '{referenced_doc}' from Google Drive or query thread for missing attachments."
                    if referenced_doc
                    else "Investigate communication thread to resolve missing context details."
                )

                situations.append(
                    Situation(
                        id=f"sit_info_gap_{uuid.uuid4().hex[:8]}",
                        type="information_gap",
                        priority=SituationPriority.MEDIUM.value,
                        novelty=0.35,
                        status=SituationStatus.OPEN.value,
                        information_required=True,
                        investigation_target=target_str,
                        context={
                            "category": "information_gap",
                            "source_observation_id": obs.id,
                            "source": obs.source,
                            "referenced_item": referenced_doc,
                            "summary": summary,
                        },
                        evidence=[obs.id],
                        created_at=ref_dt,
                        updated_at=ref_dt,
                    )
                )

        return situations

    # -------------------------------------------------------------------------
    # 7. External Dependency Risk Generator
    # -------------------------------------------------------------------------

    def _generate_external_dependency_risks(
        self,
        current_state: Any,
        observations: List[Event],
        goals: List[Goal],
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []
        open_issues = current_state.open_issues if isinstance(current_state, CurrentState) else []
        for issue in open_issues:
            desc_lower = issue.description.lower()
            if any(k in desc_lower for k in ["waiting on", "dependency", "blocked by", "external", "third party", "vendor", "partner"]):
                situations.append(
                    Situation(
                        id=f"sit_dep_risk_{uuid.uuid4().hex[:8]}",
                        type=StandardSituationCategory.EXTERNAL_DEPENDENCY_RISK.value,
                        priority=SituationPriority.HIGH.value if issue.severity in {IssueSeverity.CRITICAL.value, IssueSeverity.HIGH.value} else SituationPriority.MEDIUM.value,
                        novelty=0.45,
                        status=SituationStatus.OPEN.value,
                        information_required=True,
                        investigation_target=f"Check communication channels for updates on external blocker: '{issue.description}'.",
                        context={
                            "category": "external_dependency_risk",
                            "issue_id": issue.id,
                            "description": issue.description,
                            "severity": issue.severity,
                        },
                        evidence=[issue.id],
                        created_at=ref_dt,
                        updated_at=ref_dt,
                    )
                )

        # Also inspect recent observations for blocked external communications
        for obs in observations[-10:]:
            payload = obs.payload if isinstance(obs.payload, dict) else {}
            summary = payload.get("summary", "").lower()
            if any(k in summary for k in ["waiting on response", "blocked by vendor", "pending external approval"]):
                situations.append(
                    Situation(
                        id=f"sit_dep_risk_{uuid.uuid4().hex[:8]}",
                        type=StandardSituationCategory.EXTERNAL_DEPENDENCY_RISK.value,
                        priority=SituationPriority.MEDIUM.value,
                        novelty=0.40,
                        status=SituationStatus.OPEN.value,
                        information_required=True,
                        investigation_target="Query external communication threads for overdue dependency resolution.",
                        context={
                            "category": "external_dependency_risk",
                            "observation_id": obs.id,
                            "summary": payload.get("summary"),
                        },
                        evidence=[obs.id],
                        created_at=ref_dt,
                        updated_at=ref_dt,
                    )
                )

        return situations

    # -------------------------------------------------------------------------
    # 8. Novel Pattern Generator
    # -------------------------------------------------------------------------

    def _generate_novel_patterns(
        self,
        patterns: List[Pattern],
        hypotheses: List[Pattern],
        ref_dt: datetime,
    ) -> List[Situation]:
        situations: List[Situation] = []
        for pat in hypotheses:
            if getattr(pat, "support_count", 0) >= 3 or getattr(pat, "status", "") in {"hypothesis", "active"}:
                situations.append(
                    Situation(
                        id=f"sit_novel_pat_{uuid.uuid4().hex[:8]}",
                        type=StandardSituationCategory.NOVEL_PATTERN.value,
                        priority=SituationPriority.LOW.value,
                        novelty=0.75,
                        status=SituationStatus.OPEN.value,
                        information_required=False,
                        context={
                            "category": "novel_pattern",
                            "pattern_id": pat.id,
                            "pattern_description": pat.description,
                            "support_count": getattr(pat, "support_count", 1),
                        },
                        evidence=[pat.id],
                        created_at=ref_dt,
                        updated_at=ref_dt,
                    )
                )
        return situations

    # -------------------------------------------------------------------------
    # Stage 3: Cross-Domain State Analysis
    # -------------------------------------------------------------------------

    def _analyze_cross_domain_state(
        self,
        current_state: Any,
        observations: List[Event],
        goals: List[Goal],
        ref_dt: datetime,
    ) -> Dict[str, Any]:
        """
        Performs cross-domain state analysis across disparate domains
        (e.g., calendar density, biometrics/recovery, task commitments, communication volume, external signals).
        Returns domain interaction descriptors and multi-domain collision signals.
        """
        active_domains: Dict[str, Any] = {}

        # 1. State features
        feats: Dict[str, Any] = {}
        if isinstance(current_state, CurrentState):
            feats = current_state.computed_features
        elif hasattr(current_state, "features"):
            feats = {k: v.value for k, v in current_state.features.items()}
        elif hasattr(current_state, "get_value"):
            for k in ["recent_activity_duration", "sleep_duration", "workload_index", "stress_score"]:
                val = current_state.get_value(k)
                if val is not None:
                    feats[k] = val

        # 2. Extract domain signals from features
        for k, v in feats.items():
            if any(term in k for term in ["sleep", "recovery", "heart", "hrv", "biometric"]):
                active_domains["biometrics"] = {"feature": k, "value": v}
            elif any(term in k for term in ["workload", "meeting", "calendar_density", "activity"]):
                active_domains["workload"] = {"feature": k, "value": v}
            elif any(term in k for term in ["travel", "commute", "flight", "transit", "location"]):
                active_domains["mobility"] = {"feature": k, "value": v}
            elif any(term in k for term in ["weather", "environment", "ambient", "temperature"]):
                active_domains["environment"] = {"feature": k, "value": v}

        # 3. Extract domain signals from observations
        for obs in observations:
            obs_type = getattr(obs, "observation_type", getattr(obs, "event_type", ""))
            src = getattr(obs, "source", "")
            if src in {"gmail", "slack", "messages", "communication"} or "email" in obs_type or "message" in obs_type:
                active_domains["communication"] = {"source": src, "last_obs": obs.id}
            elif src in {"calendar", "gcal", "meet"} or "calendar" in obs_type or "meeting" in obs_type:
                active_domains["schedule"] = {"source": src, "last_obs": obs.id}
            elif src in {"drive", "filesystem", "github", "code"} or "doc" in obs_type or "code" in obs_type:
                active_domains["artifacts"] = {"source": src, "last_obs": obs.id}
            elif "unusual" in obs_type or "novel" in obs_type or "anomaly" in obs_type:
                active_domains["anomalies"] = {"source": src, "last_obs": obs.id, "type": obs_type}

        # 4. Extract domain signals from commitments / issues
        if isinstance(current_state, CurrentState):
            if current_state.current_commitments:
                active_domains["commitments"] = len(current_state.current_commitments)
            if current_state.open_issues:
                active_domains["open_issues"] = len(current_state.open_issues)

        return {
            "active_domains": active_domains,
            "domain_count": len(active_domains),
            "features": feats,
        }

    # -------------------------------------------------------------------------
    # Stage 4: New Situation Discovery (NOVEL_SITUATION)
    # -------------------------------------------------------------------------

    def _discover_new_situations(
        self,
        current_state: Any,
        observations: List[Event],
        novelty_result: Optional[NoveltyResult],
        goals: List[Goal],
        existing_candidate_categories: Set[str],
        ref_dt: datetime,
    ) -> List[Situation]:
        """
        Discovers new situations when a meaningful combination of state signals is detected
        that does NOT match any predefined candidate category primitive.
        Synthesizes NOVEL_SITUATION dynamically without requiring hardcoded rules for the exact scenario.
        """
        situations: List[Situation] = []

        # 1. Check novelty detector output
        novelty_score = 0.0
        novelty_explanation = ""
        novelty_type_str = "unfamiliar_combination"
        is_novel_by_detector = False

        if novelty_result:
            if hasattr(novelty_result, "overall_level"):
                if novelty_result.overall_level in {OverallNoveltyLevel.NOVEL_COMBINATION.value, "NOVEL_COMBINATION"}:
                    is_novel_by_detector = True
                    novelty_score = 0.90
                elif novelty_result.overall_level in {OverallNoveltyLevel.HIGHLY_UNUSUAL.value, "HIGHLY_UNUSUAL"}:
                    is_novel_by_detector = True
                    novelty_score = 0.85
                elif novelty_result.overall_level in {OverallNoveltyLevel.UNUSUAL.value, "UNUSUAL", OverallNoveltyLevel.SLIGHTLY_UNUSUAL.value, "SLIGHTLY_UNUSUAL"}:
                    is_novel_by_detector = True
                    novelty_score = 0.65
                novelty_explanation = novelty_result.to_compact_summary() if hasattr(novelty_result, "to_compact_summary") else str(novelty_result)
                novelty_type_str = str(novelty_result.overall_level)
            elif hasattr(novelty_result, "score"):
                novelty_score = float(novelty_result.score)
                is_novel_by_detector = novelty_score >= self.novelty_threshold
                novelty_explanation = getattr(novelty_result, "explanation", "Statistical anomaly detected")
                novelty_type_str = getattr(novelty_result, "novelty_type", "anomaly")

        # 2. Perform cross-domain state analysis
        cross_domain_analysis = self._analyze_cross_domain_state(
            current_state=current_state,
            observations=observations,
            goals=goals,
            ref_dt=ref_dt,
        )

        active_domains = cross_domain_analysis["active_domains"]
        domain_count = cross_domain_analysis["domain_count"]

        has_anomalous_collision = False
        collision_reasons = []

        if "anomalies" in active_domains:
            has_anomalous_collision = True
            collision_reasons.append("Unclassified anomalous observation signal interacting with active state")

        feats = cross_domain_analysis.get("features", {})
        high_deviation_feats = [
            k for k, v in feats.items()
            if isinstance(v, (int, float)) and abs(float(v)) >= 2.0
        ]
        if domain_count >= 2 and is_novel_by_detector and high_deviation_feats:
            has_anomalous_collision = True
            collision_reasons.append(f"Multi-domain interaction across {list(active_domains.keys())} with feature deviations {high_deviation_feats}")

        # 3. Check for unclassified / unmatched combinations when no predefined primitive triggered
        unhandled_observations = []
        handled_obs_types = {
            "email_received", "task_created", "action_item", "calendar_event",
            "meeting_decision", "app_focus", "activity_observed", "signal_observed",
            "unusual_state", "location_ping", "location_update", "routine_deviation",
            "newsletter_received", "system_ping", "metric_report", "notification",
            "routine_event", "info_event",
        }
        for obs in observations:
            obs_type = getattr(obs, "observation_type", getattr(obs, "event_type", ""))
            if obs_type and obs_type not in handled_obs_types:
                unhandled_observations.append(obs)

        has_unmatched_combination = (
            len(existing_candidate_categories) == 0
            and len(observations) >= 1
            and (len(unhandled_observations) >= 1 or (domain_count >= 2 and is_novel_by_detector))
        )

        if is_novel_by_detector or has_anomalous_collision or has_unmatched_combination:
            evidence_ids: List[str] = []
            for obs in observations[-5:]:
                if hasattr(obs, "id") and obs.id:
                    evidence_ids.append(obs.id)
            if hasattr(current_state, "open_issues"):
                evidence_ids.extend([i.id for i in current_state.open_issues[:3]])
            if hasattr(current_state, "current_commitments"):
                evidence_ids.extend([c.id for c in current_state.current_commitments[:3]])

            final_score = max(novelty_score, 0.70 if has_anomalous_collision else (0.65 if is_novel_by_detector else 0.60))
            explanation_text = (
                novelty_explanation
                or "; ".join(collision_reasons)
                or f"Unclassified multi-signal combination across {len(observations)} observations without matching predefined category"
            )
            context_dict = {
                "category": StandardSituationCategory.NOVEL_SITUATION.value,
                "novelty_score": final_score,
                "novelty_type": novelty_type_str,
                "cross_domain_factors": list(active_domains.keys()),
                "explanation": explanation_text,
                "contributing_features": feats,
                "unhandled_observation_count": len(unhandled_observations),
            }

            situations.append(
                Situation(
                    id=f"sit_novel_{uuid.uuid4().hex[:8]}",
                    type=StandardSituationCategory.NOVEL_SITUATION.value,
                    priority=SituationPriority.HIGH.value if final_score >= 0.8 else SituationPriority.MEDIUM.value,
                    novelty=final_score,
                    status=SituationStatus.OPEN.value,
                    information_required=True,
                    investigation_target="Investigate multi-domain anomalous state combination across relevant Hermes capabilities.",
                    context=context_dict,
                    evidence=list(set(evidence_ids)),
                    created_at=ref_dt,
                    updated_at=ref_dt,
                )
            )

        return situations

    # -------------------------------------------------------------------------
    # Convenience World Model Evaluator
    # -------------------------------------------------------------------------

    def evaluate_world_model(
        self,
        world_model: Any,
        reference_time: Optional[datetime] = None,
    ) -> SituationEvaluation:
        """
        Convenience method to evaluate candidate situations directly against a PersonalWorldModel instance.
        """
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        current_state = world_model.get_current_state(reference_time=ref_dt)
        timeline = world_model.timeline_engine.get_last_n_hours(48, reference_time=ref_dt)
        active_goals = world_model.goal_store.list_active_goals()
        known_patterns = [
            Pattern.from_dict(p) if isinstance(p, dict) else p
            for p in world_model.get_known_patterns()
        ]
        emerging_hypotheses = [
            Pattern.from_dict(p) if isinstance(p, dict) else p
            for p in world_model.get_emerging_hypotheses()
        ]

        return self.evaluate(
            current_state=current_state,
            timeline=timeline,
            goals=active_goals,
            recent_observations=timeline.events,
            known_patterns=known_patterns,
            emerging_hypotheses=emerging_hypotheses,
            reference_time=ref_dt,
        )

