"""
Personal State Representation models.

Provides a deterministic, extensible structure for representing current user personal state.

Domain-neutral design: StateFeature and StateRepresentation impose no domain constraints.
They are equally applicable to communication, calendar, document, productivity, travel,
financial, routine, and any other future personal signal domain.

Legacy Note
-----------
EntityState, UserState, and StateSnapshot are legacy shims retained for backwards
compatibility. New code should use StateRepresentation and StateFeature exclusively.
StateRepresentation is the canonical model consumed by NoveltyEngine, SituationEngine,
ContextBuilder, and InterventionPolicyEngine.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, Iterator, List, Optional
import uuid

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)


@dataclass
class StateFeature:
    """
    An individual dimension of the personal state representation.
    Explicitly tracks its value, provenance source, timestamp, and confidence.
    """
    name: str
    value: Any
    source: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validates feature attributes."""
        if not self.name or not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("StateFeature name must be a non-empty string.")

        if not self.source or not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("StateFeature source must be a non-empty string.")

        self.timestamp = ensure_timezone_aware(self.timestamp, "StateFeature timestamp")

        if not isinstance(self.confidence, (int, float)):
            raise ValueError("StateFeature confidence must be numeric.")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(f"StateFeature confidence must be in [0.0, 1.0], got {self.confidence}.")

        if not isinstance(self.metadata, dict):
            raise ValueError("StateFeature metadata must be a dictionary.")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes StateFeature into a dictionary."""
        return {
            "name": self.name,
            "value": self.value,
            "source": self.source,
            "timestamp": format_iso8601(self.timestamp),
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateFeature":
        """Constructs a StateFeature instance from a dictionary."""
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict to construct StateFeature, got {type(data).__name__}")
        for k in ("name", "value", "source"):
            if k not in data:
                raise ValueError(f"Missing required field '{k}' in StateFeature data.")

        return cls(
            name=data["name"],
            value=data["value"],
            source=data["source"],
            timestamp=ensure_timezone_aware(data.get("timestamp", datetime.now(timezone.utc)), "timestamp"),
            confidence=float(data.get("confidence", 1.0)),
            metadata=data.get("metadata", {}),
        )


class StateRepresentation:
    """
    Extensible, deterministic container holding dimensions of user state at a point in time.
    Designed to be easily serializable and consumable by downstream novelty detection.
    """

    def __init__(
        self,
        timestamp: Optional[datetime] = None,
        features: Optional[Dict[str, StateFeature]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.timestamp = ensure_timezone_aware(
            timestamp or datetime.now(timezone.utc), "StateRepresentation timestamp"
        )
        self.features: Dict[str, StateFeature] = dict(features or {})
        self.metadata: Dict[str, Any] = dict(metadata or {})

    def get_feature(self, name: str) -> Optional[StateFeature]:
        """Retrieves a StateFeature by name, or None if not present."""
        return self.features.get(name)

    def get_value(self, name: str, default: Any = None) -> Any:
        """Retrieves the raw value of a feature, or default if not present."""
        feat = self.get_feature(name)
        return feat.value if feat is not None else default

    def set_feature(
        self,
        name: str,
        value: Any,
        source: str,
        timestamp: Optional[datetime] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StateFeature:
        """Sets or replaces a feature dimension in the state representation."""
        feature_time = timestamp or self.timestamp
        feat = StateFeature(
            name=name,
            value=value,
            source=source,
            timestamp=feature_time,
            confidence=confidence,
            metadata=metadata or {},
        )
        self.features[name] = feat
        return feat

    def add_feature(self, feature: StateFeature) -> StateFeature:
        """Adds or updates a StateFeature instance directly."""
        if not isinstance(feature, StateFeature):
            raise ValueError("Expected StateFeature instance.")
        self.features[feature.name] = feature
        return feature

    def set(self, feature: StateFeature) -> StateFeature:
        """Alias for add_feature."""
        return self.add_feature(feature)

    def __len__(self) -> int:
        return len(self.features)

    def __contains__(self, name: str) -> bool:
        return name in self.features

    def __getitem__(self, name: str) -> StateFeature:
        return self.features[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self.features)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes full state representation including feature provenance."""
        return {
            "timestamp": format_iso8601(self.timestamp),
            "feature_count": len(self.features),
            "features": {k: f.to_dict() for k, f in self.features.items()},
            "metadata": self.metadata,
        }

    def to_compact_dict(self) -> Dict[str, Any]:
        """
        Produces a concise, value-only mapping suitable for novelty detection algorithms.
        """
        return {
            "timestamp": format_iso8601(self.timestamp),
            "values": {k: f.value for k, f in self.features.items()},
            "confidences": {k: f.confidence for k, f in self.features.items()},
        }

    def to_compact_text(self) -> str:
        """Produces a human and LLM readable summary line of current state dimensions."""
        items = []
        for name, feat in sorted(self.features.items()):
            val_str = json.dumps(feat.value) if isinstance(feat.value, (dict, list)) else str(feat.value)
            items.append(f"{name}={val_str} (conf={feat.confidence:.2f})")
        return f"[{format_iso8601(self.timestamp)}] " + "; ".join(items)


# Legacy entity/snapshot models for backwards compatibility
@dataclass
class EntityState:
    """Represents state of an individual tracked entity."""
    entity_id: str
    entity_type: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 1.0


@dataclass
class UserState:
    """
    LEGACY: Retained for backwards compatibility.
    New code should use StateRepresentation and register_extractor() for domain-specific signals.

    Represents a high-level snapshot of observable user state.
    Domain-neutral: 'current_activity' can be any signal type (meeting, coding, writing, travelling, etc.).
    """
    current_activity: Optional[str] = None
    focus_mode: bool = False
    signal_context: Dict[str, Any] = field(default_factory=dict)
    custom_attributes: Dict[str, Any] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class StateSnapshot:
    """LEGACY: Coherent point-in-time state snapshot. Use StateRepresentation for new code."""
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_state: UserState = field(default_factory=UserState)
    entities: Dict[str, EntityState] = field(default_factory=dict)
    active_goal_ids: List[str] = field(default_factory=list)
    active_situation_ids: List[str] = field(default_factory=list)
    version: int = 1
