"""Domain layer for Personal Intelligence.

Exports all core domain models, value objects, and enumerations.
"""

from app.domain.claims import Claim
from app.domain.context import ContextPackage, ContextRequest
from app.domain.entities import (
    Commitment,
    Constraint,
    Decision,
    Entity,
    Event,
    Goal,
    Preference,
    Project,
    Relationship,
    Task,
)
from app.domain.entity_resolution import EntityResolutionResult
from app.domain.enums import (
    ClaimStatus,
    ConfidenceCategory,
    DecisionStatus,
    EntityType,
    EvidenceType,
    ObservationSource,
    ReconciliationOutcome,
    RelationshipType,
    TemporalAspect,
)
from app.domain.evidence import Evidence
from app.domain.normalized_email import NormalizedEmailObservation
from app.domain.observations import Observation
from app.domain.reconciliation import ReconciliationRecord
from app.domain.values import (
    ConfidenceScore,
    EvidenceSpan,
    Provenance,
    TemporalRange,
    TemporalReference,
)
from app.domain.world_state import StateChange, WorldState

__all__ = [
    "Claim",
    "ClaimStatus",
    "Commitment",
    "ConfidenceCategory",
    "ConfidenceScore",
    "Constraint",
    "ContextPackage",
    "ContextRequest",
    "Decision",
    "DecisionStatus",
    "Entity",
    "EntityResolutionResult",
    "EntityType",
    "Event",
    "Evidence",
    "EvidenceSpan",
    "EvidenceType",
    "Goal",
    "NormalizedEmailObservation",
    "Observation",
    "ObservationSource",
    "Preference",
    "Project",
    "Provenance",
    "ReconciliationOutcome",
    "ReconciliationRecord",
    "Relationship",
    "RelationshipType",
    "StateChange",
    "Task",
    "TemporalAspect",
    "TemporalRange",
    "TemporalReference",
    "WorldState",
]
