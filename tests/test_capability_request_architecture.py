"""
Tests for Personal Intelligence Generic Capability-Request Architecture.

Verifies:
1. No direct source integrations (GmailClient, DriveClient, CalendarClient, MeetClient, GoogleOAuth).
2. Declarative capability requests: PI specifies WHAT INFORMATION IS NEEDED, not HOW TO ACCESS THE SOURCE.
3. InformationGapRequest and InvestigationTask structure (information_gap, preferred_capabilities, max_tool_calls <= 5).
4. Bounded investigation workflow and tool bounding.
5. Hermes host runtime tool delegation and evidence synthesis across Workspace domains.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.situations.models import Situation, SituationPriority
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.hermes_bridge.client import (
    HermesClient,
    HermesInvocationRequest,
    HermesInvocationResponse,
    HermesRuntimeBridge,
    set_active_hermes_context,
)
from personal_intelligence.hermes_bridge.investigation import (
    BoundedInvestigationWorkflow,
    InformationGapRequest,
    InvestigationResult,
    InvestigationTask,
    validate_investigation_result,
)
from personal_intelligence.hermes_bridge.situation_investigation import (
    CrossSourceEvidenceBundle,
    InvestigationPlan,
    SituationInvestigator,
)
from personal_intelligence.storage.db import DatabaseManager


class TestSourceIntegrationAbsence(unittest.TestCase):
    """Verifies that Personal Intelligence does NOT implement custom source clients."""

    def test_no_custom_source_clients_in_modules(self) -> None:
        """Confirms absence of custom Google Workspace or OAuth client classes."""
        import personal_intelligence

        # Check all module attributes
        forbidden_class_names = [
            "GmailClient",
            "DriveClient",
            "CalendarClient",
            "MeetClient",
            "GoogleOAuth",
            "GoogleWorkspaceClient",
            "OAuth2Client",
        ]

        for name in forbidden_class_names:
            self.assertFalse(
                hasattr(personal_intelligence, name),
                f"Personal Intelligence must not define {name}!",
            )


class TestDeclarativeCapabilityRequests(unittest.TestCase):
    """Verifies that Personal Intelligence only specifies WHAT is needed, not HOW."""

    def test_information_gap_request_structure(self) -> None:
        """Verifies InformationGapRequest encapsulates what is needed with bounds."""
        req = InformationGapRequest(
            information_gap="Determine whether the requested architecture document is complete.",
            preferred_capabilities=["drive", "gmail", "meet"],
            max_tool_calls=5,
            known_facts=["Design proposal sent on Aug 18", "Review meeting scheduled for tomorrow"],
            unknowns=["Has the final PDF been uploaded to Google Drive?", "Were approvals sent over Gmail?"],
            required_output={
                "findings": "list of factual findings",
                "source_references": "list of document IDs / URLs",
                "uncertainty": "remaining unknowns",
                "expiration_time": "ISO 8601 UTC timestamp",
            },
        )

        self.assertEqual(req.information_gap, "Determine whether the requested architecture document is complete.")
        self.assertEqual(req.preferred_capabilities, ["drive", "gmail", "meet"])
        self.assertEqual(req.max_tool_calls, 5)
        self.assertEqual(len(req.known_facts), 2)
        self.assertEqual(len(req.unknowns), 2)

        d = req.to_dict()
        self.assertIn("information_gap", d)
        self.assertIn("preferred_capabilities", d)
        self.assertIn("max_tool_calls", d)
        self.assertEqual(d["max_tool_calls"], 5)

    def test_max_tool_calls_validation(self) -> None:
        """Verifies that unbounded or excessive tool calls are prohibited."""
        with self.assertRaises(ValueError):
            InformationGapRequest(
                information_gap="Test gap",
                preferred_capabilities=["drive"],
                max_tool_calls=0,  # Invalid: must be >= 1
            )

        with self.assertRaises(ValueError):
            InformationGapRequest(
                information_gap="Test gap",
                preferred_capabilities=["drive"],
                max_tool_calls=25,  # Invalid: must be <= 10
            )

    def test_prompt_formatting_specifies_what_not_how(self) -> None:
        """Verifies prompt instructs Hermes to determine tool execution without exposing source API logic."""
        workflow = BoundedInvestigationWorkflow()
        task = InvestigationTask(
            information_gap="Determine whether the requested architecture document is complete.",
            preferred_capabilities=["drive", "gmail", "meet"],
            max_tool_calls=5,
            known_facts=["Author stated draft was ready"],
            unknowns=["Is document finalized in Drive?"],
            required_output={"status": "draft or final"},
        )

        prompt = workflow.format_investigation_prompt(task)

        # Must specify WHAT information is needed
        self.assertIn("WHAT INFORMATION IS NEEDED", prompt)
        self.assertIn("Determine whether the requested architecture document is complete.", prompt)
        self.assertIn("PREFERRED HERMES CAPABILITIES", prompt)
        self.assertIn("drive, gmail, meet", prompt)
        self.assertIn("Maximum tool calls allowed: 5", prompt)
        self.assertIn("Personal Intelligence specifies WHAT INFORMATION IS NEEDED, not HOW TO ACCESS THE SOURCE", prompt)


class TestSituationInvestigationCapabilityDelegation(unittest.TestCase):
    """Verifies end-to-end situation investigation using generic capability requests."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_cap_inv.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.goal_store = GoalStore(db_manager=self.db_manager)

    def tearDown(self) -> None:
        set_active_hermes_context(None)
        self.temp_dir.cleanup()

    def test_situation_gap_assessment_creates_capability_plan(self) -> None:
        """Verifies Phase 1 assesses gaps into a declarative capability-request plan."""
        investigator = SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
        )

        situation = self.situation_store.create_situation(
            type="forgotten_deliverable",
            priority=SituationPriority.HIGH.value,
            context={
                "description": "Quarterly System Architecture Document",
                "due_at": "2026-08-23T12:00:00Z",
            },
            investigation_target="Determine whether the requested architecture document is complete.",
        )

        plan = investigator._assess_gaps(
            situation=situation,
            goals=[],
            ref_dt=datetime.now(timezone.utc),
        )

        self.assertEqual(plan.information_gap, "Determine whether the requested architecture document is complete.")
        self.assertIn("drive", plan.preferred_capabilities)
        self.assertEqual(plan.max_tool_calls, 5)

        task_kwargs = plan.to_investigation_task_kwargs()
        self.assertEqual(task_kwargs["information_gap"], plan.information_gap)
        self.assertEqual(task_kwargs["preferred_capabilities"], plan.preferred_capabilities)
        self.assertEqual(task_kwargs["max_tool_calls"], 5)

    def test_situation_investigation_with_hermes_runtime_delegation(self) -> None:
        """Verifies full execution where Hermes runtime fulfills the capability request."""
        class MockHermesRuntime:
            def __init__(self):
                self.received_prompts = []

            def prompt_llm(self, prompt: str) -> str:
                self.received_prompts.append(prompt)
                return json.dumps({
                    "findings": [
                        "Architecture document 'v2.4_final.pdf' found in Google Drive folder 'Architecture Reviews'.",
                        "Confirmation email sent to lead reviewer on 2026-08-22 09:15 UTC."
                    ],
                    "source_references": [
                        "gdrive://file/doc-arch-9921",
                        "gmail://message/msg-conf-4412"
                    ],
                    "uncertainty": [],
                    "expiration_time": "2026-08-23T12:00:00Z",
                    "structured_data": {"deliverable_status": "complete"},
                })

        mock_runtime = MockHermesRuntime()
        bridge = HermesRuntimeBridge(runtime_context=mock_runtime)

        investigator = SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
            hermes_client=bridge,
        )

        situation = self.situation_store.create_situation(
            type="forgotten_deliverable",
            priority=SituationPriority.HIGH.value,
            context={"description": "Architecture Document"},
            information_required=True,
            investigation_target="Determine whether the requested architecture document is complete.",
        )


        outcome = investigator.investigate(situation=situation)

        self.assertTrue(outcome.investigation_succeeded)
        self.assertTrue(outcome.gap_resolved)
        self.assertIn("drive", outcome.evidence_bundle.facts_by_source)
        self.assertIn("gmail", outcome.evidence_bundle.facts_by_source)
        self.assertIn("Architecture document 'v2.4_final.pdf' found in Google Drive", str(outcome.evidence_bundle.all_facts()))


        # Check prompt sent to Hermes contained the declarative capability request
        self.assertEqual(len(mock_runtime.received_prompts), 1)
        prompt_text = mock_runtime.received_prompts[0]
        self.assertIn("WHAT INFORMATION IS NEEDED", prompt_text)
        self.assertIn("Determine whether the requested architecture document is complete.", prompt_text)


if __name__ == "__main__":
    unittest.main()
