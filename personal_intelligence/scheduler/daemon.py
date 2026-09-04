from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, List, Optional
import warnings

import schedule

from personal_intelligence.core.events.models import Event
from personal_intelligence.storage.db import DatabaseManager

if TYPE_CHECKING:
    from personal_intelligence.core.loop import PersonalIntelligenceEvaluationLoop

logger = logging.getLogger(__name__)


class SourcePoller:
    """
    Deprecated base class for source pollers.
    
    Architectural Notice:
    External-world observation acquisition and scheduling is owned EXCLUSIVELY by Hermes.
    Use HermesObservationScheduler (in personal_intelligence.hermes_bridge.scheduler)
    or Hermes cron/schedules.yaml to acquire external observations and send them
    through PI's record_observation() boundary.
    """

    name: str = "unknown"

    def poll(self) -> List[Event]:
        raise NotImplementedError("Subclasses must implement poll().")


class LocalEvaluationDaemon:
    """
    Personal Intelligence Local Evaluation Daemon.

    Runs the PI evaluation loop on a schedule purely over local SQLite state
    (EventStore, Timeline, StateEngine, ContextGraph, Situations, and Eligibility).
    
    External observation scheduling is strictly delegated to Hermes (HermesObservationScheduler).
    """

    def __init__(
        self,
        loop: PersonalIntelligenceEvaluationLoop,
        interval_minutes: int = 5,
    ) -> None:
        self.loop = loop
        self.interval_minutes = max(1, interval_minutes)
        self.source_pollers: List[SourcePoller] = []
        self._running = False

    def register_source(self, poller: SourcePoller) -> None:
        """
        Deprecated: Register a legacy source poller.
        External observation acquisition belongs to Hermes (HermesObservationScheduler).
        """
        warnings.warn(
            f"register_source({getattr(poller, 'name', str(poller))}) is deprecated. "
            "External observation acquisition belongs exclusively to Hermes (HermesObservationScheduler). "
            "Observations must flow through PI's record_observation() boundary.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.source_pollers.append(poller)
        logger.warning(
            "Registered legacy source poller: %s. Note: External observation scheduling belongs to Hermes.",
            getattr(poller, "name", str(poller)),
        )

    def _collect_events(self) -> List[Event]:
        """Collect events from any legacy registered source pollers (backward compatibility)."""
        all_events: List[Event] = []
        for poller in self.source_pollers:
            poller_name = getattr(poller, "name", "unknown")
            try:
                events = poller.poll()
                if events:
                    all_events.extend(events)
                logger.info(f"Collected {len(events) if events else 0} events from legacy poller {poller_name}")
            except Exception as e:
                logger.error(f"Error polling legacy poller {poller_name}: {e}")
        return all_events

    def _run_cycle(self) -> None:
        """Execute one local evaluation cycle."""
        try:
            legacy_events = self._collect_events() if self.source_pollers else None
            result = self.loop.run_cycle(incoming_events=legacy_events)
            logger.info(
                f"Local evaluation cycle complete: {result.events_processed_count} events processed, "
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
        """Executes a single evaluation cycle (useful for tests and manual runs)."""
        self._run_cycle()

    def start(self) -> None:
        """Start the local evaluation daemon. Blocks until interrupted."""
        self._running = True

        def _handle_signal(signum, frame):
            logger.info("Shutdown signal received.")
            print("\nShutting down local evaluation daemon...")
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

        logger.info(f"Local evaluation daemon started. Interval: {self.interval_minutes} minutes.")
        print(f"[*] Personal Intelligence Local Evaluation Daemon started. Interval: {self.interval_minutes} minutes. Press Ctrl+C to stop.")

        while self._running:
            schedule.run_pending()
            time.sleep(1)

        logger.info("Local evaluation daemon stopped.")


# Canonical alias for backward compatibility
PollingDaemon = LocalEvaluationDaemon
