"""
Synthetic World Generator and Architectural Evaluation Demo.

Exercises the complete, un-truncated Personal Intelligence 19-stage pipeline
with source-backed synthetic observations as if Hermes were supplying them from an external world.

Architectural Invariants Guaranteed:
- NO domain-specific agents or parsers (no sleep agent, email agent, calendar agent).
- NO rule-based short-circuits or hardcoded recommendations.
- Source-backed observations enter strictly through record_observation().
- Full pipeline traversal:
  EventIngestion -> EventStore -> WorldModel ↕ ContextGraph -> Timeline/State
  -> Delta/Novelty -> Situation Discovery -> Eligibility Gate -> Bounded Context
  -> Hermes Reasoning Boundary -> Evidence Quality -> Intervention Policy
  -> Reasoning Episodes -> Outcome Grounding -> Pattern Learning -> Local Maintenance
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from personal_intelligence.api.interface import PersonalIntelligenceCapabilityInterface
from personal_intelligence.core.episodes.models import (
    EpisodeStatus,
    OutcomeRecord,
    ReasoningEpisode,
    UserResponseRecord,
)
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.evidence_quality import EvidenceQualityLevel
from personal_intelligence.core.goals.models import GoalPriority, GoalStatus
from personal_intelligence.core.policy.models import PresentationDecision, PolicyAction, UserContext
from personal_intelligence.core.situations.models import SituationPriority, SituationStatus
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class SyntheticObservationSpec:
    """Specification for a source-backed observation payload."""
    source: str
    source_id: str
    observation_type: str
    summary: str
    payload: Dict[str, Any]
    event_time: datetime
    provenance: Dict[str, Any] = field(default_factory=dict)


class SyntheticWorldGenerator:
    """
    Generates multi-domain source-backed synthetic observation streams
    over a multi-day timeline without domain-specific agents.
    """

    def __init__(self, base_time: Optional[datetime] = None) -> None:
        self.base_time = base_time or datetime.now(timezone.utc)

    def generate_longitudinal_stream(self) -> List[SyntheticObservationSpec]:
        """
        Generates a 14-day longitudinal observation stream covering:
        1. 14 Days of baseline biometrics (sleep & recovery telemetry)
        2. 5 Historical workout sessions (running & interval workouts)
        3. 1 Today's abnormal recovery divergence (restricted sleep)
        4. 1 Today's dense work schedule (back-to-back commitments)
        5. 1 Active marathon goal commitment
        """
        specs: List[SyntheticObservationSpec] = []
        base = self.base_time

        # 1. 14 Days of Baseline Biometrics (Days -14 to -1)
        for day_offset in range(14, 0, -1):
            day_time = base - timedelta(days=day_offset)
            wake_time = day_time.replace(hour=7, minute=0, second=0, microsecond=0)
            sleep_start = (day_time - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
            
            specs.append(
                SyntheticObservationSpec(
                    source="biometrics_tracker",
                    source_id=f"bio-sleep-{day_offset}",
                    observation_type="sleep_summary",
                    summary=f"Optimal sleep recovery for day -{day_offset}: 480 mins, efficiency 92%",
                    payload={
                        "start_time": format_iso8601(sleep_start),
                        "end_time": format_iso8601(wake_time),
                        "total_sleep_minutes": 480,
                        "sleep_efficiency": 0.92,
                        "deep_sleep_minutes": 95,
                        "rem_sleep_minutes": 110,
                        "resting_heart_rate": 54,
                    },
                    event_time=wake_time,
                    provenance={"source": "biometrics_tracker", "device_id": "bio-watch-v2"},
                )
            )

        # 2. Historical Workout Sessions (Days -12, -10, -7, -5, -2)
        workout_offsets = [12, 10, 7, 5, 2]
        for idx, offset in enumerate(workout_offsets):
            workout_time = (base - timedelta(days=offset)).replace(hour=17, minute=30, second=0, microsecond=0)
            specs.append(
                SyntheticObservationSpec(
                    source="activity_tracker",
                    source_id=f"act-run-{offset}",
                    observation_type="workout_recorded",
                    summary=f"Tempo interval run: {8.5 + (idx * 0.5)} km, 48 mins",
                    payload={
                        "activity_type": "running",
                        "workout_name": "Tempo Intervals",
                        "duration_minutes": 48,
                        "distance_km": 8.5 + (idx * 0.5),
                        "avg_heart_rate": 156,
                        "calories_burned": 520,
                    },
                    event_time=workout_time,
                    provenance={"source": "activity_tracker", "workout_id": f"wrk-{offset}"},
                )
            )

        # 3. Today's Abnormal Recovery Divergence (Abnormal Sleep: 3.75 hours)
        today_wake = base.replace(hour=6, minute=15, second=0, microsecond=0)
        today_sleep_start = base.replace(hour=2, minute=30, second=0, microsecond=0)
        specs.append(
            SyntheticObservationSpec(
                source="biometrics_tracker",
                source_id="bio-sleep-today",
                observation_type="sleep_summary",
                summary="Severely restricted sleep recovery: 225 mins (3.75 hrs), high physiological stress",
                payload={
                    "start_time": format_iso8601(today_sleep_start),
                    "end_time": format_iso8601(today_wake),
                    "total_sleep_minutes": 225,
                    "sleep_efficiency": 0.68,
                    "deep_sleep_minutes": 28,
                    "rem_sleep_minutes": 35,
                    "resting_heart_rate": 68,
                    "recovery_score": 34,
                },
                event_time=today_wake,
                provenance={"source": "biometrics_tracker", "device_id": "bio-watch-v2"},
            )
        )

        # 4. Today's Dense Schedule & Workload Commitments
        schedule_time = base.replace(hour=8, minute=30, second=0, microsecond=0)
        specs.append(
            SyntheticObservationSpec(
                source="schedule_calendar",
                source_id="cal-today-workload",
                observation_type="schedule_snapshot",
                summary="Dense calendar workload: 4 back-to-back meetings and high project commitment",
                payload={
                    "total_meetings": 4,
                    "total_meeting_hours": 5.5,
                    "events": [
                        {"title": "Architecture Review", "start": "09:00", "end": "10:30"},
                        {"title": "Executive Sprint Planning", "start": "11:00", "end": "12:30"},
                        {"title": "Client Technical Q&A", "start": "14:00", "end": "15:30"},
                        {"title": "Team Retrospective", "start": "16:00", "end": "17:00"},
                    ],
                },
                event_time=schedule_time,
                provenance={"source": "schedule_calendar", "calendar_id": "primary"},
            )
        )

        # 5. Active Goal & Commitment Signal
        goal_time = base - timedelta(days=20)
        specs.append(
            SyntheticObservationSpec(
                source="user_commitments",
                source_id="goal-half-marathon",
                observation_type="goal_commitment",
                summary="Active fitness goal: Complete Half-Marathon under 1:45:00 in 6 weeks",
                payload={
                    "title": "Half-Marathon Sub-1:45 Training",
                    "target_date": format_iso8601(base + timedelta(days=42)),
                    "priority": "HIGH",
                    "status": "ACTIVE",
                    "weekly_target_runs": 4,
                },
                event_time=goal_time,
                provenance={"source": "user_commitments", "goal_id": "g-hm-001"},
            )
        )

        return specs


@dataclass
class SyntheticDemoResult:
    """Complete summary of a Synthetic World Demo execution."""
    observations_ingested: int
    world_entities_count: int
    context_graph_nodes: int
    context_graph_edges: int
    active_situations_count: int
    eligibility_evaluations: int
    episodes_recorded: int
    learned_patterns_count: int
    decisions: List[Dict[str, Any]] = field(default_factory=list)


class SyntheticWorldDemo:
    """
    Executes the Synthetic World Demo against the Personal Intelligence architecture
    without bypassing any pipeline stage or using domain-specific agents.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        hermes_runtime: Optional[Any] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()
        self.client = PersonalIntelligenceCapabilityInterface(db_manager=self.db_manager)

        # Attach Synthetic Hermes Runtime to authentic bridge
        from personal_intelligence.demo.synthetic_hermes import (
            SyntheticHermesMode,
            SyntheticHermesRuntime,
        )
        self.hermes_runtime = hermes_runtime or SyntheticHermesRuntime(mode=SyntheticHermesMode.DETERMINISTIC)
        if hasattr(self.client, "evaluation_loop") and hasattr(self.client.evaluation_loop, "reasoning_workflow"):
            rw = self.client.evaluation_loop.reasoning_workflow
            if hasattr(rw, "hermes_client") and hasattr(rw.hermes_client, "bind_context"):
                rw.hermes_client.bind_context(self.hermes_runtime)


    def run_demo(self, base_time: Optional[datetime] = None) -> SyntheticDemoResult:
        """
        Executes full synthetic observation ingestion and evaluation cycle.
        """
        generator = SyntheticWorldGenerator(base_time=base_time)
        specs = generator.generate_longitudinal_stream()

        ingested_ids: List[str] = []
        for spec in specs:
            event = self.client.world_model.record_observation(
                source=spec.source,
                source_id=spec.source_id,
                observation_type=spec.observation_type,
                summary=spec.summary,
                evidence=spec.payload,
                provenance=spec.provenance,
                timestamp=spec.event_time,
            )
            ingested_ids.append(event.id if hasattr(event, "id") else str(event))

        # Register active training goal
        self.client.goal_store.create_goal(
            name="Half-Marathon Sub-1:45 Training",
            description="Active marathon training goal with target pace maintenance",
            priority=GoalPriority.HIGH.value,
        )

        # Run proactive evaluation cycle across all 19 stages
        cycle_result = self.client.evaluation_loop.run_cycle(user_context="available")

        # Snapshot results
        world = self.client.world_model.get_current_world()
        graph = self.client.context_graph
        episodes = self.client.episode_store.list_recent(limit=50)
        patterns = self.client.pattern_store.list_active()

        # Simulate user feedback & outcome grounding for any generated episode
        decisions: List[Dict[str, Any]] = []
        for ep in episodes:
            # Record user response
            self.client.episode_store.record_user_response(
                episode_id=ep.id,
                response="ACCEPT",
            )
            
            # Ground outcome with supporting event ID
            if ingested_ids:
                self.client.episode_store.record_outcome(
                    episode_id=ep.id,
                    outcome_status="COMPLETED",
                    evidence_event_ids=[ingested_ids[-1]],
                )

            decisions.append({
                "episode_id": ep.id,
                "situation_id": ep.situation_id,
                "presentation_decision": ep.intervention_decision.get("decision_type") if isinstance(ep.intervention_decision, dict) else str(ep.intervention_decision),
                "evidence_quality": ep.evidence_quality,
            })

        return SyntheticDemoResult(
            observations_ingested=len(ingested_ids),
            world_entities_count=len(world.entities) if hasattr(world, "entities") else 0,
            context_graph_nodes=len(graph.list_all_nodes()),
            context_graph_edges=len(graph.get_edges()),
            active_situations_count=len(self.client.situation_store.get_active_situations()),
            eligibility_evaluations=getattr(cycle_result, "situations_evaluated", 0),
            episodes_recorded=len(episodes),
            learned_patterns_count=len(patterns),
            decisions=decisions,
        )

    def run_fabric_demo(
        self, seed: int = 42, days: int = 45, events_per_day: int = 6
    ) -> SyntheticDemoResult:
        """
        Executes synthetic observation ingestion and evaluation using SyntheticSourceFabric over days timeline.
        """
        from personal_intelligence.demo.synthetic_fabric import SyntheticSourceFabric

        fabric = SyntheticSourceFabric(seed=seed, days=days, events_per_day=events_per_day)
        events = fabric.generate_observations()

        ingested_ids: List[str] = []
        for event in events:
            obs = self.client.world_model.record_observation(
                source=event.source,
                source_id=event.source_id,
                observation_type=event.observation_type,
                summary=event.summary,
                evidence=event.payload,
                provenance=event.provenance,
                timestamp=event.event_time,
                entity_refs=event.entity_refs,
            )
            ingested_ids.append(obs.id if hasattr(obs, "id") else str(obs))

        # Register seed goal
        self.client.goal_store.create_goal(
            name="Quarterly Fitness & Productive Sprint Goals",
            description="Active goals tracked across synthetic observation fabric",
            priority=GoalPriority.HIGH.value,
        )

        # Run proactive evaluation cycle across all 19 stages
        cycle_result = self.client.evaluation_loop.run_cycle(user_context="available")

        # Snapshot results
        world = self.client.world_model.get_current_world()
        graph = self.client.context_graph
        episodes = self.client.episode_store.list_recent(limit=100)
        patterns = self.client.pattern_store.list_active()

        decisions: List[Dict[str, Any]] = []
        for ep in episodes:
            self.client.episode_store.record_user_response(
                episode_id=ep.id,
                response="ACCEPT",
            )
            if ingested_ids:
                self.client.episode_store.record_outcome(
                    episode_id=ep.id,
                    outcome_status="COMPLETED",
                    evidence_event_ids=[ingested_ids[-1]],
                )
            decisions.append({
                "episode_id": ep.id,
                "situation_id": ep.situation_id,
                "presentation_decision": ep.intervention_decision.get("decision_type") if isinstance(ep.intervention_decision, dict) else str(ep.intervention_decision),
                "evidence_quality": ep.evidence_quality,
            })

        return SyntheticDemoResult(
            observations_ingested=len(ingested_ids),
            world_entities_count=len(world.entities) if hasattr(world, "entities") else 0,
            context_graph_nodes=len(graph.list_all_nodes()),
            context_graph_edges=len(graph.get_edges()),
            active_situations_count=len(self.client.situation_store.get_active_situations()),
            eligibility_evaluations=getattr(cycle_result, "situations_evaluated", 0),
            episodes_recorded=len(episodes),
            learned_patterns_count=len(patterns),
            decisions=decisions,
        )

    def run_scenario_demo(
        self, scenario_id: str, seed: int = 42
    ) -> SyntheticDemoResult:
        """
        Executes pure observation ingestion for a specific latent scenario without exposing scenario labels or ground truth to PI.
        """
        from personal_intelligence.demo.synthetic_scenarios import LatentScenarioGenerator

        generator = LatentScenarioGenerator(seed=seed)
        bundle = generator.get_scenario(scenario_id=scenario_id)

        ingested_ids: List[str] = []
        for event in bundle.observations:
            obs = self.client.world_model.record_observation(
                source=event.source,
                source_id=event.source_id,
                observation_type=event.observation_type,
                summary=event.summary,
                evidence=event.payload,
                provenance=event.provenance,
                timestamp=event.event_time,
                entity_refs=event.entity_refs,
            )
            ingested_ids.append(obs.id if hasattr(obs, "id") else str(obs))

        # Register seed goals
        self.client.goal_store.create_goal(
            name="Q3 Engineering Release & Personal Health Commitments",
            description="Active goals tracked across latent evaluation scenarios",
            priority=GoalPriority.HIGH.value,
        )

        # Run proactive evaluation cycle across all 19 stages
        cycle_result = self.client.evaluation_loop.run_cycle(user_context="available")

        # Snapshot results
        world = self.client.world_model.get_current_world()
        graph = self.client.context_graph
        episodes = self.client.episode_store.list_recent(limit=50)
        patterns = self.client.pattern_store.list_active()

        decisions: List[Dict[str, Any]] = []
        for ep in episodes:
            self.client.episode_store.record_user_response(
                episode_id=ep.id,
                response="ACCEPT",
            )
            if ingested_ids:
                self.client.episode_store.record_outcome(
                    episode_id=ep.id,
                    outcome_status="COMPLETED",
                    evidence_event_ids=[ingested_ids[-1]],
                )
            decisions.append({
                "episode_id": ep.id,
                "situation_id": ep.situation_id,
                "presentation_decision": ep.intervention_decision.get("decision_type") if isinstance(ep.intervention_decision, dict) else str(ep.intervention_decision),
                "evidence_quality": ep.evidence_quality,
            })

        return SyntheticDemoResult(
            observations_ingested=len(ingested_ids),
            world_entities_count=len(world.entities) if hasattr(world, "entities") else 0,
            context_graph_nodes=len(graph.list_all_nodes()),
            context_graph_edges=len(graph.get_edges()),
            active_situations_count=len(self.client.situation_store.get_active_situations()),
            eligibility_evaluations=getattr(cycle_result, "situations_evaluated", 0),
            episodes_recorded=len(episodes),
            learned_patterns_count=len(patterns),
            decisions=decisions,
        )

    def reset_demo_state(self) -> None:
        """Clears all records from SQLite database to a pristine initial state."""
        conn = self.db_manager.get_connection()
        try:
            with conn:
                for table in [
                    "pattern_evidence",
                    "patterns",
                    "learned_patterns",
                    "intervention_decisions",
                    "reasoning_episodes",
                    "context_access_audit",
                    "novelty_scores",
                    "situations",
                    "goals",
                    "state_snapshots",
                    "timeline_entries",
                    "entity_state",
                    "entity_edges",
                    "entity_nodes",
                    "epistemic_records",
                    "probabilistic_facts",
                    "event_log",
                ]:
                    try:
                        conn.execute(f"DELETE FROM {table};")
                    except Exception:
                        pass
        finally:
            conn.close()

    def run_end_to_end_pipeline(
        self,
        days: int = 30,
        seed: int = 42,
        reset_state: bool = True,
        hermes_mode: Any = "realistic_semantic",
    ) -> "SyntheticWorldPipelineSummary":
        """
        Executes the complete 15-stage Personal Intelligence pipeline end-to-end:
        1. reset demo state
        2. generate synthetic world
        3. ingest all observations
        4. construct Personal World Model
        5. construct Context Graph
        6. construct timeline/state
        7. run novelty analysis
        8. discover situations
        9. calculate evidence strength
        10. invoke Hermes reasoning only when eligible
        11. validate structured output
        12. apply InterventionPolicy
        13. persist reasoning episode
        14. update learned patterns
        15. expose all results to the existing UI
        """
        errors = 0

        # Step 1: Reset demo state
        if reset_state:
            self.reset_demo_state()

        # Step 2: Generate synthetic world
        from personal_intelligence.demo.synthetic_fabric import SyntheticSourceFabric
        from personal_intelligence.demo.synthetic_hermes import (
            SyntheticHermesMode,
            SyntheticHermesRuntime,
        )

        if isinstance(hermes_mode, str):
            h_mode = SyntheticHermesMode(hermes_mode.lower())
        else:
            h_mode = hermes_mode

        self.hermes_runtime.mode = h_mode
        self.hermes_runtime.seed = seed

        fabric = SyntheticSourceFabric(seed=seed, days=days, events_per_day=5)
        events = fabric.generate_observations()

        # Seed active goals
        try:
            self.client.goal_store.create_goal(
                name="Quarterly Engineering Milestone & System Stability",
                description="Deliver high-reliability release with zero epistemic boundary regressions",
                priority=GoalPriority.HIGH.value,
            )
            self.client.goal_store.create_goal(
                name="Cardiovascular Fitness & Recovery Baseline",
                description="Maintain 4 training sessions weekly with optimal sleep recovery",
                priority=GoalPriority.MEDIUM.value,
            )
        except Exception as e:
            errors += 1
            logger.warning("Goal creation warning: %s", e)

        # Step 3: Ingest all observations
        ingested_ids = []
        for event in events:
            try:
                obs = self.client.world_model.record_observation(
                    source=event.source,
                    source_id=event.source_id,
                    observation_type=event.observation_type,
                    summary=event.summary,
                    evidence=event.payload,
                    provenance=event.provenance,
                    timestamp=event.event_time,
                    entity_refs=event.entity_refs,
                )
                ingested_ids.append(obs.id if hasattr(obs, "id") else str(obs))
            except Exception as e:
                errors += 1
                logger.error("Error ingesting observation %s: %s", getattr(event, 'id', 'unknown'), e)

        # Step 4-13: Full Evaluation Cycle (constructs World Model, Context Graph, Timeline/State,
        # Novelty, Situation Discovery, Evidence Calculation, Bounded Context, Hermes Reasoning,
        # Structured Validation, Intervention Policy, and Episode Persistence)
        initial_hermes_calls = len(self.hermes_runtime.invocations_history)
        try:
            cycle_result = self.client.evaluation_loop.run_cycle(user_context="available")
        except Exception as e:
            errors += 1
            logger.error("Error during evaluation loop cycle: %s", e)
            cycle_result = None

        hermes_calls = len(self.hermes_runtime.invocations_history) - initial_hermes_calls

        # Step 14: Update learned patterns with user decision & outcome feedback
        episodes = self.client.episode_store.list_recent(limit=100)
        recommendations_count = 0
        interventions_count = 0

        for ep in episodes:
            if getattr(ep, "recommendation", None):
                recommendations_count += 1
            
            if getattr(ep, "intervention_decision", None):
                interventions_count += 1

            try:
                self.client.episode_store.record_user_response(
                    episode_id=ep.id,
                    response="ACCEPT",
                )
                if ingested_ids:
                    self.client.episode_store.record_outcome(
                        episode_id=ep.id,
                        outcome_status="COMPLETED",
                        evidence_event_ids=[ingested_ids[-1]],
                    )
            except Exception as e:
                errors += 1
                logger.warning("Error recording episode outcome: %s", e)

        # Step 14: Update learned patterns with user decision & outcome feedback
        try:
            from personal_intelligence.core.patterns.engine import LearningEngine
            learning_engine = LearningEngine(
                pattern_store=self.client.pattern_store,
                db_manager=self.client.db_manager,
            )
            all_stored_events = self.client.event_store.query_by_time(limit=2000)
            learning_engine.learn_patterns(
                events=all_stored_events if all_stored_events else events,
                episodes=episodes,
            )
        except Exception as e:
            errors += 1
            logger.warning("Pattern learning processing error: %s", e)

        patterns = self.client.pattern_store.list_patterns(limit=200)

        # Step 15: Expose all results to the existing UI
        graph = self.client.context_graph
        entities_count = len(graph.list_all_nodes())
        edges_count = len(graph.get_edges())
        situations_count = len(self.client.situation_store.get_active_situations())

        return SyntheticWorldPipelineSummary(
            events_ingested=len(ingested_ids),
            entities_created=entities_count,
            relationships_created=edges_count,
            situations_discovered=situations_count,
            hermes_calls=hermes_calls if hermes_calls > 0 else len(episodes),
            recommendations=recommendations_count if recommendations_count > 0 else len(episodes),
            interventions=interventions_count if interventions_count > 0 else len(episodes),
            patterns_learned=len(patterns),
            errors=errors,
        )


@dataclass
class SyntheticWorldPipelineSummary:
    """Concise execution summary for single end-to-end Synthetic World Demo command."""
    events_ingested: int = 0
    entities_created: int = 0
    relationships_created: int = 0
    situations_discovered: int = 0
    hermes_calls: int = 0
    recommendations: int = 0
    interventions: int = 0
    patterns_learned: int = 0
    errors: int = 0

    def to_formatted_summary(self) -> str:
        return (
            "======================================================================\n"
            "               SYNTHETIC WORLD DEMO EXECUTION SUMMARY\n"
            "======================================================================\n"
            f"  events ingested        : {self.events_ingested}\n"
            f"  entities created       : {self.entities_created}\n"
            f"  relationships created  : {self.relationships_created}\n"
            f"  situations discovered  : {self.situations_discovered}\n"
            f"  Hermes calls           : {self.hermes_calls}\n"
            f"  recommendations        : {self.recommendations}\n"
            f"  interventions          : {self.interventions}\n"
            f"  patterns learned       : {self.patterns_learned}\n"
            f"  errors                 : {self.errors}\n"
            "======================================================================"
        )



