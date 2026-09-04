"""
Latent Scenarios and Ground-Truth Evaluation Framework for Personal Intelligence.

Provides 10 hidden evaluation scenarios:
1. cross_domain_project_risk
2. behavioral_routine_change
3. prolonged_screen_activity
4. travel_convergence
5. forgotten_commitment
6. multi_goal_conflict
7. opportunity
8. novel_signal_combination
9. high_volume_noise
10. contradictory_evidence

Crucial Invariant:
- Personal Intelligence NEVER receives scenario labels or ground-truth expectations.
- Observations ingested into PI are pure, source-backed Event records.
- Ground truth is kept strictly inside LatentScenarioGroundTruth for post-run evaluation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import random
from typing import Any, Dict, List, Optional

from personal_intelligence.core.events.models import Event, ensure_timezone_aware


@dataclass
class LatentScenarioGroundTruth:
    """Hidden ground truth evaluation spec maintained outside PI context."""
    scenario_id: str
    name: str
    description: str
    expected_situation_class: str
    expected_affected_entities: List[str]
    expected_affected_goals: List[str]
    expected_qualitative_recommendation: str


@dataclass
class LatentScenarioBundle:
    """Container holding hidden ground truth and pure source-backed observations."""
    scenario_id: str
    ground_truth: LatentScenarioGroundTruth
    observations: List[Event]


class LatentScenarioGenerator:
    """Generates pure observation streams and hidden ground truths for 10 evaluation scenarios."""

    SCENARIO_IDS = (
        "cross_domain_project_risk",
        "behavioral_routine_change",
        "prolonged_screen_activity",
        "travel_convergence",
        "forgotten_commitment",
        "multi_goal_conflict",
        "opportunity",
        "novel_signal_combination",
        "high_volume_noise",
        "contradictory_evidence",
    )

    def __init__(self, seed: int = 42, base_time: Optional[datetime] = None) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        if base_time is None:
            now = datetime.now(timezone.utc)
            self.base_time = datetime(now.year, now.month, now.day, 9, 0, 0, tzinfo=timezone.utc)
        else:
            self.base_time = ensure_timezone_aware(base_time, "base_time")

    def get_scenario(self, scenario_id: str) -> LatentScenarioBundle:
        """Retrieves a specific scenario bundle by ID."""
        if scenario_id not in self.SCENARIO_IDS:
            raise ValueError(f"Unknown scenario_id '{scenario_id}'. Valid choices: {self.SCENARIO_IDS}")
        
        method_name = f"_gen_{scenario_id}"
        gen_method = getattr(self, method_name)
        return gen_method()

    def get_all_scenarios(self) -> List[LatentScenarioBundle]:
        """Retrieves all 10 scenario bundles."""
        return [self.get_scenario(sid) for sid in self.SCENARIO_IDS]

    def _make_event(
        self,
        event_id: str,
        timestamp: datetime,
        source: str,
        source_id: str,
        event_type: str,
        entities: List[str],
        summary: str,
        evidence: Dict[str, Any],
        source_type: str = "general",
    ) -> Event:
        """Constructs a pure source-backed Event without any scenario labels or ground truth."""
        provenance = {
            "tool": f"hermes_fetch_{source}",
            "source_system": source,
            "source_type": source_type,
            "source_event_id": source_id,
            "retrieved_at": timestamp.isoformat(),
            "confidence": 1.0,
        }
        return Event(
            id=event_id,
            timestamp=timestamp,
            source=source,
            source_id=source_id,
            observation_type=event_type,
            entity_refs=entities,
            structured_data={
                "summary": summary,
                "evidence": evidence,
            },
            provenance=provenance,
            confidence=1.0,
            summary=summary,
        )

    # -------------------------------------------------------------------------
    # Scenario 1: Cross-Domain Project Risk
    # -------------------------------------------------------------------------
    def _gen_cross_domain_project_risk(self) -> LatentScenarioBundle:
        base = self.base_time
        gt = LatentScenarioGroundTruth(
            scenario_id="cross_domain_project_risk",
            name="Cross-Domain Project Risk",
            description="Severe sleep deprivation combined with an upcoming critical code commit/release deadline.",
            expected_situation_class="possible_goal_risk",
            expected_affected_entities=["person:user", "project:pi_core", "issue:PI-500"],
            expected_affected_goals=["goal:q3_release"],
            expected_qualitative_recommendation="Defer late-night deployment or request peer code review due to cognitive fatigue risk.",
        )
        obs = [
            self._make_event(
                event_id="evt-cdpr-01",
                timestamp=base - timedelta(days=1),
                source="whoop",
                source_id="whoop-sleep-cdpr",
                event_type="sleep_summary",
                entities=["person:user", "metric:sleep"],
                summary="Restricted sleep recovery: 210 mins (3.5 hours), high physiological strain",
                evidence={"sleep_minutes": 210, "recovery_percentage": 28, "resting_hr": 69},
                source_type="health",
            ),
            self._make_event(
                event_id="evt-cdpr-02",
                timestamp=base,
                source="github",
                source_id="gh-pr-500",
                event_type="pull_request_updated",
                entities=["person:user", "project:pi_core", "issue:PI-500"],
                summary="PR #500 Critical Security Release targeting production deploy today",
                evidence={"pr_id": 500, "status": "OPEN", "target_branch": "main", "priority": "CRITICAL"},
                source_type="developer_tools",
            ),
        ]
        return LatentScenarioBundle(scenario_id=gt.scenario_id, ground_truth=gt, observations=obs)

    # -------------------------------------------------------------------------
    # Scenario 2: Behavioral / Routine Change
    # -------------------------------------------------------------------------
    def _gen_behavioral_routine_change(self) -> LatentScenarioBundle:
        base = self.base_time
        gt = LatentScenarioGroundTruth(
            scenario_id="behavioral_routine_change",
            name="Behavioral Routine Change",
            description="Sudden shift in wake time and morning routine structure paired with high workout intensity.",
            expected_situation_class="routine_deviation",
            expected_affected_entities=["routine:morning_focus", "activity:running"],
            expected_affected_goals=["goal:fitness_habit"],
            expected_qualitative_recommendation="Monitor energy levels and adjust afternoon focus block to prevent mid-day burnout.",
        )
        obs = [
            self._make_event(
                event_id="evt-brc-01",
                timestamp=base.replace(hour=5, minute=0),
                source="routine_tracker",
                source_id="rt-brc-wake",
                event_type="routine_step_logged",
                entities=["routine:morning_focus", "person:user"],
                summary="Awoke at 05:00 (2 hours earlier than 07:00 baseline routine)",
                evidence={"wake_time": "05:00", "baseline_wake": "07:00", "deviation_minutes": -120},
                source_type="lifestyle",
            ),
            self._make_event(
                event_id="evt-brc-02",
                timestamp=base.replace(hour=6, minute=0),
                source="whoop",
                source_id="whoop-workout-brc",
                event_type="workout_completed",
                entities=["activity:running", "person:user"],
                summary="High intensity 15km interval run completed at 06:00",
                evidence={"distance_km": 15.0, "avg_hr": 168, "strain": 16.5},
                source_type="health",
            ),
        ]
        return LatentScenarioBundle(scenario_id=gt.scenario_id, ground_truth=gt, observations=obs)

    # -------------------------------------------------------------------------
    # Scenario 3: Prolonged Screen Activity
    # -------------------------------------------------------------------------
    def _gen_prolonged_screen_activity(self) -> LatentScenarioBundle:
        base = self.base_time
        gt = LatentScenarioGroundTruth(
            scenario_id="prolonged_screen_activity",
            name="Prolonged Screen Activity",
            description="14 consecutive hours of active desktop telemetry without break intervals during late-night hours.",
            expected_situation_class="prolonged_activity",
            expected_affected_entities=["device:macbook_pro", "system:screen_time"],
            expected_affected_goals=["goal:wellness_balance"],
            expected_qualitative_recommendation="Recommend immediate 15-minute eye break and wind-down session.",
        )
        obs = [
            self._make_event(
                event_id="evt-psa-01",
                timestamp=base + timedelta(hours=14),
                source="device_os",
                source_id="dev-psa-telemetry",
                event_type="system_telemetry_logged",
                entities=["device:macbook_pro", "system:screen_time"],
                summary="Continuous active desktop screen time: 14 hours 15 mins without recorded idle breaks",
                evidence={"active_hours": 14.25, "idle_breaks_count": 0, "active_window": "IDE"},
                source_type="system",
            ),
        ]
        return LatentScenarioBundle(scenario_id=gt.scenario_id, ground_truth=gt, observations=obs)

    # -------------------------------------------------------------------------
    # Scenario 4: Travel Convergence
    # -------------------------------------------------------------------------
    def _gen_travel_convergence(self) -> LatentScenarioBundle:
        base = self.base_time
        gt = LatentScenarioGroundTruth(
            scenario_id="travel_convergence",
            name="Travel Convergence",
            description="Flight travel booking, severe weather warning, and client meetings converging in destination city.",
            expected_situation_class="schedule_conflict",
            expected_affected_entities=["flight:AA123", "location:chicago", "meeting:client_sync"],
            expected_affected_goals=["goal:client_delivery"],
            expected_qualitative_recommendation="Buffer transit time between flight arrival and client meeting due to weather delay risk.",
        )
        obs = [
            self._make_event(
                event_id="evt-tc-01",
                timestamp=base,
                source="calendar",
                source_id="cal-flight-aa123",
                event_type="calendar_event_created",
                entities=["flight:AA123", "location:chicago"],
                summary="Flight AA123 to Chicago arriving at 14:00",
                evidence={"flight_num": "AA123", "destination": "Chicago ORD", "arrival_time": "14:00"},
                source_type="scheduling",
            ),
            self._make_event(
                event_id="evt-tc-02",
                timestamp=base + timedelta(hours=1),
                source="weather_service",
                source_id="wx-ord-storm",
                event_type="environment_condition_updated",
                entities=["location:chicago", "weather:thunderstorm"],
                summary="Severe thunderstorm alert at Chicago ORD with expected ground stops and flight delays",
                evidence={"location": "Chicago", "severity": "SEVERE", "delay_probability": 0.90},
                source_type="environment",
            ),
            self._make_event(
                event_id="evt-tc-03",
                timestamp=base + timedelta(hours=2),
                source="calendar",
                source_id="cal-client-chicago",
                event_type="calendar_event_created",
                entities=["meeting:client_sync", "location:chicago"],
                summary="Client Executive Sync scheduled at 14:45 in Downtown Chicago",
                evidence={"title": "Client Executive Sync", "start": "14:45", "location": "Downtown Chicago"},
                source_type="scheduling",
            ),
        ]
        return LatentScenarioBundle(scenario_id=gt.scenario_id, ground_truth=gt, observations=obs)

    # -------------------------------------------------------------------------
    # Scenario 5: Forgotten Commitment
    # -------------------------------------------------------------------------
    def _gen_forgotten_commitment(self) -> LatentScenarioBundle:
        base = self.base_time
        gt = LatentScenarioGroundTruth(
            scenario_id="forgotten_commitment",
            name="Forgotten Commitment",
            description="Explicit email commitment made 3 days ago with zero subsequent review action.",
            expected_situation_class="potential_deadline_risk",
            expected_affected_entities=["person:alice", "pr:204", "repo:pi_core"],
            expected_affected_goals=["goal:code_quality"],
            expected_qualitative_recommendation="Prompt user to complete promised code review for PR #204.",
        )
        obs = [
            self._make_event(
                event_id="evt-fc-01",
                timestamp=base - timedelta(days=3),
                source="slack",
                source_id="slack-commit-pr204",
                event_type="message_received",
                entities=["person:alice", "pr:204", "repo:pi_core"],
                summary="User sent message to Alice: 'I will complete the code review for PR #204 by end of day today.'",
                evidence={"sender": "user", "recipient": "alice", "commitment": "PR #204 review"},
                source_type="messaging",
            ),
        ]
        return LatentScenarioBundle(scenario_id=gt.scenario_id, ground_truth=gt, observations=obs)

    # -------------------------------------------------------------------------
    # Scenario 6: Multi-Goal Conflict
    # -------------------------------------------------------------------------
    def _gen_multi_goal_conflict(self) -> LatentScenarioBundle:
        base = self.base_time
        gt = LatentScenarioGroundTruth(
            scenario_id="multi_goal_conflict",
            name="Multi-Goal Conflict",
            description="Overlapping schedule commitments for a 20km marathon run and an 8-hour executive sprint.",
            expected_situation_class="schedule_conflict",
            expected_affected_entities=["goal:marathon_training", "goal:executive_sprint", "meeting:exec_planning"],
            expected_affected_goals=["goal:marathon_training", "goal:executive_sprint"],
            expected_qualitative_recommendation="Reschedule 20km run session to morning window to resolve conflict with executive sprint.",
        )
        obs = [
            self._make_event(
                event_id="evt-mgc-01",
                timestamp=base,
                source="calendar",
                source_id="cal-exec-sprint",
                event_type="calendar_event_created",
                entities=["meeting:exec_planning", "goal:executive_sprint"],
                summary="Executive Sprint Planning session scheduled for 13:00 to 17:00",
                evidence={"title": "Executive Sprint Planning", "start": "13:00", "end": "17:00"},
                source_type="scheduling",
            ),
            self._make_event(
                event_id="evt-mgc-02",
                timestamp=base + timedelta(minutes=30),
                source="routine_tracker",
                source_id="rt-run-20k",
                event_type="routine_step_logged",
                entities=["goal:marathon_training"],
                summary="Long Distance 20km Run scheduled for 14:00 to 16:30",
                evidence={"activity": "20km Run", "start": "14:00", "end": "16:30"},
                source_type="lifestyle",
            ),
        ]
        return LatentScenarioBundle(scenario_id=gt.scenario_id, ground_truth=gt, observations=obs)

    # -------------------------------------------------------------------------
    # Scenario 7: Opportunity
    # -------------------------------------------------------------------------
    def _gen_opportunity(self) -> LatentScenarioBundle:
        base = self.base_time
        gt = LatentScenarioGroundTruth(
            scenario_id="opportunity",
            name="Opportunity",
            description="Open afternoon schedule block coinciding with ideal weather and an active running goal requirement.",
            expected_situation_class="routine_deviation",
            expected_affected_entities=["goal:weekly_mileage", "location:park_trail"],
            expected_affected_goals=["goal:weekly_mileage"],
            expected_qualitative_recommendation="Capitalize on open afternoon slot and clear weather to complete weekly mileage goal.",
        )
        obs = [
            self._make_event(
                event_id="evt-opp-01",
                timestamp=base,
                source="calendar",
                source_id="cal-free-afternoon",
                event_type="schedule_snapshot",
                entities=["location:park_trail"],
                summary="Open schedule block detected: 14:00 to 18:00 (zero meetings scheduled)",
                evidence={"free_hours": 4.0, "start": "14:00", "end": "18:00"},
                source_type="scheduling",
            ),
            self._make_event(
                event_id="evt-opp-02",
                timestamp=base + timedelta(minutes=15),
                source="weather_service",
                source_id="wx-clear-22c",
                event_type="environment_condition_updated",
                entities=["location:park_trail", "weather:clear"],
                summary="Ideal outdoor conditions: 22°C, sunny, low humidity",
                evidence={"temperature": 22.0, "condition": "SUNNY", "humidity": 0.40},
                source_type="environment",
            ),
        ]
        return LatentScenarioBundle(scenario_id=gt.scenario_id, ground_truth=gt, observations=obs)

    # -------------------------------------------------------------------------
    # Scenario 8: Novel Signal Combination
    # -------------------------------------------------------------------------
    def _gen_novel_signal_combination(self) -> LatentScenarioBundle:
        base = self.base_time
        gt = LatentScenarioGroundTruth(
            scenario_id="novel_signal_combination",
            name="Novel Signal Combination",
            description="Unfamiliar marine sensor telemetry, ocean barometric pressure drops, and async laboratory calendar state.",
            expected_situation_class="unusual_state",
            expected_affected_entities=["sensor:marine_buoy_04", "location:marine_lab"],
            expected_affected_goals=["goal:field_research"],
            expected_qualitative_recommendation="Highlight novel sensor telemetry divergence and preserve uncertainty regarding field conditions.",
        )
        obs = [
            self._make_event(
                event_id="evt-nsc-01",
                timestamp=base,
                source="sensor_telemetry",
                source_id="snr-buoy-04",
                event_type="telemetry_divergence_logged",
                entities=["sensor:marine_buoy_04", "location:marine_lab"],
                summary="Marine Buoy #04 sensor anomaly: Barometric pressure dropped 25hPa in 1 hour",
                evidence={"sensor_id": "buoy_04", "pressure_drop_hpa": 25.0, "wind_knots": 48},
                source_type="system",
            ),
        ]
        return LatentScenarioBundle(scenario_id=gt.scenario_id, ground_truth=gt, observations=obs)

    # -------------------------------------------------------------------------
    # Scenario 9: High-Volume Noise
    # -------------------------------------------------------------------------
    def _gen_high_volume_noise(self) -> LatentScenarioBundle:
        base = self.base_time
        gt = LatentScenarioGroundTruth(
            scenario_id="high_volume_noise",
            name="High-Volume Noise",
            description="50+ low-importance telemetry signals surrounding 1 critical production release deadline.",
            expected_situation_class="potential_deadline_risk",
            expected_affected_entities=["project:pi_production", "issue:PROD-101"],
            expected_affected_goals=["goal:prod_launch"],
            expected_qualitative_recommendation="Isolate critical release deadline from background noise telemetries.",
        )
        obs = []
        # Generate 50 noise events
        for i in range(50):
            obs.append(
                self._make_event(
                    event_id=f"evt-hvn-noise-{i:02d}",
                    timestamp=base + timedelta(minutes=i),
                    source="device_os",
                    source_id=f"sys-noise-{i:02d}",
                    event_type="system_status_log",
                    entities=["device:macbook_pro"],
                    summary=f"Routine system background ping #{i}: CPU usage {15 + (i % 5)}%",
                    evidence={"ping_id": i, "cpu_usage": 15 + (i % 5)},
                    source_type="system",
                )
            )
        # Intersperse 1 critical release deadline event
        obs.append(
            self._make_event(
                event_id="evt-hvn-critical",
                timestamp=base + timedelta(minutes=25),
                source="jira",
                source_id="jira-prod-101",
                event_type="issue_status_updated",
                entities=["project:pi_production", "issue:PROD-101"],
                summary="CRITICAL: Production Launch Milestone PROD-101 requires deployment sign-off in 2 hours",
                evidence={"issue_key": "PROD-101", "status": "PENDING_SIGNOFF", "priority": "BLOCKER"},
                source_type="developer_tools",
            )
        )
        obs.sort(key=lambda e: e.event_time)
        return LatentScenarioBundle(scenario_id=gt.scenario_id, ground_truth=gt, observations=obs)

    # -------------------------------------------------------------------------
    # Scenario 10: Contradictory Evidence
    # -------------------------------------------------------------------------
    def _gen_contradictory_evidence(self) -> LatentScenarioBundle:
        base = self.base_time
        gt = LatentScenarioGroundTruth(
            scenario_id="contradictory_evidence",
            name="Contradictory Evidence",
            description="Calendar schedule showing 'In Meeting with Executive Board' while chat & device telemetry shows 'Working offline in transit'.",
            expected_situation_class="unusual_state",
            expected_affected_entities=["meeting:exec_board", "location:transit_train"],
            expected_affected_goals=["goal:exec_alignment"],
            expected_qualitative_recommendation="Flag contradiction between calendar location and device transit telemetry.",
        )
        obs = [
            self._make_event(
                event_id="evt-ce-01",
                timestamp=base,
                source="calendar",
                source_id="cal-exec-board",
                event_type="calendar_event_created",
                entities=["meeting:exec_board"],
                summary="Calendar status: Currently attending Executive Board In-Person Meeting",
                evidence={"title": "Executive Board Meeting", "location": "Boardroom A"},
                source_type="scheduling",
            ),
            self._make_event(
                event_id="evt-ce-02",
                timestamp=base + timedelta(minutes=5),
                source="maps_gps",
                source_id="gps-transit-train",
                event_type="location_arrival_logged",
                entities=["location:transit_train"],
                summary="GPS telemetry: Moving at 85 km/h on Regional Express Train",
                evidence={"speed_kmh": 85.0, "transit_mode": "train", "geofence": "OUT_OF_OFFICE"},
                source_type="environment",
            ),
        ]
        return LatentScenarioBundle(scenario_id=gt.scenario_id, ground_truth=gt, observations=obs)
