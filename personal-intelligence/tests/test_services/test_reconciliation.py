"""Extensive unit tests for deterministic reconciliation of Gmail-derived relationships and claims.

Verifies:
- NOVEL: Brand new relationship edge
- CONFIRM: John -> WORKS_FOR -> Company A (identical match)
- REFINE: Existing relationship enriched with higher confidence or properties
- UPDATE: John -> WORKS_FOR -> Company A -> John -> WORKS_FOR -> Company B
  * Old relationship is NOT deleted
  * Old relationship validity interval is closed (valid_to = now)
  * closed_previous_relationship_id populated
- CONFLICT: Conflicting predicate requires user confirmation (requires_user_confirmation = True)
- UNCERTAIN: Low confidence score requires user review
- Claim reconciliation outcomes (CONFIRM, UPDATE, CONFLICT, NOVEL)
"""

from __future__ import annotations

import pytest

from app.domain import (
    Claim,
    ClaimStatus,
    ConfidenceScore,
    ReconciliationOutcome,
    Relationship,
    RelationshipType,
    TemporalRange,
)
from app.services.reconciliation import ReconciliationEngine


@pytest.fixture()
def engine() -> ReconciliationEngine:
    """Fixture for ReconciliationEngine."""
    return ReconciliationEngine()


@pytest.mark.asyncio
async def test_reconcile_novel_relationship(engine: ReconciliationEngine) -> None:
    """Brand new relationship edge evaluates to NOVEL."""
    cand = Relationship(
        subject="john_id",
        predicate=RelationshipType.WORKS_FOR,
        object="company_a_id",
        confidence=ConfidenceScore.from_score(0.95),
    )

    rec = await engine.reconcile_relationship(candidate=cand, existing_relationships=[])

    assert rec.outcome == ReconciliationOutcome.NOVEL
    assert rec.previous_state is None
    assert rec.new_state["subject"] == "john_id"
    assert not rec.requires_user_confirmation
    assert "Novel" in rec.reconciliation_reason


@pytest.mark.asyncio
async def test_reconcile_confirm_relationship(engine: ReconciliationEngine) -> None:
    """Exact identical relationship evaluates to CONFIRM: John -> WORKS_FOR -> Company A."""
    existing_rel = Relationship(
        id="rel_old_1",
        subject="john_id",
        predicate=RelationshipType.WORKS_FOR,
        object="company_a_id",
        confidence=ConfidenceScore.from_score(0.90),
    )

    cand_rel = Relationship(
        subject="john_id",
        predicate=RelationshipType.WORKS_FOR,
        object="company_a_id",
        confidence=ConfidenceScore.from_score(0.90),
    )

    rec = await engine.reconcile_relationship(
        candidate=cand_rel, existing_relationships=[existing_rel]
    )

    assert rec.outcome == ReconciliationOutcome.CONFIRM
    assert rec.previous_state is not None
    assert rec.previous_state["id"] == "rel_old_1"
    assert not rec.requires_user_confirmation
    assert "Confirm" in rec.reconciliation_reason


@pytest.mark.asyncio
async def test_reconcile_refine_relationship(engine: ReconciliationEngine) -> None:
    """Higher confidence or added properties evaluates to REFINE."""
    existing_rel = Relationship(
        id="rel_old_1",
        subject="john_id",
        predicate=RelationshipType.WORKS_FOR,
        object="company_a_id",
        confidence=ConfidenceScore.from_score(0.80),
    )

    cand_rel = Relationship(
        subject="john_id",
        predicate=RelationshipType.WORKS_FOR,
        object="company_a_id",
        confidence=ConfidenceScore.from_score(0.95),  # higher confidence
        properties={"role": "Senior Engineer"},
    )

    rec = await engine.reconcile_relationship(
        candidate=cand_rel, existing_relationships=[existing_rel]
    )

    assert rec.outcome == ReconciliationOutcome.REFINE
    assert not rec.requires_user_confirmation
    assert "Refine" in rec.reconciliation_reason


@pytest.mark.asyncio
async def test_reconcile_update_relationship_closes_validity_without_deletion(
    engine: ReconciliationEngine,
) -> None:
    """UPDATE: John -> WORKS_FOR -> Company A -> John -> WORKS_FOR -> Company B closes old validity without deleting record."""
    existing_rel = Relationship(
        id="rel_company_a",
        subject="john_id",
        predicate=RelationshipType.WORKS_FOR,
        object="company_a_id",
        confidence=ConfidenceScore.from_score(0.90),
        validity=TemporalRange(),  # open-ended validity
    )
    assert existing_rel.validity.is_open_ended is True

    cand_rel = Relationship(
        id="rel_company_b",
        subject="john_id",
        predicate=RelationshipType.WORKS_FOR,
        object="company_b_id",  # new target company!
        confidence=ConfidenceScore.from_score(0.92),  # strong evidence >= 0.70
    )

    rec = await engine.reconcile_relationship(
        candidate=cand_rel, existing_relationships=[existing_rel]
    )

    assert rec.outcome == ReconciliationOutcome.UPDATE
    assert not rec.requires_user_confirmation
    assert rec.closed_previous_relationship_id == "rel_company_a"
    assert rec.previous_state is not None
    assert rec.previous_state["object"] == "company_a_id"
    assert rec.new_state["object"] == "company_b_id"

    # Guarantees old relationship is NOT deleted and validity is closed
    assert existing_rel.validity.is_open_ended is False
    assert existing_rel.validity.valid_to is not None


@pytest.mark.asyncio
async def test_reconcile_conflict_relationship_requires_user_confirmation(
    engine: ReconciliationEngine,
) -> None:
    """CONFLICT: Opposing predicate between same entities requires user confirmation."""
    existing_rel = Relationship(
        id="rel_1",
        subject="john_id",
        predicate=RelationshipType.MANAGES,
        object="team_alpha_id",
        confidence=ConfidenceScore.from_score(0.90),
    )

    cand_rel = Relationship(
        subject="john_id",
        predicate=RelationshipType.REPORTS_TO,  # conflicting predicate vs MANAGES
        object="team_alpha_id",
        confidence=ConfidenceScore.from_score(0.90),
    )

    rec = await engine.reconcile_relationship(
        candidate=cand_rel, existing_relationships=[existing_rel]
    )

    assert rec.outcome == ReconciliationOutcome.CONFLICT
    assert rec.requires_user_confirmation is True
    assert "Conflict" in rec.reconciliation_reason


@pytest.mark.asyncio
async def test_reconcile_uncertain_low_confidence(engine: ReconciliationEngine) -> None:
    """UNCERTAIN: Candidate confidence below 0.40 requires user review."""
    cand_rel = Relationship(
        subject="john_id",
        predicate=RelationshipType.WORKS_FOR,
        object="company_a_id",
        confidence=ConfidenceScore.from_score(0.30),  # < 0.40
    )

    rec = await engine.reconcile_relationship(candidate=cand_rel, existing_relationships=[])

    assert rec.outcome == ReconciliationOutcome.UNCERTAIN
    assert rec.requires_user_confirmation is True
    assert "Uncertain" in rec.reconciliation_reason


@pytest.mark.asyncio
async def test_reconcile_claim_outcomes(engine: ReconciliationEngine) -> None:
    """Reconciles claims into CONFIRM, UPDATE, CONFLICT, and NOVEL."""
    existing_claim = Claim(
        id="claim_1",
        subject="Project Alpha",
        predicate="status",
        value="in_progress",
        status=ClaimStatus.PROPOSED,
        confidence=ConfidenceScore.from_score(0.90),
    )

    # 1. Exact match -> CONFIRM
    cand_confirm = Claim(
        subject="Project Alpha",
        predicate="status",
        value="in_progress",
        confidence=ConfidenceScore.from_score(0.90),
    )
    rec_confirm = await engine.reconcile_claim(cand_confirm, [existing_claim])
    assert rec_confirm.outcome == ReconciliationOutcome.CONFIRM

    # 2. Strong new value -> UPDATE
    cand_update = Claim(
        subject="Project Alpha",
        predicate="status",
        value="completed",
        confidence=ConfidenceScore.from_score(0.95),  # >= 0.70
    )
    rec_update = await engine.reconcile_claim(cand_update, [existing_claim])
    assert rec_update.outcome == ReconciliationOutcome.UPDATE
    assert not rec_update.requires_user_confirmation

    # 3. Weak contradictory value -> CONFLICT
    cand_conflict = Claim(
        subject="Project Alpha",
        predicate="status",
        value="cancelled",
        confidence=ConfidenceScore.from_score(0.55),  # < 0.70
    )
    rec_conflict = await engine.reconcile_claim(cand_conflict, [existing_claim])
    assert rec_conflict.outcome == ReconciliationOutcome.CONFLICT
    assert rec_conflict.requires_user_confirmation is True
