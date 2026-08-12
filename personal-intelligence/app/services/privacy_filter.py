"""Policy-Driven Privacy Filter / Context Firewall.

Enforces configurable privacy policies and sanitizes ContextPackage objects
before they are exposed to external AI services (e.g. GPT-4.1) or API clients.

Capabilities:
1. PII Redaction: Automatic detection & redaction of Emails, Phone Numbers, Secrets/API Keys,
   SSNs, Credit Cards, Financial Account Numbers, and Compensation Figures.
2. Property Key Filtering: Strips sensitive property keys (e.g. 'ssn', 'password', 'api_key').
3. Entity & Relationship Boundaries: Filters out nameless entities, low-confidence edges, and blocked types.
4. Evidence Scrubbing & Masking: Sanitizes or masks evidence text snippets and raw observation excerpts.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.config.logging import get_logger
from app.domain.context import ContextPackage

logger = get_logger(__name__)


class PrivacyPolicy(BaseModel):
    """Configuration settings for Privacy Firewall policy enforcement."""

    min_confidence_threshold: float = Field(
        default=0.40, description="Minimum confidence score required for relationships and claims."
    )
    redact_pii: bool = Field(
        default=True, description="Enable automatic PII pattern redaction across all text fields."
    )
    mask_evidence_snippets: bool = Field(
        default=False, description="Replace evidence text snippets with an anonymized mask placeholder."
    )
    blocked_entity_types: set[str] = Field(
        default_factory=set, description="Entity types forbidden from passing through the firewall."
    )
    blocked_property_keys: set[str] = Field(
        default_factory=lambda: {
            "password",
            "ssn",
            "secret",
            "api_key",
            "auth_token",
            "credit_card",
            "bank_account",
            "pin",
            "private_key",
        },
        description="Attribute keys that must be stripped from entity/relationship property dicts.",
    )


# Standard PII & Secret Regex Patterns
PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # API Keys & Secret Tokens
    (
        re.compile(
            r"(?i)(?:bearer\s+[a-z0-9\-._~+/]+=*|sk-[a-zA-Z0-9]{20,}|api[_-]?key\s*[:=]\s*[a-zA-Z0-9_\-]+)",
            re.IGNORECASE,
        ),
        "[SECRET_REDACTED]",
    ),
    # Email Addresses
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "[EMAIL_REDACTED]",
    ),
    # US Social Security Numbers
    (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[SSN_REDACTED]",
    ),
    # Credit Card Numbers
    (
        re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
        "[CREDIT_CARD_REDACTED]",
    ),
    # Phone Numbers (International & US)
    (
        re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "[PHONE_REDACTED]",
    ),
    # Compensation Figures (e.g. salary: $180,000)
    (
        re.compile(r"(?i)(?:salary|compensation|annual\s+pay)\s*[:=]?\s*\$?\d+[\d,]*"),
        "[COMPENSATION_REDACTED]",
    ),
]


def scrub_pii_text(text: str | None, policy: PrivacyPolicy) -> str:
    """Scrub PII patterns from text using configured PrivacyPolicy."""
    if not text or not policy.redact_pii:
        return text or ""

    scrubbed = text
    for pattern, replacement in PII_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)

    return scrubbed


def sanitize_dict(d: dict[str, Any] | None, policy: PrivacyPolicy) -> dict[str, Any]:
    """Sanitize a dictionary by stripping blocked keys and scrubbing text values."""
    if not d:
        return {}

    sanitized: dict[str, Any] = {}
    for key, val in d.items():
        if key.lower() in policy.blocked_property_keys:
            continue

        if isinstance(val, str):
            sanitized[key] = scrub_pii_text(val, policy)
        elif isinstance(val, dict):
            sanitized[key] = sanitize_dict(val, policy)
        elif isinstance(val, list):
            sanitized[key] = [
                scrub_pii_text(v, policy) if isinstance(v, str) else v for v in val
            ]
        else:
            sanitized[key] = val

    return sanitized


class PrivacyFilter:
    """Policy-driven firewall enforcing privacy boundaries on ContextPackage objects."""

    def __init__(self, policy: PrivacyPolicy | None = None) -> None:
        self._policy = policy or PrivacyPolicy()

    @property
    def policy(self) -> PrivacyPolicy:
        """Return the active policy configuration."""
        return self._policy

    def filter_package(self, package: ContextPackage) -> ContextPackage:
        """Sanitize and enforce privacy policy boundaries on a ContextPackage.

        Args:
            package: Raw ContextPackage assembled by ContextEngine.

        Returns:
            Sanitized ContextPackage safe for external LLM reasoning.
        """
        logger.info("privacy_filter.start", package_id=package.id, request_id=package.request_id)
        policy = self._policy
        filtered_count = 0

        # -------------------------------------------------------------------
        # 1. Sanitize Entities
        # -------------------------------------------------------------------
        sanitized_entities: list[Any] = []
        for ent in package.entities:
            name = getattr(ent, "name", "").strip()
            ent_type = str(getattr(ent, "entity_type", "")).lower()

            if not name or ent_type in policy.blocked_entity_types:
                filtered_count += 1
                continue

            ent_copy = ent.model_copy(deep=True)
            ent_copy.name = scrub_pii_text(ent_copy.name, policy)
            if hasattr(ent_copy, "description") and getattr(ent_copy, "description", None):
                ent_copy.description = scrub_pii_text(ent_copy.description, policy)
            if hasattr(ent_copy, "email") and getattr(ent_copy, "email", None):
                ent_copy.email = scrub_pii_text(ent_copy.email, policy)
            if hasattr(ent_copy, "aliases") and getattr(ent_copy, "aliases", None):
                ent_copy.aliases = [scrub_pii_text(a, policy) for a in ent_copy.aliases if a]

            sanitized_entities.append(ent_copy)

        # -------------------------------------------------------------------
        # 2. Sanitize Relationships
        # -------------------------------------------------------------------
        sanitized_relationships: list[Any] = []
        for rel in package.relationships:
            if rel.confidence.score < policy.min_confidence_threshold:
                filtered_count += 1
                continue

            rel_copy = rel.model_copy(deep=True)
            if hasattr(rel_copy, "properties") and rel_copy.properties:
                rel_copy.properties = sanitize_dict(rel_copy.properties, policy)

            if rel_copy.evidence_span:
                if policy.mask_evidence_snippets:
                    rel_copy.evidence_span.text_snippet = "[EVIDENCE_SNIPPET_MASKED]"
                else:
                    rel_copy.evidence_span.text_snippet = scrub_pii_text(
                        rel_copy.evidence_span.text_snippet, policy
                    )

            sanitized_relationships.append(rel_copy)

        # -------------------------------------------------------------------
        # 3. Sanitize Claims
        # -------------------------------------------------------------------
        sanitized_claims: list[Any] = []
        for cl in package.claims:
            if hasattr(cl, "confidence") and cl.confidence.score < policy.min_confidence_threshold:
                filtered_count += 1
                continue

            cl_copy = cl.model_copy(deep=True)
            cl_copy.subject = scrub_pii_text(cl_copy.subject, policy)
            cl_copy.predicate = scrub_pii_text(cl_copy.predicate, policy)
            cl_copy.value = scrub_pii_text(cl_copy.value, policy)

            if hasattr(cl_copy, "evidence_spans") and cl_copy.evidence_spans:
                for span in cl_copy.evidence_spans:
                    if policy.mask_evidence_snippets:
                        span.text_snippet = "[EVIDENCE_SNIPPET_MASKED]"
                    else:
                        span.text_snippet = scrub_pii_text(span.text_snippet, policy)

            sanitized_claims.append(cl_copy)

        # -------------------------------------------------------------------
        # 4. Sanitize Decisions, Commitments, Events
        # -------------------------------------------------------------------
        sanitized_decisions: list[Any] = []
        for d in package.decisions:
            d_copy = d.model_copy(deep=True)
            d_copy.name = scrub_pii_text(d_copy.name, policy)
            if hasattr(d_copy, "properties") and d_copy.properties:
                d_copy.properties = sanitize_dict(d_copy.properties, policy)
            sanitized_decisions.append(d_copy)

        sanitized_commitments: list[Any] = []
        for c in package.commitments:
            c_copy = c.model_copy(deep=True)
            c_copy.name = scrub_pii_text(c_copy.name, policy)
            if hasattr(c_copy, "properties") and c_copy.properties:
                c_copy.properties = sanitize_dict(c_copy.properties, policy)
            sanitized_commitments.append(c_copy)

        sanitized_events: list[Any] = []
        for ev in package.events:
            ev_copy = ev.model_copy(deep=True)
            ev_copy.name = scrub_pii_text(ev_copy.name, policy)
            if hasattr(ev_copy, "properties") and ev_copy.properties:
                ev_copy.properties = sanitize_dict(ev_copy.properties, policy)
            sanitized_events.append(ev_copy)

        # -------------------------------------------------------------------
        # 5. Sanitize Evidence Records
        # -------------------------------------------------------------------
        sanitized_evidence: list[Any] = []
        for ev_rec in package.evidence:
            ev_copy = ev_rec.model_copy(deep=True) if hasattr(ev_rec, "model_copy") else ev_rec
            if hasattr(ev_copy, "evidence_span") and ev_copy.evidence_span:
                if policy.mask_evidence_snippets:
                    ev_copy.evidence_span.text_snippet = "[EVIDENCE_SNIPPET_MASKED]"
                else:
                    ev_copy.evidence_span.text_snippet = scrub_pii_text(
                        ev_copy.evidence_span.text_snippet, policy
                    )

            sanitized_evidence.append(ev_copy)

        # -------------------------------------------------------------------
        # 6. Sanitize State Changes & Summary
        # -------------------------------------------------------------------
        sanitized_changes: list[Any] = []
        for sc in package.state_changes:
            sc_copy = sc.model_copy(deep=True) if hasattr(sc, "model_copy") else sc
            if hasattr(sc_copy, "description") and sc_copy.description:
                sc_copy.description = scrub_pii_text(sc_copy.description, policy)
            sanitized_changes.append(sc_copy)

        sanitized_summary = scrub_pii_text(package.summary, policy)

        sanitized_package = ContextPackage(
            id=package.id,
            request_id=package.request_id,
            purpose=package.purpose,
            entities=sanitized_entities,
            relationships=sanitized_relationships,
            claims=sanitized_claims,
            decisions=sanitized_decisions,
            events=sanitized_events,
            commitments=sanitized_commitments,
            evidence=sanitized_evidence,
            state_changes=sanitized_changes,
            summary=sanitized_summary,
            assembled_at=package.assembled_at,
            filtered_count=package.filtered_count + filtered_count,
        )

        logger.info(
            "privacy_filter.complete",
            package_id=sanitized_package.id,
            filtered_items=filtered_count,
        )
        return sanitized_package
