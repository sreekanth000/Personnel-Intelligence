"""Unit tests for production system prompt rules and 20 extraction examples.

Verifies:
- All 15 mandatory extraction rules are present in PRODUCTION_EXTRACTION_SYSTEM_PROMPT.
- All 20 requested extraction categories are covered by distinct examples.
- Every expected extraction payload validates cleanly against the StructuredExtraction Pydantic model.
"""

from __future__ import annotations

import pytest

from app.services.extraction import StructuredExtraction
from app.services.prompts import EXTRACTION_EXAMPLES, PRODUCTION_EXTRACTION_SYSTEM_PROMPT


def test_production_system_prompt_all_15_rules() -> None:
    """Production system prompt must contain all 15 explicit extraction rules."""
    prompt = PRODUCTION_EXTRACTION_SYSTEM_PROMPT

    required_rules = [
        "1. Extract only evidence-supported information",
        "2. Every extracted item must have an evidence_span",
        "3. Never infer sensitive personal attributes",
        "4. Never infer relationships from email addresses alone",
        "5. Treat quoted email text as historical context",
        "6. Distinguish sender statements",
        "7. Preserve temporal expressions",
        "8. Preserve uncertainty",
        "9. Do not convert requests",
        "10. Do not convert intentions",
        "11. Do not convert discussion",
        "12. Do not treat email signatures",
        "13. Do not infer that the recipient/user agrees",
        "14. Do not infer that a project is active",
        "15. Do not create a relationship when textual evidence is insufficient",
    ]

    for rule in required_rules:
        assert rule in prompt, f"Missing prompt rule: {rule}"


def test_20_extraction_examples_count_and_categories() -> None:
    """Must provide at least 20 extraction examples covering all specified categories."""
    assert len(EXTRACTION_EXAMPLES) >= 20

    expected_categories = {
        "work_email",
        "meeting_request",
        "project_discussion",
        "job_opportunity",
        "customer_communication",
        "personal_email",
        "newsletter",
        "automated_notification",
        "reply_chain",
        "contradictory_statements",
        "future_plan",
        "completed_action",
        "request",
        "assignment",
        "uncertain_statement",
        "third_party_statement",
        "forwarded_email",
        "signature",
        "irrelevant_email",
        "email_with_multiple_entities",
    }

    found_categories = {ex["category"] for ex in EXTRACTION_EXAMPLES}
    missing = expected_categories - found_categories
    assert not missing, f"Missing required extraction example categories: {missing}"


@pytest.mark.parametrize("example", EXTRACTION_EXAMPLES)
def test_extraction_example_schema_validity(example: dict) -> None:
    """Every example's expected extraction structure must be valid for StructuredExtraction."""
    expected_data = example["expected_extraction"]
    assert "source_observation_id" in expected_data

    # Validate that expected_extraction passes Pydantic schema validation
    validated = StructuredExtraction.model_validate(expected_data)
    assert validated.source_observation_id == expected_data["source_observation_id"]
