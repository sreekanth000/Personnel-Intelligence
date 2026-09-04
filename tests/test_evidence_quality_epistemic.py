"""
Acceptance Test Suite for Evidence Quality Epistemic Model.

Verifies:
1. Evidence quality calculation communicates support level (WEAK, MODERATE, STRONG),
   NOT objective certainty or truth of the conclusion.
2. A reasoning result containing strong supporting evidence produces:
   evidence_quality = STRONG,
   but does NOT automatically produce certainty = TRUE or fact = VERIFIED.
3. Inferences supported by strong evidence remain inferences (cannot silently become observations).
4. Hermes returns evidence references and observations used, while PI calculates evidence quality.
5. Evidence quality considers:
   - source independence
   - freshness
   - consistency (contradictions)
   - directness (direct observations vs bare inferences)
   - corroboration (independent groups)
   - provenance completeness.
6. Backward compatibility for EvidenceStrengthCalculator, EvidenceStrengthLevel, and stored fields.
"""

from datetime import datetime, timedelta, timezone
import unittest

from personal_intelligence.core.evidence_quality import (
    EvidenceQualityCalculator,
    EvidenceQualityLevel,
    EvidenceStrengthCalculator,
    EvidenceStrengthLevel,
)
from personal_intelligence.core.episodes.models import ReasoningEpisode
from personal_intelligence.core.policy.engine import decide_intervention, InterventionPolicyEngine
from personal_intelligence.core.world.models import EpistemicIntegrityError, EpistemicRecord, EpistemicType
from personal_intelligence.hermes_bridge.reasoning import (
    EvidenceQuality,
    EvidenceStrength,
    StructuredReasoningSynthesis,
    validate_reasoning_synthesis,
)


class TestEvidenceQualityEpistemic(unittest.TestCase):
    """Test suite verifying Evidence Quality epistemic framing and invariants."""

    def setUp(self) -> None:
        self.calc = EvidenceQualityCalculator(stale_threshold_hours=72.0)
        self.now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)

    def test_strong_evidence_quality_does_not_claim_certainty_or_verified_fact(self) -> None:
        """
        Acceptance Requirement:
        A reasoning result containing strong supporting evidence produces evidence_quality = STRONG,
        but must NOT automatically produce certainty = TRUE or fact = VERIFIED.
        """
        evidence_items = [
            {
                "source": "gmail",
                "source_id": "msg-101",
                "origin_event_id": "evt-gmail-101",
                "event_time": self.now - timedelta(hours=2),
                "epistemic_type": "observed",
                "statement": "Client confirmed Friday deployment in email.",
                "provenance": {"tool": "gmail_fetch"},
            },
            {
                "source": "calendar",
                "source_id": "cal-202",
                "origin_event_id": "evt-cal-202",
                "event_time": self.now - timedelta(hours=1),
                "epistemic_type": "observed",
                "statement": "Deployment window scheduled on Calendar for Friday 14:00.",
                "provenance": {"tool": "calendar_list"},
            },
            {
                "source": "slack",
                "source_id": "slack-303",
                "origin_event_id": "evt-slack-303",
                "event_time": self.now - timedelta(minutes=30),
                "epistemic_type": "observed",
                "statement": "Release engineer confirmed readiness in deployment channel.",
                "provenance": {"tool": "slack_history"},
            },
        ]

        # 1. PI calculates evidence quality
        eval_result = self.calc.evaluate(evidence_items, reference_time=self.now)
        quality = self.calc.calculate(evidence_items, reference_time=self.now)

        # Evidence quality is STRONG
        self.assertEqual(quality, EvidenceQualityLevel.STRONG)
        self.assertEqual(eval_result["evidence_quality"], "strong")
        self.assertEqual(eval_result["quality"], "strong")

        # Invariant: Evidence quality communicates support, NOT objective certainty or verified fact
        self.assertFalse(eval_result["certainty"], "Strong evidence must NOT automatically produce certainty = True")
        self.assertFalse(eval_result["fact_verified"], "Strong evidence must NOT automatically produce fact = VERIFIED")

    def test_inference_supported_by_strong_evidence_remains_inference(self) -> None:
        """
        Inferences drawn from strong evidence remain inferences (epistemic_type='inferred').
        They cannot silently promote to observations or bypass observation provenance rules.
        """
        inference_record = EpistemicRecord(
            epistemic_type=EpistemicType.INFERRED,
            statement="Client will definitely execute deployment on Friday.",
            subject="Client",
            predicate="deployment_intent",
            object="confirmed",
            supporting_observation_ids=["evt-gmail-101", "evt-cal-202", "evt-slack-303"],
        )

        # Still an inference
        self.assertEqual(inference_record.epistemic_type, "inferred")

        # Even with 3 strong supporting observations, promote_to_observation must raise EpistemicIntegrityError
        with self.assertRaises(EpistemicIntegrityError):
            inference_record.promote_to_observation()

    def test_hermes_cannot_self_certify_certainty_or_confidence(self) -> None:
        """
        Hermes returns evidence references, not numerical confidence or self-certified certainty.
        Numerical confidence in Hermes output is rejected.
        """
        raw_output_with_confidence = """{
            "what_is_happening": "Project launch will succeed tomorrow.",
            "evidence_summary": ["3 confirmations received"],
            "inferences": ["Team is prepared"],
            "predictions": ["Zero downtime expected"],
            "uncertainties": [],
            "what_would_change_assessment": [],
            "recommendations": ["Proceed with release"],
            "requires_follow_up": false,
            "urgency": "medium",
            "actionability": "high",
            "relevance": "high",
            "confidence": 0.99
        }"""

        synth, errors = validate_reasoning_synthesis(raw_output_with_confidence)
        self.assertIsNone(synth)
        self.assertTrue(any("confidence" in err for err in errors))

    def test_evidence_quality_factors(self) -> None:
        """
        Evidence quality considers:
        - source independence
        - freshness
        - consistency (contradictions)
        - directness
        - corroboration
        - provenance.
        """
        # A. Consistency: Contradicting evidence marks state as CONFLICTED
        items_with_contradiction = [
            {"source": "gmail", "origin_event_id": "ev1", "event_time": self.now, "contradicts": False},
            {"source": "slack", "origin_event_id": "ev2", "event_time": self.now, "contradicts": False},
            {"source": "phone", "origin_event_id": "ev3", "event_time": self.now, "contradicts": True},
        ]
        res_conflicted = self.calc.evaluate(items_with_contradiction, reference_time=self.now)
        self.assertEqual(res_conflicted["evidence_quality"], EvidenceQualityLevel.CONFLICTED)
        self.assertTrue(res_conflicted["has_contradictions"])

        # B. Freshness: Stale evidence (>72h old) downgrades quality level
        stale_items = [
            {"source": "gmail", "origin_event_id": "ev1", "event_time": self.now - timedelta(hours=100)},
            {"source": "calendar", "origin_event_id": "ev2", "event_time": self.now - timedelta(hours=90)},
            {"source": "slack", "origin_event_id": "ev3", "event_time": self.now - timedelta(hours=80)},
        ]
        res_stale = self.calc.evaluate(stale_items, reference_time=self.now)
        self.assertTrue(res_stale["is_stale"])
        # Downgraded from STRONG to MODERATE due to staleness
        self.assertEqual(res_stale["evidence_quality"], EvidenceQualityLevel.MODERATE)

        # C. Directness: Bare inferences are filtered out
        bare_inferences = [
            {"source": "reasoning", "epistemic_type": "inferred"},  # No origin_event_id or source_id
        ]
        self.assertEqual(self.calc.calculate(bare_inferences), EvidenceQualityLevel.INSUFFICIENT_EVIDENCE)

    def test_backward_compatibility_aliases_and_policy(self) -> None:
        """
        Verifies backward compatibility:
        - EvidenceStrengthLevel is an alias for EvidenceQualityLevel
        - EvidenceStrengthCalculator is an alias for EvidenceQualityCalculator
        - ReasoningEpisode supports both evidence_quality and evidence_strength
        - InterventionPolicyEngine accepts both
        """
        self.assertIs(EvidenceStrengthLevel, EvidenceQualityLevel)
        self.assertIs(EvidenceStrengthCalculator, EvidenceQualityCalculator)
        self.assertIs(EvidenceStrength, EvidenceQuality)

        # ReasoningEpisode compatibility
        ep = ReasoningEpisode(
            situation_id="sit-1",
            evidence_quality="strong",
        )
        self.assertEqual(ep.evidence_quality, "strong")
        self.assertEqual(ep.evidence_strength, "strong")
        self.assertEqual(ep.to_dict()["evidence_quality"], "strong")
        self.assertEqual(ep.to_dict()["evidence_strength"], "strong")

        # Intervention policy compatibility
        policy_res = decide_intervention(
            urgency="high",
            actionability="high",
            evidence_quality="strong",
            attention_state="available",
        )
        self.assertEqual(policy_res.action, "INTERRUPT")
        self.assertEqual(policy_res.evidence_quality, "strong")
        self.assertEqual(policy_res.evidence_strength, "strong")


if __name__ == "__main__":
    unittest.main()
