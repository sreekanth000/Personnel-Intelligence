"""
Personal Goals model representing contextual intentions for reasoning.
Goals are purely contextual data descriptors (NOT workflows or autonomous tasks).
Provides deterministic descriptors for goal priority, deadlines, dependencies,
relevance, conflicts, progress, and situation impact.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import uuid

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)


class GoalPriority(str, Enum):
    """Priority categorization for goals."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    BACKGROUND = "background"


class GoalStatus(str, Enum):
    """Lifecycle status of a personal goal."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class GoalImpactType(str, Enum):
    """Classification of how an external situation impacts a goal."""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    IMPEDED = "impeded"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"
    CONFLICTED = "conflicted"


class GoalConflictType(str, Enum):
    """Classification of conflict mechanisms between goals or situations."""
    TIME_SCARCITY = "time_scarcity"
    ENERGY_SCARCITY = "energy_scarcity"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"
    DEPENDENCY_UNMET = "dependency_unmet"
    PRIORITY_INVERSION = "priority_inversion"


@dataclass
class GoalImpact:
    """Deterministic assessment of a situation's impact on a specific goal."""
    goal_id: str
    goal_name: str
    impact_type: str = GoalImpactType.NEUTRAL.value
    impact_score: float = 0.0  # 0.0 (no negative impact) to 1.0 (severe impediment/blocker)
    reason: str = ""
    severity: str = "medium"
    competing_factors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "goal_name": self.goal_name,
            "impact_type": self.impact_type,
            "impact_score": round(self.impact_score, 3),
            "reason": self.reason,
            "severity": self.severity,
            "competing_factors": self.competing_factors,
            "metadata": self.metadata,
        }


@dataclass
class GoalConflict:
    """Deterministic assessment of competition/conflict between multiple goals."""
    conflict_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conflict_type: str = GoalConflictType.TIME_SCARCITY.value
    goal_ids: List[str] = field(default_factory=list)
    goal_names: List[str] = field(default_factory=list)
    severity: str = "medium"
    description: str = ""
    competing_resource: str = "available_time"
    resolution_suggestion: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "conflict_type": self.conflict_type,
            "goal_ids": self.goal_ids,
            "goal_names": self.goal_names,
            "severity": self.severity,
            "description": self.description,
            "competing_resource": self.competing_resource,
            "resolution_suggestion": self.resolution_suggestion,
            "metadata": self.metadata,
        }


@dataclass
class GoalEvaluation:
    """Comprehensive evaluation of a goal in a situational context."""
    goal_id: str
    goal_name: str
    priority: str
    status: str
    effective_priority_score: float
    urgency_score: float
    relevance_score: float
    is_blocked: bool = False
    unmet_dependencies: List[str] = field(default_factory=list)
    days_until_deadline: Optional[float] = None
    progress: float = 0.0
    impact: Optional[GoalImpact] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "goal_name": self.goal_name,
            "priority": self.priority,
            "status": self.status,
            "effective_priority_score": round(self.effective_priority_score, 2),
            "urgency_score": round(self.urgency_score, 2),
            "relevance_score": round(self.relevance_score, 2),
            "is_blocked": self.is_blocked,
            "unmet_dependencies": self.unmet_dependencies,
            "days_until_deadline": round(self.days_until_deadline, 1) if self.days_until_deadline is not None else None,
            "progress": round(self.progress, 2),
            "impact": self.impact.to_dict() if self.impact else None,
            "metadata": self.metadata,
        }


@dataclass
class Goal:
    """
    Representation of a user's intention or objective.
    Serves as passive contextual information for situational reasoning.
    """
    name: str
    description: str = ""
    priority: str = GoalPriority.MEDIUM.value
    status: str = GoalStatus.ACTIVE.value
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    deadline: Optional[datetime] = None
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    domain: Optional[str] = None
    progress: float = 0.0  # 0.0 to 1.0
    target_metric: Optional[str] = None
    parent_goal_id: Optional[str] = None
    sub_goal_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validates all goal fields."""
        if not self.id or not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Goal id must be a non-empty string.")

        if not self.name or not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Goal name must be a non-empty string.")

        if self.description is None:
            self.description = ""

        if not isinstance(self.description, str):
            raise ValueError("Goal description must be a string.")

        # Normalize priority & status
        if isinstance(self.priority, GoalPriority):
            self.priority = self.priority.value
        elif isinstance(self.priority, str):
            self.priority = self.priority.strip().lower()
        else:
            raise ValueError("Goal priority must be a string or GoalPriority enum.")

        if isinstance(self.status, GoalStatus):
            self.status = self.status.value
        elif isinstance(self.status, str):
            self.status = self.status.strip().lower()
        else:
            raise ValueError("Goal status must be a string or GoalStatus enum.")

        if self.deadline is not None:
            self.deadline = ensure_timezone_aware(self.deadline, "deadline")

        if not isinstance(self.dependencies, list):
            self.dependencies = list(self.dependencies) if self.dependencies else []

        if not isinstance(self.tags, list):
            self.tags = list(self.tags) if self.tags else []

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata) if self.metadata else {}

        try:
            self.progress = max(0.0, min(1.0, float(self.progress or 0.0)))
        except (ValueError, TypeError):
            self.progress = 0.0

        self.created_at = ensure_timezone_aware(self.created_at, "created_at")
        self.updated_at = ensure_timezone_aware(self.updated_at, "updated_at")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes goal to a dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "deadline": format_iso8601(self.deadline) if self.deadline else None,
            "dependencies": self.dependencies,
            "tags": self.tags,
            "domain": self.domain,
            "progress": self.progress,
            "target_metric": self.target_metric,
            "parent_goal_id": self.parent_goal_id,
            "sub_goal_ids": self.sub_goal_ids,
            "metadata": self.metadata,
            "created_at": format_iso8601(self.created_at),
            "updated_at": format_iso8601(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Goal":
        """Constructs a Goal instance from a dictionary."""
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict to construct Goal, got {type(data).__name__}")

        if "name" not in data:
            raise ValueError("Missing required field 'name' for Goal.")

        deadline_val = data.get("deadline")
        if deadline_val and isinstance(deadline_val, str):
            try:
                deadline_dt = datetime.fromisoformat(deadline_val.replace("Z", "+00:00"))
            except Exception:
                deadline_dt = None
        elif isinstance(deadline_val, datetime):
            deadline_dt = deadline_val
        else:
            deadline_dt = None

        return cls(
            id=str(data.get("id", uuid.uuid4())),
            name=data["name"],
            description=data.get("description", ""),
            priority=data.get("priority", GoalPriority.MEDIUM.value),
            status=data.get("status", GoalStatus.ACTIVE.value),
            deadline=deadline_dt,
            dependencies=data.get("dependencies", []),
            tags=data.get("tags", []),
            domain=data.get("domain"),
            progress=data.get("progress", 0.0),
            target_metric=data.get("target_metric"),
            parent_goal_id=data.get("parent_goal_id"),
            sub_goal_ids=data.get("sub_goal_ids", []),
            metadata=data.get("metadata", {}),
            created_at=ensure_timezone_aware(data.get("created_at", datetime.now(timezone.utc)), "created_at"),
            updated_at=ensure_timezone_aware(data.get("updated_at", datetime.now(timezone.utc)), "updated_at"),
        )


