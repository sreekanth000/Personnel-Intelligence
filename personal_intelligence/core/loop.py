"""
Complete Personal Intelligence Evaluation Loop.
Orchestrates the 16-step end-to-end evaluation pipeline with strict idempotency:
1. Read new events.
2. Update state.
3. Update timeline.
4. Build current state representation.
5. Run novelty detection.
6. Evaluate active situations.
7. Generate candidate situations.
8. Determine whether reasoning is required.
9. Build bounded context.
10. Invoke Hermes if required.
11. Validate Hermes output.
12. Create/update reasoning episode.
13. Run intervention policy.
14. Decide (INTERRUPT, BRIEFING, DEFER, SUPPRESS, DISCARD).
15. Persist everything required for later learning.
16. Schedule follow-up evaluation where appropriate.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from personal_intelligence.core.activity.stream import ActivityStream
from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import (
    EpisodeStore,
    ReasoningEpisode,
)
from personal_intelligence.core.events.buffer import EventBuffer
from personal_intelligence.core.events.models import (
    Event,
    EventBatch,
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals import Goal, GoalStore
from personal_intelligence.core.novelty import NoveltyEngine, NoveltyResult
from personal_intelligence.core.policy.engine import InterventionPolicyEngine
from personal_intelligence.core.policy.models import (
    PolicyEvaluationResult,
    UserContext,
)
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.lifecycle import SituationLifecycleManager
from personal_intelligence.core.situations.models import (
    Situation,
    SituationStatus,
)
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.core.patterns import (
    LearningEngine,
    PatternStore,
)
from personal_intelligence.hermes_bridge.client import HermesClient
from personal_intelligence.hermes_bridge.reasoning import ReasoningWorkflow
from personal_intelligence.storage.db import DatabaseManager





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
            "novelty_score": novelty_score,
            "active_situations_count": len(self.active_situations),
            "episodes_created_count": len(self.episodes_created),
            "actions": [{"situation_id": sid, "action": act} for sid, act in self.actions_decided],
            "scheduled_follow_ups": [{"situation_id": sid, "next_eval": format_iso8601(dt)} for sid, dt in self.scheduled_follow_ups],
            "learned_patterns_count": sum(len(v) for v in self.learned_patterns.values()) if self.learned_patterns else 0,
        }


class PersonalIntelligenceEvaluationLoop:
    """
    Unified, idempotent coordinator for the 16-step Personal Intelligence evaluation loop.
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


    def run_cycle(
        self,
        incoming_events: Optional[List[Event]] = None,
        user_context: str = UserContext.AVAILABLE.value,
        as_of: Optional[datetime] = None,
        already_notified_situations: Optional[Set[str]] = None,
        recently_dismissed_situations: Optional[Set[str]] = None,
        follow_up_delay_minutes: int = 60,
    ) -> EvaluationLoopResult:
        """
        Executes one complete idempotent evaluation cycle across the 16 steps.
        """
        ref_dt = as_of if as_of is not None else datetime.now(timezone.utc)
        ref_dt = ensure_timezone_aware(ref_dt, "as_of")

        # ---------------------------------------------------------
        # Step 1: Read new events & commit to store idempotently
        # ---------------------------------------------------------
        stream = ActivityStream.get_instance()
        events_to_process: List[Event] = []
        if incoming_events:
            events_to_process.extend(incoming_events)
        if self.event_buffer and self.event_buffer.size() > 0:
            events_to_process.extend(self.event_buffer.drain())

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
        # Step 2: Update state
        # Step 3: Update timeline
        # Step 4: Build current state representation
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
        # Step 5: Run novelty detection
        # ---------------------------------------------------------
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
        # Step 6: Evaluate active situations (sweep expired, fetch due)
        # ---------------------------------------------------------
        self.situation_lifecycle.expire_due_situations(as_of=ref_dt)
        due_situations = self.situation_store.get_due_reevaluations(as_of=ref_dt)
        active_situations = self.situation_store.list_active()

        # ---------------------------------------------------------
        # Step 7: Generate candidate situations
        # ---------------------------------------------------------
        situation_eval = self.situation_engine.evaluate(
            current_state=current_state,
            timeline=timeline,
            goals=active_goals,
            novelty_result=novelty_result,
        )

        # ---------------------------------------------------------
        # Step 8: Determine whether reasoning is required (Idempotency)
        # ---------------------------------------------------------
        situations_needing_reasoning: List[Tuple[Situation, bool]] = []

        for cand in situation_eval.candidate_situations:
            sit, is_new = self.situation_lifecycle.register_or_update(
                candidate_situation=cand,
                current_state=current_state,
                timeline=timeline,
                goals=active_goals,
            )
            if is_new:
                stream.emit(
                    event_type="situation_created",
                    summary=f"Created situation: {sit.type} ({sit.priority.upper() if sit.priority else 'MEDIUM'})",
                    situation_id=sit.id,
                    source="situation_engine",
                )
            # Reasoning is required if situation is brand new OR new events occurred in this cycle
            if is_new or bool(events_to_process):
                situations_needing_reasoning.append((sit, is_new))

        # Also add situations whose scheduled re-evaluation time has arrived
        for due_sit in due_situations:
            if not any(s.id == due_sit.id for s, _ in situations_needing_reasoning):
                situations_needing_reasoning.append((due_sit, False))

        # ---------------------------------------------------------
        # Steps 9 - 16: Hermes Reasoning, Validation, Episode, Policy, Persistence & Schedule
        # ---------------------------------------------------------
        episodes_created: List[ReasoningEpisode] = []
        intervention_decisions: Dict[str, PolicyEvaluationResult] = {}
        actions_decided: List[Tuple[str, str]] = []
        scheduled_follow_ups: List[Tuple[str, datetime]] = []
        situations_evaluated: List[Situation] = []

        for sit, is_new in situations_needing_reasoning:
            situations_evaluated.append(sit)

            # -----------------------------------------------------------------
            # Step 7b: Situation Investigation (if information gap exists)
            # -----------------------------------------------------------------
            # When situation.information_required=True, resolve the gap through
            # Hermes existing tools BEFORE building the reasoning context.
            # This records investigation findings as normalized observation events
            # and updates the situation with enriched evidence.
            investigation_outcome: Optional[InvestigationOutcome] = None
            if sit.information_required:
                stream.emit(
                    event_type="investigation_started",
                    summary=f"Investigating information gap for situation: {sit.type}",
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
                    # Use the enriched situation for all downstream steps
                    if investigation_outcome and investigation_outcome.situation:
                        sit = investigation_outcome.situation
                        stream.emit(
                            event_type="evidence_added",
                            summary=f"Enriched situation evidence ({len(sit.evidence)} items)",
                            situation_id=sit.id,
                            source="situation_investigator",
                        )
                except Exception as inv_ex:
                    # Investigation failure is non-fatal — proceed with available evidence
                    import logging
                    logging.getLogger(__name__).warning(
                        "Situation investigation failed for %s: %s", sit.id, inv_ex
                    )

            # Step 9: Build bounded context
            bounded_ctx = self.context_builder.build_bounded_context(
                situation=sit,
                current_state=current_state,
                timeline=timeline,
                goals=active_goals,
            )

            # Step 10: Invoke Hermes if required
            # Step 11: Validate Hermes output
            # Step 12: Create/update reasoning episode
            stream.emit(
                event_type="reasoning_started",
                summary=f"Reasoning over situation {sit.type} across active goals",
                situation_id=sit.id,
                source="reasoning_workflow",
            )
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
                and investigation_outcome.investigation_succeeded
                and investigation_outcome.evidence_bundle is not None
            ):
                # Cross-source unified synthesis — reasoning over post-investigation evidence
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

            stream.emit(
                event_type="reasoning_completed",
                summary=f"Synthesized assessment: {getattr(synthesis, 'what_is_happening', 'Reasoning complete')[:80]}",
                situation_id=sit.id,
                source="reasoning_workflow",
            )

            # Step 13: Run intervention policy
            urgency = getattr(synthesis, "urgency", "medium") if synthesis else "medium"
            actionability = getattr(synthesis, "actionability", "medium") if synthesis else "medium"
            relevance = getattr(synthesis, "relevance", "medium") if synthesis else "medium"
            evidence_strength = getattr(synthesis, "evidence_strength", "moderate") if synthesis else "moderate"
            already_notified = sit.id in (already_notified_situations or set())
            recently_dismissed = sit.id in (recently_dismissed_situations or set())
            is_stale = (sit.expires_at is not None and sit.expires_at < ref_dt)
            situation_freshness = "stale" if is_stale else "fresh"

            policy_decision = self.policy_engine.evaluate(
                urgency=urgency,
                actionability=actionability,
                relevance=relevance,
                evidence_strength=evidence_strength,
                user_context=user_context,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                situation_freshness=situation_freshness,
            )

            # Step 14: Decide (INTERRUPT, BRIEFING, DEFER, SUPPRESS, DISCARD)
            action = policy_decision.action
            intervention_decisions[sit.id] = policy_decision
            actions_decided.append((sit.id, action))
            stream.emit(
                event_type="intervention_decided",
                summary=f"Policy decided: {action} ({policy_decision.reason})",
                situation_id=sit.id,
                source="policy_engine",
            )

            # Step 16: Schedule follow-up evaluation or resolve when cleared
            requires_follow_up = getattr(synthesis, "requires_follow_up", False) if synthesis else False
            urgency_val = getattr(synthesis, "urgency", "medium") if synthesis else "medium"

            follow_up_dt = None
            if requires_follow_up or (sit.status == SituationStatus.MONITORING.value and urgency_val != "low"):
                follow_up_dt = ref_dt + timedelta(minutes=follow_up_delay_minutes)
                self.situation_store.schedule_reevaluation(sit.id, follow_up_dt)
                scheduled_follow_ups.append((sit.id, follow_up_dt))
            elif urgency_val == "low" and not requires_follow_up:
                # If condition has cleared and no follow-up needed, resolve situation
                self.situation_store.resolve(sit.id, resolution_notes="Condition cleared during evaluation cycle.")

            # Step 15: Persist everything required for later learning
            if episode:
                updated_ep = self.episode_store.update_episode(
                    episode_id=episode.id,
                    intervention_decision=policy_decision.to_dict(),
                    follow_up_at=follow_up_dt,
                )
                episodes_created.append(updated_ep or episode)


        # Re-fetch active situations after lifecycle updates
        final_active_situations = self.situation_store.list_active()

        # Step 15b: Learn patterns across observations, episodes, outcomes
        learned_patterns = None
        if self.learning_engine is not None and (events_to_process or episodes_created):
            try:
                learned_patterns = self.learning_engine.learn_patterns(
                    events=events_to_process,
                    episodes=episodes_created,
                    timeline=timeline,
                    as_of=ref_dt,
                )
                if learned_patterns:
                    total_pats = sum(len(v) for v in learned_patterns.values())
                    if total_pats > 0:
                        stream.emit(
                            event_type="pattern_updated",
                            summary=f"Updated empirical pattern baseline ({total_pats} active patterns)",
                            source="learning_engine",
                        )
            except Exception as learn_ex:
                import logging
                logging.getLogger(__name__).warning("Pattern learning failed during cycle: %s", learn_ex)

        return EvaluationLoopResult(
            timestamp=ref_dt,
            events_processed_count=len(events_to_process),
            current_state=current_state,
            timeline=timeline,
            active_goals=active_goals,
            novelty_result=novelty_result,
            active_situations=final_active_situations,
            candidate_situations=situation_eval.candidate_situations,
            situations_evaluated=situations_evaluated,
            episodes_created=episodes_created,
            intervention_decisions=intervention_decisions,
            actions_decided=actions_decided,
            scheduled_follow_ups=scheduled_follow_ups,
            learned_patterns=learned_patterns,
        )

