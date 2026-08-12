"""Enumeration types for the Personal Intelligence domain.

These enums encode the finite set of valid values for classification,
status tracking, and type discrimination across the domain model.
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


class ObservationSource(StrEnum):
    """Where an observation was captured from."""

    LOCAL_FILESYSTEM = "local_filesystem"
    GMAIL = "gmail"
    GOOGLE_CALENDAR = "google_calendar"
    GOOGLE_DRIVE = "google_drive"
    GITHUB = "github"
    MANUAL_INPUT = "manual_input"
    API_IMPORT = "api_import"


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


class ClaimStatus(StrEnum):
    """Lifecycle state of a claim."""

    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTESTED = "contested"
    WITHDRAWN = "withdrawn"
    CONFIRMED = "confirmed"


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class EvidenceType(StrEnum):
    """How a piece of evidence relates to a claim."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


class ReconciliationOutcome(StrEnum):
    """Result of reconciling a new relationship or claim against existing World Model state."""

    NOVEL = "novel"
    CONFIRM = "confirm"
    REFINE = "refine"
    UPDATE = "update"
    CONFLICT = "conflict"
    UNCERTAIN = "uncertain"

    # Backward compatibility aliases
    CREATED = "novel"
    CONFIRMED = "confirm"
    UPDATED = "update"
    CONFLICTED = "conflict"
    SUPERSEDED = "update"


# ---------------------------------------------------------------------------
# Entity types
# ---------------------------------------------------------------------------


class EntityType(StrEnum):
    """Classification of entities in the personal world model."""

    PERSON = "person"
    ORGANIZATION = "organization"
    PROJECT = "project"
    PRODUCT = "product"
    ROLE = "role"
    LOCATION = "location"
    EVENT = "event"
    DOCUMENT = "document"
    CONCEPT = "concept"
    GOAL = "goal"
    TASK = "task"
    DECISION = "decision"
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    COMMITMENT = "commitment"


# ---------------------------------------------------------------------------
# Relationship Predicates (RelationshipType)
# ---------------------------------------------------------------------------


class RelationshipType(StrEnum):
    """Typed relationship predicates between entities in the world model."""

    WORKS_FOR = "works_for"
    WORKS_WITH = "works_with"
    MANAGES = "manages"
    REPORTS_TO = "reports_to"
    OWNS = "owns"
    CREATED = "created"
    INVOLVED_IN = "involved_in"
    RELATED_TO = "related_to"
    DEPENDS_ON = "depends_on"
    PART_OF = "part_of"
    MENTIONS = "mentions"
    REQUESTS = "requests"
    ASSIGNS = "assigns"
    COMMUNICATES_WITH = "communicates_with"
    INTERESTED_IN = "interested_in"
    RESPONSIBLE_FOR = "responsible_for"


# ---------------------------------------------------------------------------
# Temporal Aspects
# ---------------------------------------------------------------------------


class TemporalAspect(StrEnum):
    """Temporal aspects / operators for temporal references."""

    BEFORE = "before"
    AFTER = "after"
    DURING = "during"
    SINCE = "since"
    UNTIL = "until"
    CURRENT = "current"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class DecisionStatus(StrEnum):
    """Lifecycle state of a decision."""

    PENDING = "pending"
    MADE = "made"
    DEFERRED = "deferred"
    REVERSED = "reversed"


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


class ConfidenceCategory(StrEnum):
    """Qualitative confidence level for human readability."""

    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"
