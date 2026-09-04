"""
Data models for the Personal World Model.

Defines structured, provenance-preserving entities for:
- Current State (commitments, upcoming events, open issues, recent important activity, known goals, active situations)
- Timeline
- Goals
- Open Situations
- Known Patterns
- Emerging Hypotheses
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, List, Optional, Union
import uuid

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)


class IssueSeverity(str, Enum):
    """Severity of an open tension or issue."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class IssueStatus(str, Enum):
    """Lifecycle status of an open issue."""
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


@dataclass
class FactProvenance:
    """
    Explicit provenance metadata ensuring every derived fact in the world model
    is traceable back to its source observation, reasoning episode, and original Hermes source.
    """
    source_observation_id: Optional[str] = None
    reasoning_episode_id: Optional[str] = None
    origin_source: Optional[str] = None  # e.g. 'gmail', 'drive', 'calendar', 'meet', 'filesystem', 'user', 'hermes'
    source_id: Optional[str] = None      # e.g. message_id, doc_id, event_id, file_path
    tool: Optional[str] = None           # e.g. 'google_workspace_gmail', 'filesystem'
    retrieval_query: Optional[str] = None
    derivation_rule: Optional[str] = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.recorded_at = ensure_timezone_aware(self.recorded_at, "FactProvenance recorded_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_observation_id": self.source_observation_id,
            "reasoning_episode_id": self.reasoning_episode_id,
            "origin_source": self.origin_source,
            "source_id": self.source_id,
            "tool": self.tool,
            "retrieval_query": self.retrieval_query,
            "derivation_rule": self.derivation_rule,
            "recorded_at": format_iso8601(self.recorded_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FactProvenance":
        if not isinstance(data, dict):
            return cls()
        return cls(
            source_observation_id=data.get("source_observation_id"),
            reasoning_episode_id=data.get("reasoning_episode_id"),
            origin_source=data.get("origin_source") or data.get("source"),
            source_id=data.get("source_id"),
            tool=data.get("tool"),
            retrieval_query=data.get("retrieval_query") or data.get("query"),
            derivation_rule=data.get("derivation_rule"),
            recorded_at=ensure_timezone_aware(
                data.get("recorded_at", datetime.now(timezone.utc)), "recorded_at"
            ),
        )


class EpistemicType(str, Enum):
    """
    Explicit epistemic state categorization for Personal World Model entities and facts.
    Strictly segregated to prevent unverified inferences from masquerading as verified facts.
    """
    OBSERVED = "observed"
    DERIVED = "derived"
    INFERRED = "inferred"
    PREDICTED = "predicted"
    RECOMMENDED = "recommended"


class EpistemicIntegrityError(ValueError):
    """Raised when an illegal epistemic promotion or missing evidence lineage is detected."""
    pass


@dataclass
class EpistemicRecord:
    """
    Explicit Epistemic Record for the Personal World Model.
    Replaces generic Bayesian belief calculations with strict epistemic segregation:
    OBSERVED, DERIVED, INFERRED, PREDICTED, RECOMMENDED.
    Every record retains complete source provenance and supporting observation lineage.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    epistemic_type: str = EpistemicType.OBSERVED.value
    statement: str = ""
    subject: str = ""
    predicate: str = ""
    object: str = ""
    source: str = "unknown"             # e.g., 'gmail', 'calendar', 'hermes', 'user'
    source_id: Optional[str] = None     # e.g., message_id, event_id
    origin_event_id: Optional[str] = None
    supporting_observation_ids: List[str] = field(default_factory=list)
    contradictory_observation_ids: List[str] = field(default_factory=list)
    status: str = "active"              # active, retracted, superseded
    provenance: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.created_at = ensure_timezone_aware(self.created_at, "EpistemicRecord created_at")
        self.updated_at = ensure_timezone_aware(self.updated_at, "EpistemicRecord updated_at")
        if isinstance(self.epistemic_type, EpistemicType):
            self.epistemic_type = self.epistemic_type.value
        else:
            self.epistemic_type = str(self.epistemic_type).lower()

    def promote_to_observation(self) -> None:
        """Guards against silent promotion of INFERRED -> OBSERVED."""
        if self.epistemic_type in (EpistemicType.INFERRED.value, EpistemicType.PREDICTED.value, EpistemicType.RECOMMENDED.value):
            raise EpistemicIntegrityError(
                f"Cannot silently promote epistemic state '{self.epistemic_type}' to '{EpistemicType.OBSERVED.value}'. "
                f"Observations require direct verified ground-truth event provenance."
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "epistemic_type": self.epistemic_type,
            "statement": self.statement or f"{self.subject} {self.predicate} {self.object}".strip(),
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "source": self.source,
            "source_id": self.source_id,
            "origin_event_id": self.origin_event_id,
            "supporting_observation_ids": self.supporting_observation_ids,
            "contradictory_observation_ids": self.contradictory_observation_ids,
            "status": self.status,
            "provenance": self.provenance,
            "created_at": format_iso8601(self.created_at),
            "updated_at": format_iso8601(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpistemicRecord":
        supp_ids = data.get("supporting_observation_ids") or data.get("supporting_observation_ids_json", [])
        if isinstance(supp_ids, str):
            try:
                supp_ids = json.loads(supp_ids)
            except Exception:
                supp_ids = []
        contra_ids = data.get("contradictory_observation_ids") or data.get("contradictory_observation_ids_json", [])
        if isinstance(contra_ids, str):
            try:
                contra_ids = json.loads(contra_ids)
            except Exception:
                contra_ids = []
        prov = data.get("provenance") or data.get("provenance_json", {})
        if isinstance(prov, str):
            try:
                prov = json.loads(prov)
            except Exception:
                prov = {}
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            epistemic_type=data.get("epistemic_type", EpistemicType.OBSERVED.value),
            statement=data.get("statement", ""),
            subject=data.get("subject", ""),
            predicate=data.get("predicate", ""),
            object=data.get("object", ""),
            source=data.get("source", "unknown"),
            source_id=data.get("source_id"),
            origin_event_id=data.get("origin_event_id"),
            supporting_observation_ids=supp_ids,
            contradictory_observation_ids=contra_ids,
            status=data.get("status", "active"),
            provenance=prov,
            created_at=ensure_timezone_aware(data.get("created_at", datetime.now(timezone.utc)), "created_at"),
            updated_at=ensure_timezone_aware(data.get("updated_at", datetime.now(timezone.utc)), "updated_at"),
        )


class CommitmentStatus(str, Enum):
    """
    Allowed commitment statuses in Personal Intelligence V1.
    Strictly derived from verified observations or explicit user actions.
    Hermes inference must NOT silently change commitment status.
    """
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"

    # Backward compatibility aliases
    PENDING = "OPEN"
    EXPIRED = "OVERDUE"


@dataclass
class Commitment:
    """
    A personal commitment or action item represented as an entity (entities.entity_type = 'commitment')
    in the Personal World Model Knowledge Graph.

    Graph Relationships:
      USER -> owns -> COMMITMENT
      COMMITMENT -> supports -> GOAL
      COMMITMENT -> concerns -> PROJECT
      COMMITMENT -> associated_with -> MEETING
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    entity_type: str = "commitment"
    status: str = CommitmentStatus.OPEN.value
    due_at: Optional[datetime] = None
    priority: str = "medium"
    source: str = ""
    source_id: str = ""
    goal_id: Optional[str] = None
    satisfaction_criteria: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: Optional[datetime] = None  # Most recent related observation
    provenance: FactProvenance = field(default_factory=FactProvenance)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name and self.description:
            self.name = self.description
        elif not self.description and self.name:
            self.description = self.name
        self.created_at = ensure_timezone_aware(self.created_at, "Commitment created_at")
        self.updated_at = ensure_timezone_aware(self.updated_at, "Commitment updated_at")
        if self.due_at:
            self.due_at = ensure_timezone_aware(self.due_at, "Commitment due_at")
        if self.last_activity:
            self.last_activity = ensure_timezone_aware(self.last_activity, "Commitment last_activity")
        if isinstance(self.status, CommitmentStatus):
            self.status = self.status.value
        elif isinstance(self.status, str):
            st = self.status.strip().upper()
            if st in ("PENDING", "OPEN"):
                self.status = CommitmentStatus.OPEN.value
            elif st == "EXPIRED":
                self.status = CommitmentStatus.OVERDUE.value
            else:
                self.status = st

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "due_at": format_iso8601(self.due_at) if self.due_at else None,
            "priority": self.priority,
            "source": self.source,
            "source_id": self.source_id,
            "goal_id": self.goal_id,
            "satisfaction_criteria": self.satisfaction_criteria,
            "created_at": format_iso8601(self.created_at),
            "updated_at": format_iso8601(self.updated_at),
            "last_activity": format_iso8601(self.last_activity) if self.last_activity else None,
            "provenance": self.provenance.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Commitment":
        prov = data.get("provenance", {})
        prov_obj = prov if isinstance(prov, FactProvenance) else FactProvenance.from_dict(prov)
        name = data.get("name") or data.get("description", "")
        desc = data.get("description") or name
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=name,
            description=desc,
            entity_type=data.get("entity_type", "commitment"),
            status=data.get("status", CommitmentStatus.OPEN.value),
            due_at=ensure_timezone_aware(data["due_at"], "due_at") if data.get("due_at") else None,
            priority=data.get("priority", "medium"),
            source=data.get("source", ""),
            source_id=data.get("source_id", ""),
            goal_id=data.get("goal_id"),
            satisfaction_criteria=data.get("satisfaction_criteria", []),
            created_at=ensure_timezone_aware(data.get("created_at", datetime.now(timezone.utc)), "created_at"),
            updated_at=ensure_timezone_aware(data.get("updated_at", datetime.now(timezone.utc)), "updated_at"),
            last_activity=ensure_timezone_aware(data["last_activity"], "last_activity") if data.get("last_activity") else None,
            provenance=prov_obj,
            metadata=data.get("metadata", {}),
        )


@dataclass
class OpenIssue:
    """
    An open tension, blocker, conflict, or unresolved discrepancy requiring situational attention.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    severity: str = IssueSeverity.MEDIUM.value
    status: str = IssueStatus.OPEN.value
    situation_id: Optional[str] = None
    source_observation_ids: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: FactProvenance = field(default_factory=FactProvenance)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.created_at = ensure_timezone_aware(self.created_at, "OpenIssue created_at")
        self.updated_at = ensure_timezone_aware(self.updated_at, "OpenIssue updated_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "status": self.status,
            "situation_id": self.situation_id,
            "source_observation_ids": self.source_observation_ids,
            "created_at": format_iso8601(self.created_at),
            "updated_at": format_iso8601(self.updated_at),
            "provenance": self.provenance.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenIssue":
        prov = data.get("provenance", {})
        prov_obj = prov if isinstance(prov, FactProvenance) else FactProvenance.from_dict(prov)
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            title=data.get("title", ""),
            description=data.get("description", ""),
            severity=data.get("severity", IssueSeverity.MEDIUM.value),
            status=data.get("status", IssueStatus.OPEN.value),
            situation_id=data.get("situation_id"),
            source_observation_ids=data.get("source_observation_ids", []),
            created_at=ensure_timezone_aware(data.get("created_at", datetime.now(timezone.utc)), "created_at"),
            updated_at=ensure_timezone_aware(data.get("updated_at", datetime.now(timezone.utc)), "updated_at"),
            provenance=prov_obj,
            metadata=data.get("metadata", {}),
        )


@dataclass
class UpcomingEvent:
    """
    A scheduled upcoming commitment or calendar block in the forward horizon.
    """
    event_id: str
    title: str
    start_time: datetime
    end_time: Optional[datetime] = None
    origin_source: str = "calendar"
    source_observation_id: Optional[str] = None
    location: Optional[str] = None
    provenance: FactProvenance = field(default_factory=FactProvenance)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.start_time = ensure_timezone_aware(self.start_time, "UpcomingEvent start_time")
        if self.end_time:
            self.end_time = ensure_timezone_aware(self.end_time, "UpcomingEvent end_time")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "start_time": format_iso8601(self.start_time),
            "end_time": format_iso8601(self.end_time) if self.end_time else None,
            "origin_source": self.origin_source,
            "source_observation_id": self.source_observation_id,
            "location": self.location,
            "provenance": self.provenance.to_dict(),
            "metadata": self.metadata,
        }


@dataclass
class ImportantActivity:
    """
    A salient recent activity observation (e.g. document modification, critical email, meeting completed).
    """
    observation_id: str
    source: str
    observation_type: str
    summary: str
    timestamp: datetime
    provenance: FactProvenance = field(default_factory=FactProvenance)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.timestamp = ensure_timezone_aware(self.timestamp, "ImportantActivity timestamp")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "source": self.source,
            "observation_type": self.observation_type,
            "summary": self.summary,
            "timestamp": format_iso8601(self.timestamp),
            "provenance": self.provenance.to_dict(),
            "evidence": self.evidence,
        }


@dataclass
class CurrentState:
    """
    Structured representation of the user's CURRENT STATE derived from observations.
    """
    current_commitments: List[Commitment] = field(default_factory=list)
    upcoming_events: List[UpcomingEvent] = field(default_factory=list)
    open_issues: List[OpenIssue] = field(default_factory=list)
    recent_important_activity: List[ImportantActivity] = field(default_factory=list)
    known_goals: List[Dict[str, Any]] = field(default_factory=list)
    active_situations: List[Dict[str, Any]] = field(default_factory=list)
    computed_features: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.timestamp = ensure_timezone_aware(self.timestamp, "CurrentState timestamp")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": format_iso8601(self.timestamp),
            "current_commitments": [c.to_dict() for c in self.current_commitments],
            "upcoming_events": [e.to_dict() for e in self.upcoming_events],
            "open_issues": [i.to_dict() for i in self.open_issues],
            "recent_important_activity": [a.to_dict() for a in self.recent_important_activity],
            "known_goals": self.known_goals,
            "active_situations": self.active_situations,
            "computed_features": self.computed_features,
        }


@dataclass
class PersonalWorldModelSnapshot:
    """
    Unified snapshot of the entire Personal World Model across all core dimensions.
    """
    current_state: CurrentState
    timeline_events: List[Dict[str, Any]]
    goals: List[Dict[str, Any]]
    open_situations: List[Dict[str, Any]]
    known_patterns: List[Dict[str, Any]]
    emerging_hypotheses: List[Dict[str, Any]]
    ground_truth_facts: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.timestamp = ensure_timezone_aware(self.timestamp, "PersonalWorldModelSnapshot timestamp")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": format_iso8601(self.timestamp),
            "current_state": self.current_state.to_dict(),
            "ground_truth_facts": self.ground_truth_facts,
            "timeline": self.timeline_events,
            "goals": self.goals,
            "open_situations": self.open_situations,
            "known_patterns": self.known_patterns,
            "emerging_hypotheses": self.emerging_hypotheses,
        }


# Backward-compatibility alias for experimental research code
from personal_intelligence.experimental.probabilistic_fact import ProbabilisticFact

