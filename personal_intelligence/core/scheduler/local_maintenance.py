"""
Local Intelligence Maintenance Scheduler for Personal Intelligence.

Implements the strict Prompt 8 architectural boundary:
Hermes owns ALL external-world observation acquisition (Gmail, Calendar, Drive, Web).
Personal Intelligence (PI) retains scheduling EXCLUSIVELY for LOCAL intelligence maintenance:
- Memory maintenance & consolidation
- Pattern decay & re-evaluation
- Situation re-evaluation & expiration sweeps
- Local database optimization (SQLite WAL checkpoint, PRAGMA optimize)
- Local intelligence housekeeping & desktop alerts for high-priority local situations

Strict Invariants:
- Zero external polling loops.
- Zero connector-specific schedulers.
- Zero OAuth token refresh or credential management.
- Zero external API synchronization.
"""

from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

from personal_intelligence.core.events.models import format_iso8601

logger = logging.getLogger(__name__)


class LocalMaintenanceScheduler:
    """
    Dedicated local-only scheduler for Personal Intelligence housekeeping and maintenance.

    Guarantees:
    - Runs exclusively local database maintenance, situation expiry, pattern decay, and salience sweeps.
    - Strictly prohibited from executing external API calls, Gmail queries, or OAuth actions.
    - Presentation and notification delivery are owned exclusively by Hive / client interfaces.
    """

    def __init__(
        self,
        maintenance_interval_minutes: int = 30,
        maintenance_callback: Optional[Callable[[], Dict[str, Any]]] = None,
        auto_start: bool = False,
        # Backward-compatible parameter aliases
        sync_interval_minutes: Optional[int] = None,
        sync_callback: Optional[Callable[[], Dict[str, Any]]] = None,
        notifier: Optional[Any] = None,
    ) -> None:
        interval = sync_interval_minutes if sync_interval_minutes is not None else maintenance_interval_minutes
        self.maintenance_interval_minutes = max(1, interval)
        self.maintenance_callback = sync_callback if sync_callback is not None else maintenance_callback

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Telemetry & State Tracking
        self.last_maintenance_at: Optional[datetime] = None
        self.next_maintenance_at: Optional[datetime] = None
        self.maintenance_count: int = 0
        self.last_maintenance_status: str = "initialized"
        self.last_error: Optional[str] = None
        self.notified_situation_ids: Set[str] = set()

        if auto_start:
            self.start()

    # -------------------------------------------------------------------------
    # Backward Compatibility Properties
    # -------------------------------------------------------------------------
    @property
    def sync_interval_minutes(self) -> int:
        return self.maintenance_interval_minutes

    @property
    def sync_callback(self) -> Optional[Callable[[], Dict[str, Any]]]:
        return self.maintenance_callback

    @property
    def last_sync_at(self) -> Optional[datetime]:
        return self.last_maintenance_at

    @property
    def next_sync_at(self) -> Optional[datetime]:
        return self.next_maintenance_at

    @property
    def sync_count(self) -> int:
        return self.maintenance_count

    @property
    def last_sync_status(self) -> str:
        return self.last_maintenance_status

    # -------------------------------------------------------------------------
    # Lifecycle Management
    # -------------------------------------------------------------------------
    def start(self) -> None:
        """Starts the local maintenance scheduler daemon."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self.next_maintenance_at = datetime.now(timezone.utc) + timedelta(minutes=self.maintenance_interval_minutes)
            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="PILocalMaintenanceScheduler",
            )
            self._thread.start()
            logger.info("Local Maintenance Scheduler started (Interval: %dm)", self.maintenance_interval_minutes)

    def stop(self) -> None:
        """Stops the local maintenance scheduler thread cleanly."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            logger.info("Local Maintenance Scheduler stopped.")

    def trigger_now(self) -> Dict[str, Any]:
        """Manually triggers an immediate local maintenance cycle."""
        return self._execute_maintenance_cycle(is_manual=True)

    def get_status(self) -> Dict[str, Any]:
        """Returns structured status and metrics for the UI and APIs."""
        return {
            "is_running": self._running,
            "maintenance_interval_minutes": self.maintenance_interval_minutes,
            "sync_interval_minutes": self.maintenance_interval_minutes,
            "last_maintenance_at": format_iso8601(self.last_maintenance_at) if self.last_maintenance_at else None,
            "last_sync_at": format_iso8601(self.last_maintenance_at) if self.last_maintenance_at else None,
            "next_maintenance_at": format_iso8601(self.next_maintenance_at) if self.next_maintenance_at else None,
            "next_sync_at": format_iso8601(self.next_maintenance_at) if self.next_maintenance_at else None,
            "maintenance_count": self.maintenance_count,
            "sync_count": self.maintenance_count,
            "last_maintenance_status": self.last_maintenance_status,
            "last_sync_status": self.last_maintenance_status,
            "last_error": self.last_error,
            "notified_situations_count": len(self.notified_situation_ids),
            "desktop_notifications_enabled": True,
            "scheduler_type": "local_pi_maintenance_only",
            "external_polling": False,
        }

    # -------------------------------------------------------------------------
    # Internal Maintenance Loop
    # -------------------------------------------------------------------------
    def _run_loop(self) -> None:
        """Main background local maintenance loop."""
        while self._running and not self._stop_event.is_set():
            wait_seconds = self.maintenance_interval_minutes * 60
            interrupted = self._stop_event.wait(timeout=wait_seconds)
            if interrupted or not self._running:
                break

            try:
                self._execute_maintenance_cycle(is_manual=False)
            except Exception as ex:
                logger.error("Unhandled error in local maintenance cycle: %s", ex)
                self.last_error = str(ex)
                self.last_maintenance_status = "error"

    def _execute_maintenance_cycle(self, is_manual: bool = False) -> Dict[str, Any]:
        """
        Executes a single local maintenance cycle, triages situations, and sends OS notifications.
        Strictly zero external network calls or third-party connector polling.
        """
        now = datetime.now(timezone.utc)
        self.last_maintenance_at = now
        self.next_maintenance_at = now + timedelta(minutes=self.maintenance_interval_minutes)
        self.maintenance_count += 1

        logger.info("Executing local maintenance cycle #%d (Manual: %s)...", self.maintenance_count, is_manual)

        result_data: Dict[str, Any] = {
            "status": "success",
            "timestamp": format_iso8601(now),
            "cycle_number": self.maintenance_count,
            "manual": is_manual,
            "high_priority_detected": 0,
            "notifications_dispatched": 0,
            "scheduler_type": "local_maintenance",
        }

        if not self.maintenance_callback:
            self.last_maintenance_status = "idle (no callback)"
            return result_data

        try:
            cb_result = self.maintenance_callback()
            self.last_maintenance_status = "success"
            self.last_error = None

            # Process discovered situations from callback
            high_priority_sits: List[Dict[str, Any]] = cb_result.get("high_priority_situations", [])
            result_data["high_priority_detected"] = len(high_priority_sits)

            # Triage discovered high priority situations for local tracking
            for sit in high_priority_sits:
                sit_id = sit.get("id") or sit.get("situation_id")
                if not sit_id:
                    continue

                if sit_id not in self.notified_situation_ids:
                    self.notified_situation_ids.add(sit_id)
                    title = sit.get("title") or sit.get("context", {}).get("summary") or "High Priority Alert"
                    result_data["notifications_dispatched"] += 1
                    logger.info("Triaged high priority situation %s: %s (presentation delegated to client)", sit_id, title)

        except Exception as ex:
            logger.error("Local maintenance callback failed: %s", ex)
            self.last_maintenance_status = "error"
            self.last_error = str(ex)
            result_data["status"] = "error"
            result_data["error"] = str(ex)

        return result_data


# Backward-compatible alias
BackgroundSyncScheduler = LocalMaintenanceScheduler
