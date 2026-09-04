"""
Personal Intelligence: A local-first Personal Intelligence system built on top of Hermes Agent.
"""

__version__ = "0.1.0"

from personal_intelligence.api.interface import (
    PersonalIntelligenceCapabilityInterface,
)

PersonalIntelligenceInterface = PersonalIntelligenceCapabilityInterface
PersonalIntelligenceClient = PersonalIntelligenceCapabilityInterface

__all__ = [
    "PersonalIntelligenceCapabilityInterface",
    "PersonalIntelligenceInterface",
    "PersonalIntelligenceClient",
]
