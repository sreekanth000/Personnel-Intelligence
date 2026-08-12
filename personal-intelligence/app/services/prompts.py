"""Production System Prompt and Extraction Examples for GPT-4.1 Gmail Extraction.

Provides the production system prompt incorporating all 15 core extraction rules,
along with 20 comprehensive extraction examples covering distinct email patterns.
"""

from __future__ import annotations

from typing import Any

PRODUCTION_EXTRACTION_SYSTEM_PROMPT = """You are a precise, evidence-grounded information extraction system for Personal Intelligence.

YOUR JOB:
Given one normalized email observation (metadata, clean body text, separated quoted text, signature, and attachments metadata), identify explicit entities, relationships, events, claims, goals, projects, decisions, constraints, preferences, and temporal references.

MANDATORY EXTRACTION RULES:
1. Extract only evidence-supported information directly stated in the text.
2. Every extracted item must have an evidence_span containing the exact text snippet grounding the item.
3. Never infer sensitive personal attributes (political views, medical conditions, religious beliefs, sexual orientation, etc.).
4. Never infer relationships from email addresses alone (e.g. do not assume employment or management solely because of an @domain email).
5. Treat quoted email text as historical context; do not extract quoted text as current observations.
6. Distinguish sender statements ("I completed the task") from statements about third parties ("Bob said Alice completed the task").
7. Preserve temporal expressions (e.g. "by next Friday", "since 2023") accurately in temporal_references.
8. Preserve uncertainty explicitly (assign lower confidence scores to tentative assertions like "might", "possibly", "considering").
9. Do not convert requests ("Can you review this?") into completed actions.
10. Do not convert intentions ("We plan to launch next month") into completed goals.
11. Do not convert discussion or proposal of options into finalized decisions.
12. Do not treat email signatures (disclaimers, titles, phone numbers) as facts unless directly relevant to an explicit statement.
13. Do not infer that the recipient/user agrees with or accepts a statement merely because they received the email.
14. Do not infer that a project is active merely because it is mentioned in passing.
15. Do not create a relationship when textual evidence is insufficient.

OUTPUT FORMAT:
Return strictly structured JSON adhering to the Pydantic schema with keys:
- entities: list of Entity objects (PERSON, ORGANIZATION, PROJECT, PRODUCT, ROLE, LOCATION, EVENT, DOCUMENT, CONCEPT)
- relationships: list of Relationship objects (WORKS_FOR, WORKS_WITH, MANAGES, REPORTS_TO, OWNS, CREATED, INVOLVED_IN, RELATED_TO, DEPENDS_ON, PART_OF, MENTIONS, REQUESTS, ASSIGNS, COMMUNICATES_WITH, INTERESTED_IN, RESPONSIBLE_FOR)
- events: list of Event objects (starts_at, ends_at, location, attendees)
- claims: list of Claim objects (subject, predicate, value, status, confidence, evidence_spans)
- goals: list of Goal objects (name, target_date, status)
- projects: list of Project objects (name, status, goal_ids)
- decisions: list of Decision objects (question, alternatives, context, constraints, reasoning, decision, status)
- constraints: list of Constraint objects (constraint_type, severity)
- preferences: list of Preference objects (domain, value)
- temporal_references: list of TemporalReference objects (aspect, point_in_time, relative_text, range)

If information for any category is absent in the email, return an empty array [] for that key.
"""

CONF_HIGH = {"score": 0.9, "category": "very_high"}
CONF_MED = {"score": 0.6, "category": "high"}
CONF_LOW = {"score": 0.35, "category": "low"}


# ---------------------------------------------------------------------------
# 20 Production Extraction Examples
# ---------------------------------------------------------------------------

EXTRACTION_EXAMPLES: list[dict[str, Any]] = [
    # 1. Work email
    {
        "category": "work_email",
        "description": "Standard work email stating team assignment",
        "email": {
            "raw_observation_id": "obs_ex_1",
            "sender": "sarah@acme.com",
            "recipients": ["user@acme.com"],
            "subject": "Q3 Engineering Focus",
            "body": "Sarah leads the Infrastructure team at Acme Corp. We are starting work on Q3 scaling.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_1",
            "entities": [
                {"name": "Sarah", "entity_type": "person", "confidence": CONF_HIGH},
                {"name": "Infrastructure team", "entity_type": "role", "confidence": CONF_HIGH},
                {"name": "Acme Corp", "entity_type": "organization", "confidence": CONF_HIGH},
            ],
            "relationships": [
                {
                    "subject": "Sarah",
                    "predicate": "manages",
                    "object": "Infrastructure team",
                    "confidence": CONF_HIGH,
                    "evidence_span": {
                        "text_snippet": "Sarah leads the Infrastructure team",
                        "confidence": CONF_HIGH,
                    },
                },
                {
                    "subject": "Infrastructure team",
                    "predicate": "part_of",
                    "object": "Acme Corp",
                    "confidence": CONF_HIGH,
                    "evidence_span": {
                        "text_snippet": "Infrastructure team at Acme Corp",
                        "confidence": CONF_HIGH,
                    },
                },
            ],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 2. Meeting request
    {
        "category": "meeting_request",
        "description": "Calendar invite request, not yet confirmed",
        "email": {
            "raw_observation_id": "obs_ex_2",
            "sender": "alex@partner.com",
            "recipients": ["user@acme.com"],
            "subject": "Sync meeting",
            "body": "Can we meet tomorrow at 10am on Zoom to discuss partnership options?",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_2",
            "entities": [
                {"name": "Alex", "entity_type": "person", "confidence": CONF_HIGH},
            ],
            "relationships": [
                {
                    "subject": "Alex",
                    "predicate": "requests",
                    "object": "Sync meeting",
                    "confidence": CONF_HIGH,
                    "evidence_span": {
                        "text_snippet": "Can we meet tomorrow at 10am on Zoom",
                        "confidence": CONF_HIGH,
                    },
                }
            ],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [{"aspect": "after", "relative_text": "tomorrow at 10am"}],
        },
    },
    # 3. Project discussion
    {
        "category": "project_discussion",
        "description": "Discussion of project dependencies without decision",
        "email": {
            "raw_observation_id": "obs_ex_3",
            "sender": "bob@acme.com",
            "recipients": ["user@acme.com"],
            "subject": "Project Titan dependencies",
            "body": "Project Titan depends on the API Gateway migration. We are evaluating Redis vs Memcached.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_3",
            "entities": [
                {"name": "Project Titan", "entity_type": "project", "confidence": CONF_HIGH},
                {
                    "name": "API Gateway migration",
                    "entity_type": "project",
                    "confidence": CONF_HIGH,
                },
            ],
            "relationships": [
                {
                    "subject": "Project Titan",
                    "predicate": "depends_on",
                    "object": "API Gateway migration",
                    "confidence": CONF_HIGH,
                    "evidence_span": {
                        "text_snippet": "Project Titan depends on the API Gateway migration",
                        "confidence": CONF_HIGH,
                    },
                }
            ],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [{"name": "Project Titan", "status": "active", "confidence": CONF_HIGH}],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 4. Job opportunity
    {
        "category": "job_opportunity",
        "description": "Recruiter outreach presenting a role",
        "email": {
            "raw_observation_id": "obs_ex_4",
            "sender": "recruiter@techhead.com",
            "recipients": ["user@acme.com"],
            "subject": "Staff Engineer Role at CloudScale",
            "body": "CloudScale is hiring a Staff Engineer in San Francisco. Are you interested in learning more?",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_4",
            "entities": [
                {"name": "CloudScale", "entity_type": "organization", "confidence": CONF_HIGH},
                {"name": "Staff Engineer", "entity_type": "role", "confidence": CONF_HIGH},
                {"name": "San Francisco", "entity_type": "location", "confidence": CONF_HIGH},
            ],
            "relationships": [],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 5. Customer communication
    {
        "category": "customer_communication",
        "description": "Customer bug report",
        "email": {
            "raw_observation_id": "obs_ex_5",
            "sender": "client@enterprise.com",
            "recipients": ["support@acme.com"],
            "subject": "Billing issue ticket #4021",
            "body": "Enterprise Corp reported that invoice export fails for PDF format since Monday.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_5",
            "entities": [
                {"name": "Enterprise Corp", "entity_type": "organization", "confidence": CONF_HIGH},
            ],
            "relationships": [],
            "events": [],
            "claims": [
                {
                    "subject": "invoice export",
                    "predicate": "status",
                    "value": "fails for PDF format",
                    "status": "proposed",
                    "confidence": CONF_HIGH,
                    "evidence_spans": [
                        {
                            "text_snippet": "invoice export fails for PDF format",
                            "confidence": CONF_HIGH,
                        }
                    ],
                }
            ],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [{"aspect": "since", "relative_text": "since Monday"}],
        },
    },
    # 6. Personal email
    {
        "category": "personal_email",
        "description": "Family member trip update",
        "email": {
            "raw_observation_id": "obs_ex_6",
            "sender": "mom@family.org",
            "recipients": ["user@acme.com"],
            "subject": "Vacation in Italy",
            "body": "Dad and I are visiting Rome next month. We booked our flights.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_6",
            "entities": [
                {"name": "Rome", "entity_type": "location", "confidence": CONF_HIGH},
                {"name": "Italy", "entity_type": "location", "confidence": CONF_HIGH},
            ],
            "relationships": [],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [{"aspect": "after", "relative_text": "next month"}],
        },
    },
    # 7. Newsletter
    {
        "category": "newsletter",
        "description": "Industry news digest with external facts",
        "email": {
            "raw_observation_id": "obs_ex_7",
            "sender": "news@techdigest.io",
            "recipients": ["user@acme.com"],
            "subject": "AI Weekly #104",
            "body": "Python 3.12 was released with improved performance. Vector databases continue to grow.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_7",
            "entities": [
                {"name": "Python 3.12", "entity_type": "product", "confidence": CONF_HIGH},
            ],
            "relationships": [],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 8. Automated notification
    {
        "category": "automated_notification",
        "description": "GitHub automated PR alert",
        "email": {
            "raw_observation_id": "obs_ex_8",
            "sender": "notifications@github.com",
            "recipients": ["user@acme.com"],
            "subject": "[GitHub] PR #42 merged into main",
            "body": "Dave merged PR #42 'Fix authentication crash' into repository backend-core.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_8",
            "entities": [
                {"name": "Dave", "entity_type": "person", "confidence": CONF_HIGH},
                {"name": "backend-core", "entity_type": "project", "confidence": CONF_HIGH},
            ],
            "relationships": [
                {
                    "subject": "Dave",
                    "predicate": "created",
                    "object": "PR #42",
                    "confidence": CONF_HIGH,
                    "evidence_span": {
                        "text_snippet": "Dave merged PR #42",
                        "confidence": CONF_HIGH,
                    },
                }
            ],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 9. Reply chain
    {
        "category": "reply_chain",
        "description": "Clean email body response without treating quoted text as current",
        "email": {
            "raw_observation_id": "obs_ex_9",
            "sender": "charlie@acme.com",
            "recipients": ["user@acme.com"],
            "subject": "Re: Deployment schedule",
            "body": "I approved the staging release.",
            "quoted_reply": "On Tue, Dave wrote: Should we deploy to staging?",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_9",
            "entities": [
                {"name": "Charlie", "entity_type": "person", "confidence": CONF_HIGH},
            ],
            "relationships": [],
            "events": [],
            "claims": [
                {
                    "subject": "staging release",
                    "predicate": "approval",
                    "value": "approved by Charlie",
                    "status": "proposed",
                    "confidence": CONF_HIGH,
                    "evidence_spans": [
                        {"text_snippet": "I approved the staging release", "confidence": CONF_HIGH}
                    ],
                }
            ],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 10. Contradictory statements
    {
        "category": "contradictory_statements",
        "description": "Conflicting claims in email body preserved with uncertainty",
        "email": {
            "raw_observation_id": "obs_ex_10",
            "sender": "lead@acme.com",
            "recipients": ["user@acme.com"],
            "subject": "Office location status",
            "body": "Some teams report the NYC office is closed, but Facilities says it remains open.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_10",
            "entities": [
                {"name": "NYC office", "entity_type": "location", "confidence": CONF_HIGH},
            ],
            "relationships": [],
            "events": [],
            "claims": [
                {
                    "subject": "NYC office",
                    "predicate": "status",
                    "value": "closed",
                    "status": "contested",
                    "confidence": CONF_MED,
                    "evidence_spans": [
                        {"text_snippet": "NYC office is closed", "confidence": CONF_MED}
                    ],
                },
                {
                    "subject": "NYC office",
                    "predicate": "status",
                    "value": "open",
                    "status": "contested",
                    "confidence": CONF_MED,
                    "evidence_spans": [
                        {"text_snippet": "Facilities says it remains open", "confidence": CONF_MED}
                    ],
                },
            ],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 11. Future plan
    {
        "category": "future_plan",
        "description": "Intended plan not yet completed",
        "email": {
            "raw_observation_id": "obs_ex_11",
            "sender": "planner@acme.com",
            "recipients": ["user@acme.com"],
            "subject": "Q4 Roadmap",
            "body": "We plan to migrate our database to DuckDB by December.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_11",
            "entities": [
                {"name": "DuckDB", "entity_type": "product", "confidence": CONF_HIGH},
            ],
            "relationships": [],
            "events": [],
            "claims": [],
            "goals": [
                {
                    "name": "Migrate database to DuckDB",
                    "status": "active",
                    "confidence": CONF_HIGH,
                }
            ],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [{"aspect": "until", "relative_text": "by December"}],
        },
    },
    # 12. Completed action
    {
        "category": "completed_action",
        "description": "Explicitly confirmed past completed task",
        "email": {
            "raw_observation_id": "obs_ex_12",
            "sender": "dev@acme.com",
            "recipients": ["user@acme.com"],
            "subject": "Task completed",
            "body": "I have completed the OAuth2 token storage implementation.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_12",
            "entities": [
                {"name": "OAuth2 token storage", "entity_type": "concept", "confidence": CONF_HIGH},
            ],
            "relationships": [],
            "events": [],
            "claims": [
                {
                    "subject": "OAuth2 token storage implementation",
                    "predicate": "status",
                    "value": "completed",
                    "status": "proposed",
                    "confidence": CONF_HIGH,
                    "evidence_spans": [
                        {
                            "text_snippet": "completed the OAuth2 token storage implementation",
                            "confidence": CONF_HIGH,
                        }
                    ],
                }
            ],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 13. Request
    {
        "category": "request",
        "description": "Action item request to another person",
        "email": {
            "raw_observation_id": "obs_ex_13",
            "sender": "manager@acme.com",
            "recipients": ["dev@acme.com"],
            "subject": "Code Review Request",
            "body": "Please review pull request #12 by end of day.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_13",
            "entities": [],
            "relationships": [],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [{"aspect": "until", "relative_text": "by end of day"}],
        },
    },
    # 14. Assignment
    {
        "category": "assignment",
        "description": "Explicit task assignment to an owner",
        "email": {
            "raw_observation_id": "obs_ex_14",
            "sender": "pm@acme.com",
            "recipients": ["team@acme.com"],
            "subject": "Sprint Assignments",
            "body": "Frank is assigned to lead the security audit for Q3.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_14",
            "entities": [
                {"name": "Frank", "entity_type": "person", "confidence": CONF_HIGH},
                {"name": "security audit", "entity_type": "project", "confidence": CONF_HIGH},
            ],
            "relationships": [
                {
                    "subject": "Frank",
                    "predicate": "responsible_for",
                    "object": "security audit",
                    "confidence": CONF_HIGH,
                    "evidence_span": {
                        "text_snippet": "Frank is assigned to lead the security audit",
                        "confidence": CONF_HIGH,
                    },
                }
            ],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 15. Uncertain statement
    {
        "category": "uncertain_statement",
        "description": "Speculative or tentative assertion requiring low confidence",
        "email": {
            "raw_observation_id": "obs_ex_15",
            "sender": "analyst@acme.com",
            "recipients": ["user@acme.com"],
            "subject": "Market rumors",
            "body": "Vendor X might be launching a competing product next month, though this is unconfirmed.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_15",
            "entities": [
                {"name": "Vendor X", "entity_type": "organization", "confidence": CONF_HIGH},
            ],
            "relationships": [],
            "events": [],
            "claims": [
                {
                    "subject": "Vendor X",
                    "predicate": "product_launch",
                    "value": "competing product",
                    "status": "proposed",
                    "confidence": CONF_LOW,
                    "evidence_spans": [
                        {
                            "text_snippet": "Vendor X might be launching a competing product",
                            "confidence": CONF_LOW,
                        }
                    ],
                }
            ],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [{"aspect": "after", "relative_text": "next month"}],
        },
    },
    # 16. Third-party statement
    {
        "category": "third_party_statement",
        "description": "Statement reporting what someone else said",
        "email": {
            "raw_observation_id": "obs_ex_16",
            "sender": "grace@acme.com",
            "recipients": ["user@acme.com"],
            "subject": "Client update",
            "body": "Henry mentioned that BigCorp prefers SAML authentication.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_16",
            "entities": [
                {"name": "Henry", "entity_type": "person", "confidence": CONF_HIGH},
                {"name": "BigCorp", "entity_type": "organization", "confidence": CONF_HIGH},
                {"name": "SAML authentication", "entity_type": "concept", "confidence": CONF_HIGH},
            ],
            "relationships": [],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [
                {
                    "name": "SAML authentication preference",
                    "domain": "authentication",
                    "value": "SAML",
                    "confidence": CONF_HIGH,
                }
            ],
            "temporal_references": [],
        },
    },
    # 17. Forwarded email
    {
        "category": "forwarded_email",
        "description": "Forwarded message with inline metadata",
        "email": {
            "raw_observation_id": "obs_ex_17",
            "sender": "colleague@acme.com",
            "recipients": ["user@acme.com"],
            "subject": "Fwd: Vendor Agreement",
            "body": "FYI forwarding this below.",
            "quoted_reply": "---------- Forwarded message ---------\nFrom: legal@vendor.com\nSubject: Signed Agreement\nLegal approved the contract terms.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_17",
            "entities": [],
            "relationships": [],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 18. Signature
    {
        "category": "signature",
        "description": "Email with boilerplate signature contact info",
        "email": {
            "raw_observation_id": "obs_ex_18",
            "sender": "john@partner.com",
            "recipients": ["user@acme.com"],
            "subject": "Quick thanks",
            "body": "Thanks for sending over the report.",
            "signature": "-- \nJohn Doe\nVP of Sales | PartnerCo\nCell: 555-0199",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_18",
            "entities": [],
            "relationships": [],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 19. Irrelevant email
    {
        "category": "irrelevant_email",
        "description": "Promotional email with no personal intelligence value",
        "email": {
            "raw_observation_id": "obs_ex_19",
            "sender": "promo@store.com",
            "recipients": ["user@acme.com"],
            "subject": "50% Off Summer Sale!",
            "body": "Shop our summer collection today and save 50% on all shoes.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_19",
            "entities": [],
            "relationships": [],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
    # 20. Email with multiple entities
    {
        "category": "email_with_multiple_entities",
        "description": "Multi-entity organizational announcement",
        "email": {
            "raw_observation_id": "obs_ex_20",
            "sender": "cto@techcorp.com",
            "recipients": ["all@techcorp.com"],
            "subject": "Org Update: Nexus Project Launch",
            "body": "TechCorp is launching Project Nexus in London. Julia works for TechCorp and will lead the launch event.",
        },
        "expected_extraction": {
            "source_observation_id": "obs_ex_20",
            "entities": [
                {"name": "TechCorp", "entity_type": "organization", "confidence": CONF_HIGH},
                {"name": "Project Nexus", "entity_type": "project", "confidence": CONF_HIGH},
                {"name": "London", "entity_type": "location", "confidence": CONF_HIGH},
                {"name": "Julia", "entity_type": "person", "confidence": CONF_HIGH},
            ],
            "relationships": [
                {
                    "subject": "Julia",
                    "predicate": "works_for",
                    "object": "TechCorp",
                    "confidence": CONF_HIGH,
                    "evidence_span": {
                        "text_snippet": "Julia works for TechCorp",
                        "confidence": CONF_HIGH,
                    },
                },
                {
                    "subject": "Julia",
                    "predicate": "manages",
                    "object": "Project Nexus",
                    "confidence": CONF_HIGH,
                    "evidence_span": {
                        "text_snippet": "Julia will lead the launch event",
                        "confidence": CONF_HIGH,
                    },
                },
            ],
            "events": [],
            "claims": [],
            "goals": [],
            "projects": [{"name": "Project Nexus", "status": "active", "confidence": CONF_HIGH}],
            "decisions": [],
            "constraints": [],
            "preferences": [],
            "temporal_references": [],
        },
    },
]
