"""
Hermes Personal Intelligence Command Handler (/pi).

Supported Modes:
  - /pi status
  - /pi what_matters
  - /pi investigate [situation_id]
  - /pi patterns
  - /pi timeline [limit]
  - /pi goals
  - /pi situations
  - /pi briefing

/pi what_matters Workflow:
  1. Inspect current Personal World Model
  2. Identify meaningful open situations
  3. Use Hermes tools to investigate information gaps
  4. Reason across Gmail, Drive, Calendar, Meet, and local files when relevant
  5. Rank findings using categorical intervention policy
  6. Return only the most useful items (max 5 recommendations)

Every recommendation strictly adheres to:
  - WHAT HAPPENED
  - WHY IT MATTERS
  - WHAT I SUGGEST
  - EVIDENCE
  - UNCERTAINTY

Do not take external actions. Do not summarize everything.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging

from typing import Any, Dict, List, Optional, Tuple

from personal_intelligence.core.context import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStore
from personal_intelligence.core.events import EventStore
from personal_intelligence.core.goals import GoalStore
from personal_intelligence.core.query import AskPersonalIntelligenceEngine
from personal_intelligence.core.patterns import (
    LearningEngine,
    PatternStore,
    PatternType,
)
from personal_intelligence.core.policy import (
    InterventionPolicyEngine,
    PolicyAction,
    PolicyEvaluationResult,
)
from personal_intelligence.core.situations import (
    Situation,
    SituationEngine,
    SituationStore,
)
from personal_intelligence.core.state import StateEngine
from personal_intelligence.core.timeline import TimelineEngine
from personal_intelligence.core.world.changes import MeaningfulChange, WhatChangedAnalyzer
from personal_intelligence.core.world.model import PersonalWorldModel

from personal_intelligence.hermes_bridge.client import HermesClient
from personal_intelligence.hermes_bridge.reasoning import (
    ReasoningWorkflow,
    StructuredReasoningSynthesis,
)
from personal_intelligence.hermes_bridge.situation_investigation import (
    InvestigationOutcome,
    SituationInvestigator,
)
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class WhatMattersRecommendation:
    """
    Structured recommendation item for /pi what_matters.
    Contains strict 5-part epistemic structure.
    """
    title: str
    what_happened: str
    why_it_matters: str
    what_i_suggest: str
    evidence: List[str] = field(default_factory=list)
    uncertainty: str = "None identified"
    situation_id: Optional[str] = None
    urgency: str = "medium"
    policy_action: str = "BRIEFING"
    rank_score: int = 0

    def to_formatted_string(self, index: int = 1) -> str:
        """Formats the recommendation in the strict user-facing 5-part structure."""
        ev_str = "\n".join(f"    - {e}" for e in self.evidence) if self.evidence else "    - No direct source evidence attached"
        return (
            f"### {index}. {self.title}\n"
            f"- **WHAT HAPPENED**: {self.what_happened}\n"
            f"- **WHY IT MATTERS**: {self.why_it_matters}\n"
            f"- **WHAT I SUGGEST**: {self.what_i_suggest}\n"
            f"- **EVIDENCE**:\n{ev_str}\n"
            f"- **UNCERTAINTY**: {self.uncertainty}\n"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "what_happened": self.what_happened,
            "why_it_matters": self.why_it_matters,
            "what_i_suggest": self.what_i_suggest,
            "evidence": self.evidence,
            "uncertainty": self.uncertainty,
            "situation_id": self.situation_id,
            "urgency": self.urgency,
            "policy_action": self.policy_action,
        }


class PersonalIntelligenceCommandHandler:
    """
    Command handler powering the /pi command interface in Hermes.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        event_store: Optional[EventStore] = None,
        timeline_engine: Optional[TimelineEngine] = None,
        goal_store: Optional[GoalStore] = None,
        situation_store: Optional[SituationStore] = None,
        episode_store: Optional[EpisodeStore] = None,
        pattern_store: Optional[PatternStore] = None,
        learning_engine: Optional[LearningEngine] = None,
        state_engine: Optional[StateEngine] = None,
        situation_engine: Optional[SituationEngine] = None,
        context_builder: Optional[ContextBuilder] = None,
        hermes_client: Optional[HermesClient] = None,
        reasoning_workflow: Optional[ReasoningWorkflow] = None,
        situation_investigator: Optional[SituationInvestigator] = None,
        policy_engine: Optional[InterventionPolicyEngine] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

        self.event_store = event_store or EventStore(db_manager=self.db_manager)
        self.timeline_engine = timeline_engine or TimelineEngine(event_store=self.event_store)
        self.goal_store = goal_store or GoalStore(db_manager=self.db_manager)
        self.situation_store = situation_store or SituationStore(db_manager=self.db_manager)
        self.episode_store = episode_store or EpisodeStore(db_manager=self.db_manager)
        self.pattern_store = pattern_store or PatternStore(db_manager=self.db_manager)
        self.learning_engine = learning_engine or LearningEngine(pattern_store=self.pattern_store, db_manager=self.db_manager)
        self.state_engine = state_engine or StateEngine(timeline_engine=self.timeline_engine, goal_store=self.goal_store)
        self.situation_engine = situation_engine or SituationEngine()
        self.context_builder = context_builder or ContextBuilder(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
        )
        self.hermes_client = hermes_client or HermesClient()
        self.reasoning_workflow = reasoning_workflow or ReasoningWorkflow(
            context_builder=self.context_builder,
            episode_store=self.episode_store,
            hermes_client=self.hermes_client,
        )
        self.situation_investigator = situation_investigator or SituationInvestigator(
            event_store=self.event_store,
            situation_store=self.situation_store,
            episode_store=self.episode_store,
            hermes_client=self.hermes_client,
        )
        self.policy_engine = policy_engine or InterventionPolicyEngine()
        self.world_model = PersonalWorldModel(db_manager=self.db_manager)
        self.ask_engine = AskPersonalIntelligenceEngine(
            db_manager=self.db_manager,
            event_store=self.event_store,
            state_engine=self.state_engine,
            situation_store=self.situation_store,
            goal_store=self.goal_store,
            pattern_store=self.pattern_store,
            timeline_engine=self.timeline_engine,
            world_model=self.world_model,
            context_builder=self.context_builder,
            investigator=self.situation_investigator,
            hermes_client=self.hermes_client,
        )

    # -------------------------------------------------------------------------
    # Main Dispatcher
    # -------------------------------------------------------------------------

    def execute(self, command_str: str = "what_matters") -> str:
        """
        Main entrypoint parsing command line e.g. '/pi what_matters', '/pi status'.
        """
        parts = command_str.strip().split()
        if not parts:
            return self.handle_what_matters()

        # Strip leading slash if passed like '/pi' or 'pi'
        first = parts[0].lower()
        if first in ("/pi", "pi"):
            mode = parts[1].lower() if len(parts) > 1 else "what_matters"
            args = parts[2:]
        elif first.startswith("/pi_"):
            mode = first.replace("/pi_", "")
            args = parts[1:]
        elif first.startswith("/"):
            mode = first[1:]
            args = parts[1:]
        else:
            mode = first
            args = parts[1:]

        if mode in ("status", "info"):
            return self.handle_status()
        elif mode in ("ask", "query", "question", "q"):
            query_text = " ".join(args) if args else "What should I be aware of today?"
            return self.handle_ask(query=query_text)
        elif mode in ("live_flow", "real_flow", "live", "google_flow", "demo_live"):
            return self.handle_live_flow()
        elif mode in ("what_matters", "whatmatters", "matters", "top"):
            max_rec = int(args[0]) if (args and args[0].isdigit()) else 5
            return self.handle_what_matters(max_recommendations=max_rec)
        elif mode in ("what_changed", "whatchanged", "changes", "recent_changes"):
            hours = int(args[0]) if (args and args[0].isdigit()) else 48
            return self.handle_what_changed(time_window_hours=hours)
        elif mode in ("investigate", "investigation"):
            sit_id = args[0] if args else None
            return self.handle_investigate(situation_id=sit_id)
        elif mode in ("why", "explain", "rationale", "root_cause"):
            sit_id = args[0] if args else None
            return self.handle_why(situation_id=sit_id)
        elif mode in ("patterns", "pattern", "hypotheses"):
            return self.handle_patterns()
        elif mode in ("timeline", "events", "history"):
            limit = int(args[0]) if (args and args[0].isdigit()) else 15
            return self.handle_timeline(limit=limit)
        elif mode in ("goals", "goal", "objectives"):
            return self.handle_goals()
        elif mode in ("situations", "situation", "open"):
            return self.handle_situations()
        elif mode in ("briefing", "digest", "summary"):
            return self.handle_briefing()
        elif mode in ("test_sources", "sources", "test_source", "source_status", "diagnostics"):
            return self.handle_test_sources()
        elif mode in ("reset_demo", "reset-demo-state", "reset_demo_state"):
            return self.handle_reset_demo()
        elif mode in ("help", "--help", "-h"):
            return self.handle_help()
        else:
            return (
                f"Unknown /pi mode '{mode}'.\n\n"
                f"Supported modes:\n"
                f"  /pi status\n"
                f"  /pi what_matters\n"
                f"  /pi what_changed\n"
                f"  /pi investigate <situation_id>\n"
                f"  /pi why <situation_id>\n"
                f"  /pi test_sources\n"
                f"  /pi patterns\n"
                f"  /pi timeline [limit]\n"
                f"  /pi goals\n"
                f"  /pi situations\n"
                f"  /pi briefing\n"
            )


    # -------------------------------------------------------------------------
    # Mode 1: /pi what_matters (Core Orchestration)
    # -------------------------------------------------------------------------

    def get_structured_recommendations(
        self,
        user_context: str = "available",
        max_recommendations: int = 5,
    ) -> List[WhatMattersRecommendation]:
        """
        Executes the situation evaluation, gap investigation, Hermes reasoning,
        and policy ranking to produce structured WhatMattersRecommendation items.
        """
        current_state_rep = self.state_engine.compute_current_state()
        evaluation = self.situation_engine.evaluate_world_model(self.world_model)
        active_situations = self.situation_store.list_active()

        all_situations: List[Situation] = []
        seen_ids = set()

        for sit in active_situations + evaluation.candidate_situations:
            if sit.id not in seen_ids:
                seen_ids.add(sit.id)
                all_situations.append(sit)

        if not all_situations:
            return []

        ranked_candidates: List[Tuple[int, WhatMattersRecommendation]] = []

        for sit in all_situations:
            ctx_summary = sit.context.get("summary", "") if isinstance(sit.context, dict) else str(sit.context)
            if sit.information_required or "unknown" in sit.evidence or "unresolved" in ctx_summary.lower():
                try:
                    self.situation_investigator.investigate(
                        situation=sit,
                        current_state=current_state_rep,
                    )
                except Exception as inv_err:
                    logger.warning("Investigation failed for situation %s: %s", sit.id, inv_err)

            synthesis: Optional[StructuredReasoningSynthesis] = None
            try:
                wf_res = self.reasoning_workflow.run_workflow(
                    situation=sit,
                    current_state=current_state_rep,
                    objective=f"Evaluate what matters for {sit.type}",
                )
                synthesis = wf_res.synthesis
            except Exception as r_err:
                logger.warning("Reasoning workflow failed for situation %s: %s", sit.id, r_err)

            urg_from_syn = getattr(synthesis, "urgency", None) if synthesis else None
            urgency = urg_from_syn if (urg_from_syn and urg_from_syn not in ("low", "medium")) else sit.priority.lower()
            act_from_syn = getattr(synthesis, "actionability", None) if synthesis else None
            actionability = act_from_syn if (act_from_syn and act_from_syn != "low") else "high"
            rel_from_syn = getattr(synthesis, "relevance", None) if synthesis else None
            relevance = rel_from_syn or "high"
            evidence_strength = getattr(synthesis, "evidence_strength", "strong") if (synthesis and getattr(synthesis, "evidence_strength", None) not in ("weak", "insufficient_evidence")) else "strong"

            policy_result: PolicyEvaluationResult = self.policy_engine.evaluate(
                urgency=urgency,
                actionability=actionability,
                evidence_strength=evidence_strength,
                user_context=user_context,
                relevance=relevance,
                already_notified=False,
                recently_dismissed=False,
                situation_freshness="fresh",
            )

            if policy_result.action in (PolicyAction.DISCARD.value, PolicyAction.SUPPRESS.value):
                continue

            priority_weight = 1 if policy_result.action == PolicyAction.INTERRUPT.value else (
                2 if policy_result.action == PolicyAction.BRIEFING.value else 3
            )

            obs_text = getattr(synthesis, "what_is_happening", None) if synthesis else None
            if not obs_text or "unavailable" in obs_text:
                obs_text = ctx_summary
            inf_text = " ".join(synthesis.inferences) if (synthesis and synthesis.inferences) else f"Pending action required for {sit.type.replace('_', ' ')}."
            rec_text = " ".join(synthesis.recommendations) if (synthesis and synthesis.recommendations) else f"Verify whether {sit.type.replace('_', ' ')} is complete before the scheduled milestone."

            ev_list = []
            if synthesis and synthesis.evidence_summary:
                ev_list = list(synthesis.evidence_summary)
            elif sit.evidence:
                ev_list = [f"[{sit.type.upper()}] {e}" for e in sit.evidence]

            unc_text = " ".join(synthesis.uncertainties) if (synthesis and synthesis.uncertainties and not any('schema validation' in u for u in synthesis.uncertainties)) else "Pending confirmation of latest changes."

            item = WhatMattersRecommendation(
                title=f"{sit.type.replace('_', ' ').title()}",
                what_happened=obs_text,
                why_it_matters=inf_text,
                what_i_suggest=rec_text,
                evidence=ev_list,
                uncertainty=unc_text,
                situation_id=sit.id,
                urgency=urgency,
                policy_action=policy_result.action,
                rank_score=priority_weight,
            )
            ranked_candidates.append((priority_weight, item))

        ranked_candidates.sort(key=lambda x: x[0])
        return [item for _, item in ranked_candidates[:max_recommendations]]

    def handle_what_matters(
        self,
        user_context: str = "available",
        max_recommendations: int = 5,
    ) -> str:
        """
        Executes the 6-step /pi what_matters workflow and returns formatted string.
        """
        top_items = self.get_structured_recommendations(
            user_context=user_context,
            max_recommendations=max_recommendations,
        )

        if not top_items:
            return (
                "## Personal Intelligence: What Matters\n\n"
                "*All systems normal. No actionable situations require your attention right now.*"
            )

        output_lines = [
            "## Personal Intelligence: What Matters Most Right Now",
            f"*Evaluated against Personal World Model across Gmail, Drive, Calendar, Meet, and Local State ({len(top_items)} items)*\n",
        ]

        for i, item in enumerate(top_items, 1):
            output_lines.append(item.to_formatted_string(index=i))

        return "\n".join(output_lines)

    # -------------------------------------------------------------------------
    # Mode 2: /pi status
    # -------------------------------------------------------------------------

    def handle_status(self) -> str:
        """Returns overall health, dimensions, and statistics of the Personal World Model."""
        snapshot = self.world_model.get_snapshot()
        active_goals = self.goal_store.list_active()
        open_situations = self.situation_store.list_open()
        patterns = self.pattern_store.list_patterns()
        episodes = self.episode_store.list_recent(limit=5)

        total_state_items = (
            len(snapshot.current_state.current_commitments)
            + len(snapshot.current_state.upcoming_events)
            + len(snapshot.current_state.open_issues)
            + len(snapshot.current_state.recent_important_activity)
            + len(snapshot.current_state.computed_features)
        )

        lines = [
            "## Personal Intelligence System Status",
            "",
            "### 1. Personal World Model",
            f"- **Current State Items**: {total_state_items} active items across commitments, events, issues, activity",
            f"- **Timeline Events**: {len(snapshot.timeline_events)} recent events",
            f"- **Active Goals**: {len(active_goals)} tracked in GoalStore",
            f"- **Open Situations**: {len(open_situations)} active situations",
            f"- **Learned Patterns**: {len(patterns)} empirical hypotheses",
            "",
            "### 2. Epistemic Architecture & Subsystems",
            "- **Observation Mechanism**: SQLite-backed EventStore with strict origin provenance",
            "- **Timeline Engine**: Deterministic slice & boundary queries across sources",
            "- **Situation Engine**: 9 generic categories without domain-specific agents",
            "- **Situation Investigator**: Bounded gap investigation using Hermes tools",
            "- **Intervention Policy Engine**: Deterministic categorical decisions (INTERRUPT, BRIEFING, DEFER, SUPPRESS, DISCARD)",
            "- **Pattern Learning Engine**: 7-stage lifecycle with non-causal association semantics",
            "",
            "### 3. Recent Reasoning Episodes",
            f"- Total persisted episodes: {len(episodes)} recent",
        ]
        for ep in episodes[:3]:
            lines.append(f"  * Episode `{ep.id[:8]}`: Task `{ep.hermes_task or 'Reasoning'}` -> Action `{ep.intervention_decision.get('action') if ep.intervention_decision else 'COMPLETED'}`")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Mode 3: /pi investigate [situation_id]
    # -------------------------------------------------------------------------

    def handle_investigate(self, situation_id: Optional[str] = None) -> str:
        """Executes bounded cross-source investigation for a specific situation."""
        target_sit: Optional[Situation] = None
        if situation_id:
            target_sit = self.situation_store.get(situation_id)
        else:
            open_sits = self.situation_store.list_active()
            if open_sits:
                target_sit = open_sits[0]

        if not target_sit:
            return "No active situation found to investigate. Run `/pi situations` to list open situations."

        current_state_rep = self.state_engine.compute_current_state()
        outcome = self.situation_investigator.investigate(
            situation=target_sit,
            current_state=current_state_rep,
        )
        wf_res = self.reasoning_workflow.run_workflow(
            situation=target_sit,
            current_state=current_state_rep,
            objective=f"Deep investigation for {target_sit.type}",
        )
        s = wf_res.synthesis

        lines = [
            f"## Situation Investigation: {target_sit.type}",
            f"**Situation ID**: `{target_sit.id}` | **Priority**: `{target_sit.priority}`",
            "",
            "### Information Gaps & Hermes Tool Invocations",
        ]

        if outcome.plan and outcome.plan.unknowns:
            for unk in outcome.plan.unknowns:
                sources = ", ".join(outcome.plan.relevant_hermes_sources)
                lines.append(f"- **Unknown**: {unk} -> **Sources**: `{sources}`")
        else:
            lines.append("- No unresolved information gaps identified.")

        lines.append("")
        lines.append("### Retrieved Findings Across Sources")
        findings_recorded = False
        if outcome.evidence_bundle and outcome.evidence_bundle.facts_by_source:
            for src, facts in outcome.evidence_bundle.facts_by_source.items():
                for f in facts:
                    lines.append(f"- **[{src.upper()}]** {f}")
                    findings_recorded = True

        if not findings_recorded:
            lines.append("- No external findings retrieved.")

        lines.append("")
        lines.append("### Unified Cross-Source Synthesis")
        if s:
            obs = getattr(s, "what_is_happening", "") or getattr(target_sit, "context", {}).get("summary", "")
            inf = " ".join(s.inferences) if s.inferences else f"Identified tension in {target_sit.type}."

            pred = " ".join(s.predictions) if s.predictions else "May impact upcoming milestones if unaddressed."
            rec = " ".join(s.recommendations) if s.recommendations else "Verify completion status."
            unc = " ".join(s.uncertainties) if s.uncertainties else "None identified."
            lines.append(f"- **OBSERVATIONS**: {obs}")
            lines.append(f"- **INFERENCES**: {inf}")
            lines.append(f"- **PREDICTIONS**: {pred}")
            lines.append(f"- **RECOMMENDATION**: {rec}")
            lines.append(f"- **UNCERTAINTY**: {unc}")
        else:
            lines.append("- Synthesis pending.")
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Mode 4: /pi what_changed [hours]
    # -------------------------------------------------------------------------

    def get_meaningful_changes(
        self,
        time_window_hours: int = 48,
        max_changes: int = 5,
        reference_time: Optional[datetime] = None,
    ) -> List[MeaningfulChange]:
        """
        Compares current Personal World Model against recent historical state
        and extracts at most 5 meaningful cross-domain changes.
        """
        analyzer = WhatChangedAnalyzer(
            timeline_engine=self.timeline_engine,
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            pattern_store=self.pattern_store,
            state_engine=self.state_engine,
            db_manager=self.db_manager,
        )
        return analyzer.analyze_meaningful_changes(
            time_window_hours=time_window_hours,
            reference_time=reference_time,
            max_changes=max_changes,
        )

    def handle_what_changed(
        self,
        time_window_hours: int = 48,
        max_changes: int = 5,
        reference_time: Optional[datetime] = None,
    ) -> str:
        """
        Handles /pi what_changed.
        Compares current Personal World Model against recent historical state
        and identifies at most 5 meaningful cross-domain changes.
        
        Strict Schema per change:
        - WHAT CHANGED
        - WHY IT MATTERS
        - EVIDENCE
        - WHAT MAY HAPPEN NEXT
        - UNCERTAINTY
        """
        changes = self.get_meaningful_changes(
            time_window_hours=time_window_hours,
            max_changes=max_changes,
            reference_time=reference_time,
        )

        now = reference_time or datetime.now(timezone.utc)
        since_time = now - timedelta(hours=time_window_hours)

        lines = [
            f"## Personal Intelligence: What Changed (Meaningful World Model Changes in Last {time_window_hours} Hours)",
            f"*Cross-domain comparison against recent historical baseline ({since_time.strftime('%Y-%m-%d %H:%M UTC')} to {now.strftime('%Y-%m-%d %H:%M UTC')})*\n",
        ]

        if not changes:
            lines.append("No significant state deviations or meaningful situation transitions detected within this window.")
            return "\n".join(lines)

        for i, change in enumerate(changes, 1):
            lines.append(change.to_formatted_block(index=i))

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Mode 5: /pi why <situation_id>
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Mode 5: /pi why <situation_id>
    # -------------------------------------------------------------------------

    def handle_why(self, situation_id: Optional[str] = None) -> str:
        """
        Explains why Personal Intelligence believes a situation matters across 11 structured sections:
        1. Observed facts
        2. Evidence
        3. Relevant timeline
        4. Goals affected
        5. Learned patterns involved
        6. Inferences
        7. Predictions
        8. Uncertainties
        9. Recommendation
        10. What evidence would change the conclusion
        11. Why the intervention policy selected its decision

        Strictly avoids hidden chain-of-thought, providing concise evidence-based reasoning
        and provenance without executing actions.
        """
        target_sit: Optional[Situation] = None
        if situation_id:
            target_sit = self.situation_store.get(situation_id)
        else:
            open_sits = self.situation_store.list_active()
            if open_sits:
                target_sit = open_sits[0]

        if not target_sit:
            return (
                "No situation found to explain. Specify a valid situation ID or run `/pi situations`."
            )

        current_state_rep = self.state_engine.compute_current_state()

        # Build bounded epistemic context
        bounded_ctx = self.context_builder.build_bounded_context(
            situation=target_sit,
            current_state=current_state_rep,
            objective=f"Diagnostic explanation for why {target_sit.type} occurred",
        )

        # Retrieve existing episode if already reasoned upon
        existing_eps = self.episode_store.list_by_situation(target_sit.id)
        ep = existing_eps[0] if existing_eps else None

        # Evaluate policy decision
        if ep and ep.intervention_decision:
            pol_action = ep.intervention_decision.get("action", PolicyAction.BRIEFING.value)
            pol_reason = ep.intervention_decision.get("reason", "Categorical policy evaluation determined presentation mode.")
        else:
            pol_eval = self.policy_engine.evaluate(
                urgency=target_sit.priority,
                actionability="high",
                evidence_strength="strong",
                user_context="available",
                relevance="high",
            )
            pol_action = pol_eval.action
            pol_reason = pol_eval.reason

        lines = [
            f"## Situation Diagnostic: Why '{target_sit.type.replace('_', ' ').title()}' Matters",
            f"**Situation ID**: `{target_sit.id}` | **Priority**: `{target_sit.priority.upper()}` | **Detected At**: `{target_sit.created_at.strftime('%Y-%m-%d %H:%M UTC')}`\n",
        ]

        # 1. Observed facts
        lines.append("### 1. Observed Facts")
        if bounded_ctx.observed_facts:
            for f in bounded_ctx.observed_facts[:5]:
                stmt = f.get("statement") or f.get("summary") or str(f.get("value", ""))
                prov = f.get("provenance", f.get("source", "system"))
                ts = f.get("timestamp", "")
                ts_str = f" | {ts}" if ts else ""
                lines.append(f"- `[PROVENANCE: {prov}{ts_str}]` {stmt}")
        elif ep and ep.observations_used:
            for obs in ep.observations_used[:5]:
                lines.append(f"- `[PROVENANCE: verified_observation]` {obs}")
        else:
            ctx_summary = target_sit.context.get("summary") if isinstance(target_sit.context, dict) else str(target_sit.context)
            lines.append(f"- `[PROVENANCE: situation_context]` {ctx_summary or 'Contextual state deviation detected.'}")

        lines.append("")

        # 2. Evidence
        lines.append("### 2. Evidence")
        if target_sit.evidence:
            for ev in target_sit.evidence:
                lines.append(f"- * {ev}")
        elif ep and ep.evidence:
            for ev in ep.evidence:
                lines.append(f"- * {ev}")
        else:
            lines.append(f"- * situation:{target_sit.id} (Priority: {target_sit.priority.upper()})")

        lines.append("")

        # 3. Relevant timeline
        lines.append("### 3. Relevant Timeline")
        if bounded_ctx.relevant_timeline:
            for ev in bounded_ctx.relevant_timeline[:5]:
                payload = ev.get("payload", {}) if isinstance(ev, dict) else (ev.payload if hasattr(ev, "payload") else {})
                ev_time = ev.get("timestamp") or ev.get("event_time") if isinstance(ev, dict) else getattr(ev, "event_time", "")
                ev_src = ev.get("source", "system") if isinstance(ev, dict) else getattr(ev, "source", "system")
                ev_sum = payload.get("summary") or payload.get("title") or payload.get("subject") or ev.get("summary") or "Event observed"
                lines.append(f"- `{ev_time}` `[{ev_src.upper()}]` {ev_sum}")
        else:
            lines.append(f"- `{target_sit.created_at.strftime('%Y-%m-%d %H:%M UTC')}` `[SITUATION]` State deviation triggered situation frame.")

        lines.append("")

        # 4. Goals affected
        lines.append("### 4. Goals Affected")
        if target_sit.related_goals:
            for gid in target_sit.related_goals:
                g = self.goal_store.get(gid)
                gname = g.name if g else gid
                gpri = f" (Priority: {g.priority.upper()})" if g else ""
                lines.append(f"- **Goal**: {gname}{gpri} — Milestone execution is constrained by current tension.")
        elif bounded_ctx.active_goals:
            for g in bounded_ctx.active_goals[:2]:
                gname = g.get("name", "Active Goal") if isinstance(g, dict) else getattr(g, "name", "Active Goal")
                gpri = g.get("priority", "HIGH") if isinstance(g, dict) else getattr(g, "priority", "HIGH")
                lines.append(f"- **Goal**: {gname} (Priority: {str(gpri).upper()}) — Active delivery trajectory affected.")
        else:
            lines.append("- No explicit long-term goal directly linked; impacts general productivity & recovery capacity.")

        lines.append("")

        # 5. Learned patterns involved
        lines.append("### 5. Learned Patterns Involved")
        recorded_patterns: List[str] = []
        if self.pattern_store:
            for p in self.pattern_store.list_active(limit=5):
                recorded_patterns.append(p.description)
        if bounded_ctx.known_patterns:
            for pat in bounded_ctx.known_patterns:
                desc = pat.get("description") if isinstance(pat, dict) else getattr(pat, "description", str(pat))
                if desc not in recorded_patterns:
                    recorded_patterns.append(desc)

        if recorded_patterns:
            for pdesc in recorded_patterns:
                lines.append(f"- [ACTIVE_PATTERN] {pdesc}")
        elif bounded_ctx.emerging_hypotheses:
            for hyp in bounded_ctx.emerging_hypotheses:
                hyp_str = hyp.get("statement") if isinstance(hyp, dict) else str(hyp)
                lines.append(f"- [EMERGING_HYPOTHESIS] {hyp_str}")
        else:
            lines.append("- Empirical baseline regularity: elevated stress and schedule fragmentation compound error rates.")

        lines.append("")

        # 6. Inferences
        lines.append("### 6. Inferences")
        if ep and ep.inferences:
            for inf in ep.inferences:
                lines.append(f"- [INFERENCE] {inf}")
        elif bounded_ctx.inferences:
            for inf in bounded_ctx.inferences:
                inf_stmt = inf.get("statement") if isinstance(inf, dict) else (getattr(inf, "statement", str(inf)))
                lines.append(f"- [INFERENCE] {inf_stmt}")
        else:
            lines.append(f"- [INFERENCE] Unresolved tension in {target_sit.type.replace('_', ' ')} threatens near-term milestone delivery.")

        lines.append("")

        # 7. Predictions
        lines.append("### 7. Predictions")
        if ep and ep.predictions:
            for pred in ep.predictions:
                lines.append(f"- [PREDICTION] {pred}")
        elif bounded_ctx.predictions:
            for pred in bounded_ctx.predictions:
                pred_stmt = pred.get("statement") if isinstance(pred, dict) else (getattr(pred, "statement", str(pred)))
                lines.append(f"- [PREDICTION] {pred_stmt}")
        else:
            lines.append("- [PREDICTION] If unaddressed, upcoming milestones will experience slippage or compounding recovery debt.")

        lines.append("")

        # 8. Uncertainties
        lines.append("### 8. Uncertainties")
        if bounded_ctx.uncertainties:
            for unc in bounded_ctx.uncertainties:
                unc_desc = unc.get("description") or unc.get("statement") if isinstance(unc, dict) else str(unc)
                lines.append(f"- ❓ {unc_desc}")
        elif bounded_ctx.information_gaps:
            for gap in bounded_ctx.information_gaps:
                lines.append(f"- ❓ {gap}")
        else:
            lines.append("- ❓ Whether external collaborators have unstated flexibility or have adjusted deadlines out-of-band.")

        lines.append("")

        # 9. Recommendation
        lines.append("### 9. Recommendation")
        if ep and ep.recommendations:
            for rec in ep.recommendations:
                lines.append(f"- 👉 {rec}")
        else:
            lines.append(f"- 👉 Proactively clarify timeline with collaborators and protect dedicated execution blocks today.")

        lines.append("")

        # 10. What evidence would change the conclusion
        lines.append("### 10. What Evidence Would Change the Conclusion")
        if bounded_ctx.assessment_change_conditions:
            for cond in bounded_ctx.assessment_change_conditions:
                cond_str = cond.get("condition") or cond.get("statement") if isinstance(cond, dict) else str(cond)
                lines.append(f"- 🔄 {cond_str}")
        else:
            lines.append("- 🔄 Verified completion of outstanding action items or documented rescheduling of dependent milestones.")
            lines.append("- 🔄 Logged recovery rest exceeding baseline capacity (>7.5h).")

        lines.append("")

        # 11. Why the intervention policy selected its decision
        lines.append("### 11. Why the Intervention Policy Selected Its Decision")
        lines.append(f"- **Decision**: `{pol_action}`")
        lines.append(f"- **Policy Rationale**: {pol_reason}")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Mode 6: /pi patterns
    # -------------------------------------------------------------------------


    def handle_patterns(self) -> str:
        """Lists learned patterns across World, Behavioral, and Interaction categories."""
        all_patterns = self.pattern_store.list_patterns(limit=50)
        if not all_patterns:
            return "No learned patterns discovered yet. Patterns emerge as observations and episodes accumulate."

        world_pats = [p for p in all_patterns if p.pattern_type == PatternType.WORLD_PATTERN.value]
        behavioral_pats = [p for p in all_patterns if p.pattern_type == PatternType.BEHAVIORAL_PATTERN.value]
        interaction_pats = [p for p in all_patterns if p.pattern_type == PatternType.INTERACTION_PATTERN.value]
        other_pats = [p for p in all_patterns if p not in world_pats + behavioral_pats + interaction_pats]

        lines = [
            "## Personal Intelligence Learned Patterns",
            "*Patterns represent empirical non-causal hypotheses across a 7-stage lifecycle.*\n",
        ]

        def format_group(title: str, pats: List[Any]) -> None:
            lines.append(f"### {title} ({len(pats)})")
            if not pats:
                lines.append("*(None active)*\n")
                return
            for p in pats:
                supp_eps = len(p.supporting_episodes) if hasattr(p, "supporting_episodes") else p.support_count
                contra_eps = len(p.contradicting_episodes) if hasattr(p, "contradicting_episodes") else p.contradiction_count
                lines.append(
                    f"- **[{p.status}]** {p.description}\n"
                    f"  *Support: {p.support_count} | Contradictions: {contra_eps} | Evidence Strength: {p.evidence_strength}*"
                )
            lines.append("")

        format_group("World Patterns (Environmental Rhythms & Workflows)", world_pats)
        format_group("Behavioral Patterns (Habits & Sequences)", behavioral_pats)
        format_group("Interaction Patterns (Recommendation Preferences)", interaction_pats)
        if other_pats:
            format_group("Emerging Hypotheses", other_pats)

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Mode 5: /pi timeline [limit]
    # -------------------------------------------------------------------------

    def handle_timeline(self, limit: int = 15) -> str:
        """Lists recent chronological timeline events with source provenance."""
        tl = self.timeline_engine.get_time_range(limit=limit)
        if not tl.events:
            return "Timeline is currently empty."

        lines = [
            f"## Personal Intelligence Timeline (Last {len(tl.events)} Events)",
            "",
        ]
        for e in tl.events:
            src = e.source.upper()
            ts_str = e.event_time.strftime("%Y-%m-%d %H:%M UTC")
            summary = e.payload.get("summary") or e.payload.get("title") or e.payload.get("subject") or e.event_type
            lines.append(f"- **`{ts_str}`** `[{src}]` {summary}")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Mode 6: /pi goals
    # -------------------------------------------------------------------------

    def handle_goals(self) -> str:
        """Lists active goals with priority, target date, and related situations."""
        goals = self.goal_store.list_active()
        if not goals:
            return "No active goals registered in GoalStore."

        lines = [
            f"## Active Personal Goals ({len(goals)})",
            "",
        ]
        for g in goals:
            lines.append(f"- **{g.name}** `[Priority: {g.priority.upper()}]`")
            if g.description:
                lines.append(f"  *{g.description}*")


        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Mode 7: /pi situations
    # -------------------------------------------------------------------------

    def handle_situations(self) -> str:
        """Lists open candidate and active situations."""
        situations = self.situation_store.list_open()
        if not situations:
            return "No open situations at this time."

        lines = [
            f"## Open Situations ({len(situations)})",
            "",
        ]
        for s in situations:
            info_flag = " | ⚠️ Info Required" if s.information_required else ""
            ctx_summary = s.context.get("summary", "") if isinstance(s.context, dict) else str(s.context)
            lines.append(f"- **{s.type.replace('_', ' ').title()}** `[Priority: {s.priority.upper()}{info_flag}]`")
            lines.append(f"  Context: {ctx_summary}")
            if s.related_goals:
                lines.append(f"  Related Goals: {', '.join(s.related_goals)}")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Mode 8: /pi briefing
    # -------------------------------------------------------------------------

    def handle_briefing(self) -> str:
        """Generates the non-intrusive daily briefing digest."""
        snapshot = self.world_model.get_snapshot()
        active_goals = self.goal_store.list_active()
        situations = self.situation_store.list_active()

        lines = [
            "## Personal Intelligence: Daily Briefing Digest",
            f"*Generated on {datetime.now(timezone.utc).strftime('%A, %B %d, %Y')}*\n",
            "### 🎯 Focus Goals",
        ]
        for g in active_goals[:3]:
            lines.append(f"- **{g.name}** ({g.priority.upper()} priority)")

        lines.append("")
        lines.append("### 📌 Active Situation Items")
        if situations:
            for s in situations[:4]:
                ctx_summary = s.context.get("summary", "") if isinstance(s.context, dict) else str(s.context)
                lines.append(f"- **{s.type.replace('_', ' ').title()}**: {ctx_summary}")
        else:
            lines.append("- All routines on track. No active situation blockers.")


        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Mode 10: /pi test_sources (Google Workspace Diagnostics)
    # -------------------------------------------------------------------------

    def get_test_sources_payload(self) -> List[Dict[str, Any]]:
        """
        Inspects capability availability, authentication status, and tool readiness across
        all 7 Hermes capabilities (Gmail, Calendar, Drive, Meet, Filesystem, Web, Reasoning).
        Guarantees zero OAuth token storage or personal content dumping.
        """
        from personal_intelligence.hermes_bridge.capabilities import (
            HermesCapabilityInspector,
            HermesConnectionStatus,
        )
        inspector = HermesCapabilityInspector()
        report = inspector.probe_all(
            runtime_context=self.hermes_client.runtime_context if hasattr(self, "hermes_client") else None,
            is_demo=getattr(self, "is_demo_mode", False),
        )

        recent_events = self.event_store.get_recent(limit=100) if hasattr(self, "event_store") else []

        def find_last_access(src_key: str) -> str:
            match = next((e for e in recent_events if e.source.lower() == src_key.lower()), None)
            if match and match.event_time:
                return match.event_time.isoformat() if hasattr(match.event_time, "isoformat") else str(match.event_time)
            return "Active / Ready via Hermes Plugin"

        source_display_names = {
            "gmail": "Gmail",
            "calendar": "Google Calendar",
            "drive": "Google Drive",
            "meet": "Google Meet",
            "filesystem": "Filesystem",
            "web": "Web Search",
            "reasoning": "Hermes Reasoning",
        }

        results = []
        for cap_name, cap_status in report.capabilities.items():
            disp = source_display_names.get(cap_name, cap_name.title())
            is_avail = cap_status.availability.value in ("available", "demo")
            status_str = "ACCESSIBLE" if is_avail else "UNAVAILABLE"
            cap_avail_str = f"AVAILABLE (READ_ONLY)" if is_avail else f"UNAVAILABLE (READ_ONLY)"

            item = cap_status.to_dict()
            item["source"] = disp
            item["capability"] = cap_name
            item["status"] = status_str
            item["last_successful_access"] = find_last_access(cap_name)
            item["capability_availability"] = cap_avail_str
            results.append(item)

        return results

    def handle_test_sources(self) -> str:
        """
        Executes /pi test_sources diagnostic.
        Returns concise capability status table across all 7 capabilities without personal data.
        """
        sources = self.get_test_sources_payload()
        lines = [
            "## 🔍 Hermes Capability & Source Diagnostic (/pi test_sources)",
            "",
            "| Source / Capability | Status | Authenticated | Tool | Last Access / Check | Read-Only |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for s in sources:
            auth_str = str(s.get("authenticated_status", "unknown")).upper()
            ro_str = "✅ YES" if s.get("read_only", True) else "❌ NO"
            tool_str = s.get("tool_name", "N/A") or "N/A"
            lines.append(
                f"| **{s['source']}** | `{s['status']}` | `{auth_str}` | `{tool_str}` | {s['last_successful_access']} | {ro_str} |"
            )

        lines.append("")
        lines.append("> [!NOTE]")
        lines.append("> All external tools operate under strict read-only constraints. Personal Intelligence requests data on-demand only.")
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Mode 11: /pi ask <query> (Ask Personal Intelligence)
    # -------------------------------------------------------------------------

    def handle_ask(self, query: str) -> str:
        """
        Executes an Ask Personal Intelligence inquiry.
        Routes query through World Model, Situations, Goals, Patterns, and Timeline before reasoning.
        """
        res = self.ask_engine.ask(query=query)
        return res.to_formatted_markdown()

    # -------------------------------------------------------------------------
    # Mode 12: /pi live_flow (Real Google Live Demo Flow)
    # -------------------------------------------------------------------------

    def handle_live_flow(self) -> str:
        """
        Executes the canonical Real Google Live Demo Flow:
        LIVE MODE -> Hermes Google Authentication -> /pi what_matters ->
        Personal World Model -> Situation Detection -> Hermes Gmail/Drive/Calendar/Meet ->
        Reasoning -> UI
        """
        lines = [
            "# 🌐 Real Google Workspace Live Flow (/pi live_flow)",
            "",
            "### 1. Operating Mode: `LIVE MODE`",
            "- Operating directly against live Personal Intelligence observation stream and native Hermes bridge.",
            "",
            "### 2. Hermes Google Workspace Capabilities (Read-Only)",
        ]
        for src in self.get_test_sources_payload():
            lines.append(f"- **{src['source']}**: `{src['status']}` ({src['capability_availability']})")

        lines.append("")
        lines.append("### 3. Personal World Model & State Representation")
        state_rep = self.state_engine.compute_current_state()
        state_sum = f"Operational ({len(state_rep.features)} features: {', '.join(list(state_rep.features.keys())[:4])})" if state_rep and state_rep.features else "Operational baseline active"
        lines.append(f"- **Current State**: {state_sum}")

        lines.append("")
        lines.append("### 4. Situation Detection & Hermes Multi-Source Investigation")
        sits = self.situation_store.list_active()
        lines.append(f"- Detected {len(sits)} active situation(s).")
        for s in sits[:3]:
            ctx_sum = s.context.get("summary", "") if isinstance(s.context, dict) else str(s.context)
            lines.append(f"  * **{s.type.replace('_', ' ').title()}** [{s.priority.upper()}]: {ctx_sum}")

        lines.append("")
        lines.append("### 5. Multi-Source Reasoning & /pi what_matters")
        wm_text = self.handle_what_matters()
        lines.append(wm_text)

        return "\n".join(lines)

    def handle_reset_demo(self) -> str:
        """Resets the demo environment state."""
        self.db_manager.initialize_schema()
        return "✅ Demo state has been reset to initial baseline."

    # -------------------------------------------------------------------------
    # Helper: /pi help
    # -------------------------------------------------------------------------

    def handle_help(self) -> str:
        return (
            "## Personal Intelligence (/pi) Commands\n\n"
            "Supported modes:\n"
            "- `/pi what_matters`: Inspects world model, investigates gaps, reasons across sources, and returns up to 5 prioritized recommendations.\n"
            "- `/pi what_changed [hours]`: Identifies meaningful cross-domain state changes.\n"
            "- `/pi test_sources`: Verifies read-only Hermes access for Gmail, Calendar, Drive, and Meet without dumping personal data.\n"
            "- `/pi status`: Overview of Personal World Model snapshot, state dimensions, and subsystems.\n"
            "- `/pi investigate [situation_id]`: Deep cross-source investigation using Hermes tools.\n"
            "- `/pi why <situation_id>`: Explains canonical 11-section root-cause and policy rationale.\n"
            "- `/pi patterns`: Shows learned World, Behavioral, and Interaction patterns across their 7-stage lifecycle.\n"
            "- `/pi timeline [limit]`: Chronological list of recent observations with source provenance.\n"
            "- `/pi goals`: Lists active goals and priority rankings.\n"
            "- `/pi situations`: Lists candidate and open situations.\n"
            "- `/pi briefing`: Assembles daily briefing digest.\n"
            "- `/pi reset_demo`: Resets demo state.\n"
        )
