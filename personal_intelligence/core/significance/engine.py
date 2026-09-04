"""
Deterministic Personal Significance Engine.

Answers the fundamental question:
"Does this change matter to this person?"

Evaluates:
  - Active goal relevance and priority weighting
  - Commitment relevance and deadline proximity
  - Dependency impact (blockers for active milestones)
  - Current focus relevance
  - Novelty divergence
  - Known pattern regularities
  - Cross-domain interactions
  - Potential consequences and actionability

Produces categorical results (NOT_SIGNIFICANT, LOW, MEDIUM, HIGH, CRITICAL)
without fake numeric probabilities or LLM dependencies.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Union

from personal_intelligence.core.events.models import Event, ensure_timezone_aware
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.novelty.models import NoveltyResult
from personal_intelligence.core.patterns.models import Pattern
from personal_intelligence.core.significance.matching import GoalMatcher
from personal_intelligence.core.significance.models import SignificanceAssessment, SignificanceLevel
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.core.world.changes import MeaningfulChange
from personal_intelligence.core.world.models import Commitment, CommitmentStatus, OpenIssue


class PersonalSignificanceEngine:
    """
    Deterministic Personal Significance Evaluator.
    Determines whether a state change, observation, or situation is personally meaningful.
    """

    def __init__(
        self,
        imminent_deadline_hours: float = 6.0,
        soon_deadline_hours: float = 24.0,
        upcoming_deadline_hours: float = 72.0,
        goal_matcher: Optional[GoalMatcher] = None,
    ) -> None:
        self.imminent_deadline_hours = imminent_deadline_hours
        self.soon_deadline_hours = soon_deadline_hours
        self.upcoming_deadline_hours = upcoming_deadline_hours
        self.goal_matcher = goal_matcher or GoalMatcher()

    def evaluate_change(
        self,
        change: MeaningfulChange,
        active_goals: Optional[List[Goal]] = None,
        commitments: Optional[List[Commitment]] = None,
        open_issues: Optional[List[OpenIssue]] = None,
        novelty_result: Optional[NoveltyResult] = None,
        current_state: Optional[StateRepresentation] = None,
        patterns: Optional[List[Pattern]] = None,
        reference_time: Optional[datetime] = None,
    ) -> SignificanceAssessment:
        """
        Evaluates the personal significance of a detected cross-domain change.
        """
        now = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        goals = active_goals or []
        commits = commitments or []
        issues = open_issues or []
        pats = patterns or []
        reasons: List[str] = []
        cross_domains: List[str] = []

        goal_rel = "none"
        commit_rel = "none"
        deadline_prox = "none"
        novelty_imp = "normal"
        actionability = "none"

        # 1. Goal Relevance (using multi-strategy matcher)
        change_text = f"{change.what_changed} {change.why_it_matters} {' '.join(change.evidence)}".lower()
        matched_high_goals = []
        matched_critical_goals = []
        matched_other_goals = []
        for g in goals:
            g_desc = getattr(g, "description", "") or ""
            g_tags = getattr(g, "tags", None)
            is_rel, score, match_reason = self.goal_matcher.is_relevant(
                goal_name=g.name,
                goal_description=g_desc,
                goal_tags=g_tags,
                context_text=change_text,
            )
            if is_rel:
                prio = getattr(g, "priority", "medium")
                if prio in (GoalPriority.CRITICAL.value, "critical"):
                    matched_critical_goals.append(g.name)
                elif prio in (GoalPriority.HIGH.value, "high"):
                    matched_high_goals.append(g.name)
                else:
                    matched_other_goals.append(g.name)

        if matched_critical_goals:
            goal_rel = "critical"
            reasons.append(f"Directly affects critical goal(s): {', '.join(matched_critical_goals)}")
        elif matched_high_goals:
            goal_rel = "high"
            reasons.append(f"Directly affects high-priority goal(s): {', '.join(matched_high_goals)}")
        elif matched_other_goals:
            goal_rel = "medium" if any(getattr(g, "priority", "") == GoalPriority.MEDIUM.value for g in goals if g.name in matched_other_goals) else "low"
            reasons.append(f"Relates to active goal(s): {', '.join(matched_other_goals)}")
        else:
            goal_rel = "none"

        # 2. Commitment Relevance & Deadline Proximity
        overdue_commits = []
        imminent_commits = []
        soon_commits = []
        for c in commits:
            if c.status in (CommitmentStatus.PENDING.value, CommitmentStatus.IN_PROGRESS.value):
                c_desc = c.description.lower()
                is_related = any(term in change_text for term in c_desc.split() if len(term) > 3) or c_desc in change_text
                if is_related or change.domain == "commitment":
                    if c.due_at:
                        time_left = c.due_at - now
                        if time_left < timedelta(0):
                            overdue_commits.append(c.description)
                        elif time_left <= timedelta(hours=self.imminent_deadline_hours):
                            imminent_commits.append(c.description)
                        elif time_left <= timedelta(hours=self.soon_deadline_hours):
                            soon_commits.append(c.description)

        if overdue_commits:
            commit_rel = "critical"
            deadline_prox = "overdue"
            reasons.append(f"Related commitment is overdue: {overdue_commits[0]}")
        elif imminent_commits:
            commit_rel = "high"
            deadline_prox = "imminent_<6h"
            reasons.append(f"Commitment due within {int(self.imminent_deadline_hours)}h: {imminent_commits[0]}")
        elif soon_commits:
            commit_rel = "medium"
            deadline_prox = "soon_<24h"
            reasons.append(f"Commitment due within 24h: {soon_commits[0]}")

        # 3. Novelty Impact
        if novelty_result:
            level = getattr(novelty_result, "overall_level", "NORMAL")
            if level == "NOVEL_COMBINATION":
                novelty_imp = "novel_combination"
                reasons.append("Statistically novel multi-domain feature combination detected")
            elif level == "HIGHLY_UNUSUAL":
                novelty_imp = "highly_unusual"
                reasons.append("Highly unusual baseline deviation (z-score > 2.5)")
            elif level == "UNUSUAL":
                novelty_imp = "unusual"

        # 4. Cross-Domain Interactions
        if change.domain and change.domain != "general":
            cross_domains.append(change.domain)
        if any(w in change_text for w in ["flight", "train", "travel", "commute"]):
            cross_domains.append("mobility")
        if any(w in change_text for w in ["meeting", "calendar", "call"]):
            cross_domains.append("calendar")
        if any(w in change_text for w in ["deadline", "task", "jira", "pr"]):
            cross_domains.append("work")
        if any(w in change_text for w in ["sleep", "hrv", "fatigue"]):
            cross_domains.append("health")

        cross_domains = list(dict.fromkeys(cross_domains))
        if len(cross_domains) >= 2:
            reasons.append(f"Cross-domain interaction between {', '.join(cross_domains)}")

        # 5. Actionability Determination
        if "what_may_happen_next" in change.__dict__ and change.what_may_happen_next:
            if commit_rel in ("high", "critical") or goal_rel in ("high", "critical"):
                actionability = "high"
            elif commit_rel == "medium" or goal_rel == "medium":
                actionability = "medium"
            else:
                actionability = "low"

        # 5b. Pattern Regularities (Active/Supported patterns matching context)
        matching_patterns = []
        for p in pats:
            st = getattr(p, "status", "ACTIVE")
            if isinstance(st, str) and st.upper() in ("ACTIVE", "SUPPORTED"):
                p_desc = getattr(p, "description", "").lower()
                if any(w in change_text for w in p_desc.split() if len(w) > 4):
                    matching_patterns.append(p)
                    ctx_stmt = p.to_context_statement() if hasattr(p, "to_context_statement") else p_desc
                    reasons.append(f"Contextualized by learned pattern: {ctx_stmt}")

        # 6. Final Deterministic Categorical Synthesis
        if goal_rel == "critical" or commit_rel == "critical" or (deadline_prox == "imminent_<6h" and actionability == "high"):
            sig_level = SignificanceLevel.CRITICAL.value
        elif goal_rel == "high" or commit_rel == "high" or deadline_prox in ("imminent_<6h", "soon_<24h") or novelty_imp in ("novel_combination", "highly_unusual") or (goal_rel == "medium" and len(matching_patterns) > 0):
            sig_level = SignificanceLevel.HIGH.value
        elif goal_rel == "medium" or commit_rel == "medium" or len(cross_domains) >= 2 or novelty_imp == "unusual" or len(matching_patterns) > 0:
            sig_level = SignificanceLevel.MEDIUM.value
        elif len(change.evidence) > 0 and (goal_rel != "none" or commit_rel != "none"):
            sig_level = SignificanceLevel.LOW.value
        else:
            sig_level = SignificanceLevel.NOT_SIGNIFICANT.value

        consequence = change.what_may_happen_next or "No immediate consequence projected."

        return SignificanceAssessment(
            level=sig_level,
            reasons=reasons or ["Routine background observation."],
            goal_relevance=goal_rel,
            commitment_relevance=commit_rel,
            deadline_proximity=deadline_prox,
            novelty_impact=novelty_imp,
            cross_domain_impact=cross_domains,
            actionability=actionability,
            consequence_summary=consequence,
            timestamp=now,
        )

    def evaluate_situation(
        self,
        situation_type: str,
        situation_priority: str,
        evidence_count: int,
        novelty_score: float = 0.0,
        has_information_gap: bool = False,
        goals: Optional[List[Goal]] = None,
        patterns: Optional[List[Pattern]] = None,
        reference_time: Optional[datetime] = None,
    ) -> SignificanceAssessment:
        """
        Evaluates the significance of a candidate or active situation directly.
        """
        now = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        prio = str(situation_priority).lower()
        stype = str(situation_type).lower()
        reasons: List[str] = []
        pats = patterns or []

        # Check matching patterns
        matching_patterns = []
        schedule_syns = {"meeting", "meetings", "calendar", "schedule", "deadline", "deadlines", "delay", "delayed", "conflict"}
        health_syns = {"sleep", "fatigue", "recovery", "health", "workout", "exercise", "hrv", "strain"}
        transit_syns = {"transit", "flight", "commute", "travel", "train", "uber"}

        for p in pats:
            st = getattr(p, "status", "ACTIVE")
            if isinstance(st, str) and st.upper() != "INACTIVE":
                p_desc = getattr(p, "description", "").lower()
                p_words = set(p_desc.split())
                stype_words = set(stype.split("_"))

                is_match = (
                    any(w in stype for w in p_words if len(w) > 4)
                    or any(w in p_desc for w in stype_words if len(w) > 3)
                    or stype in p_desc
                    or bool(p_words & schedule_syns and stype_words & schedule_syns)
                    or bool(p_words & health_syns and stype_words & health_syns)
                    or bool(p_words & transit_syns and stype_words & transit_syns)
                )
                if is_match:
                    matching_patterns.append(p)
                    ctx_stmt = p.to_context_statement() if hasattr(p, "to_context_statement") else p_desc
                    reasons.append(f"Contextualized by learned pattern: {ctx_stmt}")

        if prio == "critical" or "critical" in stype:
            return SignificanceAssessment(
                level=SignificanceLevel.CRITICAL.value,
                reasons=[f"Critical priority situation: {situation_type}"] + reasons,
                goal_relevance="high",
                actionability="high",
                consequence_summary="Immediate attention required to prevent milestone or commitment breach.",
                timestamp=now,
            )

        is_high_novelty_actionable = (novelty_score >= 0.75 and (prio not in ("low", "informational", "none") or bool(goals)))
        if prio == "high" or is_high_novelty_actionable or has_information_gap or (prio == "medium" and len(matching_patterns) > 0):
            if has_information_gap:
                reasons.append("Unresolved information gap requires investigation")
            if is_high_novelty_actionable and novelty_score >= 0.75:
                reasons.append(f"Elevated novelty score ({novelty_score:.2f})")
            if prio == "high":
                reasons.append(f"High-priority situation: {situation_type}")
            elif len(matching_patterns) > 0:
                reasons.append(f"Escalated by matching learned regularities ({len(matching_patterns)} patterns)")

            return SignificanceAssessment(
                level=SignificanceLevel.HIGH.value,
                reasons=reasons or [f"High-priority situation: {situation_type}"],
                goal_relevance="high" if goals else "medium",
                actionability="high" if has_information_gap else "medium",
                consequence_summary="May escalate without situational attention or investigation.",
                timestamp=now,
            )

        if prio == "medium" or evidence_count >= 2 or len(matching_patterns) > 0:
            return SignificanceAssessment(
                level=SignificanceLevel.MEDIUM.value,
                reasons=[f"Medium priority situation: {situation_type}"] + reasons,
                goal_relevance="medium" if goals else "none",
                actionability="medium",
                consequence_summary="Moderate situational importance for upcoming digest or check-in.",
                timestamp=now,
            )

        if prio in ("low", "informational", "none") and not has_information_gap and not goals:
            return SignificanceAssessment(
                level=SignificanceLevel.NOT_SIGNIFICANT.value,
                reasons=["Low urgency routine situation with no active goal impact."],
                goal_relevance="none",
                actionability="none",
                consequence_summary="Routine situational observation; no reasoning warranted.",
                timestamp=now,
            )

        return SignificanceAssessment(
            level=SignificanceLevel.LOW.value,
            reasons=["Low urgency routine situation."],
            goal_relevance="low",
            actionability="low",
            consequence_summary="Routine situational observation.",
            timestamp=now,
        )
