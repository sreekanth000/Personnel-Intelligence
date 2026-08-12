"""Deterministic Reconciliation Engine for Gmail-derived relationships and claims.

Reconciles extracted candidate relationships against existing World Model state.
Determines outcomes:
- NOVEL: Brand new relationship not in World Model.
- CONFIRM: Matches existing active state exactly.
- REFINE: Refines existing state with new properties or evidence.
- UPDATE: Replaces old state (closes previous validity interval without deleting old record).
- CONFLICT: Direct contradiction requiring user confirmation.
- UNCERTAIN: Low confidence or ambiguous resolution requiring user review.

Guarantees:
- Old relationships are NEVER deleted on UPDATE — validity interval is closed (valid_to = now).
- Ambiguous changes set requires_user_confirmation = True.
- Audit trail stored via ReconciliationRecord (previous_state, new_state, evidence, timestamp, reason).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.config.logging import get_logger
from app.domain.claims import Claim
from app.domain.enums import ReconciliationOutcome
from app.domain.reconciliation import ReconciliationRecord
from app.domain.values import EvidenceSpan, TemporalRange

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.domain.entities import Relationship
    from app.domain.evidence import Evidence
    from app.domain.observations import Observation

logger = get_logger(__name__)


class BaseReconciliationEngine(ABC):
    """Abstract interface for deterministic reconciliation."""

    @abstractmethod
    async def reconcile_relationship(
        self,
        candidate: Relationship,
        existing_relationships: Sequence[Relationship],
        evidence: Evidence | EvidenceSpan | None = None,
    ) -> ReconciliationRecord:
        """Reconcile a candidate relationship against active World Model state."""

    @abstractmethod
    async def reconcile_claim(
        self,
        candidate: Claim,
        existing_claims: Sequence[Claim] | Any = None,
        evidence: Evidence | EvidenceSpan | Observation | None = None,
    ) -> ReconciliationRecord:
        """Reconcile a candidate claim against active World Model state."""


class ReconciliationEngine(BaseReconciliationEngine):
    """Production implementation of deterministic reconciliation."""

    def __init__(self, world_model_service: Any | None = None) -> None:
        self._world_model_service = world_model_service

    async def reconcile_relationship(
        self,
        candidate: Relationship,
        existing_relationships: Sequence[Relationship],
        evidence: Evidence | EvidenceSpan | None = None,
    ) -> ReconciliationRecord:
        """Reconcile a candidate relationship against existing World Model relationships."""
        now = datetime.now(UTC)
        cand_dict = candidate.model_dump(mode="json")
        evidence_item = evidence or candidate.evidence_span

        # Check for UNCERTAIN confidence threshold
        if candidate.confidence.score < 0.40:
            logger.warning(
                "reconciliation.uncertain_low_confidence", score=candidate.confidence.score
            )
            return ReconciliationRecord(
                outcome=ReconciliationOutcome.UNCERTAIN,
                previous_state=None,
                new_state=cand_dict,
                evidence=evidence_item,
                timestamp=now,
                reconciliation_reason=f"Uncertain: Candidate confidence score ({candidate.confidence.score}) is below minimum threshold 0.40.",
                requires_user_confirmation=True,
            )

        cand_subj = candidate.subject
        cand_obj = candidate.object
        cand_pred = str(candidate.predicate).lower()

        # Find existing active relationships between same subject or object
        active_existing = [r for r in existing_relationships if r.validity.is_open_ended]

        exact_matches = [
            r
            for r in active_existing
            if r.subject == cand_subj
            and r.object == cand_obj
            and str(r.predicate).lower() == cand_pred
        ]

        same_subject_same_pred = [
            r
            for r in active_existing
            if r.subject == cand_subj
            and str(r.predicate).lower() == cand_pred
            and r.object != cand_obj
        ]

        same_pair_diff_pred = [
            r
            for r in active_existing
            if r.subject == cand_subj
            and r.object == cand_obj
            and str(r.predicate).lower() != cand_pred
        ]

        # -------------------------------------------------------------------
        # Outcome 1: CONFIRM or REFINE
        # -------------------------------------------------------------------
        if exact_matches:
            prev_rel = exact_matches[0]
            prev_dict = prev_rel.model_dump(mode="json")

            # If candidate introduces new properties or higher confidence -> REFINE
            has_new_props = bool(
                candidate.properties and candidate.properties != prev_rel.properties
            )
            is_higher_conf = candidate.confidence.score > prev_rel.confidence.score

            if has_new_props or is_higher_conf:
                logger.info("reconciliation.refine", rel_id=candidate.id)
                return ReconciliationRecord(
                    outcome=ReconciliationOutcome.REFINE,
                    previous_state=prev_dict,
                    new_state=cand_dict,
                    evidence=evidence_item,
                    timestamp=now,
                    reconciliation_reason=f"Refine: Candidate adds new properties or higher confidence ({candidate.confidence.score} > {prev_rel.confidence.score}) to existing relationship.",
                    requires_user_confirmation=False,
                )

            logger.info("reconciliation.confirm", rel_id=candidate.id)
            return ReconciliationRecord(
                outcome=ReconciliationOutcome.CONFIRM,
                previous_state=prev_dict,
                new_state=cand_dict,
                evidence=evidence_item,
                timestamp=now,
                reconciliation_reason="Confirm: Candidate matches existing active relationship exactly.",
                requires_user_confirmation=False,
            )

        # -------------------------------------------------------------------
        # Outcome 2: UPDATE (e.g. John WORKS_FOR Company A -> John WORKS_FOR Company B)
        # -------------------------------------------------------------------
        if same_subject_same_pred:
            prev_rel = same_subject_same_pred[0]
            prev_dict = prev_rel.model_dump(mode="json")

            # Check if evidence is strong enough (confidence >= 0.70)
            if candidate.confidence.score >= 0.70:
                # Close old validity interval without deleting old record!
                prev_rel.validity = TemporalRange(
                    valid_from=prev_rel.validity.valid_from,
                    valid_to=now,
                )
                logger.info(
                    "reconciliation.update",
                    prev_id=prev_rel.id,
                    new_object=cand_obj,
                    closed_valid_to=now.isoformat(),
                )
                return ReconciliationRecord(
                    outcome=ReconciliationOutcome.UPDATE,
                    previous_state=prev_dict,
                    new_state=cand_dict,
                    evidence=evidence_item,
                    timestamp=now,
                    reconciliation_reason=f"Update: Replaced previous active target '{prev_rel.object}' with '{cand_obj}' for predicate '{cand_pred}'. Closed previous validity interval at {now.isoformat()}.",
                    requires_user_confirmation=False,
                    closed_previous_relationship_id=prev_rel.id,
                )

            # Weak update -> Require user confirmation
            logger.warning("reconciliation.ambiguous_update_user_review", prev_id=prev_rel.id)
            return ReconciliationRecord(
                outcome=ReconciliationOutcome.UPDATE,
                previous_state=prev_dict,
                new_state=cand_dict,
                evidence=evidence_item,
                timestamp=now,
                reconciliation_reason=f"Ambiguous Update: Candidate target '{cand_obj}' differs from active target '{prev_rel.object}', but confidence score {candidate.confidence.score} requires user confirmation.",
                requires_user_confirmation=True,
                closed_previous_relationship_id=prev_rel.id,
            )

        # -------------------------------------------------------------------
        # Outcome 3: CONFLICT
        # -------------------------------------------------------------------
        if same_pair_diff_pred:
            prev_rel = same_pair_diff_pred[0]
            prev_dict = prev_rel.model_dump(mode="json")
            logger.warning(
                "reconciliation.conflict",
                prev_pred=prev_rel.predicate,
                new_pred=cand_pred,
            )
            return ReconciliationRecord(
                outcome=ReconciliationOutcome.CONFLICT,
                previous_state=prev_dict,
                new_state=cand_dict,
                evidence=evidence_item,
                timestamp=now,
                reconciliation_reason=f"Conflict: Candidate predicate '{cand_pred}' contradicts existing active predicate '{prev_rel.predicate}' between '{cand_subj}' and '{cand_obj}'.",
                requires_user_confirmation=True,
            )

        # -------------------------------------------------------------------
        # Outcome 4: NOVEL
        # -------------------------------------------------------------------
        logger.info("reconciliation.novel", rel_id=candidate.id)
        return ReconciliationRecord(
            outcome=ReconciliationOutcome.NOVEL,
            previous_state=None,
            new_state=cand_dict,
            evidence=evidence_item,
            timestamp=now,
            reconciliation_reason="Novel: Brand new relationship edge not previously present in World Model.",
            requires_user_confirmation=False,
        )

    async def reconcile_claim(
        self,
        candidate: Claim,
        existing_claims: Sequence[Claim] | Any = None,
        evidence: Evidence | EvidenceSpan | Observation | None = None,
    ) -> ReconciliationRecord:
        """Reconcile a candidate claim against existing World Model claims."""
        now = datetime.now(UTC)

        # Robust handling for legacy interface calls: reconcile_claim(claim, obs)
        claims_list: list[Claim] = []
        if existing_claims is not None:
            if hasattr(existing_claims, "raw_metadata") or hasattr(
                existing_claims, "source_identifier"
            ):
                # Pass as observation evidence
                evidence = existing_claims  # type: ignore[assignment]
            elif isinstance(existing_claims, (list, tuple)):
                claims_list = [c for c in existing_claims if isinstance(c, Claim)]
            elif isinstance(existing_claims, Claim):
                claims_list = [existing_claims]

        cand_dict = candidate.model_dump(mode="json")
        evidence_item = evidence or (
            candidate.evidence_spans[0] if candidate.evidence_spans else None
        )

        if candidate.confidence.score < 0.40:
            return ReconciliationRecord(
                outcome=ReconciliationOutcome.UNCERTAIN,
                previous_state=None,
                new_state=cand_dict,
                evidence=evidence_item,
                timestamp=now,
                reconciliation_reason=f"Uncertain: Claim confidence ({candidate.confidence.score}) is below minimum threshold 0.40.",
                requires_user_confirmation=True,
            )

        exact_matches = [
            c
            for c in claims_list
            if c.subject == candidate.subject
            and c.predicate == candidate.predicate
            and c.value == candidate.value
        ]

        same_subj_pred_diff_val = [
            c
            for c in claims_list
            if c.subject == candidate.subject
            and c.predicate == candidate.predicate
            and c.value != candidate.value
        ]

        if exact_matches:
            prev_claim = exact_matches[0]
            return ReconciliationRecord(
                outcome=ReconciliationOutcome.CONFIRM,
                previous_state=prev_claim.model_dump(mode="json"),
                new_state=cand_dict,
                evidence=evidence_item,
                timestamp=now,
                reconciliation_reason="Confirm: Candidate claim matches existing claim value exactly.",
                requires_user_confirmation=False,
            )

        if same_subj_pred_diff_val:
            prev_claim = same_subj_pred_diff_val[0]
            if candidate.confidence.score >= 0.70:
                return ReconciliationRecord(
                    outcome=ReconciliationOutcome.UPDATE,
                    previous_state=prev_claim.model_dump(mode="json"),
                    new_state=cand_dict,
                    evidence=evidence_item,
                    timestamp=now,
                    reconciliation_reason=f"Update: Candidate claim value '{candidate.value}' supersedes previous value '{prev_claim.value}'.",
                    requires_user_confirmation=False,
                )
            return ReconciliationRecord(
                outcome=ReconciliationOutcome.CONFLICT,
                previous_state=prev_claim.model_dump(mode="json"),
                new_state=cand_dict,
                evidence=evidence_item,
                timestamp=now,
                reconciliation_reason=f"Conflict: Candidate claim value '{candidate.value}' contradicts existing value '{prev_claim.value}'. Requires user confirmation.",
                requires_user_confirmation=True,
            )

        return ReconciliationRecord(
            outcome=ReconciliationOutcome.NOVEL,
            previous_state=None,
            new_state=cand_dict,
            evidence=evidence_item,
            timestamp=now,
            reconciliation_reason="Novel: Brand new claim proposition.",
            requires_user_confirmation=False,
        )
