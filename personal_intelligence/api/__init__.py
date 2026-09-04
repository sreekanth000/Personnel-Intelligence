"""
Personal Intelligence Dashboard API module.
"""

from personal_intelligence.api.interface import (
    PersonalIntelligenceCapabilityInterface,
)
from personal_intelligence.api.server import (
    DashboardDataService,
    EventAPIServer,
    create_dashboard_server,
)

PersonalIntelligenceInterface = PersonalIntelligenceCapabilityInterface
PersonalIntelligenceClient = PersonalIntelligenceCapabilityInterface

__all__ = [
    "PersonalIntelligenceCapabilityInterface",
    "PersonalIntelligenceInterface",
    "PersonalIntelligenceClient",
    "DashboardDataService",
    "create_dashboard_server",
    "EventAPIServer",
]
