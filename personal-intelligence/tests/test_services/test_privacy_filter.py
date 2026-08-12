"""Unit tests for the policy-driven PrivacyFilter context firewall.

Verifies:
- PII redaction (email, phone, SSN, credit card, API keys, salary figures)
- Blocked property key stripping (password, ssn, api_key)
- Low confidence relationship & claim filtering
- Evidence text snippet masking & scrubbing
- Custom PrivacyPolicy configuration
"""

from __future__ import annotations

import pytest

from app.domain import (
    Claim,
    ClaimStatus,
    Commitment,
    ConfidenceScore,
    ContextPackage,
    Decision,
    Entity,
    EntityType,
    Evidence,
    EvidenceSpan,
    EvidenceType,
    Provenance,
    Relationship,
    RelationshipType,
    StateChange,
)
from app.services.privacy_filter import PrivacyFilter, PrivacyPolicy, scrub_pii_text


def test_scrub_pii_text_patterns() -> None:
    """Verifies regex PII scrubbing on sample sensitive strings."""
    policy = PrivacyPolicy(redact_pii=True)

    text_email = "Contact me at alice.smith@google.com for access."
    assert scrub_pii_text(text_email, policy) == "Contact me at [EMAIL_REDACTED] for access."

    text_phone = "Call +1-555-867-5309 immediately."
    assert scrub_pii_text(text_phone, policy) == "Call [PHONE_REDACTED] immediately."

    text_ssn = "Tax ID is 123-45-6789."
    assert scrub_pii_text(text_ssn, policy) == "Tax ID is [SSN_REDACTED]."

    text_key = "Authorization: Bearer secret-token-abc-1234567890"
    assert scrub_pii_text(text_key, policy) == "Authorization: [SECRET_REDACTED]"

    text_salary = "Offered annual compensation: $180,000 per year."
    assert scrub_pii_text(text_salary, policy) == "Offered annual [COMPENSATION_REDACTED] per year."


def test_privacy_filter_sanitizes_package() -> None:
    """Verifies PrivacyFilter sanitizes ContextPackage entities, relationships, evidence, and property keys."""
    policy = PrivacyPolicy(redact_pii=True)
    firewall = PrivacyFilter(policy=policy)

    span = EvidenceSpan(
        text_snippet="Send report to boss@company.org or call 555-123-4567.",
        confidence=ConfidenceScore.from_score(0.95),
    )

    ent_valid = Entity(
        id="e1",
        name="Alice Smith (alice@google.com)",
        entity_type=EntityType.PERSON,
        confidence=ConfidenceScore.from_score(0.95),
        email="alice.private@google.com",
        aliases=["alice.work@google.com", "555-867-5309"],
    )

    ent_nameless = Entity(
        id="e2",
        name="",
        entity_type=EntityType.PERSON,
        confidence=ConfidenceScore.from_score(0.50),
    )

    rel_valid = Relationship(
        id="r1",
        subject="e1",
        predicate=RelationshipType.WORKS_FOR,
        object="org_google",
        confidence=ConfidenceScore.from_score(0.90),
        evidence_span=span,
        properties={"api_key": "sk-1234567890abcdef123456", "role": "Lead Architect"},
    )

    rel_low_conf = Relationship(
        id="r2",
        subject="e1",
        predicate=RelationshipType.MANAGES,
        object="e2",
        confidence=ConfidenceScore.from_score(0.20),  # < 0.40 -> Filtered out
    )

    claim = Claim(
        id="c1",
        subject="e1",
        predicate="contact_email",
        value="secret.alice@privacy.net",
        status=ClaimStatus.CONFIRMED,
        confidence=ConfidenceScore.from_score(0.95),
        evidence_spans=[span],
    )

    ev_record = Evidence(
        id="ev1",
        target_id="r1",
        target_type="relationship",
        evidence_type=EvidenceType.SUPPORTS,
        evidence_span=span,
        content="Raw body containing phone 555-987-6543 and email john@acme.com",
        source_observation_id="obs_100",
        confidence=ConfidenceScore.from_score(0.95),
    )

    raw_package = ContextPackage(
        request_id="req_100",
        purpose="user_query",
        entities=[ent_valid, ent_nameless],
        relationships=[rel_valid, rel_low_conf],
        claims=[claim],
        decisions=[],
        events=[],
        commitments=[],
        evidence=[ev_record],
        state_changes=[],
        summary="Context assembled with email test@domain.com included.",
    )

    sanitized = firewall.filter_package(raw_package)

    # 1. Nameless entity filtered
    assert len(sanitized.entities) == 1
    assert sanitized.entities[0].name == "Alice Smith ([EMAIL_REDACTED])"

    # 2. Email & aliases PII scrubbed
    assert sanitized.entities[0].email == "[EMAIL_REDACTED]"
    assert sanitized.entities[0].aliases == ["[EMAIL_REDACTED]", "[PHONE_REDACTED]"]

    # 3. Low confidence relationship filtered
    assert len(sanitized.relationships) == 1
    assert "api_key" not in sanitized.relationships[0].properties
    assert sanitized.relationships[0].properties["role"] == "Lead Architect"
    assert "[EMAIL_REDACTED]" in sanitized.relationships[0].evidence_span.text_snippet

    # 4. Claim PII scrubbed
    assert len(sanitized.claims) == 1
    assert sanitized.claims[0].value == "[EMAIL_REDACTED]"

    # 5. Evidence content PII scrubbed
    assert len(sanitized.evidence) == 1
    assert "[PHONE_REDACTED]" in sanitized.evidence[0].content
    assert "[EMAIL_REDACTED]" in sanitized.evidence[0].content

    # 6. Summary PII scrubbed
    assert "[EMAIL_REDACTED]" in sanitized.summary
    assert sanitized.filtered_count >= 2


def test_privacy_filter_evidence_masking() -> None:
    """Verifies evidence snippet masking mode when mask_evidence_snippets=True."""
    policy = PrivacyPolicy(mask_evidence_snippets=True)
    firewall = PrivacyFilter(policy=policy)

    span = EvidenceSpan(
        text_snippet="Sensitive conversation excerpt.",
        confidence=ConfidenceScore.from_score(0.95),
    )

    rel = Relationship(
        id="r1",
        subject="e1",
        predicate=RelationshipType.RESPONSIBLE_FOR,
        object="e2",
        confidence=ConfidenceScore.from_score(0.90),
        evidence_span=span,
    )

    pkg = ContextPackage(
        request_id="req_200",
        purpose="masked_query",
        entities=[],
        relationships=[rel],
        claims=[],
        decisions=[],
        events=[],
        commitments=[],
        evidence=[],
        state_changes=[],
        summary="Masking summary test.",
    )

    sanitized = firewall.filter_package(pkg)
    assert sanitized.relationships[0].evidence_span.text_snippet == "[EVIDENCE_SNIPPET_MASKED]"
