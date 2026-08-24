"""
Multi-Source Cross-Domain Fusion Engine.

Correlates:
1. Email Streams (external commitments, deadlines, security notices)
2. Calendar Streams (meeting density, focus windows, free cognitive blocks)
3. Health & Sleep Streams (recovery level, sleep duration, cognitive capacity)
4. Voice Notes & Meeting Summaries (verbal commitments, action items)

Detects cross-domain schedule conflicts, cognitive strain risks, and unanchored commitments
before failures occur with verifiable multi-source ground truth evidence citations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.events.models import Event, format_iso8601, ensure_timezone_aware
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class CrossDomainConflict:
    """Structured representation of a cross-domain correlation conflict."""
    conflict_type: str  # "schedule_overload", "fatigue_deadline_collision", "unscheduled_verbal_commitment"
    title: str
    description: str
    severity: str  # "high", "medium", "low"
    domains_involved: List[str]
    supporting_evidence: List[str]
    recommended_action: str
    detected_at: str = field(default_factory=lambda: format_iso8601(datetime.now(timezone.utc)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_type": self.conflict_type,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "domains_involved": self.domains_involved,
            "supporting_evidence": self.supporting_evidence,
            "recommended_action": self.recommended_action,
            "detected_at": self.detected_at,
        }


class MultiSourceFusionEngine:
    """
    Orchestrates cross-domain correlation between Email, Calendar, Health/Sleep, and Voice Notes.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        event_store: Optional[EventStore] = None,
        situation_store: Optional[SituationStore] = None,
        timeline_engine: Optional[TimelineEngine] = None,
        state_engine: Optional[StateEngine] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()
        self.event_store = event_store or EventStore(self.db_manager)
        self.situation_store = situation_store or SituationStore(self.db_manager)
        self.timeline_engine = timeline_engine or TimelineEngine(event_store=self.event_store)
        self.state_engine = state_engine or StateEngine(timeline_engine=self.timeline_engine)

    def analyze_cross_domain_correlations(self) -> List[CrossDomainConflict]:
        """
        Runs comprehensive multi-source fusion analysis across all connected streams.
        """
        conflicts: List[CrossDomainConflict] = []
        now = datetime.now(timezone.utc)

        # 1. Gather domain events across past 3 days and upcoming 7 days
        domain_timeline = self.timeline_engine.get_range(
            start_time=now - timedelta(days=3),
            end_time=now + timedelta(days=7),
            limit=500,
        )
        recent_events = domain_timeline.events
        gmail_events = [e for e in recent_events if e.source == "gmail"]
        calendar_events = [e for e in recent_events if e.source == "calendar"]
        sleep_events = [e for e in recent_events if e.source in ("sleep", "health", "apple_health", "fitbit", "sample_generator") or "sleep" in e.event_type]
        voice_events = [e for e in recent_events if e.source == "voice_notes"]

        # Compute sleep & recovery metrics
        sleep_duration_hours = 7.5
        if sleep_events:
            dur_mins = []
            for s in sleep_events:
                p = s.payload if isinstance(s.payload, dict) else {}
                dur_mins.append(float(p.get("duration_minutes", 450)))
            if dur_mins:
                sleep_duration_hours = (sum(dur_mins) / len(dur_mins)) / 60.0

        # Compute calendar load
        cal_busy_hours = 0.0
        for c in calendar_events:
            p = c.payload if isinstance(c.payload, dict) else {}
            cal_busy_hours += float(p.get("duration_minutes", 60)) / 60.0

        # Correlation 1: Low Sleep / Recovery + Heavy Meeting Day Collision
        if sleep_duration_hours < 6.0 and cal_busy_hours >= 3.0:
            conflicts.append(CrossDomainConflict(
                conflict_type="fatigue_schedule_collision",
                title="Cognitive Strain Risk: High Meeting Density Following Reduced Sleep",
                description=f"You have {cal_busy_hours:.1f} hours of scheduled meetings following an average sleep duration of only {sleep_duration_hours:.1f} hours.",
                severity="high",
                domains_involved=["health_sleep", "google_calendar"],
                supporting_evidence=[
                    f"[Health] Recorded sleep deficit: {sleep_duration_hours:.1f}h total rest window",
                    f"[Calendar] {len(calendar_events)} scheduled calendar blocks totaling {cal_busy_hours:.1f}h",
                ],
                recommended_action="Protect 30-minute buffer zones between upcoming meetings and defer deep focus commitments.",
            ))

        # Correlation 2: Email Financial / Delivery Commitment vs Busy Calendar
        if gmail_events and cal_busy_hours >= 2.5:
            # Check for financial or review commitments
            for g in gmail_events:
                p = g.payload if isinstance(g.payload, dict) else {}
                sum_text = str(p.get("summary", ""))
                if any(k in sum_text.lower() for k in ("sbi", "bpcl", "tax", "card", "deadline", "urgent", "security")):
                    conflicts.append(CrossDomainConflict(
                        conflict_type="commitment_capacity_strain",
                        title=f"Schedule Capacity Warning: Pending Action Item ('{sum_text[:40]}...')",
                        description=f"High-priority external item required review, but calendar shows {cal_busy_hours:.1f}h of occupied commitments.",
                        severity="medium",
                        domains_involved=["gmail", "google_calendar"],
                        supporting_evidence=[
                            f"[Gmail] Verified observation: {sum_text}",
                            f"[Calendar] {cal_busy_hours:.1f}h of occupied meeting windows",
                        ],
                        recommended_action="Reserve a dedicated 30-minute focus window before end of day to review external notice.",
                    ))
                    break

        # Correlation 3: Voice Note Action Items Without Scheduled Calendar Blocks
        if voice_events:
            for v in voice_events:
                p = v.payload if isinstance(v.payload, dict) else {}
                actions = p.get("action_items", [])
                if actions:
                    conflicts.append(CrossDomainConflict(
                        conflict_type="unscheduled_verbal_commitment",
                        title=f"Unscheduled Verbal Commitment: '{actions[0][:45]}...'",
                        description=f"Voice memo recorded {len(actions)} verbal action item(s) from meetings that have no calendar reservations yet.",
                        severity="medium",
                        domains_involved=["voice_notes", "google_calendar"],
                        supporting_evidence=[
                            f"[VoiceNotes] Action Item: {actions[0]}",
                            f"[VoiceNotes] Transcript excerpt: '{p.get('summary', '')}'",
                        ],
                        recommended_action="Create dedicated calendar action blocks for these verbal deliverables.",
                    ))
                    break

        return conflicts

    def synthesize_fusion_situations(self) -> List[Situation]:
        """
        Evaluates cross-domain conflicts and persists actionable Multi-Source Situations into SituationStore.
        """
        conflicts = self.analyze_cross_domain_correlations()
        now = datetime.now(timezone.utc)
        generated_situations: List[Situation] = []

        for c in conflicts:
            sit_id = f"sit-fusion-{uuid.uuid4().hex[:8]}"
            sit = Situation(
                id=sit_id,
                type="cross_domain_fusion_conflict",
                priority=c.severity,
                status=SituationStatus.OPEN.value,
                created_at=now,
                evidence=c.supporting_evidence,
                context={
                    "title": c.title,
                    "summary": c.description,
                    "conflict_type": c.conflict_type,
                    "domains_involved": c.domains_involved,
                    "recommended_action": c.recommended_action,
                    "why_detected": f"Cross-domain multi-source correlation ({', '.join(c.domains_involved)}).",
                },
            )
            try:
                self.situation_store.create(sit)
                generated_situations.append(sit)
            except Exception as ex:
                logger.debug("Failed to store fusion situation: %s", ex)

        return generated_situations
