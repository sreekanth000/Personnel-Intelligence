"""
Deterministic GoalEngine for reasoning about relationships between goals and situations.
Operates purely above GoalStore without LLMs, embeddings, or heuristic black boxes.

Core Responsibilities:
1. Deterministic Goal Priority & Urgency Scoring (User-owned weights + deadline proximity scaling)
2. Goal Deadlines & Lifecycle Tracking
3. Goal Dependency Graph & Blocker Detection
4. Situation-to-Goal Impact Assessment (Resource scarcity, impediment, risk)
5. Goal Conflict & Competition Detection (Time scarcity, energy scarcity, dependency blocks)
6. Goal Relevance & Situational Alignment
7. Goal Progress & Momentum Tracking
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Union
import uuid

from personal_intelligence.core.events.models import ensure_timezone_aware
from personal_intelligence.core.goals.models import (
    Goal,
    GoalConflict,
    GoalConflictType,
    GoalEvaluation,
    GoalImpact,
    GoalImpactType,
    GoalPriority,
    GoalStatus,
)
from personal_intelligence.core.goals.store import GoalStore

if TYPE_CHECKING:
    from personal_intelligence.core.situations.models import Situation
    from personal_intelligence.core.state.models import StateRepresentation
    from personal_intelligence.core.timeline.engine import TimelineEngine
    from personal_intelligence.core.timeline.models import Timeline

logger = logging.getLogger(__name__)

# Base deterministic priority weights (User-owned, deterministic)
PRIORITY_WEIGHTS = {
    GoalPriority.CRITICAL.value: 3.0,
    GoalPriority.HIGH.value: 2.0,
    GoalPriority.MEDIUM.value: 1.0,
    GoalPriority.LOW.value: 0.5,
    GoalPriority.BACKGROUND.value: 0.2,
}


class GoalEngine:
    """
    Deterministic engine that reasons about user goals, deadlines, dependencies,
    resource conflicts, and situational impacts.
    """

    def __init__(
        self,
        goal_store: GoalStore,
        timeline_engine: Optional[TimelineEngine] = None,
    ) -> None:
        self.goal_store = goal_store
        self.timeline_engine = timeline_engine

    # -------------------------------------------------------------------------
    # 1. Deterministic Priority & Urgency
    # -------------------------------------------------------------------------

    def get_effective_priority(
        self,
        goal: Goal,
        reference_time: Optional[datetime] = None,
    ) -> float:
        """
        Computes the effective numeric priority score of a goal.
        Combines deterministic user-defined priority weight with deadline proximity multiplier.
        Does NOT use an LLM or ML.
        """
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        p_val = goal.priority.lower() if isinstance(goal.priority, str) else goal.priority.value
        base_weight = PRIORITY_WEIGHTS.get(p_val, 1.0)

        urgency_multiplier = self.get_urgency_multiplier(goal, ref_dt)
        return round(base_weight * urgency_multiplier, 2)

    def get_urgency_multiplier(
        self,
        goal: Goal,
        reference_time: Optional[datetime] = None,
    ) -> float:
        """
        Calculates a deterministic urgency multiplier based on deadline proximity:
          - Overdue: 2.0x
          - Within 24 hours: 1.6x
          - Within 3 days: 1.3x
          - Within 7 days: 1.1x
          - No deadline or > 7 days: 1.0x
        """
        if not goal.deadline:
            return 1.0

        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        time_diff = (goal.deadline - ref_dt).total_seconds()
        hours_remaining = time_diff / 3600.0

        if hours_remaining < 0:
            return 2.0  # Overdue
        elif hours_remaining <= 24.0:
            return 1.6  # Due today
        elif hours_remaining <= 72.0:
            return 1.3  # Due in 3 days
        elif hours_remaining <= 168.0:
            return 1.1  # Due in a week
        return 1.0

    def get_days_until_deadline(
        self,
        goal: Goal,
        reference_time: Optional[datetime] = None,
    ) -> Optional[float]:
        """Returns days until goal deadline, or None if no deadline."""
        if not goal.deadline:
            return None
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        seconds = (goal.deadline - ref_dt).total_seconds()
        return round(seconds / 86400.0, 2)

    # -------------------------------------------------------------------------
    # 2. Dependency Graph & Blockers
    # -------------------------------------------------------------------------

    def check_dependencies(
        self,
        goal: Goal,
        all_goals: Optional[List[Goal]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates dependencies of a goal.
        A goal is considered blocked if any prerequisite goal is not in COMPLETED status.
        """
        if not goal.dependencies:
            return {
                "is_blocked": False,
                "unmet_dependencies": [],
                "completed_dependencies": [],
                "missing_dependency_ids": [],
            }

        goals_pool = all_goals if all_goals is not None else self.goal_store.list_all_goals()
        goals_by_id = {g.id: g for g in goals_pool}

        unmet = []
        completed = []
        missing = []

        for dep_id in goal.dependencies:
            dep_goal = goals_by_id.get(dep_id)
            if not dep_goal:
                missing.append(dep_id)
                unmet.append(dep_id)
            elif dep_goal.status == GoalStatus.COMPLETED.value:
                completed.append(dep_id)
            else:
                unmet.append(dep_id)

        is_blocked = len(unmet) > 0
        return {
            "is_blocked": is_blocked,
            "unmet_dependencies": unmet,
            "completed_dependencies": completed,
            "missing_dependency_ids": missing,
        }

    # -------------------------------------------------------------------------
    # 3. Goal Relevance to Situation
    # -------------------------------------------------------------------------

    def calculate_relevance(
        self,
        goal: Goal,
        situation: Situation,
        current_state: Optional[StateRepresentation] = None,
    ) -> float:
        """
        Deterministically scores relevance [0.0 to 1.0] of a goal to a situation.
        Matches keywords, domains, linked_goals, tags, and state context.
        """
        # Direct linkage
        if hasattr(situation, "linked_goals") and situation.linked_goals:
            if goal.id in situation.linked_goals or goal.name in situation.linked_goals:
                return 1.0

        score = 0.0

        # Text matching
        goal_text = f"{goal.name} {goal.description} {' '.join(goal.tags)} {goal.domain or ''}".lower()
        sit_summary = ""
        if hasattr(situation, "context_summary") and situation.context_summary:
            sit_summary = str(situation.context_summary).lower()
        elif hasattr(situation, "context") and isinstance(situation.context, dict):
            sit_summary = str(situation.context.get("summary", "") or situation.context.get("category", "")).lower()
        sit_title = str(getattr(situation, "title", "")).lower()
        evidence_str = " ".join(str(e) for e in getattr(situation, "evidence", []))
        situation_text = f"{situation.type} {sit_summary} {sit_title} {evidence_str}".lower()

        # Goal keywords in situation
        goal_words = set(w for w in goal_text.split() if len(w) > 3)
        if goal_words:
            matches = sum(1 for w in goal_words if w in situation_text)
            match_ratio = matches / len(goal_words)
            score += min(0.6, match_ratio * 0.8)

        # Domain overlap heuristics
        training_keywords = {"exercise", "run", "workout", "fitness", "training", "marathon", "sleep", "recovery", "health", "walk"}
        work_keywords = {"architecture", "project", "code", "design", "meeting", "review", "milestone", "deadline", "release", "ship"}

        goal_is_training = any(k in goal_text for k in training_keywords)
        goal_is_work = any(k in goal_text for k in work_keywords)

        sit_is_training = any(k in situation_text for k in training_keywords) or "strain" in situation.type or "sleep" in situation.type
        sit_is_work = any(k in situation_text for k in work_keywords) or "workload" in situation.type or "schedule" in situation.type

        if (goal_is_training and sit_is_training) or (goal_is_work and sit_is_work):
            score += 0.35

        # State overlap if provided
        if current_state:
            ctx_signal = str(current_state.get_value("recent_context_signal", "")).lower()
            act_signal = str(current_state.get_value("active_signal_type", "")).lower()
            if ctx_signal and ctx_signal != "unknown" and ctx_signal in goal_text:
                score += 0.2
            if act_signal and act_signal != "idle" and act_signal in goal_text:
                score += 0.2

        return round(min(1.0, score), 2)

    # -------------------------------------------------------------------------
    # 4. Situation-to-Goal Impact Assessment
    # -------------------------------------------------------------------------

    def evaluate_situation_impact(
        self,
        situation: Situation,
        goals: Optional[List[Goal]] = None,
        current_state: Optional[StateRepresentation] = None,
        reference_time: Optional[datetime] = None,
    ) -> List[GoalImpact]:
        """
        Deterministically evaluates how a situation impacts active user goals.
        Identifies resource competition, schedule conflict risks, energy scarcity,
        or positive alignment.
        """
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        active_goals = goals if goals is not None else self.goal_store.list_active_goals()
        impacts: List[GoalImpact] = []

        sit_type = situation.type.lower()
        sit_summary = ""
        if hasattr(situation, "context_summary") and situation.context_summary:
            sit_summary = str(situation.context_summary).lower()
        elif hasattr(situation, "context") and isinstance(situation.context, dict):
            sit_summary = str(situation.context.get("summary", "") or situation.context.get("category", "")).lower()
        evidence_str = " ".join(str(e) for e in getattr(situation, "evidence", []))
        sit_text = f"{sit_type} {sit_summary} {evidence_str}".lower()

        # Check resource scarcity indicators from situation & state
        is_time_scarcity = any(k in sit_text for k in ["schedule_conflict", "conflicting_commitments", "high_meeting_density", "time_scarcity", "reduced_available_time", "calendar_density", "meeting"])
        is_energy_scarcity = any(k in sit_text for k in ["sleep_deficit", "strain", "fatigue", "prolonged_activity", "exhaustion", "cognitive_physical_strain_risk"])

        if current_state:
            density = current_state.get_value("event_density", 0.0)
            if density and float(density) > 0.08:  # High event density indicates busy/loaded state
                is_time_scarcity = True

        for goal in active_goals:
            relevance = self.calculate_relevance(goal, situation, current_state)
            goal_text = f"{goal.name} {goal.description} {' '.join(goal.tags)}".lower()

            impact_type = GoalImpactType.NEUTRAL.value
            impact_score = 0.0
            reason = "No significant situational friction."
            competing = []

            # 1. Explicit linkage in situation
            if hasattr(situation, "linked_goals") and (goal.id in situation.linked_goals or goal.name in situation.linked_goals):
                impact_type = GoalImpactType.AT_RISK.value
                impact_score = 0.8
                reason = f"Goal '{goal.name}' is explicitly identified as linked to situation '{situation.type}'."
                competing.append(situation.type)

            # 2. Physical/Training goals under energy scarcity (e.g. sleep deficit / high fatigue)
            elif is_energy_scarcity and any(k in goal_text for k in ["exercise", "run", "workout", "fitness", "training", "marathon"]):
                impact_type = GoalImpactType.AT_RISK.value
                impact_score = 0.75
                reason = f"Goal '{goal.name}' requires physical exertion which is contraindicated under current physiological strain / sleep deficit."
                competing.append("energy_scarcity")
                competing.append(situation.type)

            # 3. High-focus/Work goals under high meeting density or time scarcity
            elif is_time_scarcity and any(k in goal_text for k in ["architecture", "project", "code", "deep_work", "writing", "focus", "deliver"]):
                impact_type = GoalImpactType.IMPEDED.value
                impact_score = 0.65
                reason = f"Available time for goal '{goal.name}' is constrained by competing calendar density or schedule commitments."
                competing.append("available_time_scarcity")
                competing.append(situation.type)

            # 4. Dependency blocks
            dep_status = self.check_dependencies(goal, active_goals)
            if dep_status["is_blocked"]:
                impact_type = GoalImpactType.BLOCKED.value
                impact_score = 0.85
                reason = f"Goal '{goal.name}' is blocked by unmet prerequisite dependencies: {dep_status['unmet_dependencies']}."
                competing.append("unmet_dependencies")

            # 5. Overdue / Urgent deadline pressure
            elif goal.deadline and (goal.deadline < ref_dt):
                impact_type = GoalImpactType.AT_RISK.value
                impact_score = 0.9
                reason = f"Goal '{goal.name}' is overdue past deadline ({goal.deadline.isoformat()})."
                competing.append("overdue_deadline")

            # 6. General high relevance
            elif relevance > 0.4:
                impact_type = GoalImpactType.IMPEDED.value
                impact_score = round(relevance * 0.7, 2)
                reason = f"Goal '{goal.name}' aligns with situation context and may experience friction."

            if impact_type != GoalImpactType.NEUTRAL.value or impact_score > 0.0:
                severity = "critical" if impact_score >= 0.8 else ("high" if impact_score >= 0.6 else "medium")
                impacts.append(
                    GoalImpact(
                        goal_id=goal.id,
                        goal_name=goal.name,
                        impact_type=impact_type,
                        impact_score=impact_score,
                        reason=reason,
                        severity=severity,
                        competing_factors=competing,
                        metadata={
                            "relevance": relevance,
                            "effective_priority": self.get_effective_priority(goal, ref_dt),
                        },
                    )
                )

        # Sort by impact_score descending
        impacts.sort(key=lambda imp: (imp.impact_score, imp.metadata.get("effective_priority", 1.0)), reverse=True)
        return impacts

    # -------------------------------------------------------------------------
    # 5. Goal Conflict & Resource Contention Detection
    # -------------------------------------------------------------------------

    def detect_conflicts(
        self,
        goals: Optional[List[Goal]] = None,
        situation: Optional[Situation] = None,
        current_state: Optional[StateRepresentation] = None,
        reference_time: Optional[datetime] = None,
    ) -> List[GoalConflict]:
        """
        Detects resource contention and conflicts among active goals.
        Example:
          - High calendar density / reduced time + Work Goal A (Critical) vs Exercise Goal B (High)
            -> Time scarcity conflict.
          - Dependent Goal B scheduled before prerequisite Goal A completed
            -> Dependency unmet conflict.
        """
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        active_goals = goals if goals is not None else self.goal_store.list_active_goals()
        conflicts: List[GoalConflict] = []

        if len(active_goals) < 1:
            return conflicts

        # 1. Dependency conflicts
        for goal in active_goals:
            dep_info = self.check_dependencies(goal, active_goals)
            if dep_info["is_blocked"]:
                conflicts.append(
                    GoalConflict(
                        conflict_type=GoalConflictType.DEPENDENCY_UNMET.value,
                        goal_ids=[goal.id] + dep_info["unmet_dependencies"],
                        goal_names=[goal.name],
                        severity="high",
                        description=f"Goal '{goal.name}' cannot proceed because dependencies are unmet: {dep_info['unmet_dependencies']}.",
                        competing_resource="dependency_prerequisite",
                        resolution_suggestion=f"Focus on completing prerequisite goals before progressing '{goal.name}'.",
                        metadata={"goal_id": goal.id, "unmet": dep_info["unmet_dependencies"]},
                    )
                )

        # 2. Time & Bandwidth Scarcity conflicts (multiple competing high-priority goals under time pressure)
        is_constrained_time = False
        if situation:
            sit_summary = ""
            if hasattr(situation, "context_summary") and situation.context_summary:
                sit_summary = str(situation.context_summary).lower()
            elif hasattr(situation, "context") and isinstance(situation.context, dict):
                sit_summary = str(situation.context.get("summary", "") or situation.context.get("category", "")).lower()
            evidence_str = " ".join(str(e) for e in getattr(situation, "evidence", []))
            sit_text = f"{situation.type} {sit_summary} {evidence_str}".lower()
            if any(k in sit_text for k in ["schedule_conflict", "conflicting_commitments", "high_meeting_density", "time_scarcity", "reduced_available_time", "calendar"]):
                is_constrained_time = True
        if current_state:
            gp = current_state.get_value("goal_pressure", {})
            if isinstance(gp, dict) and gp.get("pressure_score", 0.0) >= 3.0:
                is_constrained_time = True

        high_priority_goals = [
            g for g in active_goals
            if g.priority in {GoalPriority.CRITICAL.value, GoalPriority.HIGH.value}
        ]

        if is_constrained_time and len(high_priority_goals) >= 2:
            # Sort by effective priority to suggest clear deterministic resolution
            sorted_high = sorted(
                high_priority_goals,
                key=lambda g: self.get_effective_priority(g, ref_dt),
                reverse=True,
            )
            top_goal = sorted_high[0]
            secondary_goals = sorted_high[1:]

            conflicts.append(
                GoalConflict(
                    conflict_type=GoalConflictType.TIME_SCARCITY.value,
                    goal_ids=[g.id for g in sorted_high],
                    goal_names=[g.name for g in sorted_high],
                    severity="high" if any(g.priority == GoalPriority.CRITICAL.value for g in sorted_high) else "medium",
                    description=(
                        f"Time scarcity conflict: {len(sorted_high)} high-priority goals "
                        f"('{top_goal.name}', {', '.join(repr(g.name) for g in secondary_goals)}) "
                        f"compete for limited available time in current schedule."
                    ),
                    competing_resource="available_time",
                    resolution_suggestion=(
                        f"Prioritize higher effective priority goal '{top_goal.name}' "
                        f"(priority score {self.get_effective_priority(top_goal, ref_dt)}) "
                        f"and defer secondary objectives."
                    ),
                    metadata={
                        "top_priority_goal_id": top_goal.id,
                        "secondary_goal_ids": [g.id for g in secondary_goals],
                    },
                )
            )

        return conflicts

    # -------------------------------------------------------------------------
    # 6. Comprehensive Goal Ranking & Evaluation
    # -------------------------------------------------------------------------

    def evaluate_goal(
        self,
        goal: Goal,
        situation: Optional[Situation] = None,
        current_state: Optional[StateRepresentation] = None,
        all_goals: Optional[List[Goal]] = None,
        reference_time: Optional[datetime] = None,
    ) -> GoalEvaluation:
        """Produces a comprehensive deterministic evaluation of a single goal."""
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        eff_priority = self.get_effective_priority(goal, ref_dt)
        urgency = self.get_urgency_multiplier(goal, ref_dt)
        days_left = self.get_days_until_deadline(goal, ref_dt)
        dep_info = self.check_dependencies(goal, all_goals)

        relevance = 0.0
        impact: Optional[GoalImpact] = None
        if situation:
            relevance = self.calculate_relevance(goal, situation, current_state)
            impacts = self.evaluate_situation_impact(situation, [goal], current_state, ref_dt)
            if impacts:
                impact = impacts[0]

        return GoalEvaluation(
            goal_id=goal.id,
            goal_name=goal.name,
            priority=goal.priority,
            status=goal.status,
            effective_priority_score=eff_priority,
            urgency_score=urgency,
            relevance_score=relevance,
            is_blocked=dep_info["is_blocked"],
            unmet_dependencies=dep_info["unmet_dependencies"],
            days_until_deadline=days_left,
            progress=goal.progress,
            impact=impact,
            metadata={"domain": goal.domain, "tags": goal.tags},
        )

    def rank_goals_for_situation(
        self,
        situation: Situation,
        goals: Optional[List[Goal]] = None,
        current_state: Optional[StateRepresentation] = None,
        reference_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ranks active goals in order of situational importance and impact.
        Returns a list of structured goal summaries for Hermes ContextBuilder.
        """
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        active_goals = goals if goals is not None else self.goal_store.list_active_goals()
        evaluations = [
            self.evaluate_goal(g, situation, current_state, active_goals, ref_dt)
            for g in active_goals
        ]

        # Composite ranking key:
        # Score = effective_priority * (1.0 + relevance * 0.5 + (impact.impact_score if impact else 0.0))
        def rank_key(ev: GoalEvaluation) -> float:
            imp_val = ev.impact.impact_score if ev.impact else 0.0
            return ev.effective_priority_score * (1.0 + (ev.relevance_score * 0.5) + imp_val)

        evaluations.sort(key=rank_key, reverse=True)

        results = []
        for ev in evaluations:
            d = ev.to_dict()
            d["composite_rank_score"] = round(rank_key(ev), 2)
            results.append(d)
        return results

    # -------------------------------------------------------------------------
    # 7. Progress & Store Forwarding
    # -------------------------------------------------------------------------

    def estimate_progress(
        self,
        goal: Goal,
        timeline: Optional[Timeline] = None,
    ) -> float:
        """Returns the current validated progress of a goal."""
        return round(float(goal.progress or 0.0), 2)

    def list_active_goals(self) -> List[Goal]:
        """Queries active goals directly from GoalStore."""
        return self.goal_store.list_active_goals()

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        """Retrieves a goal from GoalStore."""
        return self.goal_store.get_goal(goal_id)
