"""
Deprecated: Use personal_intelligence.core.scheduler.local_maintenance instead.

This module is maintained strictly for backward compatibility.
All background scheduling inside Personal Intelligence is restricted to LOCAL PI MAINTENANCE.
External observation scheduling is exclusively owned by Hermes (HermesObservationScheduler).
"""

import warnings

from personal_intelligence.core.scheduler.local_maintenance import (
    BackgroundSyncScheduler,
    LocalMaintenanceScheduler,
)

warnings.warn(
    "personal_intelligence.core.scheduler.background_sync is deprecated. "
    "Use personal_intelligence.core.scheduler.local_maintenance.LocalMaintenanceScheduler instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["BackgroundSyncScheduler", "LocalMaintenanceScheduler"]
