"""
Pattern models representing empirical associations, recurring routines, and longitudinal behavioral patterns.
Enforces non-causal association semantics and 7-stage lifecycle progression.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)


class PatternStatus(str, Enum):
    """Lifecycle progression states for learned personal patterns."""
    OBSERVED = "OBSERVED"           # First observed candidate association
    HYPOTHESIS = "HYPOTHESIS"       # Repeatedly observed candidate under evaluation
    EMERGING = "EMERGING"           # Gaining statistical support without strong contradiction
    SUPPORTED = "SUPPORTED"         # Well-evidenced regular personal pattern
    ACTIVE = "ACTIVE"               # High-confidence, actively used for contextual reasoning
    DECAYING = "DECAYING"           # Experiencing contradictions or absence of recent reinforcement
    INACTIVE = "INACTIVE"           # Deprecated, retired, or disproven


class PatternType(str, Enum):
    """Broad domain classification of personal patterns."""
    WORLD_PATTERN = "WORLD_PATTERN"             # External environment, schedule rhythms, transit/weather
    BEHAVIORAL_PATTERN = "BEHAVIORAL_PATTERN"   # User routines, habit sequences, activity/recovery associations
    INTERACTION_PATTERN = "INTERACTION_PATTERN" # User interaction preferences, recommendation responsiveness


class EvidenceObservationType(str, Enum):
    """Type of empirical observation regarding a pattern."""
    SUPPORT = "SUPPORT"                 # Observation reinforces the pattern association
    CONTRADICTION = "CONTRADICTION"     # Observation contradicts the expected association


class PatternCadence(str, Enum):
    """Temporal frequency or repetition type of a pattern."""
    DAILY = "daily"
    WEEKLY = "weekly"
    WEEKDAY = "weekday"
    WEEKEND = "weekend"
    MONTHLY = "monthly"
    EVENT_TRIGGERED = "event_triggered"
    IRREGULAR = "irregular"


@dataclass
class PatternEvidence:
    """
    Individual instance of supporting or contradictory empirical evidence.
    """
    evidence_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pattern_id: str = ""
    observation_type: str = EvidenceObservationType.SUPPORT.value
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    episode_id: Optional[str] = None
    event_ids: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.observed_at = ensure_timezone_aware(self.observed_at, "observed_at")
        if isinstance(self.observation_type, EvidenceObservationType):
            self.observation_type = self.observation_type.value
        elif isinstance(self.observation_type, str):
            self.observation_type = self.observation_type.strip().upper()

    def to_dict(self) -> Dict[str, Any]:
        """Serializes pattern evidence to dictionary."""
        return {
            "evidence_id": self.evidence_id,
            "pattern_id": self.pattern_id,
            "observation_type": self.observation_type,
            "observed_at": format_iso8601(self.observed_at),
            "episode_id": self.episode_id,
            "event_ids": self.event_ids,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatternEvidence":
        """Deserializes dictionary to PatternEvidence."""
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict for PatternEvidence, got {type(data).__name__}")

        obs_dt = data.get("observed_at") or datetime.now(timezone.utc)
        return cls(
            evidence_id=str(data.get("evidence_id") or uuid.uuid4()),
            pattern_id=str(data.get("pattern_id", "")),
            observation_type=str(data.get("observation_type", EvidenceObservationType.SUPPORT.value)),
            observed_at=ensure_timezone_aware(obs_dt, "observed_at"),
            episode_id=data.get("episode_id"),
            event_ids=data.get("event_ids", []),
            details=data.get("details", {}),
        )


@dataclass
class Pattern:
    """
    Representation of a learned empirical personal pattern or association.
    Guarantees non-causal representation (associations only, never causation claims).
    """
    description: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pattern_type: str = PatternType.BEHAVIORAL_PATTERN.value
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    support_count: int = 1
    contradiction_count: int = 0
    evidence_strength: str = "weak"  # "weak" | "moderate" | "strong"
    status: str = PatternStatus.OBSERVED.value
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.first_seen = ensure_timezone_aware(self.first_seen, "first_seen")
        self.last_seen = ensure_timezone_aware(self.last_seen, "last_seen")
        if isinstance(self.status, PatternStatus):
            self.status = self.status.value
        elif isinstance(self.status, str):
            self.status = self.status.strip().upper()
        if isinstance(self.pattern_type, PatternType):
            self.pattern_type = self.pattern_type.value
        elif isinstance(self.pattern_type, str):
            self.pattern_type = self.pattern_type.strip().upper()
        self.evidence_strength = str(self.evidence_strength).strip().lower()
        self.description = self._sanitize_non_causal(self.description)

    @staticmethod
    def _sanitize_non_causal(text: str) -> str:
        """Sanitizes causal claims into non-causal empirical associations."""
        phrasing = str(text or "").strip()
        causal_replacements = {
            " causes ": " appears associated with ",
            " cause ": " appear associated with ",
            " leads to ": " appears correlated with ",
            " lead to ": " appear correlated with ",
            " results in ": " is frequently followed by ",
            " result in ": " are frequently followed by ",
            " will happen": " has historically occurred in similar situations",
        }
        for causal_word, assoc_word in causal_replacements.items():
            if causal_word in phrasing:
                phrasing = phrasing.replace(causal_word, assoc_word)
        return phrasing

    @property
    def lifecycle_status(self) -> str:
        """Standard lifecycle status alias."""
        return self.status

    @property
    def recency(self) -> float:
        """Calculates days since last seen relative to current time."""
        now = datetime.now(timezone.utc)
        return round(max(0.0, (now - self.last_seen).total_seconds() / 86400.0), 2)

    @property
    def first_observed(self) -> datetime:
        """Alias for first_seen."""
        return self.first_seen

    @property
    def last_observed(self) -> datetime:
        """Alias for last_seen."""
        return self.last_seen

    @property
    def decay_state(self) -> str:
        """Returns the current decay state of the pattern ('active', 'decaying', 'inactive')."""
        st = self.status.upper()
        if st == PatternStatus.DECAYING.value:
            return "decaying"
        elif st == PatternStatus.INACTIVE.value:
            return "inactive"
        return "active"

    @property
    def source_observations(self) -> List[str]:
        """Returns list of source observation/event IDs supporting this pattern."""
        obs = list(self.metadata.get("source_observations", []))
        if not obs and "supporting_event_ids" in self.metadata:
            obs = list(self.metadata.get("supporting_event_ids", []))
        return obs

    @property
    def supporting_observations(self) -> List[str]:
        """Alias for source_observations."""
        return self.source_observations

    @property
    def contradicting_observations(self) -> List[str]:
        """Returns list of contradicting observation/event IDs."""
        return list(self.metadata.get("contradicting_event_ids", []))

    @property
    def supporting_evidence(self) -> List[str]:
        """Returns consolidated list of supporting evidence (episodes, observations, and state signals)."""
        supp = list(self.metadata.get("supporting_evidence", []))
        for ep in self.supporting_episodes:
            if ep not in supp:
                supp.append(ep)
        for obs in self.source_observations:
            if obs not in supp:
                supp.append(obs)
        return supp

    @property
    def contradicting_evidence(self) -> List[str]:
        """Returns consolidated list of contradicting evidence (episodes, observations)."""
        contra = list(self.metadata.get("contradicting_evidence", []))
        for ep in self.contradicting_episodes:
            if ep not in contra:
                contra.append(ep)
        for obs in self.contradicting_observations:
            if obs not in contra:
                contra.append(obs)
        return contra

    @property
    def pattern_id(self) -> str:
        """Backwards compatible alias for id."""
        return self.id

    @property
    def confidence(self) -> float:
        """Calculates empirical support ratio without claiming certainty."""
        total = self.support_count + self.contradiction_count
        if total == 0:
            return 0.5
        return round(self.support_count / total, 3)

    @property
    def supporting_episodes(self) -> List[str]:
        """Returns list of supporting reasoning episode IDs referenced by this pattern."""
        return list(self.metadata.get("supporting_episodes", []))

    @property
    def contradicting_episodes(self) -> List[str]:
        """Returns list of contradicting reasoning episode IDs referenced by this pattern."""
        return list(self.metadata.get("contradicting_episodes", []))

    def to_context_statement(self) -> str:
        """
        Formats the pattern as an epistemic context statement for reasoning.
        Guarantees non-causal, non-deterministic framing ('Historically, similar situations were often followed by...').
        """
        desc = self.description.strip()
        if not desc.startswith(("Historically,", "Observed association:", "User appears", "Calendar", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays")):
            return f"Historically, similar situations were often followed by: {desc}"
        return desc

    @property
    def evidence_quality(self) -> str:
        """Communicates empirical evidence quality support."""
        return self.evidence_strength

    @evidence_quality.setter
    def evidence_quality(self, val: str) -> None:
        self.evidence_strength = str(val).strip().lower()

    def to_dict(self) -> Dict[str, Any]:
        """Serializes pattern to dictionary."""
        return {
            "id": self.id,
            "pattern_id": self.id,
            "pattern_type": self.pattern_type,
            "description": self.description,
            "context_statement": self.to_context_statement(),
            "first_seen": format_iso8601(self.first_seen),
            "last_seen": format_iso8601(self.last_seen),
            "first_observed": format_iso8601(self.first_seen),
            "last_observed": format_iso8601(self.last_seen),
            "support_count": self.support_count,
            "contradiction_count": self.contradiction_count,
            "evidence_quality": self.evidence_quality,
            "evidence_strength": self.evidence_strength,
            "status": self.status,
            "lifecycle_status": self.status,
            "decay_state": self.decay_state,
            "confidence": self.confidence,
            "recency_days": self.recency,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "source_observations": self.source_observations,
            "supporting_observations": self.supporting_observations,
            "contradicting_observations": self.contradicting_observations,
            "supporting_episodes": self.supporting_episodes,
            "contradicting_episodes": self.contradicting_episodes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pattern":
        """Deserializes dictionary to Pattern."""
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict for Pattern, got {type(data).__name__}")

        p_id = data.get("id") or data.get("pattern_id") or str(uuid.uuid4())
        f_seen = data.get("first_seen") or data.get("first_observed_at") or datetime.now(timezone.utc)
        l_seen = data.get("last_seen") or data.get("last_observed_at") or datetime.now(timezone.utc)
        p_type = data.get("pattern_type") or PatternType.BEHAVIORAL_PATTERN.value

        meta = dict(data.get("metadata", {}))
        if "supporting_episodes" in data and "supporting_episodes" not in meta:
            meta["supporting_episodes"] = data["supporting_episodes"]
        if "contradicting_episodes" in data and "contradicting_episodes" not in meta:
            meta["contradicting_episodes"] = data["contradicting_episodes"]

        return cls(
            id=str(p_id),
            description=str(data.get("description", "")),
            pattern_type=str(p_type),
            first_seen=ensure_timezone_aware(f_seen, "first_seen"),
            last_seen=ensure_timezone_aware(l_seen, "last_seen"),
            support_count=int(data.get("support_count", 1)),
            contradiction_count=int(data.get("contradiction_count", 0)),
            evidence_strength=str(data.get("evidence_quality") or data.get("evidence_strength", "weak")),
            status=str(data.get("status", PatternStatus.OBSERVED.value)),
            metadata=meta,
        )



@dataclass
class LearnedPattern:
    """
    Backwards-compatible legacy pattern representation.
    """
    name: str
    description: str
    pattern_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cadence: PatternCadence = PatternCadence.DAILY
    confidence: float = 0.5
    observation_count: int = 1
    first_observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    typical_time_window: Optional[str] = None
    typical_days: List[int] = field(default_factory=list)
    associated_events: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
