"""
Data models for Personal Significance Assessment.
Evaluates whether a state change, observation, or situation is personally meaningful.
Categorical assessment without fake numeric probabilities.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from personal_intelligence.core.events.models import ensure_timezone_aware, format_iso8601


class SignificanceLevel(str, Enum):
    """Categorical significance classification."""
    NOT_SIGNIFICANT = "not_significant"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SignificanceAssessment:
    """
    Structured outcome of Personal Significance evaluation.
    Answers: "Does this change matter to this person?"
    """
    level: str  # SignificanceLevel enum value
    reasons: List[str] = field(default_factory=list)
    goal_relevance: str = "none"  # none, low, medium, high, critical
    commitment_relevance: str = "none"  # none, low, medium, high, critical
    deadline_proximity: str = "none"  # none, upcoming_<72h, soon_<24h, imminent_<6h
    novelty_impact: str = "normal"  # normal, unusual, highly_unusual, novel_combination
    cross_domain_impact: List[str] = field(default_factory=list)
    actionability: str = "none"  # none, low, medium, high
    consequence_summary: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.timestamp = ensure_timezone_aware(self.timestamp, "SignificanceAssessment timestamp")
        if isinstance(self.level, SignificanceLevel):
            self.level = self.level.value
        else:
            self.level = str(self.level).lower()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "reasons": self.reasons,
            "goal_relevance": self.goal_relevance,
            "commitment_relevance": self.commitment_relevance,
            "deadline_proximity": self.deadline_proximity,
            "novelty_impact": self.novelty_impact,
            "cross_domain_impact": self.cross_domain_impact,
            "actionability": self.actionability,
            "consequence_summary": self.consequence_summary,
            "timestamp": format_iso8601(self.timestamp),
        }
