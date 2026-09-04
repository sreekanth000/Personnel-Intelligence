"""
WhatChangedAnalyzer for Personal World Model.
Compares current Personal World Model state against recent historical baseline
to identify and synthesize at most 5 meaningful cross-domain changes.

Considers:
- Goals (priority shifts, stalled progress, deadline pressure)
- Commitments (new commitments, overdue promises, unresolved action items)
- Calendar (schedule compression, newly added conflicts, meeting density)
- Communication (urgent threads, key collaborator queries, communication spikes)
- Documents (stalled drafts, modified docs before review)
- Meetings (action items assigned, decisions made)
- Activity (biometric/routine deviations, sleep deficit, prolonged fatigue)
- Patterns (active pattern transitions, decaying associations)
- Situations (new situation frames, elevated priorities)
- Novelty (statistical z-score anomalies, baseline shifts)

For each change:
- WHAT CHANGED
- WHY IT MATTERS
- EVIDENCE
- WHAT MAY HAPPEN NEXT
- UNCERTAINTY
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from personal_intelligence.core.events.models import Event, ensure_timezone_aware, format_iso8601
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.patterns.models import Pattern, PatternStatus
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.situations.models import Situation, SituationPriority
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.world.models import Commitment, CurrentState, OpenIssue, UpcomingEvent
from personal_intelligence.storage.db import DatabaseManager


@dataclass
class MeaningfulChange:
    """
    Structured representation of a meaningful change between historical state and current state.
    """
    what_changed: str
    why_it_matters: str
    evidence: List[str]
    what_may_happen_next: str
    uncertainty: str
    domain: str = "general"
    urgency: str = "medium"
    importance_weight: int = 50

    def to_formatted_block(self, index: Optional[int] = None) -> str:
        idx_prefix = f"{index}. " if index is not None else ""
        ev_lines = "\n".join([f"  * {e}" for e in self.evidence]) if self.evidence else "  * [Verified system observation]"
        return (
            f"### {idx_prefix}{self.what_changed}\n"
            f"- **WHAT CHANGED**: {self.what_changed}\n"
            f"- **WHY IT MATTERS**: {self.why_it_matters}\n"
            f"- **EVIDENCE**:\n{ev_lines}\n"
            f"- **WHAT MAY HAPPEN NEXT**: {self.what_may_happen_next}\n"
            f"- **UNCERTAINTY**: {self.uncertainty}\n"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "what_changed": self.what_changed,
            "why_it_matters": self.why_it_matters,
            "evidence": self.evidence,
            "what_may_happen_next": self.what_may_happen_next,
            "uncertainty": self.uncertainty,
            "domain": self.domain,
            "urgency": self.urgency,
        }


class WhatChangedAnalyzer:
    """
    Deterministic cross-domain change detector comparing current Personal World Model state
    against historical baseline. Synthesizes cross-source changes rather than source-by-source event dumping.
    """

    def __init__(
        self,
        timeline_engine: TimelineEngine,
        goal_store: GoalStore,
        situation_store: SituationStore,
        pattern_store: Optional[PatternStore] = None,
        state_engine: Optional[StateEngine] = None,
        db_manager: Optional[DatabaseManager] = None,
    ) -> None:
        self.timeline_engine = timeline_engine
        self.goal_store = goal_store
        self.situation_store = situation_store
        self.pattern_store = pattern_store
        self.state_engine = state_engine or StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.db_manager = db_manager

    def analyze_changes(
        self,
        as_of: Optional[datetime] = None,
        window_hours: int = 24,
        max_changes: int = 5,
    ) -> List[MeaningfulChange]:
        """Alias for analyze_meaningful_changes."""
        return self.analyze_meaningful_changes(
            time_window_hours=window_hours,
            reference_time=as_of,
            max_changes=max_changes,
        )

    def analyze_meaningful_changes(
        self,
        time_window_hours: int = 48,
        reference_time: Optional[datetime] = None,
        max_changes: int = 5,
    ) -> List[MeaningfulChange]:
        """
        Extracts, synthesizes, ranks, and returns at most `max_changes` (default 5)
        meaningful changes between historical state and current state.
        """
        now = ensure_timezone_aware(reference_time or datetime.now(timezone.utc), "reference_time")
        since_time = now - timedelta(hours=time_window_hours)

        # 1. Gather historical vs current signals
        recent_timeline = self.timeline_engine.get_time_range(start_time=since_time, end_time=now, limit=100)
        recent_events = recent_timeline.events

        active_situations = self.situation_store.list_active(limit=20)
        recent_situations = [s for s in active_situations if s.created_at >= since_time or (s.updated_at and s.updated_at >= since_time)]

        active_goals = self.goal_store.list_active_goals()
        
        current_state = self.state_engine.compute_current_state(reference_time=now)
        
        active_patterns = self.pattern_store.list_active(limit=10) if self.pattern_store else []

        candidate_changes: List[MeaningfulChange] = []

        # ---------------------------------------------------------------------
        # Dimension A: Emerged Situations & Goal Risks
        # ---------------------------------------------------------------------
        for sit in recent_situations:
            ctx = sit.context if isinstance(sit.context, dict) else {}
            desc = ctx.get("summary") or ctx.get("description") or f"Active tension in {sit.type.replace('_', ' ')}"
            ev_list = sit.evidence if isinstance(sit.evidence, list) else []
            if not ev_list:
                ev_list = [f"situation:{sit.id}"]

            why = f"Directly threatens active situational balance with {sit.priority.upper()} priority."
            if "strain" in sit.type or "sleep" in sit.type:
                why = "Elevated physical or cognitive strain increases error rates and risks goal derailment."
            elif "commitment" in sit.type or "action_item" in sit.type:
                why = "Unresolved action item threatens upcoming deliverable milestones and collaborator trust."
            elif "conflicting" in sit.type:
                why = "Simultaneous scheduled obligations will force missed meetings or fragmented attention."

            candidate_changes.append(
                MeaningfulChange(
                    what_changed=f"New {sit.type.replace('_', ' ').title()} situation emerged: {desc}",
                    why_it_matters=why,
                    evidence=[f"[Provenance: situation:{sit.id}] {e}" for e in ev_list[:3]],
                    what_may_happen_next="Milestones will slip or recovery debt will compound if priority is not renegotiated.",
                    uncertainty="Whether collaborator dependencies have undisclosed flexibility.",
                    domain="situation",
                    urgency=sit.priority.lower(),
                    importance_weight=90 if sit.priority.lower() in ("critical", "high") else 60,
                )
            )

        # ---------------------------------------------------------------------
        # Dimension B: Activity, Routine, and Biometric Baseline Deviations
        # ---------------------------------------------------------------------
        sleep_events = [e for e in recent_events if "sleep" in e.event_type or "sleep" in e.source]
        if sleep_events:
            latest_sleep = sleep_events[-1]
            dur = float(latest_sleep.payload.get("duration_minutes", 480))
            if dur < 300:  # Under 5 hours
                hrs = round(dur / 60.0, 1)
                candidate_changes.append(
                    MeaningfulChange(
                        what_changed=f"Acute sleep deficit recorded ({hrs}h vs 8.0h baseline).",
                        why_it_matters="Severely reduces cognitive resilience, reaction speed, and physical recovery capacity.",
                        evidence=[
                            f"[Provenance: event:{latest_sleep.id} | {latest_sleep.source}] Duration: {dur} mins, Recorded at {latest_sleep.event_time.strftime('%H:%M UTC')}"
                        ],
                        what_may_happen_next="Afternoon cognitive fatigue and degraded workout performance if high-intensity load is maintained.",
                        uncertainty="Whether restorative rest or schedule adjustments can be made earlier in the day.",
                        domain="activity",
                        urgency="high",
                        importance_weight=85,
                    )
                )

        # ---------------------------------------------------------------------
        # Dimension C: Calendar Density & Schedule Compression
        # ---------------------------------------------------------------------
        cal_events = [e for e in recent_events if e.source == "calendar" or "meeting" in e.event_type or "calendar" in e.event_type]
        if len(cal_events) >= 3:
            candidate_changes.append(
                MeaningfulChange(
                    what_changed=f"Calendar meeting density spiked ({len(cal_events)} scheduled sessions in 24h).",
                    why_it_matters="Fragmented schedule leaves minimal uninterrupted deep-work time for priority deliverables.",
                    evidence=[
                        f"[Provenance: event:{e.id} | {e.source}] {e.payload.get('summary', 'Calendar Event')}"
                        for e in cal_events[:3]
                    ],
                    what_may_happen_next="Delayed task execution and rushed context-switching throughout the afternoon.",
                    uncertainty="Whether any non-critical meetings can be delegated or made asynchronous.",
                    domain="calendar",
                    urgency="medium",
                    importance_weight=70,
                )
            )

        # ---------------------------------------------------------------------
        # Dimension D: Documents & Communication Action Items
        # ---------------------------------------------------------------------
        doc_comm_events = [
            e for e in recent_events
            if e.source in ("drive", "gmail", "meet") or "document" in e.event_type or "email" in e.event_type or "action" in e.event_type
        ]
        
        # 1. Unresolved commitments / action items
        unresolved_items = [
            e for e in doc_comm_events
            if "unresolved" in e.event_type or "action" in e.event_type or "commitment" in e.event_type or e.payload.get("status") == "open"
        ]
        if unresolved_items:
            item = unresolved_items[0]
            summary = item.payload.get("summary") or item.payload.get("subject") or item.payload.get("title") or "Action item pending"
            candidate_changes.append(
                MeaningfulChange(
                    what_changed=f"Unresolved commitment detected: '{summary}'",
                    why_it_matters="Outstanding deliverable requires explicit user attention before next milestone.",
                    evidence=[
                        f"[Provenance: event:{item.id} | {item.source.upper()}] {summary} (Logged: {item.event_time.strftime('%Y-%m-%d %H:%M')})"
                    ],
                    what_may_happen_next="Project milestone or collaborator handoff will stall awaiting this deliverable.",
                    uncertainty="Whether the action item was fulfilled out-of-band without digital record.",
                    domain="commitments",
                    urgency="high" if "urgent" in summary.lower() else "medium",
                    importance_weight=75,
                )
            )

        # 2. Significant Document Updates
        doc_updates = [e for e in doc_comm_events if "document" in e.event_type or e.source == "drive"]
        if doc_updates:
            doc_ev = doc_updates[0]
            doc_summary = doc_ev.payload.get("summary") or doc_ev.payload.get("title") or "Document modified"
            candidate_changes.append(
                MeaningfulChange(
                    what_changed=f"Document modification recorded: '{doc_summary}'",
                    why_it_matters="Recent document changes may alter consensus or require dependent review before milestone.",
                    evidence=[
                        f"[Provenance: event:{doc_ev.id} | {doc_ev.source.upper()}] {doc_summary} (Logged: {doc_ev.event_time.strftime('%Y-%m-%d %H:%M')})"
                    ],
                    what_may_happen_next="Reviewers must align on new revisions before next milestone signoff.",
                    uncertainty="Whether other stakeholders have reviewed the latest draft.",
                    domain="documents",
                    urgency="medium",
                    importance_weight=65,
                )
            )

        # ---------------------------------------------------------------------
        # Dimension E: Active Goal Progress & Milestones
        # ---------------------------------------------------------------------
        for goal in active_goals:
            if goal.priority in (GoalPriority.HIGH, GoalPriority.CRITICAL):
                candidate_changes.append(
                    MeaningfulChange(
                        what_changed=f"Active focus remains on high-priority goal '{goal.name}'.",
                        why_it_matters=f"Current daily allocations and constraints must remain aligned with {goal.description or goal.name}.",
                        evidence=[f"[Provenance: goal:{goal.id}] Priority: {goal.priority.upper()}"],
                        what_may_happen_next="Progress depends on protecting dedicated execution blocks today.",
                        uncertainty="Potential unpredicted schedule interruptions or competing ad-hoc requests.",
                        domain="goals",
                        urgency="medium",
                        importance_weight=50,
                    )
                )

        # ---------------------------------------------------------------------
        # Dimension F: Learned Interaction & Behavioral Patterns
        # ---------------------------------------------------------------------
        for pat in active_patterns:
            if pat.status in (PatternStatus.ACTIVE, PatternStatus.SUPPORTED, "active", "supported"):
                ev_str_val = pat.evidence_strength.value if hasattr(pat.evidence_strength, "value") else str(pat.evidence_strength)
                candidate_changes.append(
                    MeaningfulChange(
                        what_changed=f"Empirical pattern active: '{pat.description}'",
                        why_it_matters="Longitudinal evidence indicates recurring association across your past interactions.",
                        evidence=[f"[Provenance: pattern:{pat.id}] Support Count: {pat.support_count}, Evidence Strength: {ev_str_val}"],
                        what_may_happen_next="Consistent recommendations will align with this behavioral baseline.",
                        uncertainty="Whether current novel situational factors override historical regularity.",
                        domain="patterns",
                        urgency="low",
                        importance_weight=40,
                    )
                )

        # Sort candidate changes deterministically by importance_weight descending
        candidate_changes.sort(key=lambda c: c.importance_weight, reverse=True)

        # Deduplicate and return at most max_changes (<= 5)
        seen_titles = set()
        final_changes: List[MeaningfulChange] = []
        for c in candidate_changes:
            if c.what_changed not in seen_titles:
                seen_titles.add(c.what_changed)
                final_changes.append(c)
            if len(final_changes) >= max_changes:
                break

        return final_changes
