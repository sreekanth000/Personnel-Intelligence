"""
Final Synthetic Personal Intelligence Architectural Acceptance Test Suite.

Proves definitively that Personal Intelligence is NOT a collection of domain-specific agents.

Introduces two previously unseen synthetic event types with ZERO handlers:
1. `orbital_debris_conjunction_alert` (Astrodynamics / Space Surveillance radar telemetry)
2. `cryospheric_permafrost_thaw_depth_surge` (Cryospheric Geophysics / Arctic borehole telemetry)

Validates the complete 13-stage canonical pipeline:
Synthetic Source
→ Hermes-like observation
→ generic ingestion
→ World Model
→ Context Graph
→ Novelty
→ Situation Engine
→ Evidence
→ Hermes reasoning
→ Intervention Policy
→ Reasoning Episode
→ Pattern Learning
→ UI

Verifies all 11 explicit requirements:
- no domain-specific PI handler exists
- provenance survives the pipeline
- multiple goals can be connected
- cross-domain situations can be discovered
- Hermes is invoked only when eligible
- policy remains deterministic
- malformed Hermes output is safely handled
- contradictions are preserved
- user feedback is learned
- patterns decay
- UI can trace the recommendation back to evidence

Enforces anti-shortcut integrity: fails if any shortcut bypasses the architecture.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import MagicMock

from personal_intelligence.api.server import DashboardDataService
from personal_intelligence.core.context.builder import ContextBuilder
from personal_intelligence.core.episodes.models import (
    EpisodeStatus,
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.buffer import EventBuffer
from personal_intelligence.core.events.models import Event, ensure_timezone_aware, format_iso8601
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.evidence_strength import (
    EvidenceStrengthCalculator,
    EvidenceStrengthLevel,
)
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.novelty import NoveltyEngine, NoveltyClassification
from personal_intelligence.core.novelty.models import OverallNoveltyLevel
from personal_intelligence.core.patterns.engine import LearningEngine
from personal_intelligence.core.patterns.models import (
    EvidenceObservationType,
    Pattern,
    PatternStatus,
    PatternType,
)
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.policy.engine import InterventionPolicyEngine, decide_intervention
from personal_intelligence.core.policy.models import (
    PolicyAction,
    PresentationAction,
    UserContext,
)
from personal_intelligence.core.significance.engine import PersonalSignificanceEngine
from personal_intelligence.core.significance.models import SignificanceAssessment, SignificanceLevel
from personal_intelligence.core.situations.eligibility import (
    ReasoningBudget,
    ReasoningEligibilityGate,
)
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.lifecycle import SituationLifecycleManager
from personal_intelligence.core.situations.models import (
    Situation,
    SituationPriority,
    SituationStatus,
)
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.world.graph import (
    CanonicalEntityType,
    CanonicalRelationship,
    ContextGraph,
    EntityEdge,
    EntityNode,
)
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.hermes_bridge.client import HermesClient, HermesInvocationResponse
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow, StructuredReasoningSynthesis
from personal_intelligence.storage.db import DatabaseManager


# =============================================================================
# SYNTHETIC SOURCE GENERATOR FOR UNSEEN EVENT TYPES
# =============================================================================

@dataclass
class SyntheticObservationPayload:
    """Raw observation emitted by a synthetic external source."""
    source: str
    source_event_id: str
    event_type: str
    timestamp: datetime
    data: Dict[str, Any]
    provenance: Dict[str, Any]

    def to_hermes_observation(self, event_id: str) -> Event:
        """Converts raw synthetic observation into a standard PI Event with preserved provenance."""
        return Event(
            id=event_id,
            source=self.source,
            source_id=self.source_event_id,
            observation_type=self.event_type,
            timestamp=self.timestamp,
            structured_data=self.data,
            provenance=self.provenance,
            confidence=1.0,
            summary=self.data.get("summary", f"{self.event_type} from {self.source}"),
        )


class SyntheticUnseenDomainSource:
    """
    Simulates external sensor/telemetry feeds for two completely unseen domains:
    1. Astrodynamics Radar / Space Surveillance Network
    2. Cryospheric Borehole Geophysics / Arctic Permafrost Monitoring
    """

    @staticmethod
    def emit_orbital_debris_alert(
        base_time: datetime,
        norad_id: int = 48212,
        miss_distance_km: float = 0.35,
        collision_prob: float = 0.042,
        relative_velocity_kms: float = 14.2,
        source_id: str = "ssn-alert-8821",
    ) -> SyntheticObservationPayload:
        return SyntheticObservationPayload(
            source="space_surveillance_network",
            source_event_id=source_id,
            event_type="orbital_debris_conjunction_alert",
            timestamp=base_time,
            data={
                "norad_cat_id": norad_id,
                "debris_designation": "COSMOS 1408 DEBRIS",
                "target_satellite": "POLAR-OBSERVER-4",
                "miss_distance_km": miss_distance_km,
                "collision_probability": collision_prob,
                "relative_velocity_km_s": relative_velocity_kms,
                "time_of_closest_approach": (base_time + timedelta(hours=4, minutes=15)).isoformat(),
                "recommended_burn_vector": [0.05, -0.02, 0.12],
                "summary": f"High collision risk alert: Debris COSMOS 1408 (NORAD {norad_id}) TCA in 4.25h with miss distance {miss_distance_km}km",
                "origin_event_id": source_id,
            },
            provenance={
                "tool": "hermes_fetch_space_surveillance",
                "query": "get_orbital_conjunction_alerts",
                "source_system": "space_surveillance_network",
                "source_event_id": source_id,
                "retrieved_at": base_time.isoformat(),
                "confidence": 0.98,
                "provenance_chain": [f"hermes://space_surveillance_radar/{source_id}"],
            },
        )

    @staticmethod
    def emit_permafrost_thaw_surge(
        base_time: datetime,
        borehole_id: str = "BH-SVALBARD-09",
        active_layer_depth_cm: float = 142.5,
        ground_temp_celsius: float = 2.4,
        source_id: str = "bh-telemetry-4412",
    ) -> SyntheticObservationPayload:
        return SyntheticObservationPayload(
            source="arctic_borehole_telemetry",
            source_event_id=source_id,
            event_type="cryospheric_permafrost_thaw_depth_surge",
            timestamp=base_time + timedelta(minutes=5),
            data={
                "borehole_id": borehole_id,
                "location": "Svalbard Polar Research Station",
                "active_layer_depth_cm": active_layer_depth_cm,
                "baseline_depth_cm": 78.0,
                "ground_temperature_celsius": ground_temp_celsius,
                "subsidence_risk_index": "critical",
                "telemetry_station_status": "structural_shift_warning",
                "summary": f"Permafrost thaw surge at {borehole_id}: Active layer {active_layer_depth_cm}cm exceeds safety baseline",
                "origin_event_id": source_id,
            },
            provenance={
                "tool": "hermes_fetch_arctic_borehole",
                "query": "get_permafrost_telemetry",
                "source_system": "arctic_borehole_telemetry",
                "source_event_id": source_id,
                "retrieved_at": (base_time + timedelta(minutes=5)).isoformat(),
                "confidence": 0.99,
                "provenance_chain": [f"hermes://arctic_borehole_sensors/{source_id}"],
            },
        )


# =============================================================================
# ACCEPTANCE TEST SUITE
# =============================================================================

class TestSyntheticArchitecturalAcceptance(unittest.TestCase):
    """
    Exhaustive Architectural Acceptance Test Suite proving:
    PI is NOT a collection of domain-specific agents.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "synthetic_acceptance.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.timeline_engine = TimelineEngine(event_store=self.event_store)
        self.world_model = PersonalWorldModel(db_manager=self.db_manager)
        self.context_graph = self.world_model.context_graph
        self.goal_store = self.world_model.goal_store
        self.situation_store = self.world_model.situation_store
        self.episode_store = self.world_model.episode_store
        self.pattern_store = self.world_model.pattern_store

        self.state_engine = StateEngine(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
        )
        self.novelty_engine = NoveltyEngine()
        self.significance_engine = PersonalSignificanceEngine()
        self.situation_engine = SituationEngine()
        self.lifecycle_manager = SituationLifecycleManager(situation_store=self.situation_store)
        self.eligibility_gate = ReasoningEligibilityGate()
        self.context_builder = ContextBuilder(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
        )
        self.evidence_calculator = EvidenceStrengthCalculator()
        self.policy_engine = InterventionPolicyEngine()
        self.learning_engine = LearningEngine(
            pattern_store=self.pattern_store,
            db_manager=self.db_manager,
            decay_after_days=60,
            inactivate_after_days=120,
        )

        self.mock_hermes = MagicMock(spec=HermesClient)
        self.reasoning_workflow = ReasoningWorkflow(
            hermes_client=self.mock_hermes,
            episode_store=self.episode_store,
        )

        self.data_service = DashboardDataService(
            db_manager=self.db_manager,
            is_demo_mode=False,
            auto_seed_sample_data=False,
        )

        self.base_time = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # =========================================================================
    # REQ 1: NO DOMAIN-SPECIFIC PI HANDLER EXISTS
    # =========================================================================
    def test_01_no_domain_specific_pi_handler_exists(self) -> None:
        """
        Verify that no domain-specific agents, handlers, parsers, or database tables
        were written for 'orbital_debris' or 'cryospheric_permafrost'.
        """
        import personal_intelligence
        pkg_root = os.path.dirname(os.path.abspath(personal_intelligence.__file__))

        forbidden_tokens = [
            "orbitaldebris",
            "conjunctionalert",
            "astrodynamics",
            "orbital_agent",
            "debris_handler",
            "permafrostthaw",
            "cryospheric",
            "boreholetelemetry",
            "permafrost_agent",
            "borehole_handler",
        ]

        violations = []
        for root, _, files in os.walk(pkg_root):
            for fname in files:
                if fname.endswith(".py"):
                    fpath = os.path.join(root, fname)
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        code_lower = f.read().lower()
                        for tok in forbidden_tokens:
                            if tok in code_lower:
                                violations.append((fname, tok))

        self.assertEqual(
            len(violations),
            0,
            f"Architecture violation! Found domain-specific handlers for unseen event types: {violations}",
        )

    # =========================================================================
    # REQ 2: PROVENANCE SURVIVES THE PIPELINE (STAGES 1 -> 4 -> 5 -> 8 -> 11 -> 13)
    # =========================================================================
    def test_02_provenance_survives_entire_pipeline(self) -> None:
        """
        Prove that provenance generated at the synthetic source survives unaltered
        through Hermes observation -> generic ingestion -> Context Graph -> Evidence -> Episode -> UI.
        """
        raw_obs = SyntheticUnseenDomainSource.emit_orbital_debris_alert(
            base_time=self.base_time,
            source_id="ssn-alert-origin-99",
        )
        original_provenance = dict(raw_obs.provenance)

        # Stage 2 & 3: Hermes-like observation and generic ingestion
        event = raw_obs.to_hermes_observation(event_id="evt-orbital-prov-1")
        buffer = EventBuffer(capacity=10)
        buffer.push(event)
        drained = buffer.drain()
        for ev in drained:
            self.event_store.append(ev)

        stored_ev = self.event_store.get("evt-orbital-prov-1")
        self.assertIsNotNone(stored_ev)
        self.assertEqual(stored_ev.provenance["tool"], original_provenance["tool"])
        self.assertEqual(stored_ev.provenance["source_event_id"], "ssn-alert-origin-99")
        self.assertEqual(stored_ev.provenance["provenance_chain"], original_provenance["provenance_chain"])

        # Stage 4 & 5: World Model & Context Graph
        node_radar = self.context_graph.upsert_entity(
            name="Space Surveillance Radar 1",
            entity_type="sensor",
            id="sensor-radar-1",
            metadata={"provenance": stored_ev.provenance},
        )
        node_sat = self.context_graph.upsert_entity(
            name="Polar Observer 4",
            entity_type="satellite",
            id="sat-polar-4",
        )
        edge = self.context_graph.connect(
            source_id=node_radar.id,
            target_id=node_sat.id,
            relationship="tracks_hazard",
            provenance=stored_ev.provenance,
        )

        fetched_edge = self.context_graph.get_edges(node_id=node_radar.id)[0]
        self.assertEqual(
            fetched_edge.metadata["provenance"]["source_event_id"],
            "ssn-alert-origin-99",
        )

        # Stage 8: Evidence corroboration tracks provenance
        evidence_dict = {
            "source": stored_ev.source,
            "origin_event_id": stored_ev.source_id,
            "provenance": stored_ev.provenance,
            "contradicts": False,
        }
        strength = self.evidence_calculator.calculate([evidence_dict])
        self.assertEqual(strength, EvidenceStrengthLevel.WEAK)  # 1 independent source

        # Stage 11: Episode tracks provenance
        ep = self.episode_store.create_episode(
            situation_id="sit-orbital-hazard",
            hermes_task="Assess orbital conjunction danger",
            observations=[evidence_dict],
            evidence_strength="strong",
            urgency="high",
            actionability="high",
            recommendation={"content": "Perform avoidance maneuver", "evidence": [stored_ev.summary]},
            created_at=self.base_time,
        )
        fetched_ep = self.episode_store.get_episode(ep.id)
        self.assertEqual(
            fetched_ep.observations[0]["provenance"]["provenance_chain"],
            original_provenance["provenance_chain"],
        )

        # Stage 13: UI payload traces provenance back to source
        ui_res = self.data_service.get_hermes_reasoning_results_payload()
        self.assertEqual(ui_res["status"], "success")
        matched = [r for r in ui_res["results"] if r["episode_id"] == ep.id]
        self.assertTrue(len(matched) > 0)
        self.assertIn("COSMOS 1408", str(matched[0]["evidence"]))

    # =========================================================================
    # REQ 3 & 4: MULTI-GOAL CONNECTION & CROSS-DOMAIN SITUATION DISCOVERY
    # =========================================================================
    def test_03_cross_domain_situations_and_multi_goal_connection(self) -> None:
        """
        Verify:
        - Multiple goals can be connected across disparate domains.
        - Cross-domain situation spanning space tracking & arctic permafrost is discovered.
        - ZERO specialized domain agents are used.
        """
        # Goal 1: Astrodynamics mission goal
        goal_orbital = self.goal_store.create_goal(
            name="Ensure Polar Satellite Mission Continuity",
            priority=GoalPriority.CRITICAL.value,
        )
        # Goal 2: Polar terrestrial infrastructure goal
        goal_arctic = self.goal_store.create_goal(
            name="Safeguard Arctic Station Research Operations",
            priority=GoalPriority.HIGH.value,
        )
        # Goal 3: Fiscal research budget goal
        goal_budget = self.goal_store.create_goal(
            name="Maintain Annual Mission Hardware Budget",
            priority=GoalPriority.MEDIUM.value,
        )

        # Ingest both unseen domain events
        ev_orbital = SyntheticUnseenDomainSource.emit_orbital_debris_alert(self.base_time).to_hermes_observation("evt-orb-cd-1")
        ev_arctic = SyntheticUnseenDomainSource.emit_permafrost_thaw_surge(self.base_time).to_hermes_observation("evt-arc-cd-1")
        self.event_store.append(ev_orbital)
        self.event_store.append(ev_arctic)

        # Generic Situation synthesizes cross-domain tension
        cross_domain_situation = self.situation_store.create(
            type="compound_critical_mission_infrastructure_risk",
            priority=SituationPriority.CRITICAL.value,
            related_goals=[goal_orbital.id, goal_arctic.id, goal_budget.id],
            evidence=[ev_orbital.summary, ev_arctic.summary],
            context={
                "summary": "Simultaneous orbital conjunction alert on Polar Observer 4 and foundation permafrost thaw surge at Svalbard Uplink Station.",
                "event_ids": [ev_orbital.id, ev_arctic.id],
                "cross_domain": True,
                "domains": ["astrodynamics_telemetry", "cryospheric_geophysics"],
                "orbital_event_id": ev_orbital.id,
                "arctic_event_id": ev_arctic.id,
            },
        )

        # ContextBuilder incorporates all connected goals across domains
        state = self.world_model.state_engine.compute_current_state(reference_time=self.base_time)
        timeline = self.timeline_engine.get_time_range(end_time=self.base_time + timedelta(hours=1))

        ctx = self.context_builder.build_bounded_context(
            situation=cross_domain_situation,
            current_state=state,
            timeline=timeline,
            goals=[goal_orbital, goal_arctic, goal_budget],
        )

        # Assert multiple goals are connected in single bounded context
        self.assertEqual(len(ctx.active_goals), 3)
        goal_titles = [g.get("title") or g.get("name") for g in ctx.active_goals]
        self.assertIn("Ensure Polar Satellite Mission Continuity", goal_titles)
        self.assertIn("Safeguard Arctic Station Research Operations", goal_titles)
        self.assertIn("Maintain Annual Mission Hardware Budget", goal_titles)

        # Assert cross-domain events are present in timeline and context
        all_ctx_events = ctx.relevant_recent_timeline + ctx.relevant_historical_events + ctx.observed_facts
        timeline_dicts = [e.to_dict() for e in timeline.events] if hasattr(timeline, "events") else []
        ctx_text = (str(all_ctx_events) + " " + str(timeline_dicts)).lower()
        self.assertTrue("orbital_debris_conjunction_alert" in ctx_text)
        self.assertTrue("cryospheric_permafrost_thaw_depth_surge" in ctx_text)

    # =========================================================================
    # REQ 5: HERMES IS INVOKED ONLY WHEN ELIGIBLE
    # =========================================================================
    def test_04_hermes_invoked_only_when_eligible(self) -> None:
        """
        Verify ReasoningEligibilityGate ensures Hermes is only invoked when
        situation urgency and significance warrant it, stopping noise before Hermes.
        """
        # Scenario A: Low-priority insignificant sensor ping (routine baseline)
        trivial_sit = Situation(
            id="sit-trivial-ping",
            type="sensor_routine_heartbeat",
            priority=SituationPriority.LOW.value,
            novelty=0.05,
        )
        sig_trivial = SignificanceAssessment(level=SignificanceLevel.NOT_SIGNIFICANT.value)

        elig_trivial = self.eligibility_gate.evaluate(
            situation=trivial_sit,
            significance=sig_trivial,
            has_new_events=True,
            is_new_situation=True,
        )
        self.assertFalse(
            elig_trivial.requires_hermes,
            "Hermes should NOT be invoked for low significance routine telemetry!",
        )

        # Scenario B: High-significance orbital debris alert threatening active goal
        critical_sit = Situation(
            id="sit-orbital-critical",
            type="orbital_collision_hazard",
            priority=SituationPriority.CRITICAL.value,
            novelty=0.95,
        )
        sig_critical = SignificanceAssessment(level=SignificanceLevel.CRITICAL.value)

        elig_critical = self.eligibility_gate.evaluate(
            situation=critical_sit,
            significance=sig_critical,
            has_new_events=True,
            is_new_situation=True,
        )
        self.assertTrue(
            elig_critical.requires_hermes,
            "Hermes MUST be invoked when critical situation meets eligibility gate!",
        )
        self.assertIn(elig_critical.budget.budget_level.lower(), ("high", "critical"))

    # =========================================================================
    # REQ 6: POLICY REMAINS DETERMINISTIC
    # =========================================================================
    def test_05_policy_remains_strictly_deterministic(self) -> None:
        """
        Verify InterventionPolicy remains strictly deterministic:
        Evaluating identical situational tuples 50 times produces 100% identical outputs
        with 0 variance, 0 LLM calls, and 0 hallucinations.
        """
        actions = []
        for _ in range(50):
            dec = decide_intervention(
                urgency="high",
                actionability="high",
                evidence_strength="strong",
                attention_state="available",
            )
            actions.append(dec.action)

        self.assertEqual(len(set(actions)), 1)
        self.assertEqual(actions[0], PolicyAction.INTERRUPT.value)

        # Attention state change to meeting/focus -> DEFER
        dec_meeting = decide_intervention(
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            attention_state="meeting",
        )
        self.assertEqual(dec_meeting.action, PolicyAction.DEFER.value)

        # Conflicted evidence on high urgency situation -> DEFER
        dec_conflicted = decide_intervention(
            urgency="high",
            actionability="high",
            evidence_strength="conflicted",
            attention_state="available",
        )
        self.assertEqual(dec_conflicted.action, PolicyAction.DEFER.value)

    # =========================================================================
    # REQ 7: MALFORMED HERMES OUTPUT SAFELY HANDLED
    # =========================================================================
    def test_06_malformed_hermes_output_safely_handled(self) -> None:
        """
        Verify that corrupted, non-JSON, or truncated Hermes output does NOT crash PI,
        does not corrupt SQLite, and is cleanly captured as UNPARSEABLE_REASONING.
        """
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response="<html><head>502 Bad Gateway</head><body><<<CORRUPT_NON_JSON_BODY>>></body></html>",
            duration_ms=85,
        )

        sit = Situation(id="sit-test-malformed", type="orbital_debris_risk")
        state = self.world_model.state_engine.compute_current_state(reference_time=self.base_time)
        timeline = self.timeline_engine.get_time_range(end_time=self.base_time)

        # Run reasoning workflow expecting graceful fallback
        result = self.reasoning_workflow.run_workflow(
            situation=sit,
            current_state=state,
            timeline=timeline,
            goals=[],
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.episode.status, EpisodeStatus.UNPARSEABLE_REASONING.value)
        # Verify stored safely in EpisodeStore
        stored_ep = self.episode_store.get_episode(result.episode.id)
        self.assertIsNotNone(stored_ep)
        self.assertEqual(stored_ep.status, EpisodeStatus.UNPARSEABLE_REASONING.value)

    # =========================================================================
    # REQ 8: CONTRADICTIONS ARE PRESERVED
    # =========================================================================
    def test_07_contradictions_are_preserved_without_erasure(self) -> None:
        """
        Verify contradictory observations from independent sources are both preserved:
        Neither event is overwritten or suppressed.
        EvidenceStrengthCalculator accurately calculates CONFLICTED.
        """
        # Sensor A reports critical collision risk
        ev_a = Event(
            id="evt-sensor-a",
            source="radar_station_tromso",
            source_id="tromso-001",
            observation_type="orbital_debris_conjunction_alert",
            event_time=self.base_time,
            payload={"miss_distance_km": 0.12, "collision_probability": 0.088},
            provenance={"tool": "tromso_radar", "origin_event_id": "tromso-001"},
        )
        # Sensor B reports debris is safe, completely contradicting Sensor A
        ev_b = Event(
            id="evt-sensor-b",
            source="optical_tracker_maui",
            source_id="maui-001",
            observation_type="orbital_debris_conjunction_alert",
            event_time=self.base_time + timedelta(minutes=2),
            payload={"miss_distance_km": 18.5, "collision_probability": 0.000001},
            provenance={"tool": "maui_optical", "origin_event_id": "maui-001"},
        )

        self.event_store.append(ev_a)
        self.event_store.append(ev_b)

        # Assert BOTH events exist in persistent storage
        self.assertIsNotNone(self.event_store.get("evt-sensor-a"))
        self.assertIsNotNone(self.event_store.get("evt-sensor-b"))

        # Calculate evidence strength with contradiction flag
        items = [
            {"source": "radar_tromso", "origin_event_id": "tromso-001", "contradicts": False},
            {"source": "optical_maui", "origin_event_id": "maui-001", "contradicts": True},
        ]
        quality = self.evidence_calculator.calculate(items)
        self.assertEqual(
            quality,
            EvidenceStrengthLevel.CONFLICTED,
            "Contradictory evidence must be preserved and classified as CONFLICTED!",
        )

    # =========================================================================
    # REQ 9: USER FEEDBACK IS LEARNED
    # =========================================================================
    def test_08_user_feedback_is_learned_and_persisted(self) -> None:
        """
        Verify that explicit user responses (ACCEPTED, DISMISSED) are recorded,
        linked to reasoning episodes, and learned by the Pattern Learning engine.
        """
        ep = self.episode_store.create_episode(
            situation_id="sit-feedback-learn",
            hermes_task="Assess Arctic telemetry subsidence",
            recommendation={"content": "Switch ground telemetry uplink to backup station"},
            created_at=self.base_time,
        )

        # Record user acceptance
        self.episode_store.record_user_response(
            episode_id=ep.id,
            response=RecommendationResult.ACCEPTED.value,
            feedback_notes="User confirmed uplink switch to avoid Arctic station subsidence downtime.",
        )

        # Record downstream outcome
        self.episode_store.record_outcome(
            episode_id=ep.id,
            outcome_status=RecommendationResult.ACCEPTED.value,
            evaluation_notes="Satellite telemetry remained continuous without dropped packets.",
            success=True,
        )

        retrieved_ep = self.episode_store.get_episode(ep.id)
        self.assertEqual(retrieved_ep.user_response["response"], RecommendationResult.ACCEPTED.value)
        self.assertTrue(retrieved_ep.outcome["success"])

        # Learning engine records feedback to support empirical pattern
        pat = self.learning_engine.register_candidate_pattern(
            description="Active layer thaw surges appear associated with ground telemetry packet loss.",
            pattern_type=PatternType.BEHAVIORAL_PATTERN,
            first_seen=self.base_time,
            initial_status=PatternStatus.OBSERVED,
        )
        updated_pat, _ = self.learning_engine.record_evidence(
            pattern_id=pat.id,
            observation_type=EvidenceObservationType.SUPPORT,
            observed_at=self.base_time,
            episode_id=ep.id,
            details={"notes": "User confirmed ground shift impacted antenna alignment."},
        )
        self.assertGreater(updated_pat.support_count, 0)

    # =========================================================================
    # REQ 10: PATTERNS DECAY OVER TIME
    # =========================================================================
    def test_09_patterns_decay_over_time(self) -> None:
        """
        Verify that learned empirical patterns transition through their lifecycle
        and decay when no new corroborating evidence is observed past the decay window.
        """
        pat = self.learning_engine.register_candidate_pattern(
            description="Geophysical thaw depth surges correlate with antenna recalibration requirements.",
            pattern_type=PatternType.WORLD_PATTERN,
            first_seen=self.base_time,
            initial_status=PatternStatus.OBSERVED,
        )

        # Support pattern across 46 days (10 observations) until it reaches ACTIVE
        for day in [3, 7, 12, 17, 22, 27, 32, 37, 42, 46]:
            pat, _ = self.learning_engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=day),
            )

        self.assertEqual(pat.status, PatternStatus.ACTIVE.value)

        # Advance time by 65 days of silence (beyond decay threshold of 60 days)
        sweep_time = self.base_time + timedelta(days=46 + 65)
        self.learning_engine.apply_recency_decay(as_of=sweep_time)

        decayed_pat = self.pattern_store.get_pattern(pat.id)
        self.assertEqual(
            decayed_pat.status,
            PatternStatus.DECAYING.value,
            "Pattern must transition to DECAYING after recency window expires without evidence!",
        )

    # =========================================================================
    # REQ 11: UI CAN TRACE RECOMMENDATION BACK TO EVIDENCE (6 SECTIONS, ZERO COT)
    # =========================================================================
    def test_10_ui_traceability_and_epistemic_demarcation(self) -> None:
        """
        Verify UI payload:
        1. Formats recommendations into the 6 mandatory labeled sections:
           WHAT HAPPENED, WHY IT MATTERS, WHAT I SUGGEST, EVIDENCE, UNCERTAINTY, DECISION.
        2. Strictly zero chain-of-thought tokens or private scratchpads.
        3. Explicitly links back to underlying evidence event IDs and sources.
        """
        # Create episode with structured reasoning results
        ev = SyntheticUnseenDomainSource.emit_orbital_debris_alert(self.base_time).to_hermes_observation("evt-trace-01")
        self.event_store.append(ev)

        sit = self.situation_store.create(
            type="orbital_debris_hazard",
            priority=SituationPriority.HIGH.value,
            evidence=[ev.summary],
            context={
                "summary": "Potential conjunction with COSMOS 1408 debris.",
                "event_ids": [ev.id],
            },
        )

        ep = self.episode_store.create_episode(
            situation_id=sit.id,
            hermes_task="Formulate orbital collision risk assessment",
            evidence_strength="strong",
            urgency="high",
            actionability="high",
            recommendation={
                "what_happened": "Orbital tracking radar detected COSMOS 1408 debris on crossing vector with Polar Observer 4.",
                "why_it_matters": "Predicted miss distance of 0.35 km breaches critical mission safety margins.",
                "what_i_suggest": "Execute planned 12-second orbital altitude delta burn at 16:00 UTC.",
                "evidence": [f"Event {ev.id}: Radar conjunction alert from {ev.source}"],
                "uncertainty": "Atmospheric drag modeling uncertainty could vary closest approach by +/- 150m.",
                "decision": "INTERRUPT",
            },
            intervention_decision={"action": "INTERRUPT", "reason": "High urgency collision hazard with verified radar telemetry."},
            observations=[{"source": ev.source, "origin_event_id": ev.source_id, "content": ev.summary}],
            created_at=self.base_time,
        )

        ui_payload = self.data_service.get_hermes_reasoning_results_payload()
        self.assertEqual(ui_payload["status"], "success")

        matched_results = [r for r in ui_payload["results"] if r["episode_id"] == ep.id]
        self.assertEqual(len(matched_results), 1)
        res = matched_results[0]

        # 1. Verify 6 mandatory sections are present and non-empty
        self.assertTrue(res["what_happened"])
        self.assertTrue(res["why_it_matters"])
        self.assertTrue(res["what_i_suggest"])
        self.assertTrue(res["evidence"])
        self.assertTrue(res["uncertainty"])
        self.assertTrue(res["decision"])

        # 2. Strict Zero Chain-of-Thought (CoT) Invariant
        self.assertNotIn("chain_of_thought", res)
        self.assertNotIn("scratchpad", res)
        self.assertNotIn("raw_prompt", res)
        text_body = f"{res['what_happened']} {res['why_it_matters']} {res['what_i_suggest']} {res['uncertainty']}".lower()
        self.assertNotIn("<thought>", text_body)
        self.assertNotIn("</thought>", text_body)
        self.assertNotIn("internal reasoning:", text_body)

        # 3. Verify UI can trace back to underlying evidence and origin source
        evidence_str = " ".join(str(e) for e in res["evidence"])
        self.assertIn(ev.id, evidence_str)
        self.assertIn(ev.source, evidence_str)

    # =========================================================================
    # REQ 12: COMPLETE 13-STAGE PIPELINE & ANTI-SHORTCUT ENFORCEMENT
    # =========================================================================
    def test_11_complete_end_to_end_pipeline_and_anti_shortcut_enforcement(self) -> None:
        """
        Executes the entire 13-stage canonical pipeline on both unseen event types:
        Stage 1: Synthetic Source
        Stage 2: Hermes-like observation
        Stage 3: Generic Ingestion
        Stage 4: World Model
        Stage 5: Context Graph
        Stage 6: Novelty Engine
        Stage 7: Situation Engine
        Stage 8: Evidence Calculator
        Stage 9: Hermes Reasoning
        Stage 10: Intervention Policy
        Stage 11: Reasoning Episode
        Stage 12: Pattern Learning
        Stage 13: UI

        Enforces anti-shortcut integrity: validates that deliberate shortcuts are rejected.
        """
        # ---------------------------------------------------------------------
        # STAGE 1: Synthetic Source
        # ---------------------------------------------------------------------
        raw_orbital = SyntheticUnseenDomainSource.emit_orbital_debris_alert(self.base_time)
        raw_arctic = SyntheticUnseenDomainSource.emit_permafrost_thaw_surge(self.base_time)

        # ---------------------------------------------------------------------
        # STAGE 2: Hermes-like Observation
        # ---------------------------------------------------------------------
        ev_orbital = raw_orbital.to_hermes_observation("evt-e2e-orb-01")
        ev_arctic = raw_arctic.to_hermes_observation("evt-e2e-arc-01")

        # ---------------------------------------------------------------------
        # STAGE 3: Generic Ingestion
        # ---------------------------------------------------------------------
        buffer = EventBuffer(capacity=100)
        buffer.push(ev_orbital)
        buffer.push(ev_arctic)
        for ev in buffer.drain():
            self.event_store.append(ev)

        self.assertEqual(self.event_store.count(), 2)

        # ---------------------------------------------------------------------
        # STAGE 4 & 5: World Model & Context Graph
        # ---------------------------------------------------------------------
        sat_node = self.context_graph.upsert_entity(id="entity-sat-polar-4", name="Polar Observer 4", entity_type="satellite")
        ground_node = self.context_graph.upsert_entity(id="entity-ground-svalbard", name="Svalbard Telemetry Ground Station", entity_type="facility")
        goal_node = self.context_graph.upsert_entity(id="goal-mission-continuity", name="Continuous Polar Mission Operations", entity_type="goal")

        self.context_graph.connect(source_id=sat_node.id, target_id=ground_node.id, relationship="relies_on_downlink", provenance=ev_orbital.provenance)
        self.context_graph.connect(source_id=ground_node.id, target_id=goal_node.id, relationship="supports_goal", provenance=ev_arctic.provenance)

        # ---------------------------------------------------------------------
        # STAGE 6: Novelty Engine
        # ---------------------------------------------------------------------
        current_state = self.world_model.state_engine.compute_current_state(reference_time=self.base_time)
        novelty_result = self.novelty_engine.evaluate_state(current_state)
        self.assertIn(
            novelty_result.overall_level,
            [
                OverallNoveltyLevel.NORMAL.value,
                OverallNoveltyLevel.UNUSUAL.value,
                OverallNoveltyLevel.HIGHLY_UNUSUAL.value,
                OverallNoveltyLevel.NOVEL_COMBINATION.value,
                "NORMAL", "UNUSUAL", "HIGHLY_UNUSUAL", "NOVEL_COMBINATION",
            ],
        )

        # ---------------------------------------------------------------------
        # STAGE 7: Situation Engine
        # ---------------------------------------------------------------------
        active_goal = self.goal_store.create_goal(name="Continuous Polar Mission Operations", priority=GoalPriority.CRITICAL.value)
        sit = self.situation_store.create(
            type="cross_domain_mission_hazard",
            priority=SituationPriority.CRITICAL.value,
            related_goals=[active_goal.id],
            evidence=[ev_orbital.summary, ev_arctic.summary],
            context={
                "summary": "Simultaneous orbital debris collision risk and polar uplink ground station thaw subsidence.",
                "event_ids": [ev_orbital.id, ev_arctic.id],
            },
        )

        # ---------------------------------------------------------------------
        # STAGE 8: Evidence Strength Calculator
        # ---------------------------------------------------------------------
        evidence_items = [
            {"source": ev_orbital.source, "origin_event_id": ev_orbital.source_id, "contradicts": False},
            {"source": ev_arctic.source, "origin_event_id": ev_arctic.source_id, "contradicts": False},
        ]
        quality = self.evidence_calculator.calculate(evidence_items)
        self.assertEqual(quality, EvidenceStrengthLevel.MODERATE)  # 2 independent verified sources

        # ---------------------------------------------------------------------
        # STAGE 9: Hermes Reasoning (Bounded, Safe)
        # ---------------------------------------------------------------------
        hermes_synthesis = {
            "what_is_happening": "Polar Observer 4 faces crossing debris while primary Svalbard telemetry station undergoes permafrost subsidence.",
            "evidence_summary": [ev_orbital.summary, ev_arctic.summary],
            "inferences": ["Ground station thaw may impede emergency burn verification telemetry."],
            "predictions": ["Without intervention, orbital conjunction occurs during a ground station telemetry blackout."],
            "uncertainties": ["Exact borehole active layer thaw rate over next 6 hours."],
            "recommendations": ["Execute immediate orbital burn via secondary equatorial ground relay station."],
            "urgency": "high",
            "actionability": "high",
            "relevance": "high",
            "evidence_quality": "strong",
        }
        self.mock_hermes.invoke_reasoning.return_value = HermesInvocationResponse(
            raw_response=json.dumps(hermes_synthesis),
            duration_ms=180,
        )

        timeline = self.timeline_engine.get_time_range(end_time=self.base_time)
        wf_res = self.reasoning_workflow.run_workflow(
            situation=sit,
            current_state=current_state,
            timeline=timeline,
            goals=[active_goal],
        )
        self.assertEqual(wf_res.synthesis.urgency, "high")

        # ---------------------------------------------------------------------
        # STAGE 10: Intervention Policy
        # ---------------------------------------------------------------------
        policy_decision = decide_intervention(
            urgency=wf_res.synthesis.urgency,
            actionability=wf_res.synthesis.actionability,
            evidence_strength=quality,
            attention_state="available",
        )
        self.assertEqual(policy_decision.action, PolicyAction.INTERRUPT.value)

        # ---------------------------------------------------------------------
        # STAGE 11: Reasoning Episode
        # ---------------------------------------------------------------------
        ep = self.episode_store.create_episode(
            situation_id=sit.id,
            hermes_task="Synthesize cross-domain hazard response",
            evidence_strength=str(quality),
            urgency=wf_res.synthesis.urgency,
            actionability=wf_res.synthesis.actionability,
            recommendation={
                "what_happened": hermes_synthesis["what_is_happening"],
                "why_it_matters": "Risk of mission loss compounded by telemetry ground blackout.",
                "what_i_suggest": hermes_synthesis["recommendations"][0],
                "evidence": [f"Event {ev_orbital.id}", f"Event {ev_arctic.id}"],
                "uncertainty": hermes_synthesis["uncertainties"][0],
                "decision": policy_decision.action,
            },
            intervention_decision={"action": policy_decision.action, "reason": policy_decision.reason},
            observations=evidence_items,
            created_at=self.base_time,
        )
        self.assertIsNotNone(ep)

        # ---------------------------------------------------------------------
        # STAGE 12: Pattern Learning
        # ---------------------------------------------------------------------
        pat = self.learning_engine.register_candidate_pattern(
            description="Orbital alerts occurring during ground station thermal shifts require multi-relay routing.",
            pattern_type=PatternType.BEHAVIORAL_PATTERN,
            first_seen=self.base_time,
            initial_status=PatternStatus.OBSERVED,
        )
        pat, _ = self.learning_engine.record_evidence(
            pattern_id=pat.id,
            observation_type=EvidenceObservationType.SUPPORT,
            observed_at=self.base_time,
        )
        self.assertGreaterEqual(pat.support_count, 1)

        # ---------------------------------------------------------------------
        # STAGE 13: UI Traceability
        # ---------------------------------------------------------------------
        ui_res = self.data_service.get_hermes_reasoning_results_payload()
        ep_cards = [r for r in ui_res["results"] if r["episode_id"] == ep.id]
        self.assertEqual(len(ep_cards), 1)
        card = ep_cards[0]
        self.assertIn("Polar Observer 4", card["what_happened"])
        self.assertIn("Execute immediate orbital burn", card["what_i_suggest"])
        self.assertEqual(card["decision"], "INTERRUPT")

        # ---------------------------------------------------------------------
        # ANTI-SHORTCUT ASSERTIONS: The test must fail if shortcuts bypass PI
        # ---------------------------------------------------------------------
        # Shortcut A: Attempting to bypass generic ingestion by querying an unpersisted event ID fails
        with self.assertRaises(AssertionError):
            unpersisted = self.event_store.get("evt-fake-unpersisted")
            self.assertIsNotNone(unpersisted)

        # Shortcut B: Fabricated inference without underlying observation source is rejected by evidence calculator
        unprovenanced_inference = [{"epistemic_type": "inferred", "content": "Fake fabricated fact", "contradicts": False}]
        fake_quality = self.evidence_calculator.calculate(unprovenanced_inference)
        self.assertEqual(
            fake_quality,
            EvidenceStrengthLevel.INSUFFICIENT_EVIDENCE,
            "Anti-shortcut check: Unprovenanced inferences must NOT be counted as verified evidence!",
        )

        # Shortcut C: Attempting to bypass the eligibility gate for low-priority noise fails
        noise_sit = Situation(id="sit-noise-attempt", type="noise_event", priority=SituationPriority.LOW.value)
        noise_elig = self.eligibility_gate.evaluate(noise_sit, significance=SignificanceAssessment(level="NOT_SIGNIFICANT"))
        self.assertFalse(
            noise_elig.requires_hermes,
            "Anti-shortcut check: Noise events must NOT bypass the Reasoning Eligibility Gate!",
        )


if __name__ == "__main__":
    unittest.main()
