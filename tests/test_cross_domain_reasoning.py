"""
Unit and integration tests for Cross-Domain Context Reasoning.
Verifies that the ContextBuilder combines information across unrelated event domains
(e.g., Sleep + Calendar Workload + Fitness Goal + Current Activity, or
Calendar Train + Current Location + Weather + Travel History) without domain agents.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.context import (
    BoundedReasoningContext,
    ContextBuilder,
    classify_event_domain,
)
from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    ReasoningEpisode,
)
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.situations.models import Situation, SituationPriority
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.models import StateFeature, StateRepresentation
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.hermes_bridge.client import (
    HermesClient,
    HermesInvocationResponse,
)
from personal_intelligence.hermes_bridge.reasoning import (
    ReasoningWorkflow,
    StructuredReasoningSynthesis,
)
from personal_intelligence.storage.db import DatabaseManager


class TestCrossDomainContextReasoning(unittest.TestCase):
    """Test suite validating cross-domain context synthesis without siloed domain agents."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_cross_domain.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.context_builder = ContextBuilder(situation_store=self.situation_store)
        self.mock_hermes_client = MagicMock(spec=HermesClient)

        self.workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=self.mock_hermes_client,
        )

        self.now = datetime(2026, 8, 15, 16, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_domain_classifier_heuristics(self) -> None:
        """Verify domain classification for disparate event types and sources."""
        self.assertEqual(classify_event_domain("sleep_session", "oura"), "biometrics_health")
        self.assertEqual(classify_event_domain("heart_rate_spike", "whoop"), "biometrics_health")
        self.assertEqual(classify_event_domain("workout_completed", "strava"), "biometrics_health")
        self.assertEqual(classify_event_domain("meeting_scheduled", "gcal"), "schedule_work")
        self.assertEqual(classify_event_domain("task_deadline", "jira"), "schedule_work")
        self.assertEqual(classify_event_domain("train_ticket_booking", "amtrak"), "mobility_transit")
        self.assertEqual(classify_event_domain("flight_departure", "airline"), "mobility_transit")
        self.assertEqual(classify_event_domain("weather_storm_alert", "openweather"), "location_environment")
        self.assertEqual(classify_event_domain("gps_location_update", "geo"), "location_environment")
        self.assertEqual(classify_event_domain("app_switch", "macos_monitor"), "device_activity")
        self.assertEqual(classify_event_domain("goal_milestone", "system"), "goals_intentions")

    def test_cross_domain_reasoning_health_work_goals_activity(self) -> None:
        """
        Verify cross-domain reasoning combining 4 disparate domains:
        1. Sleep (biometrics_health)
        2. Calendar workload (schedule_work)
        3. Fitness Goal (goals_intentions)
        4. Current Activity (device_activity)

        The recommendation requires synthesizing information from all domains:
        Low sleep (5.2h) + heavy meeting schedule (4 upcoming) + fitness goal (half marathon) + current deep coding.
        """
        # 1. State Representation combining biometrics, workload, and activity
        state = StateRepresentation(timestamp=self.now)
        state.set_feature("sleep_duration_hours", 5.2, "oura", self.now)
        state.set_feature("upcoming_meetings_count", 4, "gcal", self.now)
        state.set_feature("current_activity", "deep_coding", "macos_monitor", self.now)
        state.set_feature("active_goal_count", 2, "goals_engine", self.now)

        # 2. Timeline Events spanning multiple domains
        t_sleep = self.now - timedelta(hours=8)
        t_meeting = self.now + timedelta(minutes=45)
        t_editor = self.now - timedelta(minutes=15)

        timeline = Timeline([
            Event(id="evt-sleep-1", event_type="sleep_session", source="oura", event_time=t_sleep, payload={"duration_hours": 5.2, "rem_pct": 12}),
            Event(id="evt-cal-1", event_type="calendar_meeting", source="gcal", event_time=t_meeting, payload={"title": "Q3 Architecture Review", "duration_mins": 60}),
            Event(id="evt-app-1", event_type="app_switch", source="macos_monitor", event_time=t_editor, payload={"app": "VSCode", "focus_score": 0.92}),
        ])

        # 3. Active Goal (Intentions)
        fitness_goal = Goal(
            id="goal-half-marathon",
            name="Half Marathon Sub-2hr Training",
            description="Complete scheduled 10-mile tempo run today",
            priority=GoalPriority.HIGH,
        )

        # 4. Situation Frame
        situation = self.situation_store.create_situation(
            title="High Strain with Low Sleep Recovery",
            description="User has low sleep recovery, heavy calendar workload, and an active demanding training goal.",
            situation_type="cross_domain_strain_risk",
            evidence=["event:evt-sleep-1", "event:evt-cal-1"],
            related_goals=["goal-half-marathon"],
            priority=SituationPriority.HIGH.value,
        )

        # 5. Build Bounded Context
        bounded_ctx = self.context_builder.build_bounded_context(
            situation=situation,
            current_state=state,
            timeline=timeline,
            goals=[fitness_goal],
        )

        # Verify ContextBuilder captured all 4 distinct domains
        domains = bounded_ctx.metadata.get("cross_domain_domains", [])
        self.assertGreaterEqual(len(domains), 4)
        self.assertIn("biometrics_health", domains)
        self.assertIn("schedule_work", domains)
        self.assertIn("goals_intentions", domains)
        self.assertIn("device_activity", domains)

        # Verify prompt highlights cross-domain context
        prompt_str = bounded_ctx.to_prompt_string()
        self.assertIn("Cross-Domain Context Synthesis", prompt_str)
        self.assertIn("sleep_duration_hours", prompt_str)
        self.assertIn("Half Marathon Sub-2hr Training", prompt_str)
        self.assertIn("Architecture Review", prompt_str)

        # 6. Hermes multi-domain reasoning mock
        hermes_synthesis = {
            "what_is_happening": "User has restricted sleep (5.2h) and 4 upcoming meetings while targeting a 10-mile tempo run during intense coding.",
            "evidence_summary": [
                "Sleep duration: 5.2 hours from oura (event:evt-sleep-1)",
                "Upcoming meeting at 16:45: Q3 Architecture Review (event:evt-cal-1)",
                "Active high-priority goal: Half Marathon Sub-2hr Training",
                "Current activity: deep_coding in VSCode",
            ],
            "inferences": [
                "High cognitive fatigue combined with intense physical exertion risks injury or burnout.",
                "Meeting schedule leaves inadequate time for a 10-mile tempo workout before evening.",
            ],
            "predictions": [
                "Attempting 10-mile workout today will likely result in incomplete recovery and impaired focus for afternoon review.",
            ],
            "recommendations": [
                "Convert today's 10-mile tempo run to a 20-minute recovery walk/jog to protect recovery.",
                "Reschedule high-intensity training session to tomorrow morning after adequate sleep.",
            ],
            "uncertainties": [
                "Whether user can reschedule the afternoon architecture review.",
            ],
            "requires_follow_up": False,
            "urgency": "medium",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }
        self.mock_hermes_client.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_synthesis),
            duration_ms=520,
        )

        # 7. Run Workflow
        workflow_res = self.workflow.run_workflow(
            situation=situation,
            current_state=state,
            timeline=timeline,
            goals=[fitness_goal],
        )

        # Verify episode and synthesis
        self.assertIsNotNone(workflow_res.episode)
        self.assertEqual(workflow_res.episode.status, EpisodeStatus.REASONING_COMPLETED.value)
        self.assertEqual(len(workflow_res.synthesis.evidence_summary), 4)
        self.assertIn("Convert today's 10-mile tempo run", workflow_res.synthesis.recommendations[0])

    def test_cross_domain_reasoning_train_location_weather_history(self) -> None:
        """
        Verify cross-domain reasoning combining 4 disparate domains:
        1. Transit / Calendar (mobility_transit: Amtrak Train departure)
        2. Geolocation (location_environment: Suburban office 18 miles away)
        3. Meteorology / Weather (location_environment: Storm warning / rain)
        4. Historical travel records (mobility_transit: Past travel history in rain)

        The recommendation requires synthesizing information from all domains:
        Depart 25 minutes earlier due to combined distance and heavy rain traffic.
        """
        # 1. State Representation
        state = StateRepresentation(timestamp=self.now)
        state.set_feature("current_location", "Suburban Tech Park (18 miles from station)", "gps_geo", self.now)
        state.set_feature("weather_condition", "Heavy Rain / Storm Warning", "openweather", self.now)
        state.set_feature("next_transit_departure", "17:45 Amtrak Train #2150", "amtrak", self.now)

        # 2. Timeline Events across multiple domains
        t_hist_commute = self.now - timedelta(days=3)
        t_weather = self.now - timedelta(minutes=30)
        t_train = self.now + timedelta(hours=1, minutes=45)

        timeline = Timeline([
            # Historical event
            Event(
                id="evt-hist-commute",
                event_type="commute_completed",
                source="uber_trip",
                event_time=t_hist_commute,
                payload={"route": "Suburban Tech Park to Station", "duration_minutes": 55, "weather": "rain"},
            ),
            # Recent weather event
            Event(
                id="evt-weather-storm",
                event_type="weather_update",
                source="openweather",
                event_time=t_weather,
                payload={"condition": "Heavy Rain", "precipitation_mm": 18.5, "traffic_delay_index": 1.6},
            ),
            # Upcoming transit departure
            Event(
                id="evt-amtrak-train",
                event_type="train_departure",
                source="amtrak",
                event_time=t_train,
                payload={"train_number": "Amtrak 2150", "station": "Central Station", "departure_time": "17:45"},
            ),
        ])

        # 3. Situation Frame
        situation = self.situation_store.create_situation(
            title="Potential Missed Train Departure Risk",
            description="Upcoming scheduled train departure during severe weather storm from suburban location.",
            situation_type="transit_delay_risk",
            evidence=["event:evt-amtrak-train", "event:evt-weather-storm"],
            priority=SituationPriority.HIGH.value,
        )

        # 4. Build Bounded Context
        bounded_ctx = self.context_builder.build_bounded_context(
            situation=situation,
            current_state=state,
            timeline=timeline,
        )

        domains = bounded_ctx.metadata.get("cross_domain_domains", [])
        self.assertGreaterEqual(len(domains), 2)
        self.assertIn("mobility_transit", domains)
        self.assertIn("location_environment", domains)

        # Verify historical and recent multi-domain events were extracted
        recent_types = [e["event_type"] for e in bounded_ctx.relevant_recent_timeline]
        self.assertIn("weather_update", recent_types)
        self.assertIn("train_departure", recent_types)

        hist_types = [e["event_type"] for e in bounded_ctx.relevant_historical_events]
        self.assertIn("commute_completed", hist_types)

        # 5. Hermes Mock Response
        hermes_synthesis = {
            "what_is_happening": "User is 18 miles from Central Station with a 17:45 Amtrak train during an active heavy rain storm.",
            "evidence_summary": [
                "Upcoming train: Amtrak 2150 departing 17:45 (event:evt-amtrak-train)",
                "Current location: Suburban Tech Park 18 miles from station",
                "Weather: Heavy Rain with 1.6x traffic delay index (event:evt-weather-storm)",
                "Historical commute data: Same route took 55 minutes in rain (event:evt-hist-commute)",
            ],
            "inferences": [
                "Standard 25-minute travel time will be insufficient under current weather traffic.",
            ],
            "predictions": [
                "Departing at typical 17:15 will cause user to miss train boarding.",
            ],
            "recommendations": [
                "Depart for Central Station by 16:45 (30 minutes earlier than normal) to account for weather delays.",
            ],
            "uncertainties": [
                "Whether Amtrak train #2150 is also experiencing inbound weather delays.",
            ],
            "requires_follow_up": True,
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_strength": "strong",
        }
        self.mock_hermes_client.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_synthesis),
            duration_ms=480,
        )

        # 6. Run Workflow
        workflow_res = self.workflow.run_workflow(
            situation=situation,
            current_state=state,
            timeline=timeline,
        )

        # Verify cross-domain recommendation
        self.assertIn("Depart for Central Station by 16:45", workflow_res.synthesis.recommendations[0])
        self.assertEqual(workflow_res.synthesis.urgency, "high")

    def test_multi_domain_diversity_prevents_high_frequency_starvation(self) -> None:
        """
        Verify that a burst of high-frequency events in one domain (e.g. 25 app clicks)
        does NOT crowd out critical single events from other domains (sleep, calendar, weather).
        """
        # Create 25 rapid app_switch events in device_activity
        events = []
        for i in range(25):
            events.append(Event(
                id=f"evt-app-{i}",
                event_type="app_switch",
                source="macos_monitor",
                event_time=self.now - timedelta(minutes=i + 1),
                payload={"app": f"Editor_{i}"},
            ))

        # Add 1 biometrics event, 1 calendar event, 1 weather event
        events.append(Event(
            id="evt-sleep-rare",
            event_type="sleep_session",
            source="oura",
            event_time=self.now - timedelta(minutes=40),
            payload={"duration_hours": 6.0},
        ))
        events.append(Event(
            id="evt-cal-rare",
            event_type="calendar_deadline",
            source="gcal",
            event_time=self.now - timedelta(minutes=50),
            payload={"task": "Grant Proposal Submission"},
        ))
        events.append(Event(
            id="evt-weather-rare",
            event_type="weather_update",
            source="openweather",
            event_time=self.now - timedelta(minutes=30),
            payload={"rain": True},
        ))

        timeline = Timeline(events)

        situation = self.situation_store.create_situation(
            title="Multi-Domain Cross Check",
            description="Situation evaluating cross-domain diversity.",
            situation_type="general_context_check",
            evidence=["event:evt-cal-rare"],
            priority=SituationPriority.MEDIUM.value,
        )

        state = StateRepresentation(timestamp=self.now)
        state.set_feature("sleep_hours", 6.0, "oura", self.now)
        state.set_feature("deadline_today", True, "gcal", self.now)

        # Build bounded context with max_recent_events = 10
        builder = ContextBuilder(max_recent_events=10)
        bounded_ctx = builder.build_bounded_context(
            situation=situation,
            current_state=state,
            timeline=timeline,
        )

        extracted_types = {e["event_type"] for e in bounded_ctx.relevant_recent_timeline}

        # Verify diverse domains are all preserved despite 25 app_switch events
        self.assertIn("sleep_session", extracted_types)
        self.assertIn("calendar_deadline", extracted_types)
        self.assertIn("weather_update", extracted_types)
        self.assertIn("app_switch", extracted_types)


if __name__ == "__main__":
    unittest.main()
