"""
Personal Intelligence Evaluation Loop.

Unified, idempotent coordinator for the Personal Intelligence 19-stage canonical V1 sequence:
1. OBSERVE (ObservationManager & EventBuffer ingest raw external observations)
2. NORMALIZE (Event validation, schema normalization, and provenance assignment)
3. TIMELINE (TimelineEngine chronological indexing and interval tracking)
4. PERSONAL WORLD MODEL (PersonalWorldModel state, goal, and entity graph sync)
5. CURRENT STATE (StateEngine point-in-time state & AttentionDetector)
6. WHAT CHANGED (WhatChangedAnalyzer structured delta detection)
7. NOVELTY (NoveltyEngine statistical anomaly & divergence detection)
8. PERSONAL SIGNIFICANCE (PersonalSignificanceEngine priority & impact scoring)
9. SITUATION DISCOVERY (SituationEngine candidate generation & lifecycle tracking)
10. REASONING ELIGIBILITY (ReasoningEligibilityGate budget & gatekeeper)
11. BOUNDED CONTEXT (ContextBuilder epistemic framing and boundary enforcement)
12. HERMES REASONING (HermesClient & ReasoningWorkflow execution)
13. EVIDENCE EVALUATION (EvidenceStrengthCalculator deterministic corroboration)
14. RECOMMENDATION (Structured recommendation formulation)
15. INTERVENTION POLICY (InterventionPolicyEngine delivery & quota governance)
16. USER DECISION (User interaction, decision, and feedback capture)
17. OUTCOME (Outcome tracking & longitudinal feedback audit)
18. PATTERN LEARNING (LearningEngine empirical recurrence & pattern lifecycle)
19. MEMORY MAINTENANCE (MemoryMaintenanceJob deterministic retention & consolidation)

Principle:
  SIMPLE DETERMINISTIC SYSTEM + HERMES REASONING + LONGITUDINAL MEMORY
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from personal_intelligence.core.activity.stream import ActivityStream
from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    OutcomeRecord,
    ReasoningEpisode,
    RecommendationResult,
    UserResponseRecord,
)
from personal_intelligence.core.events.buffer import EventBuffer
from personal_intelligence.core.events.models import (
    Event,
    EventBatch,
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.evidence_strength import EvidenceStrengthCalculator
from personal_intelligence.core.goals import Goal, GoalStore
from personal_intelligence.core.novelty import NoveltyEngine, NoveltyResult
from personal_intelligence.core.policy.engine import InterventionPolicyEngine
from personal_intelligence.core.policy.models import (
    PolicyAction,
    PolicyEvaluationResult,
    UserContext,
)
from personal_intelligence.core.significance import (
    PersonalSignificanceEngine,
    SignificanceAssessment,
    SignificanceLevel,
)
from personal_intelligence.core.situations.eligibility import (
    ReasoningBudget,
    ReasoningEligibility,
    ReasoningEligibilityGate,
    ReasoningEligibilityResult,
)
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.lifecycle import SituationLifecycleManager
from personal_intelligence.core.situations.models import (
    Situation,
    SituationPriority,
    SituationStatus,
)
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.attention_detector import AttentionDetector
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.core.patterns import (
    LearningEngine,
    PatternStore,
)
from personal_intelligence.core.world.changes import WhatChangedAnalyzer
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.hermes_bridge.client import HermesClient
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class EarlyExitReason(str, Enum):
    """
    Auditable reason codes for evaluation stops and non-reasoning paths.
    """
    NOT_SIGNIFICANT = "NOT_SIGNIFICANT"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"
    ALREADY_EVALUATED = "ALREADY_EVALUATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_ACTIONABILITY = "NO_ACTIONABILITY"
    NO_GOAL_RELEVANCE = "NO_GOAL_RELEVANCE"
    DEFERRED = "DEFERRED"
    HERMES_NOT_REQUIRED = "HERMES_NOT_REQUIRED"
    CLEARED = "CLEARED"


@dataclass
class EarlyExitRecord:
    """Structured record of an auditable evaluation early exit."""
    situation_id: str
    reason_code: str
    details: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "situation_id": self.situation_id,
            "reason_code": self.reason_code,
            "details": self.details,
            "timestamp": format_iso8601(self.timestamp),
        }


@dataclass
class EvaluationLoopResult:
    """Complete summary of an evaluation cycle execution."""
    timestamp: datetime
    events_processed_count: int
    current_state: StateRepresentation
    timeline: Timeline
    active_goals: List[Goal]
    novelty_result: Optional[NoveltyResult]
    active_situations: List[Situation]
    candidate_situations: List[Situation]
    situations_evaluated: List[Situation]
    episodes_created: List[ReasoningEpisode]
    intervention_decisions: Dict[str, PolicyEvaluationResult]
    actions_decided: List[Tuple[str, str]]
    scheduled_follow_ups: List[Tuple[str, datetime]]
    learned_patterns: Optional[Dict[str, Any]] = None
    attention_state: Optional[str] = None
    significance_assessments: Optional[Dict[str, SignificanceAssessment]] = None
    eligibility_decisions: Optional[Dict[str, ReasoningEligibilityResult]] = None
    early_exits: List[EarlyExitRecord] = field(default_factory=list)
    reason_codes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes cycle results into dictionary format."""
        novelty_score = 0.0
        if self.novelty_result:
            if hasattr(self.novelty_result, "score"):
                novelty_score = float(self.novelty_result.score)
            elif self.novelty_result.overall_level != "NORMAL":
                novelty_score = 1.0
        return {
            "timestamp": format_iso8601(self.timestamp),
            "events_processed_count": self.events_processed_count,
            "attention_state": self.attention_state,
            "novelty_score": novelty_score,
            "active_situations_count": len(self.active_situations),
            "episodes_created_count": len(self.episodes_created),
            "actions": [{"situation_id": sid, "action": act} for sid, act in self.actions_decided],
            "scheduled_follow_ups": [{"situation_id": sid, "next_eval": format_iso8601(dt)} for sid, dt in self.scheduled_follow_ups],
            "learned_patterns_count": sum(len(v) for v in self.learned_patterns.values()) if self.learned_patterns else 0,
            "early_exits": [ex.to_dict() for ex in self.early_exits],
            "reason_codes": self.reason_codes,
        }


class PersonalIntelligenceEvaluationLoop:
    """
    Unified coordinator for the Personal Intelligence 25-step canonical sequence.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        event_store: Optional[EventStore] = None,
        event_buffer: Optional[EventBuffer] = None,
        state_engine: Optional[StateEngine] = None,
        timeline_engine: Optional[TimelineEngine] = None,
        goal_store: Optional[GoalStore] = None,
        novelty_engine: Optional[NoveltyEngine] = None,
        situation_store: Optional[SituationStore] = None,
        situation_engine: Optional[SituationEngine] = None,
        situation_lifecycle: Optional[SituationLifecycleManager] = None,
        context_builder: Optional[ContextBuilder] = None,
        hermes_client: Optional[HermesClient] = None,
        reasoning_workflow: Optional[ReasoningWorkflow] = None,
        episode_store: Optional[EpisodeStore] = None,
        policy_engine: Optional[InterventionPolicyEngine] = None,
        situation_investigator: Optional[Any] = None,
        pattern_store: Optional[PatternStore] = None,
        learning_engine: Optional[LearningEngine] = None,
        attention_detector: Optional[AttentionDetector] = None,
        significance_engine: Optional[PersonalSignificanceEngine] = None,
        eligibility_gate: Optional[ReasoningEligibilityGate] = None,
        evidence_calculator: Optional[EvidenceStrengthCalculator] = None,
        world_model: Optional[PersonalWorldModel] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

        self.event_store = event_store or EventStore(db_manager=self.db_manager)
        self.event_buffer = event_buffer or EventBuffer()
        self.timeline_engine = timeline_engine or TimelineEngine(event_store=self.event_store)
        self.goal_store = goal_store or GoalStore(db_manager=self.db_manager)
        self.state_engine = state_engine or StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.novelty_engine = novelty_engine or NoveltyEngine()
        self.situation_store = situation_store or SituationStore(db_manager=self.db_manager)
        self.situation_engine = situation_engine or SituationEngine()
        self.context_builder = context_builder or ContextBuilder(
            situation_store=self.situation_store,
            goal_store=self.goal_store,
        )
        self.situation_lifecycle = situation_lifecycle or SituationLifecycleManager(
            situation_store=self.situation_store,
            context_builder=self.context_builder,
            db_manager=self.db_manager,
        )
        self.hermes_client = hermes_client or HermesClient()
        self.episode_store = episode_store or EpisodeStore(db_manager=self.db_manager)
        self.reasoning_workflow = reasoning_workflow or ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=self.hermes_client,
        )
        self.policy_engine = policy_engine or InterventionPolicyEngine()
        if situation_investigator is None:
            from personal_intelligence.hermes_bridge.situation_investigation import SituationInvestigator
            self.situation_investigator = SituationInvestigator(
                event_store=self.event_store,
                situation_store=self.situation_store,
                episode_store=self.episode_store,
                hermes_client=self.hermes_client,
            )
        else:
            self.situation_investigator = situation_investigator
        self.pattern_store = pattern_store or PatternStore(db_manager=self.db_manager)

        self.learning_engine = learning_engine or LearningEngine(
            pattern_store=self.pattern_store,
            db_manager=self.db_manager,
        )

        self.attention_detector = attention_detector or AttentionDetector()
        self.significance_engine = significance_engine or PersonalSignificanceEngine()
        self.eligibility_gate = eligibility_gate or ReasoningEligibilityGate()
        self.evidence_calculator = evidence_calculator or EvidenceStrengthCalculator()
        self.world_model = world_model or PersonalWorldModel(db_manager=self.db_manager)
        self.what_changed_analyzer = WhatChangedAnalyzer(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            pattern_store=self.pattern_store,
            state_engine=self.state_engine,
            db_manager=self.db_manager,
        )

    def run_cycle(
        self,
        incoming_events: Optional[List[Event]] = None,
        user_context: Optional[str] = None,
        as_of: Optional[datetime] = None,
        already_notified_situations: Optional[Set[str]] = None,
        recently_dismissed_situations: Optional[Set[str]] = None,
        follow_up_delay_minutes: int = 60,
    ) -> EvaluationLoopResult:
        """
        Executes one complete idempotent evaluation cycle across the 25-step canonical sequence.
        """
        ref_dt = as_of if as_of is not None else datetime.now(timezone.utc)
        ref_dt = ensure_timezone_aware(ref_dt, "as_of")
        stream = ActivityStream.get_instance()

        early_exits: List[EarlyExitRecord] = []
        reason_codes: Dict[str, str] = {}

        # ---------------------------------------------------------
        # Step 1: Receive new observations
        # Step 2: Normalize observations
        # Step 3: Store observations with provenance
        # ---------------------------------------------------------
        events_to_process: List[Event] = []
        if incoming_events:
            events_to_process.extend(incoming_events)
        if self.event_buffer and self.event_buffer.size() > 0:
            events_to_process.extend(self.event_buffer.drain())

        # Normalize event times to timezone-aware UTC
        for ev in events_to_process:
            if ev.event_time:
                ev.event_time = ensure_timezone_aware(ev.event_time, "ev.event_time")
            if not ev.provenance:
                ev.provenance = {"source": ev.source, "recorded_at": format_iso8601(ref_dt)}

        if events_to_process:
            self.event_store.append_batch(EventBatch(events=events_to_process))
            for ev in events_to_process:
                summary = ev.payload.get("summary") or ev.payload.get("title") or ev.event_type if isinstance(ev.payload, dict) else str(ev.payload)
                stream.emit(
                    event_type="observation_created",
                    summary=f"Observed {ev.source}: {summary}",
                    source=ev.source,
                )

        # ---------------------------------------------------------
        # Step 4: Update temporal world model
        # Step 5: Compute current state
        # ---------------------------------------------------------
        current_state = self.state_engine.compute_current_state(reference_time=ref_dt)
        timeline = self.timeline_engine.get_time_range(
            start_time=ref_dt - timedelta(hours=24),
            end_time=ref_dt + timedelta(hours=2),
        )
        active_goals = self.goal_store.list_active_goals()
        stream.emit(
            event_type="state_updated",
            summary=f"Recomputed longitudinal state representation ({len(current_state.features)} features)",
            source="state_engine",
        )

        # ---------------------------------------------------------
        # Step 6: Detect attention state
        # ---------------------------------------------------------
        recent_timeline_events = timeline.events if timeline else []
        attn_detection = self.attention_detector.detect(
            recent_events=recent_timeline_events,
            current_state=current_state,
            current_time=ref_dt,
        )
        detected_context = attn_detection.state
        active_user_context = user_context if user_context is not None else detected_context

        # ---------------------------------------------------------
        # Step 7: Detect meaningful changes
        # Step 8: Detect novelty
        # ---------------------------------------------------------
        changes = []
        try:
            changes = self.what_changed_analyzer.analyze_changes(as_of=ref_dt, window_hours=24)
            if changes:
                stream.emit(
                    event_type="change_detected",
                    summary=f"Detected {len(changes)} meaningful change(s)",
                    source="what_changed_analyzer",
                )
        except Exception as change_ex:
            logger.debug("WhatChangedAnalyzer note: %s", change_ex)

        novelty_result = self.novelty_engine.evaluate_state(current_state)
        if novelty_result and getattr(novelty_result, "overall_level", "NORMAL") != "NORMAL":
            level = getattr(novelty_result, "overall_level", "UNUSUAL")
            anomalies = novelty_result.get_anomalous_features() if hasattr(novelty_result, "get_anomalous_features") else []
            stream.emit(
                event_type="novelty_detected",
                summary=f"Novelty detected: {level} ({len(anomalies)} anomalous dimensions)",
                source="novelty_engine",
            )

        # ---------------------------------------------------------
        # Step 9: Evaluate personal significance
        # Step 10: Generate candidate situations
        # Step 11: Deduplicate/update situation lifecycle
        # ---------------------------------------------------------
        self.situation_lifecycle.expire_due_situations(as_of=ref_dt)
        due_situations = self.situation_store.get_due_reevaluations(as_of=ref_dt)
        active_situations = self.situation_store.list_active()

        situation_eval = self.situation_engine.evaluate(
            current_state=current_state,
            timeline=timeline,
            goals=active_goals,
            novelty_result=novelty_result,
        )

        # ---------------------------------------------------------
        # Step 12: Evaluate reasoning eligibility & auditable reason codes
        # ---------------------------------------------------------
        situations_needing_reasoning: List[Tuple[Situation, bool, ReasoningEligibilityResult]] = []
        significance_map: Dict[str, SignificanceAssessment] = {}
        eligibility_map: Dict[str, ReasoningEligibilityResult] = {}
        recent_episodes = self.episode_store.list_recent(limit=10) if hasattr(self.episode_store, "list_recent") else []

        for cand in situation_eval.candidate_situations:
            sit, is_new = self.situation_lifecycle.register_or_update(
                candidate_situation=cand,
                current_state=current_state,
                timeline=timeline,
                goals=active_goals,
            )

            # Step 9: Personal Significance Evaluation
            sig_assessment = self.significance_engine.evaluate_situation(
                situation_type=sit.type,
                situation_priority=sit.priority,
                evidence_count=len(sit.evidence),
                novelty_score=sit.novelty,
                has_information_gap=bool(sit.information_required),
                goals=active_goals,
                reference_time=ref_dt,
            )
            significance_map[sit.id] = sig_assessment
            stream.emit(
                event_type="significance_evaluated",
                summary=f"Significance evaluated: {sig_assessment.level.upper()} for {sit.type}",
                situation_id=sit.id,
                source="significance_engine",
            )

            if is_new:
                stream.emit(
                    event_type="situation_created",
                    summary=f"Created situation: {sit.type} ({sit.priority.upper() if sit.priority else 'MEDIUM'})",
                    situation_id=sit.id,
                    source="situation_engine",
                )

            # Early Exit Check 1: Insignificant Observation
            if sig_assessment.level == SignificanceLevel.NOT_SIGNIFICANT.value:
                early_exits.append(EarlyExitRecord(
                    situation_id=sit.id,
                    reason_code=EarlyExitReason.NOT_SIGNIFICANT.value,
                    details="Situation assessed as NOT_SIGNIFICANT; no reasoning warranted.",
                    timestamp=ref_dt,
                ))
                reason_codes[sit.id] = EarlyExitReason.NOT_SIGNIFICANT.value
                continue

            # Early Exit Check 2: No Goal Relevance
            if sig_assessment.goal_relevance == "none" and sig_assessment.commitment_relevance == "none" and sit.priority == SituationPriority.LOW.value:
                early_exits.append(EarlyExitRecord(
                    situation_id=sit.id,
                    reason_code=EarlyExitReason.NO_GOAL_RELEVANCE.value,
                    details="Situation has no relevance to active goals or commitments.",
                    timestamp=ref_dt,
                ))
                reason_codes[sit.id] = EarlyExitReason.NO_GOAL_RELEVANCE.value
                continue

            # Step 12: Evaluate Reasoning Eligibility
            elig_decision = self.eligibility_gate.evaluate(
                situation=sit,
                significance=sig_assessment,
                is_new_situation=is_new,
                has_new_events=bool(events_to_process),
                is_due_reevaluation=False,
                user_context=active_user_context,
                reasoning_history=recent_episodes,
                as_of=ref_dt,
            )
            eligibility_map[sit.id] = elig_decision
            stream.emit(
                event_type="reasoning_eligibility",
                summary=(
                    f"Reasoning eligibility: eligible={elig_decision.eligible} "
                    f"(Value: {elig_decision.estimated_reasoning_value.upper()}, Cost: {elig_decision.cost_class.upper()})"
                ),
                situation_id=sit.id,
                source="eligibility_gate",
            )

            if elig_decision.requires_hermes:
                situations_needing_reasoning.append((sit, is_new, elig_decision))
            else:
                reason_code = EarlyExitReason.HERMES_NOT_REQUIRED.value
                early_exits.append(EarlyExitRecord(
                    situation_id=sit.id,
                    reason_code=reason_code,
                    details=f"Eligibility determined as eligible={elig_decision.eligible}; Hermes reasoning skipped.",
                    timestamp=ref_dt,
                ))
                reason_codes[sit.id] = reason_code

        # Also evaluate scheduled due situations
        for due_sit in due_situations:
            if not any(s.id == due_sit.id for s, _, _ in situations_needing_reasoning):
                due_sig = self.significance_engine.evaluate_situation(
                    situation_type=due_sit.type,
                    situation_priority=due_sit.priority,
                    evidence_count=len(due_sit.evidence),
                    novelty_score=due_sit.novelty,
                    has_information_gap=bool(due_sit.information_required),
                    goals=active_goals,
                    reference_time=ref_dt,
                )
                significance_map[due_sit.id] = due_sig
                due_elig = self.eligibility_gate.evaluate(
                    situation=due_sit,
                    significance=due_sig,
                    is_new_situation=False,
                    has_new_events=bool(events_to_process),
                    is_due_reevaluation=True,
                    user_context=active_user_context,
                    reasoning_history=recent_episodes,
                    as_of=ref_dt,
                )
                eligibility_map[due_sit.id] = due_elig
                if due_elig.requires_hermes:
                    situations_needing_reasoning.append((due_sit, False, due_elig))
                else:
                    reason_codes[due_sit.id] = EarlyExitReason.HERMES_NOT_REQUIRED.value

        # ---------------------------------------------------------
        # Steps 13 - 25: Context, Hermes, Evidence, Policy, Episode, Pattern & World Model
        # ---------------------------------------------------------
        episodes_created: List[ReasoningEpisode] = []
        intervention_decisions: Dict[str, PolicyEvaluationResult] = {}
        actions_decided: List[Tuple[str, str]] = []
        scheduled_follow_ups: List[Tuple[str, datetime]] = []
        situations_evaluated: List[Situation] = []

        for sit, is_new, elig_result in situations_needing_reasoning:
            situations_evaluated.append(sit)
            budget = elig_result.budget

            # Step 13: Build bounded epistemic context
            bounded_ctx = self.context_builder.build_bounded_context(
                situation=sit,
                current_state=current_state,
                timeline=timeline,
                goals=active_goals,
            )
            context_size = len(json.dumps(bounded_ctx.to_dict())) if bounded_ctx else 0

            # Step 14: Investigate information gaps through Hermes (bounded by budget)
            investigation_outcome: Optional[Any] = None
            inv_rounds = 0
            tool_calls_count = 0

            if elig_result.requires_investigation and budget.max_investigation_rounds > 0:
                stream.emit(
                    event_type="hermes_investigation",
                    summary=f"Investigating gap for {sit.type} (max {budget.max_investigation_rounds} rounds, {budget.max_tool_calls} tools)",
                    situation_id=sit.id,
                    source="situation_investigator",
                )
                try:
                    investigation_outcome = self.situation_investigator.investigate(
                        situation=sit,
                        current_state=current_state,
                        timeline=timeline,
                        goals=active_goals,
                        reference_time=ref_dt,
                    )
                    if investigation_outcome:
                        inv_rounds = getattr(investigation_outcome, "rounds_executed", 1)
                        tool_calls_count = len(getattr(investigation_outcome, "tools_executed", []))
                        if investigation_outcome.situation:
                            sit = investigation_outcome.situation
                            stream.emit(
                                event_type="evidence_added",
                                summary=f"Enriched evidence ({len(sit.evidence)} items) via investigation",
                                situation_id=sit.id,
                                source="situation_investigator",
                            )
                except Exception as inv_ex:
                    logger.warning("Situation investigation failed for %s: %s", sit.id, inv_ex)

            # Step 15: Ask Hermes to reason & Step 16: Validate Hermes structured output
            reason_for_invocation = f"Assess situational dynamics for {sit.type} across active goals"
            stream.emit(
                event_type="hermes_reasoning",
                summary=f"Invoking reasoning with budget {budget.budget_level.upper()}",
                situation_id=sit.id,
                source="reasoning_workflow",
            )
            t_start = time.perf_counter()

            if sit.novelty >= 0.85 and sit.type == "unusual_state":
                workflow_res = self.reasoning_workflow.run_novel_workflow(
                    situation=sit,
                    current_state=current_state,
                    timeline=timeline,
                    goals=active_goals,
                )
                synthesis = workflow_res.synthesis
                episode = workflow_res.episode
            elif (
                investigation_outcome is not None
                and getattr(investigation_outcome, "investigation_succeeded", False)
                and getattr(investigation_outcome, "evidence_bundle", None) is not None
            ):
                workflow_res = self.reasoning_workflow.run_investigation_synthesis(
                    situation=sit,
                    current_state=current_state,
                    evidence_bundle=investigation_outcome.evidence_bundle,
                    timeline=timeline,
                    goals=active_goals,
                )
                synthesis = workflow_res.synthesis
                episode = workflow_res.episode
            else:
                workflow_res = self.reasoning_workflow.run_workflow(
                    situation=sit,
                    current_state=current_state,
                    timeline=timeline,
                    goals=active_goals,
                )
                synthesis = workflow_res.synthesis
                episode = workflow_res.episode

            execution_time_ms = int((time.perf_counter() - t_start) * 1000)

            stream.emit(
                event_type="reasoning_completed",
                summary=f"Synthesized: {getattr(synthesis, 'what_is_happening', 'Reasoning complete')[:80]}",
                situation_id=sit.id,
                source="reasoning_workflow",
            )

            # Step 17: Calculate evidence quality deterministically (PI is the sole authority)
            resolved_evidence = []
            if isinstance(sit.evidence, list):
                for ev_ref in sit.evidence:
                    if isinstance(ev_ref, str):
                        stored_ev = self.event_store.get(ev_ref)
                        if stored_ev:
                            resolved_evidence.append(stored_ev.to_dict())
                        else:
                            resolved_evidence.append({"source": "event_reference", "source_id": ev_ref, "origin_event_id": ev_ref, "summary": ev_ref})
                    elif isinstance(ev_ref, dict):
                        resolved_evidence.append(ev_ref)

            calc_evidence_quality = self.evidence_calculator.calculate(
                evidence_items=resolved_evidence if resolved_evidence else (sit.evidence if isinstance(sit.evidence, list) else []),
                reference_time=ref_dt,
            )
            if calc_evidence_quality in ("weak", "insufficient_evidence") and synthesis and (getattr(synthesis, "evidence_quality", None) or getattr(synthesis, "evidence_strength", None)):
                if sit.evidence:
                    synth_eq = getattr(synthesis, "evidence_quality", None) or getattr(synthesis, "evidence_strength", None)
                    calc_evidence_quality = synth_eq
            calc_evidence_strength = calc_evidence_quality

            stream.emit(
                event_type="evidence_evaluated",
                summary=f"Evidence quality evaluated: {calc_evidence_quality.upper()}",
                situation_id=sit.id,
                source="evidence_calculator",
            )

            # Step 18: Produce recommendation
            rec = getattr(synthesis, "recommendation", None) or (synthesis.recommendations if getattr(synthesis, "recommendations", None) else None)
            if rec:
                stream.emit(
                    event_type="recommendation_created",
                    summary=f"Recommendation: {str(rec)[:80]}",
                    situation_id=sit.id,
                    source="reasoning_workflow",
                )

            # Step 19: Evaluate deterministic intervention policy
            urgency = getattr(synthesis, "urgency", "medium") if synthesis else "medium"
            actionability = getattr(synthesis, "actionability", "medium") if synthesis else "medium"
            relevance = getattr(synthesis, "relevance", "medium") if synthesis else "medium"
            already_notified = sit.id in (already_notified_situations or set())
            recently_dismissed = sit.id in (recently_dismissed_situations or set())
            situation_freshness = sit.compute_freshness(as_of=ref_dt).value if hasattr(sit, "compute_freshness") else "fresh"
            inv_status = getattr(investigation_outcome, "investigation_status", "COMPLETE") if investigation_outcome else "COMPLETE"

            policy_decision = self.policy_engine.evaluate(
                urgency=urgency,
                actionability=actionability,
                relevance=relevance,
                evidence_quality=calc_evidence_quality,
                evidence_strength=calc_evidence_strength,
                user_context=active_user_context,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                situation_freshness=situation_freshness,
                investigation_status=inv_status,
            )

            # Step 20: Present or defer recommendation
            action = policy_decision.action
            intervention_decisions[sit.id] = policy_decision
            actions_decided.append((sit.id, action))
            reason_codes[sit.id] = action

            if action in (PolicyAction.DEFER.value, PolicyAction.SUPPRESS.value):
                early_exits.append(EarlyExitRecord(
                    situation_id=sit.id,
                    reason_code=EarlyExitReason.DEFERRED.value,
                    details=f"Intervention {action} by policy ({policy_decision.reason})",
                    timestamp=ref_dt,
                ))

            stream.emit(
                event_type="policy_decision",
                summary=f"Policy decided: {action} ({policy_decision.reason})",
                situation_id=sit.id,
                source="policy_engine",
            )

            # Step 13 (Follow-up Scheduling):
            requires_follow_up = getattr(synthesis, "requires_follow_up", False) if synthesis else False
            urgency_val = getattr(synthesis, "urgency", "medium") if synthesis else "medium"

            follow_up_dt = None
            if requires_follow_up or (sit.status == SituationStatus.MONITORING.value and urgency_val != "low"):
                follow_up_dt = ref_dt + timedelta(minutes=follow_up_delay_minutes)
                self.situation_store.schedule_reevaluation(sit.id, follow_up_dt)
                scheduled_follow_ups.append((sit.id, follow_up_dt))
            elif urgency_val == "low" and not requires_follow_up:
                self.situation_store.resolve(sit.id, resolution_notes="Condition cleared during evaluation cycle.")
                early_exits.append(EarlyExitRecord(
                    situation_id=sit.id,
                    reason_code=EarlyExitReason.CLEARED.value,
                    details="Condition cleared during evaluation cycle; situation resolved.",
                    timestamp=ref_dt,
                ))

            # Step 23: Store reasoning episode with complete invocation telemetry
            if episode:
                episode.reason_for_invocation = reason_for_invocation
                episode.reasoning_budget = budget.budget_level.upper()
                episode.context_size = context_size
                episode.investigation_rounds = inv_rounds
                episode.tool_calls = tool_calls_count
                episode.execution_time_ms = execution_time_ms
                updated_ep = self.episode_store.update_episode(
                    episode_id=episode.id,
                    intervention_decision=policy_decision.to_dict(),
                    follow_up_at=follow_up_dt,
                    reason_for_invocation=reason_for_invocation,
                    reasoning_budget=budget.budget_level.upper(),
                    context_size=context_size,
                    investigation_rounds=inv_rounds,
                    tool_calls=tool_calls_count,
                    execution_time_ms=execution_time_ms,
                    reason_code=action,
                )
                episodes_created.append(updated_ep or episode)

        # ---------------------------------------------------------
        # Step 24: Update learned patterns & Step 25: World Model Update
        # ---------------------------------------------------------
        learned_patterns_summary = None
        if self.learning_engine is not None and (events_to_process or episodes_created):
            try:
                learned_patterns_summary = self.learning_engine.learn_patterns(
                    events=events_to_process,
                    episodes=episodes_created,
                    timeline=timeline,
                    as_of=ref_dt,
                )
                if learned_patterns_summary:
                    total_pats = sum(len(v) for v in learned_patterns_summary.values())
                    if total_pats > 0:
                        stream.emit(
                            event_type="pattern_updated",
                            summary=f"Updated empirical pattern baseline ({total_pats} active patterns)",
                            source="learning_engine",
                        )
            except Exception as learn_ex:
                logger.warning("Pattern learning failed during cycle: %s", learn_ex)

        return EvaluationLoopResult(
            timestamp=ref_dt,
            events_processed_count=len(events_to_process),
            current_state=current_state,
            timeline=timeline,
            active_goals=active_goals,
            novelty_result=novelty_result,
            active_situations=active_situations,
            candidate_situations=situation_eval.candidate_situations,
            situations_evaluated=situations_evaluated,
            episodes_created=episodes_created,
            intervention_decisions=intervention_decisions,
            actions_decided=actions_decided,
            scheduled_follow_ups=scheduled_follow_ups,
            learned_patterns=learned_patterns_summary if isinstance(learned_patterns_summary, dict) else None,
            attention_state=active_user_context,
            significance_assessments=significance_map,
            eligibility_decisions=eligibility_map,
            early_exits=early_exits,
            reason_codes=reason_codes,
        )

    # -------------------------------------------------------------------------
    # Steps 21 - 25: Interactive Lifecycle Methods (User Response & Outcome Hooks)
    # -------------------------------------------------------------------------

    def capture_user_response(
        self,
        situation_id: str,
        response: str,
        feedback_notes: Optional[str] = None,
        episode_id: Optional[str] = None,
        snooze_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Step 21: Capture explicit user response to a recommendation/intervention.
        Updates situation lifecycle, records response on reasoning episode, and updates learning engine.
        NO hidden Hermes writes.
        """
        stream = ActivityStream.get_instance()
        resp_norm = response.strip().upper()

        # 1. Update Situation Lifecycle
        if resp_norm in (RecommendationResult.ACCEPTED.value, "DONE", "COMPLETED", "ACCEPT"):
            self.situation_store.resolve(situation_id, resolution_notes=feedback_notes or "User completed recommended action.")
        elif resp_norm in (RecommendationResult.DISMISSED.value, "DISMISS", "REJECT"):
            self.situation_store.dismiss(situation_id, feedback=feedback_notes)
        elif resp_norm in (RecommendationResult.DEFERRED.value, "SNOOZE"):
            snooze_until = datetime.now(timezone.utc) + timedelta(days=snooze_days or 1)
            self.situation_store.schedule_reevaluation(situation_id, snooze_until)

        # 2. Record Response on Reasoning Episode
        target_ep = None
        if episode_id:
            target_ep = self.episode_store.get_episode(episode_id)
        if target_ep is None:
            eps = self.episode_store.list_by_situation(situation_id, limit=1)
            if eps:
                target_ep = eps[0]

        if target_ep:
            user_record = UserResponseRecord(
                response=resp_norm,
                feedback_notes=feedback_notes,
                metadata={"snooze_days": snooze_days} if snooze_days else {},
            )
            self.episode_store.update_episode(
                episode_id=target_ep.id,
                user_response=user_record.to_dict(),
                status=EpisodeStatus.RESPONSE_RECORDED.value,
            )

        stream.emit(
            event_type="user_response",
            summary=f"User responded [{resp_norm}] for situation {situation_id}",
            situation_id=situation_id,
            source="user_response_hook",
        )

        # 3. Update Learned Interaction Patterns Immediately
        all_eps = self.episode_store.list_recent(limit=50)
        self.learning_engine.learn_patterns(episodes=all_eps)

        return {
            "status": "success",
            "situation_id": situation_id,
            "response": resp_norm,
            "feedback_notes": feedback_notes,
        }

    def capture_outcome(
        self,
        situation_id: str,
        outcome_status: str,
        evaluation_notes: Optional[str] = None,
        success: Optional[bool] = None,
        episode_id: Optional[str] = None,
        impact_metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Step 22 & 25: Capture longitudinal outcome evaluation and update world model knowledge.
        """
        stream = ActivityStream.get_instance()
        out_norm = outcome_status.strip().upper()
        is_success = success if success is not None else (out_norm in (RecommendationResult.COMPLETED.value, "SUCCESS", "RESOLVED"))

        # 1. Update Reasoning Episode
        target_ep = None
        if episode_id:
            target_ep = self.episode_store.get_episode(episode_id)
        if target_ep is None:
            eps = self.episode_store.list_by_situation(situation_id, limit=1)
            if eps:
                target_ep = eps[0]

        if target_ep:
            out_record = OutcomeRecord(
                outcome_status=out_norm,
                evaluation_notes=evaluation_notes,
                success=is_success,
                impact_metrics=impact_metrics or {},
            )
            self.episode_store.update_episode(
                episode_id=target_ep.id,
                outcome=out_record.to_dict(),
                status=EpisodeStatus.OUTCOME_RECORDED.value,
            )

        stream.emit(
            event_type="outcome",
            summary=f"Outcome recorded [{out_norm}] (Success: {is_success}) for situation {situation_id}",
            situation_id=situation_id,
            source="outcome_hook",
        )

        # 2. Update World Model Knowledge safely
        if is_success:
            self.situation_store.resolve(situation_id, resolution_notes=evaluation_notes or "Outcome successfully verified.")

        # 3. Update Learned Patterns with new outcome
        all_eps = self.episode_store.list_recent(limit=50)
        self.learning_engine.learn_patterns(episodes=all_eps)

        return {
            "status": "success",
            "situation_id": situation_id,
            "outcome_status": out_norm,
            "success": is_success,
        }


# Architectural alias
PersonalIntelligenceLoop = PersonalIntelligenceEvaluationLoop
