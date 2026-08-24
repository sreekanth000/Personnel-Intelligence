"""
Intervention policy models governing user interruptions, briefing queues, and suppression rules.
Pure categorical model without numerical interruption scores or fake confidence values.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.events.models import format_iso8601


class PolicyAction(str, Enum):
    """
    Categorical policy action returned by InterventionPolicyEngine.
    
    Governs ONLY how and when recommendations/alerts are presented to the user:
    - INTERRUPT: Proactively present recommendation to the user immediately.
    - BRIEFING: Queue recommendation silently for the next scheduled briefing/digest.
    - DEFER: Defer presentation until the user becomes available.
    - SUPPRESS: Suppress presentation due to user context, focus mode, or dismissal cooldown.
    - DISCARD: Silently discard recommendation (low urgency, already notified, stale, or low value).

    NOTE: DISCARD does NOT mean deleting the reasoning episode.
    The reasoning episode is always retained in reasoning_episodes for future empirical learning.
    Only the user-facing recommendation is discarded.
    """
    INTERRUPT = "INTERRUPT"
    BRIEFING = "BRIEFING"
    DEFER = "DEFER"
    SUPPRESS = "SUPPRESS"
    DISCARD = "DISCARD"


class UserContext(str, Enum):
    """Categorical user availability and activity context."""
    AVAILABLE = "available"
    BUSY = "busy"
    MEETING = "meeting"
    DEEP_WORK = "deep_work"
    SLEEP = "sleep"
    DRIVING = "driving"
    DND = "dnd"
    # Aliases
    SLEEPING = "sleep"
    DO_NOT_DISTURB = "dnd"


class DeliveryMode(str, Enum):
    """Channel and urgency mode for delivering recommendations or alerts."""
    SILENT_LOG = "silent_log"           # Log to timeline/state only, do not notify
    DIGEST = "digest"                   # Include in next scheduled user briefing/digest
    NOTIFICATION = "notification"       # Normal priority notification
    URGENT_INTERRUPT = "urgent_interrupt"  # Immediate interrupt bypassing focus mode


class UserFeedback(str, Enum):
    """User response to an intervention, used to learn what works."""
    ACCEPTED = "accepted"
    IGNORED = "ignored"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    HELPFUL = "helpful"
    ANNOYING = "annoying"


@dataclass
class InterruptionBudget:
    """Tracks allowable interruption limits per time window to avoid user fatigue."""
    max_interruptions_per_day: int = 5
    interruptions_today: int = 0
    quiet_hours_start: Optional[str] = "22:00"
    quiet_hours_end: Optional[str] = "07:00"
    respect_focus_mode: bool = True
    last_reset: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class InterventionDecision:
    """
    A policy decision regarding whether, when, and how to reach out to the user.
    Learns over time which interventions succeed based on past feedback.
    """
    situation_id: str
    delivery_mode: DeliveryMode
    reasoning: str
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    recommended_content: Optional[str] = None
    user_feedback: Optional[UserFeedback] = None
    feedback_notes: Optional[str] = None
    feedback_received_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyEvaluationResult:
    """
    Structured outcome of an intervention policy evaluation.
    Pure categorical assessment without numerical confidence scores.
    
    The canonical chain is:
    OBSERVATION -> INFERENCE -> PREDICTION -> RECOMMENDATION -> USER DECISION -> ACTION
    
    The PolicyEvaluationResult governs ONLY the presentation mode of the recommendation
    (INTERRUPT, BRIEFING, DEFER, SUPPRESS, DISCARD). It does not trigger external actions.
    """
    action: str
    reason: str
    urgency: str
    actionability: str
    evidence_strength: str
    user_context: str
    relevance: str = "medium"
    situation_freshness: str = "fresh"
    already_notified: bool = False
    recently_dismissed: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if isinstance(self.action, PolicyAction):
            self.action = self.action.value
        elif isinstance(self.action, str):
            self.action = self.action.strip().upper()

    def to_dict(self) -> Dict[str, Any]:
        """Serializes policy evaluation into a dictionary."""
        return {
            "action": self.action,
            "reason": self.reason,
            "inputs": {
                "urgency": self.urgency,
                "actionability": self.actionability,
                "relevance": self.relevance,
                "evidence_strength": self.evidence_strength,
                "user_context": self.user_context,
                "situation_freshness": self.situation_freshness,
                "already_notified": self.already_notified,
                "recently_dismissed": self.recently_dismissed,
            },
            "timestamp": format_iso8601(self.timestamp),
        }

