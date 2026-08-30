from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, List, Optional

import schedule

from personal_intelligence.core.events.models import Event
from personal_intelligence.storage.db import DatabaseManager

if TYPE_CHECKING:
    from personal_intelligence.core.loop import PersonalIntelligenceEvaluationLoop

logger = logging.getLogger(__name__)


class SourcePoller:
    """Base class for source pollers. Subclass and implement poll()."""

    name: str = "unknown"

    def poll(self) -> List[Event]:
        raise NotImplementedError("Subclasses must implement poll().")


class PollingDaemon:
    """
    Runs the PI evaluation loop on a schedule, collecting events from
    registered source pollers before each cycle.
    """

    def __init__(
        self,
        loop: PersonalIntelligenceEvaluationLoop,
        interval_minutes: int = 5,
    ) -> None:
        self.loop = loop
        self.interval_minutes = interval_minutes
        self.source_pollers: List[SourcePoller] = []
        self._running = False

    def register_source(self, poller: SourcePoller) -> None:
        """Register a source poller (Gmail, Slack, Calendar, etc.)."""
        self.source_pollers.append(poller)
        logger.info(f"Registered source poller: {getattr(poller, 'name', str(poller))}")

    def _collect_events(self) -> List[Event]:
        """Collect events from all registered source pollers."""
        all_events: List[Event] = []
        for poller in self.source_pollers:
            poller_name = getattr(poller, "name", "unknown")
            try:
                events = poller.poll()
                if events:
                    all_events.extend(events)
                logger.info(f"Collected {len(events) if events else 0} events from {poller_name}")
            except Exception as e:
                logger.error(f"Error polling {poller_name}: {e}")
        return all_events

    def _run_cycle(self) -> None:
        """Execute one polling + evaluation cycle."""
        try:
            events = self._collect_events()
            result = self.loop.run_cycle(incoming_events=events if events else None)
            logger.info(
                f"Cycle complete: {result.events_processed_count} events processed, "
                f"{len(result.episodes_created)} episodes, "
                f"{len(result.actions_decided)} actions decided"
            )
            print(
                f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] "
                f"Evaluation cycle completed: {result.events_processed_count} events, "
                f"{len(result.actions_decided)} action(s)"
            )
        except Exception as e:
            logger.error(f"Evaluation cycle error: {e}", exc_info=True)
            print(f"[!] Error during evaluation cycle: {e}")

    def run_once(self) -> None:
        """Executes a single polling + evaluation cycle (useful for tests and manual runs)."""
        self._run_cycle()

    def start(self) -> None:
        """Start the polling daemon. Blocks until interrupted."""
        self._running = True

        def _handle_signal(signum, frame):
            logger.info("Shutdown signal received.")
            print("\nShutting down polling daemon...")
            self._running = False

        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, AttributeError):
            # In non-main thread environments
            pass

        schedule.clear()
        schedule.every(self.interval_minutes).minutes.do(self._run_cycle)

        # Run one immediate cycle on startup
        self._run_cycle()

        logger.info(f"Polling daemon started. Interval: {self.interval_minutes} minutes.")
        print(f"[*] Personal Intelligence Polling Daemon started. Polling every {self.interval_minutes} minutes. Press Ctrl+C to stop.")

        while self._running:
            schedule.run_pending()
            time.sleep(1)

        logger.info("Polling daemon stopped.")
