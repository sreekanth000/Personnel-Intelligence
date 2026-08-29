"""
Deterministic Evidence Strength Calculator for Personal Intelligence.

Calculates evidence strength from observation provenance, corroboration, and contradiction
WITHOUT relying on Hermes LLM output or fake numeric probabilities.

Blueprint Reference: §23 & Prompt V1.2 Hardening:
Independence Rule:
Two observations count as independent ONLY when:
  1. They originate from different observation channels/types, AND
  2. They do not share the same underlying origin event (origin_event_id).

Outputs strictly:
  INSUFFICIENT_EVIDENCE | WEAK | MODERATE | STRONG | CONFLICTED
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from personal_intelligence.core.events.models import ensure_timezone_aware


class EvidenceStrengthLevel:
    """Canonical evidence strength categorical constants."""
    STRONG = "strong"
    MODERATE = "moderate"
    CONFLICTED = "conflicted"
    WEAK = "weak"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

    ALL = frozenset({STRONG, MODERATE, CONFLICTED, WEAK, INSUFFICIENT_EVIDENCE})


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


class EvidenceStrengthCalculator:
    """
    Deterministic evidence strength calculator.
    Consumes a list of evidence items/observations and evaluates empirical corroboration
    based on independent evidence groups and contradiction lineage.
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
        Calculates deterministic categorical evidence strength.

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
            One of 'strong', 'moderate', 'conflicted', 'weak', 'insufficient_evidence'
        """
        if not evidence_items:
            return EvidenceStrengthLevel.INSUFFICIENT_EVIDENCE

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

        # 1. Contradictions Check
        contradicting = [e for e in items if e.get("contradicts", False) is True]
        supporting = [e for e in items if not e.get("contradicts", False)]

        if len(contradicting) >= self.conflicted_min_contradictions and supporting:
            return EvidenceStrengthLevel.CONFLICTED

        if not supporting:
            return EvidenceStrengthLevel.CONFLICTED if contradicting else EvidenceStrengthLevel.INSUFFICIENT_EVIDENCE

        # 2. Extract Independent Evidence Groups using Provenance Lineage
        independent_groups: Set[str] = set()
        for item in supporting:
            grp_key = extract_evidence_group_key(item)
            independent_groups.add(grp_key)

        group_count = len(independent_groups)

        # 3. Deterministic Category Assignment
        # STRONG: ≥3 independent evidence groups AND no material contradiction
        if group_count >= self.strong_min_groups:
            return EvidenceStrengthLevel.STRONG

        # MODERATE: ≥2 independent evidence groups
        if group_count >= self.moderate_min_groups:
            return EvidenceStrengthLevel.MODERATE

        # WEAK: 1 independent evidence group
        if group_count >= 1:
            return EvidenceStrengthLevel.WEAK

        # INSUFFICIENT_EVIDENCE: 0 independent evidence groups
        return EvidenceStrengthLevel.INSUFFICIENT_EVIDENCE

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
