"""
Novelty detection data models and classifications.
Represents statistical divergence of state features against historical baselines.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)


class NoveltyClassification(str, Enum):
    """Classification for individual state feature divergence."""
    NORMAL = "normal"
    UNUSUAL = "unusual"
    HIGHLY_UNUSUAL = "highly_unusual"
    NOVEL_COMBINATION = "novel_combination"


class OverallNoveltyLevel(str, Enum):
    """Overall classification level for the complete state representation."""
    NORMAL = "NORMAL"
    UNUSUAL = "UNUSUAL"
    HIGHLY_UNUSUAL = "HIGHLY_UNUSUAL"
    NOVEL_COMBINATION = "NOVEL_COMBINATION"

    # Backward-compatible alias
    SLIGHTLY_UNUSUAL = "UNUSUAL"


# Alias for concise referencing
NoveltyLevel = OverallNoveltyLevel



@dataclass
class FeatureNoveltyResult:
    """
    Novelty evaluation result for a single state feature dimension.
    """
    feature: str
    current_value: Any
    baseline: Dict[str, Any]
    deviation: float
    classification: str
    explanation: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.classification, NoveltyClassification):
            self.classification = self.classification.value
        elif isinstance(self.classification, str):
            self.classification = self.classification.strip().lower()
        else:
            raise ValueError("FeatureNoveltyResult classification must be a string or NoveltyClassification enum.")

    def is_anomalous(self) -> bool:
        """Returns True if this feature is unusual or highly unusual."""
        return self.classification in (
            NoveltyClassification.UNUSUAL.value,
            NoveltyClassification.HIGHLY_UNUSUAL.value,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes feature novelty result to a dictionary."""
        return {
            "feature": self.feature,
            "current_value": self.current_value,
            "baseline": self.baseline,
            "deviation": self.deviation,
            "classification": self.classification,
            "explanation": self.explanation,
        }


@dataclass
class NoveltyResult:
    """
    Aggregated statistical novelty evaluation result across all dimensions of a StateRepresentation.
    """
    overall_level: str
    feature_results: List[FeatureNoveltyResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    assessment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.overall_level, OverallNoveltyLevel):
            self.overall_level = self.overall_level.value
        elif isinstance(self.overall_level, str):
            self.overall_level = self.overall_level.strip().upper()
        else:
            raise ValueError("NoveltyResult overall_level must be a string or OverallNoveltyLevel enum.")

        self.timestamp = ensure_timezone_aware(self.timestamp, "NoveltyResult timestamp")

    def get_anomalous_features(self) -> List[FeatureNoveltyResult]:
        """Returns only the feature results classified as unusual or highly unusual."""
        return [f for f in self.feature_results if f.is_anomalous()]

    def to_dict(self) -> Dict[str, Any]:
        """Serializes NoveltyResult into a dictionary."""
        return {
            "assessment_id": self.assessment_id,
            "timestamp": format_iso8601(self.timestamp),
            "overall_level": self.overall_level,
            "anomalous_feature_count": len(self.get_anomalous_features()),
            "feature_results": [f.to_dict() for f in self.feature_results],
            "metadata": self.metadata,
        }

    def to_compact_summary(self) -> str:
        """Produces a concise summary string for situational reasoning context."""
        anomalies = self.get_anomalous_features()
        if not anomalies:
            return f"[{self.overall_level}] All {len(self.feature_results)} state dimensions within normal historical baseline."

        anomaly_strings = [
            f"{f.feature}={f.current_value} ({f.classification}" + (f", dev={f.deviation:.2f})" if isinstance(f.deviation, (int, float)) else ")")
            for f in anomalies
        ]
        return f"[{self.overall_level}] Divergences detected: " + "; ".join(anomaly_strings)


# Legacy types for backwards compatibility
class NoveltyType(str, Enum):
    """Categorization of novelty or anomaly."""
    UNSEEN_EVENT = "unseen_event"
    SCHEDULE_DEVIATION = "schedule_deviation"
    BEHAVIORAL_SHIFT = "behavioral_shift"
    GOAL_CONFLICT = "goal_conflict"
    ENVIRONMENTAL_CHANGE = "environmental_change"
    TEMPORAL_ANOMALY = "temporal_anomaly"


@dataclass
class NoveltyScore:
    """Legacy NoveltyScore representation."""
    score: float
    novelty_type: NoveltyType
    explanation: str
    assessment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 1.0
    contributing_factors: List[str] = field(default_factory=list)
    baseline_reference: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
