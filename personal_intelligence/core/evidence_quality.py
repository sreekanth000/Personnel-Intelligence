"""
Deterministic Evidence Quality Calculator for Personal Intelligence.

Calculates evidence quality from observation provenance, corroboration, and contradiction
WITHOUT relying on Hermes LLM output or fake numeric probabilities.

Epistemic Framing Principle:
The system communicates the quality and support provided by available evidence (WEAK, MODERATE, STRONG),
NOT that the underlying conclusion is objectively true or guaranteed certain.
STRONG evidence does NOT imply a TRUE conclusion or VERIFIED fact.

Outputs strictly:
  WEAK | MODERATE | STRONG | CONFLICTED | INSUFFICIENT_EVIDENCE
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from personal_intelligence.core.events.models import ensure_timezone_aware


class EvidenceQualityLevel:
    """Canonical evidence quality categorical levels.
    
    These categories describe the available evidence support, not certainty of the conclusion.
    """
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    CONFLICTED = "conflicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

    ALL = frozenset({STRONG, MODERATE, WEAK, CONFLICTED, INSUFFICIENT_EVIDENCE})


# Backward-compatible alias
EvidenceStrengthLevel = EvidenceQualityLevel


def extract_evidence_group_key(item: Dict[str, Any]) -> str:
    """
    Computes an evidence grouping key based on provenance lineage.
    
    If an item has an origin_event_id or parent_id, that lineage roots the group.
    Otherwise, the channel/source (e.g., 'gmail', 'calendar') forms the root group.
    """
    prov = item.get("provenance") or {}
    if not isinstance(prov, dict):
        prov = {}

    origin_id = (
        item.get("origin_event_id")
        or prov.get("origin_event_id")
        or item.get("parent_id")
        or prov.get("parent_id")
        or item.get("thread_id")
        or prov.get("thread_id")
    )

    source_type = (
        item.get("source")
        or item.get("origin_source")
        or item.get("source_type")
        or prov.get("origin_source")
        or prov.get("source")
        or "unknown"
    )
    source_type = str(source_type).strip().lower()

    if origin_id:
        # Items sharing the same underlying origin event belong to the same lineage group
        return f"lineage:{str(origin_id).strip().lower()}"

    # Items without explicit origin sharing the same source channel belong to the channel group
    return f"channel:{source_type}"


class EvidenceQualityCalculator:
    """
    Deterministic evidence quality calculator.
    Consumes a list of evidence items/observations and evaluates empirical corroboration
    based on independent evidence groups, contradiction lineage, freshness, and directness.
    
    Important Epistemic Invariant:
    Communicates evidence quality/support, NOT conclusion certainty.
    A conclusion supported by STRONG evidence remains an inference/hypothesis,
    never automatically a guaranteed truth or verified fact.
    """

    def __init__(
        self,
        strong_min_independent_groups: int = 3,
        moderate_min_independent_groups: int = 2,
        conflicted_min_contradictions: int = 1,
        stale_threshold_hours: float = 72.0,
        **kwargs: Any,
    ) -> None:
        self.strong_min_groups = strong_min_independent_groups
        self.moderate_min_groups = moderate_min_independent_groups
        self.conflicted_min_contradictions = conflicted_min_contradictions
        self.stale_threshold = timedelta(hours=stale_threshold_hours)

    def calculate(
        self,
        evidence_items: Sequence[Dict[str, Any]],
        reference_time: Optional[datetime] = None,
    ) -> str:
        """
        Calculates deterministic categorical evidence quality (WEAK, MODERATE, STRONG).

        Parameters
        ----------
        evidence_items : sequence of dict
            Each item should contain:
              - 'source': str (e.g. 'gmail', 'calendar', 'drive', 'slack', 'device')
              - 'source_id': str (optional, verifies provenance)
              - 'origin_event_id': str (optional, verifies lineage)
              - 'contradicts': bool (optional, flag for contradicting evidence)
              - 'observed_at' / 'event_time': str or datetime (optional for recency check)
        reference_time : datetime, optional
            Current reference time for recency evaluation.

        Returns
        -------
        str
            One of 'strong', 'moderate', 'weak', 'conflicted', 'insufficient_evidence'
        """
        if not evidence_items:
            return EvidenceQualityLevel.INSUFFICIENT_EVIDENCE

        # Normalize items whether strings, dicts, or objects
        items: List[Dict[str, Any]] = []
        for e in evidence_items:
            if isinstance(e, dict):
                items.append(e)
            elif isinstance(e, str):
                items.append({"source": "evidence_text", "content": e, "contradicts": False, "source_id": "txt_item"})
            else:
                items.append({"source": str(type(e).__name__), "content": str(e), "contradicts": False})

        now = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )

        # 1. Contradictions Check (Consistency)
        contradicting = [e for e in items if e.get("contradicts", False) is True]
        supporting = [e for e in items if not e.get("contradicts", False)]

        if len(contradicting) >= self.conflicted_min_contradictions and supporting:
            return EvidenceQualityLevel.CONFLICTED

        if not supporting:
            return EvidenceQualityLevel.CONFLICTED if contradicting else EvidenceQualityLevel.INSUFFICIENT_EVIDENCE

        # 2. Epistemic Directness: Filter out bare inferences masquerading as observations
        direct_supporting = []
        for item in supporting:
            # Epistemic guard: Inferences cannot serve as primary facts without supporting observation
            if item.get("epistemic_type") == "inferred" and not (item.get("origin_event_id") or item.get("source_id")):
                continue
            direct_supporting.append(item)

        if not direct_supporting:
            return EvidenceQualityLevel.INSUFFICIENT_EVIDENCE

        # 3. Extract Independent Evidence Groups using Provenance Lineage (Source Independence & Corroboration)
        independent_groups: Set[str] = set()
        for item in direct_supporting:
            grp_key = extract_evidence_group_key(item)
            independent_groups.add(grp_key)

        group_count = len(independent_groups)

        # 4. Freshness Evaluation
        all_stale = True
        has_timestamps = False
        for item in direct_supporting:
            raw_ts = item.get("event_time") or item.get("observed_at") or item.get("timestamp")
            if raw_ts:
                has_timestamps = True
                try:
                    ts = ensure_timezone_aware(raw_ts, "item_time")
                    if now - ts <= self.stale_threshold:
                        all_stale = False
                        break
                except Exception:
                    pass

        # If all evidence with timestamps is stale, downgrade quality level
        is_stale = has_timestamps and all_stale

        # 5. Deterministic Category Assignment
        # STRONG: ≥3 independent evidence groups AND no material contradiction AND fresh
        if group_count >= self.strong_min_groups:
            return EvidenceQualityLevel.MODERATE if is_stale else EvidenceQualityLevel.STRONG

        # MODERATE: ≥2 independent evidence groups
        if group_count >= self.moderate_min_groups:
            return EvidenceQualityLevel.WEAK if is_stale else EvidenceQualityLevel.MODERATE

        # WEAK: 1 independent evidence group
        if group_count >= 1:
            return EvidenceQualityLevel.WEAK

        # INSUFFICIENT_EVIDENCE: 0 independent evidence groups
        return EvidenceQualityLevel.INSUFFICIENT_EVIDENCE

    def evaluate(
        self,
        evidence_items: Sequence[Dict[str, Any]],
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Comprehensive deterministic evaluation returning structured epistemic factors:
        source independence, freshness, consistency, directness, corroboration, provenance completeness.
        
        Strict Epistemic Invariant:
        Returns certainty=False and fact_verified=False. Evidence quality measures evidentiary
        support, NOT objective certainty of the conclusion.
        """
        quality = self.calculate(evidence_items, reference_time=reference_time)

        # Detailed factor breakdown
        independent_groups: Set[str] = set()
        has_contradiction = False
        all_stale = True
        has_timestamps = False
        provenance_complete = True
        direct_count = 0
        inferred_count = 0

        now = ensure_timezone_aware(reference_time or datetime.now(timezone.utc), "reference_time")

        for e in evidence_items:
            if not isinstance(e, dict):
                provenance_complete = False
                continue
            if e.get("contradicts", False):
                has_contradiction = True
            else:
                independent_groups.add(extract_evidence_group_key(e))
                ep_type = str(e.get("epistemic_type", "observed")).lower()
                if ep_type == "inferred":
                    inferred_count += 1
                elif ep_type in ("predicted", "prediction"):
                    pass
                else:
                    direct_count += 1

            # Provenance check
            if not (e.get("source_id") or e.get("id") or e.get("provenance")):
                provenance_complete = False

            # Recency
            raw_ts = e.get("event_time") or e.get("observed_at") or e.get("timestamp")
            if raw_ts:
                has_timestamps = True
                try:
                    ts = ensure_timezone_aware(raw_ts, "recency")
                    if now - ts <= self.stale_threshold:
                        all_stale = False
                except Exception:
                    pass

        is_stale = has_timestamps and all_stale

        corroboration = (
            "strong_corroboration" if len(independent_groups) >= self.strong_min_groups
            else ("moderate_corroboration" if len(independent_groups) >= self.moderate_min_groups
                  else ("single_source" if len(independent_groups) == 1 else "unsupported"))
        )

        return {
            "evidence_quality": quality,
            "quality": quality,
            "strength": quality,  # Backward compatibility alias
            "evidence_strength": quality,  # Backward compatibility alias
            "independent_sources_count": len(independent_groups),
            "corroboration_status": corroboration,
            "has_contradictions": has_contradiction,
            "is_stale": is_stale,
            "provenance_complete": provenance_complete,
            "direct_observations_count": direct_count,
            "inferred_items_count": inferred_count,
            # Epistemic Invariants: High quality evidence does NOT assert conclusion certainty or facthood
            "certainty": False,
            "fact_verified": False,
        }

    @staticmethod
    def validate_epistemic_conversion(
        fact_candidate: Dict[str, Any],
        supporting_observations: Sequence[Dict[str, Any]],
    ) -> bool:
        """
        Enforces the non-negotiable Epistemic Rule:
        Never allow INFERENCE -> FACT without explicit supporting observation/evidence.
        """
        if not supporting_observations:
            return False

        # If candidate is an inference, it cannot be promoted to fact unless backed by verified observations
        has_direct_obs = False
        for obs in supporting_observations:
            if not isinstance(obs, dict):
                continue
            ep_type = obs.get("epistemic_type", "observed")
            if ep_type in ("observed", "direct"):
                has_direct_obs = True
                break

        return has_direct_obs

    def calculate_from_observations(
        self,
        observations: List[Dict[str, Any]],
        contradictions: Optional[List[Dict[str, Any]]] = None,
        reference_time: Optional[datetime] = None,
    ) -> str:
        """Convenience method accepting separate observation and contradiction lists."""
        items: List[Dict[str, Any]] = []
        for obs in observations:
            item = dict(obs)
            item.setdefault("contradicts", False)
            items.append(item)
        if contradictions:
            for contra in contradictions:
                item = dict(contra)
                item["contradicts"] = True
                items.append(item)
        return self.calculate(items, reference_time=reference_time)


# Backward-compatible alias
EvidenceStrengthCalculator = EvidenceQualityCalculator
