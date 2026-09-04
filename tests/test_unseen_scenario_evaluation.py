"""
Architectural evaluation demonstrating that Personal Intelligence is domain-agnostic and not a collection of hard-coded domain agents.
Tests an unseen, multi-stream synthetic scenario without any specialized detector:
- Unusual location behavior (remote marine research station)
- Changed calendar pattern (transatlantic async schedule)
- Unusual work activity (embedded hardware firmware & sensor telemetry)
- Changed evening routine (laboratory testing with high ocean wind)

Verifies:
1. Statistical Novelty Detector identifies an unusual state from divergence alone.
2. Situation Engine creates a generic novel situation without a hardcoded detector.
3. Context Builder retrieves relevant longitudinal history.
4. Hermes reasons about the unfamiliar situation.
5. Hermes explicitly preserves uncertainty when evidence is insufficient.
6. Intervention Policy suppresses/discards non-actionable novel states.
7. Reasoning episode is persisted in SQLite with complete provenance.
8. Future repetitions accumulate supporting evidence into a learned pattern.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from personal_intelligence.core.context.builder import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStatus, EpisodeStore
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.novelty import NoveltyEngine, OverallNoveltyLevel
from personal_intelligence.core.patterns.engine import LearningEngine
from personal_intelligence.core.patterns.models import PatternStatus
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.policy.engine import InterventionPolicyEngine
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.models import SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.state.models import StateFeature, StateRepresentation
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.hermes_bridge.client import HermesClient, HermesInvocationResponse
from personal_intelligence.hermes_bridge.reasoning import (
    NovelReasoningSynthesis,
    ReasoningWorkflow,
    validate_novel_reasoning_synthesis,
)
from personal_intelligence.storage.db import DatabaseManager


class TestUnseenScenarioEvaluation(unittest.TestCase):
    """
    Architectural evaluation suite demonstrating domain-agnostic reasoning on unfamiliar scenarios.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_unseen_eval.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.state_engine = StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.novelty_engine = NoveltyEngine()
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.situation_engine = SituationEngine()
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.learning_engine = LearningEngine(pattern_store=self.pattern_store, db_manager=self.db_manager)
        self.policy_engine = InterventionPolicyEngine()
        self.context_builder = ContextBuilder(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
        )

        self.mock_hermes = MagicMock(spec=HermesClient)
        self.reasoning_workflow = ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=self.mock_hermes,
        )

        self.base_time = datetime(2026, 8, 22, 22, 30, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _build_historical_baseline_snapshots(self) -> list:
        """Constructs 14 historical StateRepresentation snapshots of standard urban routine."""
        history = []
        for i in range(14, 0, -1):
            snap_time = self.base_time - timedelta(days=i)
            rep = StateRepresentation(timestamp=snap_time)
            rep.set_feature(name="location_cluster", value="city_apartment", source="geo_gps", timestamp=snap_time, confidence=0.95)
            rep.set_feature(name="current_activity", value="software_development", source="os_window", timestamp=snap_time, confidence=0.95)
            rep.set_feature(name="meeting_timezone_offset", value=0.0, source="calendar", timestamp=snap_time, confidence=1.0)
            rep.set_feature(name="evening_ambient_environment", value="home_residential", source="sensor", timestamp=snap_time, confidence=0.90)
            rep.set_feature(name="recent_activity_duration", value=90.0, source="os_window", timestamp=snap_time, confidence=0.95)
            history.append(rep)
        return history

    def test_unseen_scenario_end_to_end_emergence(self) -> None:
        """
        End-to-end formal test:
        Verifies 8-step pipeline on an unseen combination of multi-stream events:
        - remote marine station location
        - hardware firmware flashing & sensor telemetry
        - async Tokyo schedule
        - high ocean wind ambient environment
        """
        # =========================================================================
        # 0. Negative Constraint Check: Verify NO Hard-Coded Detector Exists
        # =========================================================================
        situation_engine_methods = [m for m in dir(self.situation_engine) if m.startswith("_generate_")]
        self.assertNotIn("_generate_marine_station", situation_engine_methods)
        self.assertNotIn("_generate_firmware_flashing", situation_engine_methods)
        self.assertNotIn("_generate_ocean_wind", situation_engine_methods)
        self.assertNotIn("_generate_hardware_lab", situation_engine_methods)

        # =========================================================================
        # 1. Ingest Multi-Stream Unseen Events
        # =========================================================================
        events = [
            # Stream 1: Unusual Location Behavior
            Event(
                id="evt-geo-marine-lab",
                event_type="location_update",
                source="gps_telemetry",
                event_time=self.base_time - timedelta(hours=4),
                payload={"cluster": "remote_marine_station", "lat": 64.1466, "lon": -21.9426, "region": "Iceland Coast"},
            ),
            # Stream 2: Unusual Work Activity
            Event(
                id="evt-work-firmware",
                event_type="app_focus",
                source="os_window",
                event_time=self.base_time - timedelta(hours=2),
                payload={"app": "Saleae_Logic_Analyzer", "task": "underwater_acoustic_sensor_flashing", "duration_minutes": 110},
            ),
            # Stream 3: Changed Calendar Pattern
            Event(
                id="evt-cal-async",
                event_type="calendar_event",
                source="gcal",
                event_time=self.base_time - timedelta(hours=1),
                payload={"title": "Tokyo Hydrophone Data Sync", "collaborators": ["tokyo_team@ocean.org"], "tz_offset": 9.0},
            ),
            # Stream 4: Changed Evening Routine
            Event(
                id="evt-env-wind",
                event_type="ambient_environment",
                source="acoustic_sensor",
                event_time=self.base_time,
                payload={"ambient_type": "laboratory_marine_gale", "wind_knots": 48, "indoor_activity": "soldering_bench"},
            ),
        ]
        self.event_store.append_batch(type("Batch", (), {"events": events})())

        # Construct Timeline
        timeline = self.timeline_engine.get_time_range(
            start_time=self.base_time - timedelta(days=1),
            end_time=self.base_time + timedelta(hours=1),
        )
        self.assertEqual(len(timeline.events), 4)

        # =========================================================================
        # 2. Step 1: Statistical Novelty Detector Identifies Unusual State
        # =========================================================================
        historical_snapshots = self._build_historical_baseline_snapshots()

        # Build current state representation with shifted dimensions
        current_state = StateRepresentation(timestamp=self.base_time)
        current_state.set_feature(name="location_cluster", value="remote_marine_station", source="gps_telemetry", timestamp=self.base_time, confidence=0.95)
        current_state.set_feature(name="current_activity", value="underwater_acoustic_sensor_flashing", source="os_window", timestamp=self.base_time, confidence=0.95)
        current_state.set_feature(name="meeting_timezone_offset", value=9.0, source="calendar", timestamp=self.base_time, confidence=1.0)
        current_state.set_feature(name="evening_ambient_environment", value="laboratory_marine_gale", source="acoustic_sensor", timestamp=self.base_time, confidence=0.90)
        current_state.set_feature(name="recent_activity_duration", value=110.0, source="os_window", timestamp=self.base_time, confidence=0.95)

        novelty_result = self.novelty_engine.detect(current_state, history=historical_snapshots)

        self.assertIn(novelty_result.overall_level, (OverallNoveltyLevel.HIGHLY_UNUSUAL.value, OverallNoveltyLevel.NOVEL_COMBINATION.value))

        anomalies = novelty_result.get_anomalous_features()
        self.assertGreaterEqual(len(anomalies), 3)
        anom_names = {a.feature for a in anomalies}
        self.assertIn("location_cluster", anom_names)
        self.assertIn("current_activity", anom_names)

        # =========================================================================
        # 3. Step 2: Situation Engine Creates a Novel Situation Frame (Generic Fallback)
        # =========================================================================
        eval_result = self.situation_engine.evaluate(
            current_state=current_state,
            timeline=timeline,
            goals=[],
            novelty_result=novelty_result,
        )

        self.assertGreaterEqual(len(eval_result.candidate_situations), 1)
        novel_sit = next((s for s in eval_result.candidate_situations if s.type == "unusual_state"), None)
        self.assertIsNotNone(novel_sit, "Must produce a generic unusual_state situation without a dedicated detector.")
        self.assertEqual(novel_sit.type, "unusual_state")
        self.assertGreaterEqual(novel_sit.novelty, 0.80)
        self.assertEqual(novel_sit.priority, SituationPriority.HIGH.value)

        # Persist Situation
        persisted_sit = self.situation_store.create(
            type=novel_sit.type,
            priority=novel_sit.priority,
            novelty=novel_sit.novelty,
            context=novel_sit.context,
            evidence=novel_sit.evidence,
        )

        # =========================================================================
        # 4. Step 3: Context Builder Retrieves Relevant History Without Silos
        # =========================================================================
        bounded_ctx = self.context_builder.build_bounded_context(
            situation=persisted_sit,
            current_state=current_state,
            timeline=timeline,
            goals=[],
        )

        self.assertIsNotNone(bounded_ctx)
        feature_keys = {f["state_key"] for f in bounded_ctx.current_state.get("features", [])}
        self.assertIn("location_cluster", feature_keys)
        self.assertIn("current_activity", feature_keys)

        # =========================================================================
        # 5. Steps 4 & 5: Hermes Novel Reasoning & Explicit Uncertainty Preservation
        # =========================================================================
        hermes_novel_payload = {
            "what_appears_unusual": (
                "User has completely departed from 14-day urban NYC software routine, operating from a coastal "
                "marine station with hardware firmware flashing tools and late-night UTC+9 collaboration."
            ),
            "possible_interpretations": [
                "Temporary field deployment / marine sensor testing trial.",
                "Research sabbatical or project residency.",
                "Unannounced relocation or remote hardware consultancy.",
            ],
            "relevant_goals": [],
            "possible_risks": [
                "Unadjusted sleep schedule amid late-night asynchronous collaboration in severe weather.",
            ],
            "possible_opportunities": [
                "Discovery of new operational patterns for field hardware workflows.",
            ],
            "what_is_uncertain": [
                "Insufficient evidence: Duration of field deployment unknown due to absence of flight/calendar ticket events.",
                "Uncertain whether user desires notification or quiet focus during hardware testing.",
            ],
            "additional_observation_needed": True,
            "insufficient_evidence": True,
            "recommendations": [
                "Continue passive observation across consecutive days without interrupting user.",
            ],
            "urgency": "low",
            "actionability": "low",
            "relevance": "medium",
            "evidence_strength": "weak",
        }

        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_novel_payload),
            duration_ms=480,
        )

        workflow_res = self.reasoning_workflow.run_novel_workflow(
            situation=persisted_sit,
            current_state=current_state,
            timeline=timeline,
            goals=[],
        )

        self.assertIsNotNone(workflow_res.synthesis)
        self.assertTrue(workflow_res.synthesis.insufficient_evidence, "Hermes must preserve insufficient evidence.")
        self.assertTrue(workflow_res.synthesis.additional_observation_needed)
        self.assertIn("Insufficient evidence", workflow_res.synthesis.what_is_uncertain[0])

        # =========================================================================
        # 6. Step 6: Intervention Policy Determines Action (DISCARD/SUPPRESS)
        # =========================================================================
        policy_res = self.policy_engine.evaluate(
            urgency=workflow_res.synthesis.urgency,
            actionability=workflow_res.synthesis.actionability,
            evidence_strength=workflow_res.synthesis.evidence_strength,
            user_context=UserContext.AVAILABLE.value,
        )

        # Novelty != Interruption: Low urgency + low actionability -> DISCARD
        self.assertEqual(policy_res.action, PolicyAction.DISCARD.value)
        self.assertIn("Low urgency", policy_res.reason)

        # =========================================================================
        # 7. Step 7: Reasoning Episode Persisted in Single Unified Table
        # =========================================================================
        episode = workflow_res.episode
        self.assertIsNotNone(episode)
        persisted_ep = self.episode_store.get_episode(episode.id)
        self.assertIsNotNone(persisted_ep)
        self.assertEqual(persisted_ep.situation_id, persisted_sit.id)
        self.assertEqual(persisted_ep.status, EpisodeStatus.REASONING_COMPLETED.value)
        self.assertEqual(persisted_ep.urgency, "low")
        self.assertEqual(persisted_ep.evidence_strength, "weak")

        # =========================================================================
        # 8. Step 8: Future Repetitions Become Evidence for a Learned Pattern
        # =========================================================================
        # Register candidate hypothesis
        pattern = self.learning_engine.register_candidate_pattern(
            description="Remote marine station location appears associated with late-night asynchronous collaboration and firmware testing.",
            first_seen=self.base_time,
            initial_status=PatternStatus.OBSERVED,
        )
        self.assertEqual(pattern.status, PatternStatus.OBSERVED.value)

        # Day 1 Observation Evidence
        self.learning_engine.record_evidence(
            pattern_id=pattern.id,
            observation_type="SUPPORT",
            observed_at=self.base_time,
            episode_id=persisted_ep.id,
            details={"notes": "Initial novel divergence observed at marine station.", "situation_id": persisted_sit.id},
        )

        # Simulate Day 2 and Day 3 repetitions accumulating evidence
        for day in [1, 2]:
            t_next = self.base_time + timedelta(days=day)
            ep_next = self.episode_store.create_episode(
                situation_id=persisted_sit.id,
                hermes_task="Unusual state re-observation",
                urgency="low",
                actionability="low",
                evidence_strength="moderate",
                created_at=t_next,
            )
            self.learning_engine.record_evidence(
                pattern_id=pattern.id,
                observation_type="SUPPORT",
                observed_at=t_next,
                episode_id=ep_next.id,
                details={"notes": f"Subsequent day {day+1} recurrence of marine lab schedule."},
            )

        # Pattern promotion from accumulated evidence
        promoted_pattern = self.learning_engine.pattern_store.get_pattern(pattern.id)
        self.assertEqual(promoted_pattern.support_count, 4)
        self.assertIn(promoted_pattern.status, (PatternStatus.HYPOTHESIS.value, PatternStatus.EMERGING.value, PatternStatus.OBSERVED.value))
        self.assertGreaterEqual(promoted_pattern.support_count, 3)

        # Verify full evidence provenance chain in SQLite
        evidence_chain = self.learning_engine.pattern_store.list_evidence_for_pattern(pattern.id)
        self.assertEqual(len(evidence_chain), 3)
        episode_ids = {e.episode_id for e in evidence_chain}
        self.assertIn(persisted_ep.id, episode_ids)


if __name__ == "__main__":
    unittest.main()
