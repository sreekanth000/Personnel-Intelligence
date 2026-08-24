"""
Novelty Reasoning Orchestrator.
Orchestrates end-to-end processing for statistically unfamiliar situations:
Statistical Novelty -> NOVEL Situation -> Bounded Reasoning Context ->
Hermes Novel Investigation -> Episode Persistence -> Categorical Intervention Policy.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from personal_intelligence.core.context import (
    BoundedReasoningContext,
    ContextBuilder,
)
from personal_intelligence.core.episodes import (
    EpisodeStore,
    ReasoningEpisode,
)
from personal_intelligence.core.goals.models import Goal
from personal_intelligence.core.novelty.models import (
    NoveltyLevel,
    NoveltyResult,
)
from personal_intelligence.core.patterns.models import LearnedPattern
from personal_intelligence.core.policy import (
    InterventionPolicyEngine,
    PolicyAction,
    PolicyEvaluationResult,
    UserContext,
)
from personal_intelligence.core.situations.engine import SituationEngine
from personal_intelligence.core.situations.models import Situation, SituationEvaluation
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.hermes_bridge.reasoning import (
    NovelReasoningSynthesis,
    NovelReasoningWorkflowResult,
    ReasoningWorkflow,
)
from personal_intelligence.storage.db import DatabaseManager


@dataclass
class NoveltyReasoningPipelineResult:
    """End-to-end outcome of novel situation reasoning and policy evaluation."""
    situation: Situation
    bounded_context: BoundedReasoningContext
    novel_synthesis: NovelReasoningSynthesis
    reasoning_episode: ReasoningEpisode
    policy_evaluation: PolicyEvaluationResult
    workflow_result: NovelReasoningWorkflowResult


class NoveltyReasoningOrchestrator:
    """
    Coordinates statistical novelty detection with exploratory Hermes reasoning,
    ensuring epistemic uncertainty preservation and deterministic policy enforcement.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        situation_engine: Optional[SituationEngine] = None,
        situation_store: Optional[SituationStore] = None,
        context_builder: Optional[ContextBuilder] = None,
        reasoning_workflow: Optional[ReasoningWorkflow] = None,
        policy_engine: Optional[InterventionPolicyEngine] = None,
        episode_store: Optional[EpisodeStore] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.situation_engine = situation_engine or SituationEngine()
        self.situation_store = situation_store or SituationStore(db_manager=self.db_manager)
        self.context_builder = context_builder or ContextBuilder()
        self.reasoning_workflow = reasoning_workflow or ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=episode_store or EpisodeStore(db_manager=self.db_manager),
        )
        self.policy_engine = policy_engine or InterventionPolicyEngine()
        self.episode_store = episode_store or EpisodeStore(db_manager=self.db_manager)

    def process_novel_state(
        self,
        novelty_result: NoveltyResult,
        current_state: StateRepresentation,
        timeline: Optional[Timeline] = None,
        goals: Optional[List[Goal]] = None,
        patterns: Optional[List[LearnedPattern]] = None,
        episodes: Optional[List[Any]] = None,
        user_context: Optional[str] = UserContext.AVAILABLE.value,
        already_notified: bool = False,
        recently_dismissed: bool = False,
    ) -> NoveltyReasoningPipelineResult:
        """
        Executes complete pipeline:
        1. Creates NOVEL situation from statistical deviations.
        2. Builds bounded reasoning context.
        3. Invokes Hermes exploratory investigation with epistemic restraint.
        4. Persists reasoning episode with complete provenance.
        5. Evaluates intervention policy.
        """
        now = datetime.now(timezone.utc)
        tl = timeline if timeline is not None else Timeline([])
        gl = goals if goals is not None else []

        # 1. Formulate / generate NOVEL situation
        candidate_eval = self.situation_engine.evaluate(
            current_state=current_state,
            timeline=tl,
            goals=gl,
            novelty_result=novelty_result,
        )

        unusual_candidates = [
            s for s in candidate_eval.candidate_situations
            if s.type in ("unusual_state", "novel", "novel_state")
        ]

        if unusual_candidates:
            situation = self.situation_store.create_situation(
                title=unusual_candidates[0].type.replace("_", " ").title(),
                description=f"Candidate situation: {unusual_candidates[0].type}",
                situation_type=unusual_candidates[0].type,
                evidence=unusual_candidates[0].evidence,
                related_goals=unusual_candidates[0].related_goals,
                context={
                    "novelty_level": str(novelty_result.overall_level),
                    "novel_features": [f.to_dict() for f in novelty_result.feature_results if f.is_anomalous()],
                    "state_summary": current_state.to_compact_dict(),
                },
            )
        else:
            situation_title = "Novel Personal State Combination"
            situation_desc = f"Statistical novelty level '{novelty_result.overall_level}' detected across state dimensions."
            evidence_list = [f"novelty_level:{novelty_result.overall_level}"]
            related_goals = [g.id for g in gl if g.is_active]

            # Persist situation
            situation = self.situation_store.create_situation(
                title=situation_title,
                description=situation_desc,
                situation_type="unusual_state",
                evidence=evidence_list,
                related_goals=related_goals,
                context={
                    "novelty_level": str(novelty_result.overall_level),
                    "novel_features": [f.to_dict() for f in novelty_result.feature_results if f.is_anomalous()],
                    "state_summary": current_state.to_compact_dict(),
                },
            )

        # 2 & 3. Build bounded context and run Hermes novel reasoning workflow
        workflow_res = self.reasoning_workflow.run_novel_workflow(
            situation=situation,
            current_state=current_state,
            timeline=timeline,
            goals=goals,
            patterns=patterns,
            episodes=episodes,
            objective="Exploratory investigation of statistically novel personal state combination",
        )

        synth = workflow_res.synthesis
        episode = workflow_res.episode

        # 4. Evaluate Categorical Intervention Policy (Novel != Notify)
        policy_eval = self.policy_engine.evaluate(
            urgency=synth.urgency,
            actionability=synth.actionability,
            evidence_strength=synth.evidence_strength,
            user_context=user_context or UserContext.AVAILABLE.value,
            already_notified=already_notified,
            recently_dismissed=recently_dismissed,
        )

        # Update episode with intervention decision
        if episode:
            action_val = policy_eval.action.value if hasattr(policy_eval.action, "value") else str(policy_eval.action)
            self.episode_store.update_episode(
                episode_id=episode.episode_id,
                status=episode.status,
                metadata={
                    "policy_action": action_val,
                    "policy_reason": policy_eval.reason,
                    "intervention_decision": policy_eval.to_dict(),
                },
            )

        return NoveltyReasoningPipelineResult(
            situation=situation,
            bounded_context=workflow_res.bounded_context,
            novel_synthesis=synth,
            reasoning_episode=episode,
            policy_evaluation=policy_eval,
            workflow_result=workflow_res,
        )
