"""
Goals and intentions module.
Provides GoalStore for persistence and GoalEngine for deterministic goal reasoning.
"""

from personal_intelligence.core.goals.engine import GoalEngine
from personal_intelligence.core.goals.models import (
    Goal,
    GoalConflict,
    GoalConflictType,
    GoalEvaluation,
    GoalImpact,
    GoalImpactType,
    GoalPriority,
    GoalStatus,
)
from personal_intelligence.core.goals.store import GoalStore

__all__ = [
    "Goal",
    "GoalStore",
    "GoalEngine",
    "GoalStatus",
    "GoalPriority",
    "GoalImpact",
    "GoalImpactType",
    "GoalConflict",
    "GoalConflictType",
    "GoalEvaluation",
]

