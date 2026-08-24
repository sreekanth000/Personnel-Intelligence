"""
Unit and integration tests for Bounded External Investigation through Hermes.
Verifies information gap formulation (known_facts, unknowns, question_to_investigate, required_output),
Hermes response schema validation (findings, source_references, uncertainty, expiration_time),
retry loops on validation failure, and clean derived evidence integration without raw web dumps.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.events.buffer import EventBuffer
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.hermes_bridge.client import (
    HermesClient,
    HermesInvocationRequest,
    HermesInvocationResponse,
)
from personal_intelligence.hermes_bridge.investigation import (
    BoundedInvestigationWorkflow,
    InvestigationResult,
    InvestigationTask,
    validate_investigation_result,
)
from personal_intelligence.storage.db import DatabaseManager


class TestBoundedExternalInvestigation(unittest.TestCase):
    """Test suite for Bounded External Investigation via Hermes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_investigation.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.event_buffer = EventBuffer()
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.mock_hermes = MagicMock(spec=HermesClient)

        self.workflow = BoundedInvestigationWorkflow(
            hermes_client=self.mock_hermes,
            situation_store=self.situation_store,
            event_buffer=self.event_buffer,
        )

        self.now = datetime(2026, 8, 22, 17, 30, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_investigation_task_validation(self) -> None:
        """Verify strict validation of investigation tasks."""
        # 1. Valid task creation
        task = self.workflow.create_task(
            question_to_investigate="What is the current traffic on Route 9?",
            known_facts=["Current location: Office", "Destination: Station"],
            unknowns=["Current Route 9 delay"],
            required_output={"delay_minutes": "integer"},
        )
        self.assertIsNotNone(task.task_id)
        self.assertEqual(task.question_to_investigate, "What is the current traffic on Route 9?")

        # 2. Reject empty question
        with self.assertRaises(ValueError):
            self.workflow.create_task(
                question_to_investigate="",
                known_facts=["Fact 1"],
                unknowns=["Unknown 1"],
                required_output={"field": "string"},
            )

        # 3. Reject empty known_facts
        with self.assertRaises(ValueError):
            self.workflow.create_task(
                question_to_investigate="Valid question?",
                known_facts=[],
                unknowns=["Unknown 1"],
                required_output={"field": "string"},
            )

        # 4. Reject empty unknowns
        with self.assertRaises(ValueError):
            self.workflow.create_task(
                question_to_investigate="Valid question?",
                known_facts=["Fact 1"],
                unknowns=[],
                required_output={"field": "string"},
            )

        # 5. Reject empty required_output
        with self.assertRaises(ValueError):
            self.workflow.create_task(
                question_to_investigate="Valid question?",
                known_facts=["Fact 1"],
                unknowns=["Unknown 1"],
                required_output={},
            )

    def test_end_to_end_train_weather_traffic_investigation(self) -> None:
        """
        Verify end-to-end bounded investigation:
        Known: train time (17:45), location (Suburban Office), normal travel time (25m)
        Unknown: weather, traffic, transport disruption
        Bounded Question: Check Route 9 traffic delay, weather intensity, and Amtrak #2150 status.
        """
        # 1. Create target situation
        situation = self.situation_store.create(
            type="upcoming_transit_trip",
            priority=SituationPriority.HIGH.value,
            context={"train": "Amtrak #2150", "origin": "Suburban Office", "destination": "Central Station"},
            evidence=["event:evt-train-ticket"],
        )

        # 2. Formulate bounded investigation task
        known_facts = [
            "Train: Amtrak Northeast Regional #2150 departing Central Station at 17:45 UTC",
            "Current location: Suburban Office (18 miles west of Central Station)",
            "Historical travel time: 25 minutes in normal dry conditions",
        ]
        unknowns = [
            "Current weather conditions and precipitation intensity near Route 9 corridor",
            "Live traffic congestion and incident delays on Route 9 eastbound",
            "Amtrak #2150 active delays or track disruptions",
        ]
        required_output = {
            "traffic_delay_minutes": "integer",
            "weather_condition": "string",
            "transit_delay_status": "string",
            "recommended_extra_buffer_minutes": "integer",
        }
        question = "What is the live traffic delay on Route 9 to Central Station, active precipitation intensity, and departure status of Amtrak #2150?"

        task = self.workflow.create_task(
            question_to_investigate=question,
            known_facts=known_facts,
            unknowns=unknowns,
            required_output=required_output,
            situation_id=situation.id,
            valid_duration_minutes=45,
        )

        # Verify bounded prompt formatting
        prompt = self.workflow.format_investigation_prompt(task)
        self.assertIn("KNOWN LOCAL FACTS", prompt)
        self.assertIn("SPECIFIC INFORMATION GAPS", prompt)
        self.assertIn("Amtrak Northeast Regional #2150", prompt)
        self.assertIn("CRITICAL INVESTIGATION CONSTRAINTS", prompt)
        self.assertIn("Do NOT search broadly", prompt)

        # 3. Mock Hermes returning valid structured output
        exp_time = self.now + timedelta(minutes=45)
        hermes_output = {
            "findings": [
                "Route 9 Eastbound has a 20-minute accident delay near Exit 4.",
                "Heavy rain active across metropolitan area with 18mm/hr precipitation.",
                "Amtrak #2150 is currently reported on time at Central Station with normal boarding.",
            ],
            "source_references": [
                "https://511.state.gov/traffic/route-9-east",
                "https://api.weather.gov/stations/KNYC/radar",
                "https://transit.amtrak.com/status/train/2150",
            ],
            "structured_data": {
                "traffic_delay_minutes": 20,
                "weather_condition": "heavy_rain",
                "transit_delay_status": "on_time",
                "recommended_extra_buffer_minutes": 25,
            },
            "uncertainty": [
                "Accident clearance duration on Route 9 is estimated between 20-35 minutes.",
            ],
            "expiration_time": exp_time.isoformat(),
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_output),
            duration_ms=450,
        )

        # 4. Execute investigation
        result = self.workflow.execute_investigation(task)

        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.findings), 3)
        self.assertEqual(len(result.source_references), 3)
        self.assertEqual(result.structured_data["traffic_delay_minutes"], 20)
        self.assertEqual(result.structured_data["weather_condition"], "heavy_rain")
        self.assertFalse(result.is_expired(as_of=self.now))
        self.assertTrue(result.is_expired(as_of=self.now + timedelta(hours=1)))

        # 5. Integrate into Situation without raw web clutter
        updated_situation = self.workflow.integrate_investigation_into_situation(
            result=result,
            situation=situation,
        )

        # Verify situation evidence & context updated with derived findings only
        self.assertIn(f"external_investigation:{task.task_id}", updated_situation.evidence)
        self.assertIn("Route 9 Eastbound has a 20-minute accident delay", updated_situation.context["latest_external_findings"][0])
        self.assertEqual(len(updated_situation.context["external_investigations"]), 1)

        ext_inv_record = updated_situation.context["external_investigations"][0]
        self.assertEqual(ext_inv_record["sources"], hermes_output["source_references"])
        self.assertEqual(ext_inv_record["structured_data"]["recommended_extra_buffer_minutes"], 25)

        # Verify EventBuffer received a derived event
        drained_events = self.event_buffer.drain()
        self.assertEqual(len(drained_events), 1)
        self.assertEqual(drained_events[0].event_type, "external_investigation_finding")
        self.assertEqual(drained_events[0].source, "hermes_investigation")

    def test_validation_retry_loop_on_malformed_first_attempt(self) -> None:
        """
        Verify that when Hermes returns invalid output on attempt 1 (e.g. missing source_references),
        the retry prompt provides explicit field feedback, and attempt 2 succeeds.
        """
        task = self.workflow.create_task(
            question_to_investigate="Is the airport security queue currently delayed?",
            known_facts=["Flight departure at 19:30"],
            unknowns=["Terminal 2 TSA wait times"],
            required_output={"tsa_wait_minutes": "integer"},
        )

        # Attempt 1: missing source_references and expiration_time
        invalid_payload = {
            "findings": ["Terminal 2 wait time is 35 minutes."],
            "uncertainty": [],
        }

        # Attempt 2: valid payload
        exp_time = self.now + timedelta(minutes=30)
        valid_payload = {
            "findings": ["Terminal 2 TSA wait time is currently 35 minutes."],
            "source_references": ["https://tsa.gov/airports/jfk/wait-times"],
            "structured_data": {"tsa_wait_minutes": 35},
            "uncertainty": ["Wait times fluctuate every 15 minutes."],
            "expiration_time": exp_time.isoformat(),
        }

        self.mock_hermes.invoke_reasoning.side_effect = [
            HermesInvocationResponse(raw_response=json.dumps(invalid_payload), duration_ms=200),
            HermesInvocationResponse(raw_response=json.dumps(valid_payload), duration_ms=250),
        ]

        result = self.workflow.execute_investigation(task, max_retries=2)

        self.assertTrue(result.is_valid)
        self.assertEqual(self.mock_hermes.invoke_reasoning.call_count, 2)
        self.assertEqual(result.source_references[0], "https://tsa.gov/airports/jfk/wait-times")

        # Verify retry prompt included validation errors from attempt 1
        second_call_prompt = self.mock_hermes.invoke_reasoning.call_args_list[1][1]["request"].prompt
        self.assertIn("VALIDATION ERRORS ON PREVIOUS ATTEMPT", second_call_prompt)
        self.assertIn("source_references", second_call_prompt)

    def test_permanent_failure_fallback_preserves_error(self) -> None:
        """
        Verify that permanent unparseable output creates a safe fallback result
        with is_valid=False and preserves validation errors without crashing.
        """
        task = self.workflow.create_task(
            question_to_investigate="Check status of power outage in sector 4",
            known_facts=["Power flickered at 16:00"],
            unknowns=["Utility restoration ETA"],
            required_output={"restoration_eta": "string"},
        )

        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response="Sorry, I am unable to connect to the utility portal.",
            duration_ms=100,
        )

        result = self.workflow.execute_investigation(task, max_retries=1)

        self.assertFalse(result.is_valid)
        self.assertIn("Response was not valid JSON", result.uncertainty[0])
        self.assertEqual(len(result.validation_errors), 1)


if __name__ == "__main__":
    unittest.main()
