"""
Backward-compatibility module for Evidence Strength -> Evidence Quality transition.

DEPRECATION NOTICE:
Conceptual framing has migrated from 'Evidence Strength' to 'Evidence Quality'
via EvidenceQualityCalculator. The system communicates the quality/support of available
evidence (WEAK, MODERATE, STRONG) without claiming objective truth or conclusion certainty.
"""

from personal_intelligence.core.evidence_quality import (
    EvidenceQualityCalculator,
    EvidenceQualityLevel,
    EvidenceStrengthCalculator,
    EvidenceStrengthLevel,
    extract_evidence_group_key,
)

__all__ = [
    "EvidenceQualityCalculator",
    "EvidenceQualityLevel",
    "EvidenceStrengthCalculator",
    "EvidenceStrengthLevel",
    "extract_evidence_group_key",
]
