"""Base connector interface.

Connectors are responsible for fetching raw observations from external data sources.
V0 only supports Gmail as an external source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.domain.observations import Observation


class BaseConnector(ABC):
    """Abstract base class for all data source connectors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this connector (e.g. 'gmail')."""

    @abstractmethod
    def fetch_observations(
        self,
        since: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[Observation]:
        """Fetch raw observations from the source.

        Args:
            since: Optional cursor/timestamp string to fetch incremental data.
            limit: Maximum number of observations to fetch per call.

        Yields:
            Observation domain instances.
        """
