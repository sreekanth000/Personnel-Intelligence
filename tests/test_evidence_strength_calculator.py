"""
Unit tests for EvidenceStrengthCalculator (Blueprint §23, Decision 1).
"""

import unittest

from personal_intelligence.core.evidence_strength import (
    EvidenceStrengthCalculator,
    EvidenceStrengthLevel,
)
from personal_intelligence.hermes_bridge.reasoning import EvidenceStrength


class TestEvidenceStrengthCalculator(unittest.TestCase):
    def setUp(self) -> None:
        self.calc = EvidenceStrengthCalculator(
            strong_min_sources=3,
            strong_min_confidence=0.7,
            moderate_min_sources=2,
            moderate_solo_min_confidence=0.8,
            conflicted_min_contradictions=2,
        )

    def test_empty_evidence_returns_insufficient_evidence(self) -> None:
        """0 items -> insufficient_evidence."""
        res = self.calc.calculate([])
        self.assertEqual(res, EvidenceStrengthLevel.INSUFFICIENT_EVIDENCE)
        self.assertEqual(res, EvidenceStrength.INSUFFICIENT_EVIDENCE.value)

    def test_conflicted_evidence_with_multiple_contradictions(self) -> None:
        """≥2 contradicting items -> conflicted."""
        items = [
            {"source": "gmail", "confidence": 0.9, "contradicts": False},
            {"source": "calendar", "confidence": 0.85, "contradicts": True},
            {"source": "slack", "confidence": 0.8, "contradicts": True},
        ]
        res = self.calc.calculate(items)
        self.assertEqual(res, EvidenceStrengthLevel.CONFLICTED)
        self.assertEqual(res, EvidenceStrength.CONFLICTED.value)

    def test_strong_evidence_with_three_corroborating_sources(self) -> None:
        """≥3 distinct sources with high confidence -> strong."""
        items = [
            {"source": "gmail", "confidence": 0.9},
            {"source": "calendar", "confidence": 0.85},
            {"source": "drive", "confidence": 0.75},
        ]
        res = self.calc.calculate(items)
        self.assertEqual(res, EvidenceStrengthLevel.STRONG)
        self.assertEqual(res, EvidenceStrength.STRONG.value)

    def test_moderate_evidence_with_two_sources(self) -> None:
        """2 distinct sources -> moderate."""
        items = [
            {"source": "gmail", "confidence": 0.7},
            {"source": "calendar", "confidence": 0.7},
        ]
        res = self.calc.calculate(items)
        self.assertEqual(res, EvidenceStrengthLevel.MODERATE)
        self.assertEqual(res, EvidenceStrength.MODERATE.value)

    def test_single_source_produces_weak_under_v12(self) -> None:
        """V1.2: A single source group strictly produces WEAK regardless of float confidence."""
        items = [
            {"source": "gmail", "confidence": 0.95},
        ]
        res = self.calc.calculate(items)
        self.assertEqual(res, EvidenceStrengthLevel.WEAK)

    def test_weak_evidence_single_low_confidence_source(self) -> None:
        """1 source -> weak."""
        items = [
            {"source": "gmail", "confidence": 0.5},
        ]
        res = self.calc.calculate(items)
        self.assertEqual(res, EvidenceStrengthLevel.WEAK)
        self.assertEqual(res, EvidenceStrength.WEAK.value)


if __name__ == "__main__":
    unittest.main()
