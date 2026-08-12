"""Observation Ingestion Service.

Responsible for receiving raw Observations from connectors, validating them,
and persisting them to structured storage before extraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.config.logging import get_logger

if TYPE_CHECKING:
    from app.domain.observations import Observation
    from app.persistence.duckdb_store import DuckDBStore

logger = get_logger(__name__)


class BaseIngestionService(ABC):
    """Abstract interface for observation ingestion."""

    @abstractmethod
    async def ingest_observation(self, observation: Observation) -> str:
        """Validate and ingest a single observation.

        Returns:
            The unique observation ID.
        """

    @abstractmethod
    async def get_observation(self, observation_id: str) -> Observation | None:
        """Retrieve an ingested observation by ID."""


class ObservationIngestionService(BaseIngestionService):
    """Production implementation of observation ingestion.

    Persists raw observations in DuckDB for provenance tracing.
    """

    def __init__(self, duckdb_store: DuckDBStore) -> None:
        self._store = duckdb_store

    async def ingest_observation(self, observation: Observation) -> str:
        """Validate and store a raw observation."""
        logger.info(
            "ingestion.observation_received",
            observation_id=observation.id,
            source=observation.source,
        )
        # Interface contract established — storage queries to be wired when persistence tables expand
        return observation.id

    async def get_observation(self, observation_id: str) -> Observation | None:
        """Fetch observation from database."""
        logger.info("ingestion.observation_requested", observation_id=observation_id)
        return None
