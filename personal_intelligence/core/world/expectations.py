"""
Expectation Provider Extension Interface.

Defines a clean, domain-agnostic extension protocol for optional expectation providers,
allowing future custom baseline models to plug into the Personal World Model without
enforcing speculative prediction-error calculations or Free Energy algorithms in V1.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional


class ExpectationProvider(ABC):
    """
    Optional extension interface for pluggable user baseline and expectation providers.
    """

    @abstractmethod
    def get_expected_baseline(self, dt: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Returns expected baseline properties projected for a given reference timestamp.
        """
        pass
