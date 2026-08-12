"""Unit tests for Entity Resolution in the Personal World Model.

Verifies:
- Same person matching (exact name and normalized email match)
- Same organization matching (exact canonical organization domain match)
- Alias matching (alternate names / email aliases)
- Different people with same name (ambiguous case marking requires_review=True)
- Email aliases matching
- Organization domains matching
- Ambiguous cases prevention of automatic merging
"""

from __future__ import annotations

from app.domain import ConfidenceScore, Entity, EntityType
from app.services.entity_resolution import EntityResolver


def test_resolve_same_person_exact_email() -> None:
    """Exact normalized email address matches single existing person entity."""
    resolver = EntityResolver()

    existing_alice = Entity(
        id="ent_alice_1",
        entity_type=EntityType.PERSON,
        name="Alice Smith",
        email="alice@acme.com",
        confidence=ConfidenceScore.from_score(0.95),
    )

    extracted_alice = Entity(
        entity_type=EntityType.PERSON,
        name="Alice",
        email="ALICE@ACME.COM",  # case insensitive
        confidence=ConfidenceScore.from_score(0.90),
    )

    res = resolver.resolve_entity(extracted_alice, [existing_alice])

    assert res.matched_entity is not None
    assert res.matched_entity.id == existing_alice.id
    assert not res.requires_review
    assert "Exact normalized email match" in res.match_reason
    assert res.confidence.score >= 0.95


def test_resolve_same_organization_domain() -> None:
    """Exact canonical domain matches single existing organization entity."""
    resolver = EntityResolver()

    existing_acme = Entity(
        id="org_acme_1",
        entity_type=EntityType.ORGANIZATION,
        name="Acme Corporation",
        domain="acme.com",
        confidence=ConfidenceScore.from_score(0.99),
    )

    extracted_org = Entity(
        entity_type=EntityType.ORGANIZATION,
        name="acme.com",
        domain="acme.com",
        confidence=ConfidenceScore.from_score(0.90),
    )

    res = resolver.resolve_entity(extracted_org, [existing_acme])

    assert res.matched_entity is not None
    assert res.matched_entity.id == existing_acme.id
    assert not res.requires_review
    assert "domain match" in res.match_reason


def test_resolve_aliases_match() -> None:
    """Alias match resolves alternate names correctly."""
    resolver = EntityResolver()

    existing_bob = Entity(
        id="ent_bob_1",
        entity_type=EntityType.PERSON,
        name="Robert Jones",
        aliases=["Bob Jones", "bobj@acme.com"],
        confidence=ConfidenceScore.from_score(0.95),
    )

    extracted_bob = Entity(
        entity_type=EntityType.PERSON,
        name="Bob Jones",
        confidence=ConfidenceScore.from_score(0.85),
    )

    res = resolver.resolve_entity(extracted_bob, [existing_bob])

    assert res.matched_entity is not None
    assert res.matched_entity.id == existing_bob.id
    assert not res.requires_review
    assert "Alias match" in res.match_reason


def test_different_people_with_same_name_ambiguous() -> None:
    """Multiple candidates sharing exact same name are marked ambiguous for review."""
    resolver = EntityResolver()

    alice_england = Entity(
        id="ent_alice_uk",
        entity_type=EntityType.PERSON,
        name="Alice Smith",
        email="alice.smith@acme.co.uk",
        confidence=ConfidenceScore.from_score(0.90),
    )
    alice_usa = Entity(
        id="ent_alice_us",
        entity_type=EntityType.PERSON,
        name="Alice Smith",
        email="alice.smith@acme.com",
        confidence=ConfidenceScore.from_score(0.90),
    )

    extracted_ambiguous = Entity(
        entity_type=EntityType.PERSON,
        name="Alice Smith",
        confidence=ConfidenceScore.from_score(0.80),
    )

    res = resolver.resolve_entity(extracted_ambiguous, [alice_england, alice_usa])

    assert res.matched_entity is None
    assert res.requires_review is True
    assert len(res.candidate_entities) == 2
    assert "Ambiguous name match" in res.match_reason


def test_resolve_email_aliases() -> None:
    """Extracted email matching candidate email alias resolves cleanly."""
    resolver = EntityResolver()

    existing_user = Entity(
        id="ent_user_1",
        entity_type=EntityType.PERSON,
        name="Charlie Brown",
        email="charlie@primary.com",
        aliases=["cbrown@secondary.org"],
        confidence=ConfidenceScore.from_score(0.95),
    )

    extracted_alias_email = Entity(
        entity_type=EntityType.PERSON,
        name="Charlie",
        email="cbrown@secondary.org",
        confidence=ConfidenceScore.from_score(0.90),
    )

    res = resolver.resolve_entity(extracted_alias_email, [existing_user])

    assert res.matched_entity is not None
    assert res.matched_entity.id == existing_user.id
    assert not res.requires_review


def test_organization_domains_matching() -> None:
    """Organization resolution matches on domain field or domain name."""
    resolver = EntityResolver()

    org_kuzu = Entity(
        id="org_kuzu_1",
        entity_type=EntityType.ORGANIZATION,
        name="Kuzu Inc",
        domain="kuzudb.com",
        confidence=ConfidenceScore.from_score(0.95),
    )

    extracted_kuzu = Entity(
        entity_type=EntityType.ORGANIZATION,
        name="kuzudb.com",
        confidence=ConfidenceScore.from_score(0.90),
    )

    res = resolver.resolve_entity(extracted_kuzu, [org_kuzu])

    assert res.matched_entity is not None
    assert res.matched_entity.id == org_kuzu.id
    assert not res.requires_review


def test_ambiguous_case_conflicting_email_signals() -> None:
    """Same name but conflicting email addresses marks ambiguous for review."""
    resolver = EntityResolver()

    existing_dave = Entity(
        id="ent_dave_1",
        entity_type=EntityType.PERSON,
        name="Dave Miller",
        email="dave@company-a.com",
        confidence=ConfidenceScore.from_score(0.90),
    )

    extracted_dave_diff_email = Entity(
        entity_type=EntityType.PERSON,
        name="Dave Miller",
        email="dave@company-b.com",
        confidence=ConfidenceScore.from_score(0.90),
    )

    res = resolver.resolve_entity(extracted_dave_diff_email, [existing_dave])

    assert res.matched_entity is None
    assert res.requires_review is True
    assert len(res.candidate_entities) == 1
    assert "conflicting emails" in res.match_reason


def test_thread_participant_continuity_matching() -> None:
    """Thread participant continuity matches entity appearing in thread context."""
    resolver = EntityResolver()

    existing_frank = Entity(
        id="ent_frank_1",
        entity_type=EntityType.PERSON,
        name="Frank Wright",
        email="frank@acme.com",
        confidence=ConfidenceScore.from_score(0.90),
    )

    extracted_frank = Entity(
        entity_type=EntityType.PERSON,
        name="Frank",
        confidence=ConfidenceScore.from_score(0.80),
    )

    res = resolver.resolve_entity(
        extracted_frank,
        [existing_frank],
        thread_participants=["frank@acme.com", "user@acme.com"],
    )

    assert res.matched_entity is not None
    assert res.matched_entity.id == existing_frank.id
    assert not res.requires_review
    assert "Thread participant continuity" in res.match_reason
