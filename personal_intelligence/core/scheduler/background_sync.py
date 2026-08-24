"""
Background Synchronization and Epistemic Triage Scheduler for Personal Intelligence.
Runs periodic silent syncs (default: 30 minutes) and triggers native OS desktop notifications
for newly emerging High-Priority / Critical Situations.
"""

from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

from personal_intelligence.core.events.models import format_iso8601
from personal_intelligence.core.notifications.notifier import DesktopNotifier, send_desktop_alert
from personal_intelligence.core.situations.models import SituationPriority

logger = logging.getLogger(__name__)


class BackgroundSyncScheduler:
    """
    Background daemon thread managing continuous periodic synchronization,
    intelligent situational triage, and high-priority OS desktop alert dispatch.
    """

    def __init__(
        self,
        sync_interval_minutes: int = 30,
        sync_callback: Optional[Callable[[], Dict[str, Any]]] = None,
        notifier: Optional[DesktopNotifier] = None,
        auto_start: bool = False,
    ) -> None:
        self.sync_interval_minutes = max(1, sync_interval_minutes)
        self.sync_callback = sync_callback
        self.notifier = notifier or DesktopNotifier()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Telemetry & State Tracking
        self.last_sync_at: Optional[datetime] = None
        self.next_sync_at: Optional[datetime] = None
        self.sync_count: int = 0
        self.last_sync_status: str = "initialized"
        self.last_error: Optional[str] = None
        self.notified_situation_ids: Set[str] = set()

        if auto_start:
            self.start()

    def start(self) -> None:
        """Starts the background sync scheduler daemon."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self.next_sync_at = datetime.now(timezone.utc) + timedelta(minutes=self.sync_interval_minutes)
            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="PIBackgroundSyncScheduler",
            )
            self._thread.start()
            logger.info("Background Sync Scheduler started (Interval: %dm)", self.sync_interval_minutes)

    def stop(self) -> None:
        """Stops the background scheduler thread cleanly."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            logger.info("Background Sync Scheduler stopped.")

    def trigger_now(self) -> Dict[str, Any]:
        """Manually triggers an immediate background synchronization cycle."""
        return self._execute_sync_cycle(is_manual=True)

    def get_status(self) -> Dict[str, Any]:
        """Returns structured status and metrics for the UI and APIs."""
        return {
            "is_running": self._running,
            "sync_interval_minutes": self.sync_interval_minutes,
            "last_sync_at": format_iso8601(self.last_sync_at) if self.last_sync_at else None,
            "next_sync_at": format_iso8601(self.next_sync_at) if self.next_sync_at else None,
            "sync_count": self.sync_count,
            "last_sync_status": self.last_sync_status,
            "last_error": self.last_error,
            "notified_situations_count": len(self.notified_situation_ids),
            "desktop_notifications_enabled": True,
        }

    def _run_loop(self) -> None:
        """Main background scheduling loop."""
        while self._running and not self._stop_event.is_set():
            # Wait for interval or stop event
            wait_seconds = self.sync_interval_minutes * 60
            interrupted = self._stop_event.wait(timeout=wait_seconds)
            if interrupted or not self._running:
                break

            # Execute scheduled sync
            try:
                self._execute_sync_cycle(is_manual=False)
            except Exception as ex:
                logger.error("Unhandled error in background sync cycle: %s", ex)
                self.last_error = str(ex)
                self.last_sync_status = "error"

    def _execute_sync_cycle(self, is_manual: bool = False) -> Dict[str, Any]:
        """Executes a single sync cycle, triages situations, and sends OS notifications."""
        now = datetime.now(timezone.utc)
        self.last_sync_at = now
        self.next_sync_at = now + timedelta(minutes=self.sync_interval_minutes)
        self.sync_count += 1

        logger.info("Executing background sync cycle #%d (Manual: %s)...", self.sync_count, is_manual)

        result_data: Dict[str, Any] = {
            "status": "success",
            "timestamp": format_iso8601(now),
            "cycle_number": self.sync_count,
            "manual": is_manual,
            "high_priority_detected": 0,
            "notifications_dispatched": 0,
        }

        if not self.sync_callback:
            self.last_sync_status = "idle (no callback)"
            return result_data

        try:
            cb_result = self.sync_callback()
            self.last_sync_status = "success"
            self.last_error = None

            # Process discovered situations from callback
            high_priority_sits: List[Dict[str, Any]] = cb_result.get("high_priority_situations", [])
            result_data["high_priority_detected"] = len(high_priority_sits)

            # Dispatch desktop notifications for newly discovered high-priority items
            for sit in high_priority_sits:
                sit_id = sit.get("id") or sit.get("situation_id")
                if not sit_id:
                    continue

                if sit_id not in self.notified_situation_ids:
                    self.notified_situation_ids.add(sit_id)
                    title = sit.get("title") or sit.get("context", {}).get("summary") or "High Priority Alert"
                    msg = sit.get("context", {}).get("why_detected") or sit.get("summary") or "New high priority situation detected."
                    pri = sit.get("priority", "high")

                    # Dispatch native OS notification
                    self.notifier.send(
                        title=f"Personal Intelligence: {title}",
                        message=msg,
                        priority=pri,
                    )
                    result_data["notifications_dispatched"] += 1
                    logger.info("Dispatched native desktop alert for situation %s: %s", sit_id, title)

        except Exception as ex:
            logger.error("Background sync callback failed: %s", ex)
            self.last_sync_status = "error"
            self.last_error = str(ex)
            result_data["status"] = "error"
            result_data["error"] = str(ex)

        return result_data
