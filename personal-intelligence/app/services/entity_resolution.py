"""Entity Resolution Service using deterministic matching rules.

Evaluates:
1. Exact normalized email address match
2. Exact canonical organization domain match
3. Exact canonical name match
4. Alias match
5. Thread participant continuity

Does NOT use GPT-4.1 for final resolution.
Does NOT merge entities automatically when confidence is ambiguous.
Marks ambiguous cases with requires_review=True and matched_entity=None.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config.logging import get_logger
from app.domain.entity_resolution import EntityResolutionResult
from app.domain.enums import EntityType
from app.domain.values import ConfidenceScore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.domain.entities import Entity

logger = get_logger(__name__)


def _normalize_str(s: str | None) -> str:
    """Return lowercase, whitespace-stripped string for canonical comparison."""
    if not s:
        return ""
    return " ".join(s.lower().strip().split())


class EntityResolver:
    """Deterministic entity resolution engine for Personal World Model."""

    def resolve_entity(
        self,
        extracted_entity: Entity,
        existing_entities: Sequence[Entity],
        thread_participants: Sequence[str] | None = None,
    ) -> EntityResolutionResult:
        """Resolve an extracted entity against a set of existing entities.

        Args:
            extracted_entity: Entity extracted from an observation.
            existing_entities: Existing entities in the world model.
            thread_participants: Optional list of email addresses/names participating in the email thread.

        Returns:
            EntityResolutionResult with matched_entity, candidate_entities, match_reason, confidence, requires_review.
        """
        if not existing_entities:
            logger.info("entity_resolution.no_existing_entities", name=extracted_entity.name)
            return EntityResolutionResult(
                matched_entity=None,
                candidate_entities=[],
                match_reason="No existing entities in world model to match against.",
                confidence=ConfidenceScore.from_score(1.0),
                requires_review=False,
            )

        extracted_name_norm = _normalize_str(extracted_entity.name)
        extracted_email_norm = _normalize_str(extracted_entity.email)
        extracted_domain_norm = _normalize_str(extracted_entity.domain)

        # Helper: check if string looks like an email address
        if (
            not extracted_email_norm
            and "@" in extracted_name_norm
            and " " not in extracted_name_norm
        ):
            extracted_email_norm = extracted_name_norm

        # Filter candidates of compatible entity type
        type_compatible = [
            e for e in existing_entities if e.entity_type == extracted_entity.entity_type
        ]

        # -------------------------------------------------------------------
        # Rule 1: Exact normalized email address match
        # -------------------------------------------------------------------
        if extracted_email_norm:
            email_matches: list[Entity] = []
            for candidate in existing_entities:
                cand_email = _normalize_str(candidate.email)
                cand_aliases = [_normalize_str(a) for a in candidate.aliases]
                if cand_email == extracted_email_norm or extracted_email_norm in cand_aliases:
                    email_matches.append(candidate)

            if len(email_matches) == 1:
                match = email_matches[0]
                logger.info(
                    "entity_resolution.matched_email",
                    matched_id=match.id,
                    email=extracted_email_norm,
                )
                return EntityResolutionResult(
                    matched_entity=match,
                    candidate_entities=email_matches,
                    match_reason=f"Exact normalized email match: '{extracted_email_norm}'",
                    confidence=ConfidenceScore.from_score(0.98),
                    requires_review=False,
                )
            elif len(email_matches) > 1:
                logger.warning(
                    "entity_resolution.ambiguous_email", matches_count=len(email_matches)
                )
                return EntityResolutionResult(
                    matched_entity=None,
                    candidate_entities=email_matches,
                    match_reason=f"Ambiguous email match: {len(email_matches)} entities share email '{extracted_email_norm}'",
                    confidence=ConfidenceScore.from_score(0.40),
                    requires_review=True,
                )

        # -------------------------------------------------------------------
        # Rule 2: Exact canonical organization domain match
        # -------------------------------------------------------------------
        if extracted_entity.entity_type == EntityType.ORGANIZATION or extracted_domain_norm:
            domain_matches: list[Entity] = []
            target_domain = extracted_domain_norm or extracted_name_norm
            if "." in target_domain:  # looks like a domain name e.g. acme.com
                for candidate in existing_entities:
                    if candidate.entity_type == EntityType.ORGANIZATION:
                        cand_domain = _normalize_str(candidate.domain) or _normalize_str(
                            candidate.name
                        )
                        cand_aliases = [_normalize_str(a) for a in candidate.aliases]
                        if cand_domain == target_domain or target_domain in cand_aliases:
                            domain_matches.append(candidate)

                if len(domain_matches) == 1:
                    match = domain_matches[0]
                    logger.info(
                        "entity_resolution.matched_domain",
                        matched_id=match.id,
                        domain=target_domain,
                    )
                    return EntityResolutionResult(
                        matched_entity=match,
                        candidate_entities=domain_matches,
                        match_reason=f"Exact canonical organization domain match: '{target_domain}'",
                        confidence=ConfidenceScore.from_score(0.95),
                        requires_review=False,
                    )
                elif len(domain_matches) > 1:
                    logger.warning(
                        "entity_resolution.ambiguous_domain", matches_count=len(domain_matches)
                    )
                    return EntityResolutionResult(
                        matched_entity=None,
                        candidate_entities=domain_matches,
                        match_reason=f"Ambiguous domain match: {len(domain_matches)} organizations match domain '{target_domain}'",
                        confidence=ConfidenceScore.from_score(0.40),
                        requires_review=True,
                    )

        # -------------------------------------------------------------------
        # Rule 3: Exact canonical name match
        # -------------------------------------------------------------------
        name_matches: list[Entity] = [
            cand for cand in type_compatible if _normalize_str(cand.name) == extracted_name_norm
        ]

        if len(name_matches) == 1:
            match = name_matches[0]
            # Check if there are contradictory email signals (different email on candidate vs extracted)
            if (
                extracted_email_norm
                and match.email
                and _normalize_str(match.email) != extracted_email_norm
            ):
                logger.warning(
                    "entity_resolution.name_match_email_conflict",
                    name=extracted_entity.name,
                    ext_email=extracted_email_norm,
                    cand_email=match.email,
                )
                return EntityResolutionResult(
                    matched_entity=None,
                    candidate_entities=[match],
                    match_reason=f"Ambiguous match: Same name '{extracted_entity.name}' but conflicting emails ({extracted_email_norm} vs {match.email})",
                    confidence=ConfidenceScore.from_score(0.35),
                    requires_review=True,
                )

            logger.info(
                "entity_resolution.matched_canonical_name",
                matched_id=match.id,
                name=extracted_entity.name,
            )
            return EntityResolutionResult(
                matched_entity=match,
                candidate_entities=name_matches,
                match_reason=f"Exact canonical name match: '{extracted_entity.name}'",
                confidence=ConfidenceScore.from_score(0.90),
                requires_review=False,
            )
        elif len(name_matches) > 1:
            logger.warning("entity_resolution.ambiguous_name", matches_count=len(name_matches))
            return EntityResolutionResult(
                matched_entity=None,
                candidate_entities=name_matches,
                match_reason=f"Ambiguous name match: {len(name_matches)} different entities share name '{extracted_entity.name}'",
                confidence=ConfidenceScore.from_score(0.35),
                requires_review=True,
            )

        # -------------------------------------------------------------------
        # Rule 4: Alias match
        # -------------------------------------------------------------------
        alias_matches: list[Entity] = []
        for candidate in type_compatible:
            cand_aliases = [_normalize_str(a) for a in candidate.aliases]
            if extracted_name_norm in cand_aliases or (
                extracted_email_norm and extracted_email_norm in cand_aliases
            ):
                alias_matches.append(candidate)

        if len(alias_matches) == 1:
            match = alias_matches[0]
            logger.info(
                "entity_resolution.matched_alias", matched_id=match.id, alias=extracted_entity.name
            )
            return EntityResolutionResult(
                matched_entity=match,
                candidate_entities=alias_matches,
                match_reason=f"Alias match: '{extracted_entity.name}' matched alias of '{match.name}'",
                confidence=ConfidenceScore.from_score(0.88),
                requires_review=False,
            )
        elif len(alias_matches) > 1:
            return EntityResolutionResult(
                matched_entity=None,
                candidate_entities=alias_matches,
                match_reason=f"Ambiguous alias match: {len(alias_matches)} entities match alias '{extracted_entity.name}'",
                confidence=ConfidenceScore.from_score(0.35),
                requires_review=True,
            )

        # -------------------------------------------------------------------
        # Rule 5: Thread participant continuity
        # -------------------------------------------------------------------
        if thread_participants:
            norm_participants = [_normalize_str(p) for p in thread_participants]
            tp_matches: list[Entity] = []

            for candidate in type_compatible:
                cand_email = _normalize_str(candidate.email)
                cand_name = _normalize_str(candidate.name)
                cand_aliases = [_normalize_str(a) for a in candidate.aliases]

                if (
                    cand_email in norm_participants
                    or cand_name in norm_participants
                    or any(a in norm_participants for a in cand_aliases)
                ) and candidate not in tp_matches:
                    tp_matches.append(candidate)

            if len(tp_matches) == 1:
                match = tp_matches[0]
                logger.info("entity_resolution.matched_thread_continuity", matched_id=match.id)
                return EntityResolutionResult(
                    matched_entity=match,
                    candidate_entities=tp_matches,
                    match_reason=f"Thread participant continuity match with '{match.name}'",
                    confidence=ConfidenceScore.from_score(0.85),
                    requires_review=False,
                )
            elif len(tp_matches) > 1:
                return EntityResolutionResult(
                    matched_entity=None,
                    candidate_entities=tp_matches,
                    match_reason=f"Ambiguous thread participant continuity match: {len(tp_matches)} participants match thread context",
                    confidence=ConfidenceScore.from_score(0.40),
                    requires_review=True,
                )

        # -------------------------------------------------------------------
        # No match found -> New entity candidate
        # -------------------------------------------------------------------
        logger.info("entity_resolution.no_match_new_entity", name=extracted_entity.name)
        return EntityResolutionResult(
            matched_entity=None,
            candidate_entities=[],
            match_reason=f"No matching entity found for '{extracted_entity.name}'. Candidate for new entity.",
            confidence=ConfidenceScore.from_score(0.50),
            requires_review=False,
        )
