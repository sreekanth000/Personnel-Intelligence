"""
Context construction and investigation prompt builder for Hermes Agent runtime invocations.
Transforms a Situation into a bounded, relevance-filtered cross-domain reasoning context with full provenance.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set
import uuid

from personal_intelligence.core.context.models import BoundedReasoningContext
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.goals.engine import GoalEngine
from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.patterns.models import LearnedPattern
from personal_intelligence.core.situations.models import Situation
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.core.timeline.models import Timeline


def classify_event_domain(event_type: str, source: str = "", payload: Optional[Dict[str, Any]] = None) -> str:
    """
    Categorizes an event into a high-level generic domain for cross-domain synthesis.
    No domain agents are used; this is a deterministic classifier for multi-domain bounding.
    """
    et = (event_type or "").lower()
    src = (source or "").lower()
    pay_str = str(payload or {}).lower()
    combined = f"{et} {src} {pay_str}"

    # 1. Biometrics & Health (Sleep, recovery, heart rate, workouts, vitals, steps)
    if any(k in combined for k in [
        "sleep", "oura", "whoop", "heart_rate", "hrv", "workout", "exercise",
        "strava", "fitbit", "steps", "health", "vitals", "recovery", "strain", "run", "cycling"
    ]):
        return "biometrics_health"

    # 2. Schedule & Workload (Calendar, meetings, deadlines, tasks, PRs, work)
    if any(k in combined for k in [
        "calendar", "meeting", "gcal", "outlook", "deadline", "task", "jira",
        "github", "commit", "workload", "focus", "work", "presentation", "interview"
    ]):
        return "schedule_work"

    # 3. Mobility & Transit (Train, flight, transit, commute, tickets, travel)
    if any(k in combined for k in [
        "train", "transit", "flight", "airline", "amtrak", "commute", "uber",
        "lyft", "ticket", "boarding", "departure", "trip", "travel", "delay"
    ]):
        return "mobility_transit"

    # 4. Location & Environment (GPS, weather, forecast, rain, temp, geo)
    if any(k in combined for k in [
        "location", "geo", "gps", "weather", "forecast", "temp", "rain",
        "storm", "air_quality", "ambient", "environment", "celsius", "humidity"
    ]):
        return "location_environment"

    # 5. Device & Focus Activity (App switch, browser, editor, window, screen, coding, activity)
    if any(k in combined for k in [
        "app_switch", "browser", "editor", "keystroke", "window", "desktop",
        "screen", "device", "input", "tab", "vscode", "terminal", "coding", "activity", "monitor"
    ]):
        return "device_activity"

    # 6. Goals & Intentions
    if any(k in combined for k in ["goal", "intention", "milestone", "target"]):
        return "goals_intentions"

    return "generic_observation"


def classify_state_feature_domain(feature_name: str, source: str = "") -> str:
    """Categorizes a state feature dimension into its primary generic domain."""
    return classify_event_domain(feature_name, source)


class ContextBuilder:
    """
    Assembles a bounded, relevance-filtered cross-domain reasoning context for Hermes.
    Produces a structured epistemic context strictly separated into:
      1. OPEN_SITUATION
      2. OBSERVED_FACTS (verified facts with provenance)
      3. INFERENCES (analytical deductions, never presented as facts)
      4. PREDICTIONS (forward trajectory forecasts)
      5. KNOWN_PATTERNS (empirical recurring patterns)
      6. EMERGING_HYPOTHESES (candidate explanations)
      7. ACTIVE_GOALS (current active user goals enriched by GoalEngine)
      8. RELEVANT_TIMELINE (bounded chronological events)
      9. INFORMATION_GAPS (unknowns to investigate)
      10. UNCERTAINTIES (low-confidence signals and ambiguities)

    Guarantees:
      - Strict token bounding (target 500–2,000 tokens).
      - Every observed fact contains origin provenance coordinates.
      - Never converts an inference into a fact.
      - Never presents an LLM-generated claim from an old episode as a current fact.
      - Never dumps the complete SQLite database or raw API histories.
    """

    def __init__(
        self,
        timeline_engine: Optional[TimelineEngine] = None,
        goal_store: Optional[GoalStore] = None,
        situation_store: Optional[SituationStore] = None,
        goal_engine: Optional[GoalEngine] = None,
        recent_window_minutes: int = 120,
        max_recent_events: int = 15,
        max_historical_events: int = 10,
        max_goals: int = 5,
        max_patterns: int = 5,
        max_similar_situations: int = 3,
        max_recent_episodes: int = 3,
        max_facts: int = 15,
        max_tokens: int = 2000,
        auditor: Optional[Any] = None,
    ) -> None:
        self.timeline_engine = timeline_engine
        self.goal_store = goal_store
        self.situation_store = situation_store
        self.goal_engine = goal_engine or (GoalEngine(goal_store=self.goal_store, timeline_engine=self.timeline_engine) if self.goal_store else None)
        self.recent_window_minutes = recent_window_minutes
        self.max_recent_events = max_recent_events
        self.max_historical_events = max_historical_events
        self.max_goals = max_goals
        self.max_patterns = max_patterns
        self.max_similar_situations = max_similar_situations
        self.max_recent_episodes = max_recent_episodes
        self.max_facts = max_facts
        self.max_tokens = max(500, min(max_tokens, 8000))
        self.auditor = auditor

    def build_bounded_context(
        self,
        situation: Situation,
        current_state: StateRepresentation,
        timeline: Optional[Timeline] = None,
        goals: Optional[List[Goal]] = None,
        patterns: Optional[List[LearnedPattern]] = None,
        episodes: Optional[List[Any]] = None,
        objective: Optional[str] = None,
    ) -> BoundedReasoningContext:
        """
        Constructs a complete BoundedReasoningContext for the given Situation across all relevant domains.
        """
        ref_dt = current_state.timestamp or datetime.now(timezone.utc)
        ref_iso = format_iso8601(ref_dt)

        # 1. State Representation with full provenance and domain tagging
        formatted_state = self._format_state(current_state)

        # 2. Extract evidence references from situation
        evidence_event_ids = {
            item.replace("event:", "") for item in situation.evidence if str(item).startswith("event:")
        }

        # 3. Identify active domain anchors from State and Goals
        active_state_domains = {
            feat["domain"] for feat in formatted_state.get("features", [])
        }
        active_goals = self._extract_active_goals(situation, goals)
        active_goal_domains = {
            classify_event_domain(g["name"], g["description"]) for g in active_goals
        }
        all_anchor_domains = active_state_domains | active_goal_domains

        # 4. Relevant Recent Timeline with Cross-Domain Relevance & Diversity Scoring
        recent_events = self._extract_recent_events(
            timeline=timeline,
            ref_dt=ref_dt,
            situation=situation,
            evidence_ids=evidence_event_ids,
            anchor_domains=all_anchor_domains,
        )

        # 5. Relevant Historical Events across domains
        historical_events = self._extract_historical_events(
            timeline=timeline,
            ref_dt=ref_dt,
            situation=situation,
            evidence_ids=evidence_event_ids,
            recent_ids={e["event_id"] for e in recent_events},
            anchor_domains=all_anchor_domains,
        )

        # 6. Known Patterns (Filtered by activity/cadence)
        known_patterns = self._extract_known_patterns(current_state, patterns)

        # 7. Similar Past Situations
        similar_past = self._extract_similar_past_situations(situation)

        # 8. Recent Reasoning Episodes (Preserved as past cycle inferences, never raw facts)
        recent_episodes = self._extract_recent_episodes(situation, episodes)

        # 9. Compute Cross-Domain Breakdown and Active Domains
        domain_breakdown: Dict[str, int] = defaultdict(int)
        for feat in formatted_state.get("features", []):
            domain_breakdown[feat["domain"]] += 1
        for e in recent_events:
            domain_breakdown[e.get("domain", "generic_observation")] += 1
        for e in historical_events:
            domain_breakdown[e.get("domain", "generic_observation")] += 1
        for g in active_goals:
            g_dom = classify_event_domain(g["name"], g["description"])
            domain_breakdown[g_dom] += 1

        cross_domain_domains = sorted(list(domain_breakdown.keys()))

        # 10. Emerging Hypotheses (Deterministic candidate explanations)
        emerging_hypotheses = self._generate_emerging_hypotheses(
            situation, current_state, recent_events, cross_domain_domains
        )

        # 11. Uncertainties & Ambiguities
        uncertainties = self._extract_uncertainties(current_state, situation, recent_events)

        # 12. Observed Facts (Verified ground-truth with provenance)
        observed_facts = self._extract_observed_facts(current_state, recent_events, situation)

        # 13. Derived Inferences (System inferences + past episode evaluations)
        inferences = self._extract_inferences(situation, current_state, recent_episodes, cross_domain_domains)

        # 14. Downstream Predictions (Forward trajectory forecasts)
        predictions = self._extract_predictions(situation, current_state, active_goals, timeline)

        # 15. Information Gaps (Outstanding unknowns)
        information_gaps = self._extract_information_gaps(situation)

        # 16. Assessment Change Conditions (Concrete conditions that alter or resolve reasoning)
        assessment_change_conditions = self._extract_assessment_change_conditions(
            situation=situation,
            current_state=current_state,
            active_goals=active_goals,
            uncertainties=uncertainties,
        )

        default_obj = f"Evaluate situational risk and bounded reasoning for '{situation.type}'"
        ctx = BoundedReasoningContext(
            situation=situation.to_dict(),
            current_state=formatted_state,
            relevant_recent_timeline=recent_events,
            relevant_historical_events=historical_events,
            active_goals=active_goals,
            known_patterns=known_patterns,
            emerging_hypotheses=emerging_hypotheses,
            similar_past_situations=similar_past,
            recent_reasoning_episodes=recent_episodes,
            uncertainties=uncertainties,
            observed_facts=observed_facts,
            inferences=inferences,
            predictions=predictions,
            information_gaps=information_gaps,
            assessment_change_conditions=assessment_change_conditions,
            objective=objective or default_obj,
            metadata={
                "recent_event_count": len(recent_events),
                "historical_event_count": len(historical_events),
                "active_goal_count": len(active_goals),
                "pattern_count": len(known_patterns),
                "hypothesis_count": len(emerging_hypotheses),
                "uncertainty_count": len(uncertainties),
                "observed_facts_count": len(observed_facts),
                "inferences_count": len(inferences),
                "predictions_count": len(predictions),
                "information_gaps_count": len(information_gaps),
                "assessment_change_conditions_count": len(assessment_change_conditions),
                "cross_domain_domains": cross_domain_domains,
                "domain_breakdown": dict(domain_breakdown),
                "domain_count": len(cross_domain_domains),
                "max_tokens_budget": self.max_tokens,
            },
        )

        # Audit context access if auditor is configured
        if self.auditor is not None:
            self.auditor.record_access(
                accessor="hermes_reasoning",
                situation_id=situation.id,
                events_accessed_count=len(recent_events) + len(historical_events),
                features_accessed=[f["state_key"] for f in formatted_state.get("features", [])],
                sensitivity_level="standard",
                purpose=objective or default_obj,
                metadata={"cross_domain_count": len(cross_domain_domains)},
            )

        return ctx

    def build_cross_source_context(
        self,
        situation: Situation,
        current_state: StateRepresentation,
        evidence_bundle: Any,  # CrossSourceEvidenceBundle — avoid circular import
        timeline: Optional[Timeline] = None,
        goals: Optional[List[Goal]] = None,
        patterns: Optional[List[LearnedPattern]] = None,
        episodes: Optional[List[Any]] = None,
        available_hermes_tools: Optional[List[str]] = None,
    ) -> BoundedReasoningContext:
        """
        Assembles a unified cross-source BoundedReasoningContext from a CrossSourceEvidenceBundle.

        The resulting context is NOT a per-source summary — it integrates all source evidence
        into a single coherent situation context, augmented with:
          - Which Hermes tools are available to resolve remaining unknowns
          - A unified evidence narrative across gmail / drive / meet / calendar / filesystem
          - Remaining unresolved information gaps as named uncertainties

        This context is intended for ReasoningWorkflow.run_investigation_synthesis().
        """
        # Start with the standard bounded context as the base
        base_ctx = self.build_bounded_context(
            situation=situation,
            current_state=current_state,
            timeline=timeline,
            goals=goals,
            patterns=patterns,
            episodes=episodes,
            objective=(
                f"Cross-source unified reasoning for '{situation.type}' situation. "
                "Reason across all Hermes sources as a single unified context. "
                "Do NOT produce per-source summaries."
            ),
        )

        # Build unified evidence narrative from the bundle
        unified_narrative = evidence_bundle.to_unified_context_string()

        # Add cross-source evidence as emerging hypotheses (structured, not raw)
        all_facts = evidence_bundle.all_facts()
        if all_facts:
            cross_source_hypothesis = {
                "hypothesis_id": "cross_source_unified",
                "statement": unified_narrative[:2000],
                "confidence": 0.6,
                "domains": list(evidence_bundle.facts_by_source.keys()),
                "source": "cross_source_investigation",
            }
            updated_hypotheses = list(base_ctx.emerging_hypotheses)
            updated_hypotheses.insert(0, cross_source_hypothesis)
        else:
            updated_hypotheses = list(base_ctx.emerging_hypotheses)

        # Add remaining unknowns as explicit uncertainties
        updated_uncertainties = list(base_ctx.uncertainties)
        for unk in evidence_bundle.remaining_unknowns[:5]:
            updated_uncertainties.append({
                "uncertainty_id": f"gap:{unk[:30]}",
                "type": "investigation_gap",
                "description": unk,
                "source": "investigation_gap",
                "domain": "cross_source",
                "potential_impact": "medium",
                "impact": "medium",
            })

        # Extract augmented observed facts from evidence bundle
        observed_facts = self._extract_observed_facts(
            current_state=current_state,
            recent_events=base_ctx.relevant_recent_timeline,
            situation=situation,
            evidence_bundle=evidence_bundle,
        )

        # Extract information gaps
        information_gaps = self._extract_information_gaps(
            situation=situation,
            evidence_bundle=evidence_bundle,
        )

        # Build Hermes tool hints for any remaining gaps
        tool_hints: List[str] = list(available_hermes_tools or [])
        if not tool_hints and evidence_bundle.remaining_unknowns:
            from personal_intelligence.hermes_bridge.situation_investigation import (
                HERMES_SOURCE_HINTS,
            )
            for src in evidence_bundle.facts_by_source:
                if src in HERMES_SOURCE_HINTS:
                    tool_hints.append(HERMES_SOURCE_HINTS[src])

        # Update metadata with cross-source context markers
        updated_metadata = dict(base_ctx.metadata)
        updated_metadata.update({
            "is_cross_source_context": True,
            "sources_investigated": list(evidence_bundle.facts_by_source.keys()),
            "source_references": evidence_bundle.source_references[:10],
            "investigation_task_ids": evidence_bundle.investigation_task_ids,
            "remaining_unknowns_count": len(evidence_bundle.remaining_unknowns),
            "hermes_tool_hints": tool_hints[:5],
            "hermes_tools_used": evidence_bundle.hermes_tools_used,
            "facts_by_source_count": {
                src: len(facts) for src, facts in evidence_bundle.facts_by_source.items()
            },
        })

        return BoundedReasoningContext(
            situation=base_ctx.situation,
            current_state=base_ctx.current_state,
            relevant_recent_timeline=base_ctx.relevant_recent_timeline,
            relevant_historical_events=base_ctx.relevant_historical_events,
            active_goals=base_ctx.active_goals,
            known_patterns=base_ctx.known_patterns,
            emerging_hypotheses=updated_hypotheses,
            similar_past_situations=base_ctx.similar_past_situations,
            recent_reasoning_episodes=base_ctx.recent_reasoning_episodes,
            uncertainties=updated_uncertainties,
            observed_facts=observed_facts,
            inferences=base_ctx.inferences,
            predictions=base_ctx.predictions,
            information_gaps=information_gaps,
            objective=base_ctx.objective,
            context_id=base_ctx.context_id,
            created_at=base_ctx.created_at,
            metadata=updated_metadata,
        )

    # --- Epistemic Section Extractors ---

    def _extract_observed_facts(
        self,
        current_state: StateRepresentation,
        recent_events: List[Dict[str, Any]],
        situation: Situation,
        evidence_bundle: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extracts verified ground-truth facts with strict provenance.
        Never includes speculative inferences or uncorroborated hypotheses.
        """
        facts: List[Dict[str, Any]] = []

        # 1. Direct state features (verified measurements with source provenance)
        for name, feat in sorted(current_state.features.items()):
            domain = classify_state_feature_domain(feat.name, feat.source)
            facts.append({
                "key": feat.name,
                "value": feat.value,
                "statement": f"State feature '{feat.name}' is {feat.value}",
                "source": feat.source,
                "provenance": f"state:{feat.name}:{feat.source}",
                "timestamp": format_iso8601(feat.timestamp),
                "confidence": "high" if feat.confidence >= 0.85 else "moderate",
                "domain": domain,
            })

        # 2. Corroborated facts from evidence bundle if present
        if evidence_bundle is not None:
            for src, src_facts in getattr(evidence_bundle, "facts_by_source", {}).items():
                for f_text in src_facts:
                    facts.append({
                        "key": f"evidence_{src}",
                        "value": f_text,
                        "statement": f_text,
                        "source": src,
                        "provenance": f"{src}:evidence",
                        "timestamp": format_iso8601(current_state.timestamp or datetime.now(timezone.utc)),
                        "confidence": "high",
                        "domain": classify_event_domain("", src, {}),
                    })

        # 3. Direct factual findings in situation evidence
        for ev in situation.evidence:
            ev_str = str(ev)
            if ev_str.startswith("finding:"):
                finding_txt = ev_str[8:]
                facts.append({
                    "key": "situation_evidence_finding",
                    "value": finding_txt,
                    "statement": finding_txt,
                    "source": "situation_evidence",
                    "provenance": "hermes_investigation",
                    "timestamp": format_iso8601(situation.updated_at or datetime.now(timezone.utc)),
                    "confidence": "high",
                    "domain": "generic_observation",
                })

        return facts[:self.max_facts]

    def _extract_inferences(
        self,
        situation: Situation,
        current_state: StateRepresentation,
        recent_episodes: List[Dict[str, Any]],
        cross_domain_domains: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Extracts derived analytical inferences with explicit provenance.
        Never presents inferences or past reasoning claims as direct facts.
        """
        inferences: List[Dict[str, Any]] = []

        # Multi-domain cross-domain interplay inference
        if len(cross_domain_domains) >= 2:
            domains_str = ", ".join([d.replace("_", " ").title() for d in cross_domain_domains])
            inferences.append({
                "origin": "cross_domain_analysis",
                "statement": f"Multi-domain interplay detected across {len(cross_domain_domains)} domains ({domains_str}).",
                "domain": "cross_domain",
            })

        # Past episode assessments — explicitly tagged as past cycle inferences
        for ep in recent_episodes:
            ep_id = ep.get("episode_id", "past_episode")
            trig = ep.get("trigger_type", "reasoning_cycle")
            inferences.append({
                "origin": f"past_episode:{ep_id}",
                "statement": f"Prior reasoning cycle evaluated trigger '{trig}' (status: {ep.get('status', 'completed')}).",
                "domain": "reasoning_history",
            })

        return inferences

    def _extract_predictions(
        self,
        situation: Situation,
        current_state: StateRepresentation,
        active_goals: List[Dict[str, Any]],
        timeline: Optional[Timeline],
    ) -> List[Dict[str, Any]]:
        """
        Formulates forward-looking timeline projections and trajectory forecasts.
        """
        predictions: List[Dict[str, Any]] = []
        ctx = situation.context or {}

        # Trajectory forecast based on situation type
        stype = situation.type.lower()
        if "prolonged" in stype:
            dur = ctx.get("duration_minutes", 0)
            predictions.append({
                "scope": "workload_trajectory",
                "statement": f"Sustained activity duration ({dur:.0f}m) projected to compress downstream schedule availability.",
            })
        elif "conflict" in stype or "commitment" in stype:
            predictions.append({
                "scope": "commitment_trajectory",
                "statement": "Overlapping obligations will require explicit prioritization before scheduled milestones.",
            })
        elif "risk" in stype:
            predictions.append({
                "scope": "goal_trajectory",
                "statement": "Execution velocity on priority goals may experience delay if friction is unmitigated.",
            })

        return predictions

    def _extract_information_gaps(
        self,
        situation: Situation,
        evidence_bundle: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Identifies outstanding questions / missing information for external Hermes tools.
        """
        gaps: List[Dict[str, Any]] = []
        if situation.investigation_target:
            gaps.append({
                "question": situation.investigation_target,
                "type": "investigation_target",
            })

        if evidence_bundle is not None:
            for unk in getattr(evidence_bundle, "remaining_unknowns", []):
                if unk not in [g["question"] for g in gaps]:
                    gaps.append({
                        "question": unk,
                        "type": "bundle_unknown",
                    })

        return gaps


    # --- Internal Relevance & Diversity Filter Helpers ---

    def _format_state(self, current_state: StateRepresentation) -> Dict[str, Any]:
        """Formats current state with explicit state_key provenance and domain tagging."""
        features_list = []
        for name, feat in sorted(current_state.features.items()):
            domain = classify_state_feature_domain(feat.name, feat.source)
            features_list.append({
                "state_key": feat.name,
                "value": feat.value,
                "source": feat.source,
                "domain": domain,
                "timestamp": format_iso8601(feat.timestamp),
                "confidence": feat.confidence,
                "metadata": feat.metadata,
            })
        return {
            "timestamp": format_iso8601(current_state.timestamp),
            "features": features_list,
        }

    def _extract_recent_events(
        self,
        timeline: Optional[Timeline],
        ref_dt: datetime,
        situation: Situation,
        evidence_ids: Set[str],
        anchor_domains: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Slices relevant events within recent window using multi-domain relevance scoring
        and cross-domain diversity allocation.
        """
        if not timeline or timeline.is_empty:
            return []

        recent_cutoff = ref_dt - timedelta(minutes=self.recent_window_minutes)
        candidates = []
        domains_present = anchor_domains or set()

        # Score candidate events
        scored_events: List[Dict[str, Any]] = []
        for evt in timeline.events:
            is_recent = evt.event_time >= recent_cutoff
            is_evidence = evt.id in evidence_ids
            if not (is_recent or is_evidence):
                continue

            dom = classify_event_domain(evt.event_type, evt.source, evt.payload)

            # Relevance Score Calculation
            score = 0.0

            # 1. Evidence bonus
            if is_evidence:
                score += 15.0

            # 2. Temporal recency score (0 to 5 points)
            age_mins = max(0.0, (ref_dt - evt.event_time).total_seconds() / 60.0)
            recency_score = max(0.0, 5.0 * (1.0 - (age_mins / max(1.0, float(self.recent_window_minutes)))))
            score += recency_score

            # 3. Anchor domain match bonus
            if dom in domains_present:
                score += 5.0

            # 4. Situation type / context match
            stype = situation.type.lower()
            if any(k in evt.event_type.lower() for k in stype.split("_")):
                score += 4.0

            scored_events.append({
                "event": evt,
                "domain": dom,
                "score": score,
            })

        if not scored_events:
            return []

        # Cross-Domain Diversity Allocation:
        # Group candidates by domain and ensure top event from each domain is included
        by_domain: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in scored_events:
            by_domain[item["domain"]].append(item)

        for d in by_domain:
            by_domain[d].sort(key=lambda x: x["score"], reverse=True)

        selected_events: List[Event] = []
        selected_ids: Set[str] = set()

        # Pass 1: Select top event from each domain to guarantee cross-domain diversity
        for dom, d_events in sorted(by_domain.items()):
            if len(selected_events) >= self.max_recent_events:
                break
            top_evt = d_events[0]["event"]
            if top_evt.id not in selected_ids:
                selected_events.append(top_evt)
                selected_ids.add(top_evt.id)

        # Pass 2: Fill remaining capacity with overall highest-scoring events
        remaining_capacity = self.max_recent_events - len(selected_events)
        if remaining_capacity > 0:
            all_remaining = [
                item for item in scored_events if item["event"].id not in selected_ids
            ]
            all_remaining.sort(key=lambda x: x["score"], reverse=True)
            for item in all_remaining[:remaining_capacity]:
                selected_events.append(item["event"])
                selected_ids.add(item["event"].id)

        # Sort final selection chronologically
        selected_events.sort(key=lambda e: (e.event_time, e.ingested_at))

        return [
            {
                "event_id": e.id,
                "timestamp": format_iso8601(e.event_time),
                "event_type": e.event_type,
                "source": e.source,
                "domain": classify_event_domain(e.event_type, e.source, e.payload),
                "subject": e.subject_id,
                "payload": e.payload,
                "confidence": e.confidence,
            }
            for e in selected_events
        ]

    def _extract_historical_events(
        self,
        timeline: Optional[Timeline],
        ref_dt: datetime,
        situation: Situation,
        evidence_ids: Set[str],
        recent_ids: Set[str],
        anchor_domains: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Queries older relevant events matching active domains, situation type, or evidence.
        Prevents full-log dumping while preserving cross-domain longitudinal depth.
        """
        if not timeline or timeline.is_empty:
            return []

        recent_cutoff = ref_dt - timedelta(minutes=self.recent_window_minutes)
        relevant_types = {situation.type}
        if "divergent_features" in situation.context:
            for feat in situation.context["divergent_features"]:
                relevant_types.add(feat)

        target_domains = anchor_domains or set()

        historical: List[Event] = []
        for evt in timeline.events:
            if evt.id in recent_ids:
                continue
            if evt.event_time < recent_cutoff:
                dom = classify_event_domain(evt.event_type, evt.source, evt.payload)
                if (
                    evt.event_type in relevant_types
                    or evt.id in evidence_ids
                    or dom in target_domains
                ):
                    historical.append(evt)

        sliced = historical[-self.max_historical_events:]
        return [
            {
                "event_id": e.id,
                "timestamp": format_iso8601(e.event_time),
                "event_type": e.event_type,
                "source": e.source,
                "domain": classify_event_domain(e.event_type, e.source, e.payload),
                "subject": e.subject_id,
                "payload": e.payload,
                "confidence": e.confidence,
            }
            for e in sliced
        ]

    def _extract_active_goals(
        self,
        situation: Situation,
        goals: Optional[List[Goal]],
    ) -> List[Dict[str, Any]]:
        """Filters and ranks active goals using GoalEngine deterministic ranking."""
        raw_goals = list(goals or [])
        if not raw_goals and self.goal_store:
            raw_goals = self.goal_store.list_active_goals()

        # Strictly exclude completed, abandoned, or archived goals
        candidate_goals = [
            g for g in raw_goals
            if (g.status.value if hasattr(g.status, "value") else str(g.status)).lower() == "active"
        ]

        if not candidate_goals:
            return []

        # If GoalEngine is available, use rich deterministic situational ranking
        if self.goal_engine:
            ranked_evals = self.goal_engine.rank_goals_for_situation(
                situation=situation,
                goals=candidate_goals,
            )
            sliced = ranked_evals[:self.max_goals]
            return [
                {
                    "goal_id": g_eval["goal_id"],
                    "name": g_eval["goal_name"],
                    "description": next((g.description for g in candidate_goals if g.id == g_eval["goal_id"]), ""),
                    "domain": classify_event_domain(g_eval["goal_name"]),
                    "priority": g_eval["priority"],
                    "status": g_eval["status"],
                    "effective_priority_score": g_eval.get("effective_priority_score"),
                    "urgency_score": g_eval.get("urgency_score"),
                    "relevance_score": g_eval.get("relevance_score"),
                    "is_blocked": g_eval.get("is_blocked", False),
                    "impact": g_eval.get("impact"),
                    "days_until_deadline": g_eval.get("days_until_deadline"),
                }
                for g_eval in sliced
            ]

        # Fallback sorting if GoalEngine is not configured
        priority_order = {
            GoalPriority.CRITICAL.value: 4,
            GoalPriority.HIGH.value: 3,
            GoalPriority.MEDIUM.value: 2,
            GoalPriority.LOW.value: 1,
            GoalPriority.BACKGROUND.value: 0,
        }

        related_set = set(situation.related_goals) if hasattr(situation, "related_goals") else set()
        sorted_goals = sorted(
            candidate_goals,
            key=lambda g: (
                1 if g.id in related_set else 0,
                priority_order.get(g.priority.lower() if isinstance(g.priority, str) else g.priority.value, 0),
            ),
            reverse=True,
        )

        sliced = sorted_goals[:self.max_goals]
        return [
            {
                "goal_id": g.id,
                "name": g.name,
                "description": g.description,
                "domain": classify_event_domain(g.name, g.description),
                "priority": g.priority.value if hasattr(g.priority, "value") else str(g.priority),
                "status": g.status.value if hasattr(g.status, "value") else str(g.status),
                "created_at": format_iso8601(g.created_at),
            }
            for g in sliced
        ]

    def _extract_known_patterns(
        self,
        current_state: StateRepresentation,
        patterns: Optional[List[Any]],
    ) -> List[Dict[str, Any]]:
        """Extracts patterns matching current activity or temporal cadence with lifecycle status."""
        if not patterns:
            return []

        curr_act = str(current_state.get_value("current_activity") or "").lower()
        matching = []
        for p in patterns:
            # Check active status
            is_active = getattr(p, "is_active", True)
            status = getattr(p, "status", "ACTIVE")
            if isinstance(status, str) and status.upper() == "INACTIVE":
                continue
            if not is_active:
                continue

            desc = getattr(p, "description", getattr(p, "name", ""))
            if curr_act and curr_act in desc.lower():
                matching.append(p)
            else:
                matching.append(p)

        sliced = matching[:self.max_patterns]
        result = []
        for p in sliced:
            p_id = getattr(p, "id", getattr(p, "pattern_id", "pat"))
            desc = getattr(p, "description", getattr(p, "name", ""))
            name = getattr(p, "name", desc)
            status = getattr(p, "status", "ACTIVE")
            supp = getattr(p, "support_count", getattr(p, "observation_count", 1))
            strength = getattr(p, "evidence_strength", "moderate")
            conf = getattr(p, "confidence", 0.5)
            cadence = getattr(p, "cadence", "daily")
            cadence_str = cadence.value if hasattr(cadence, "value") else str(cadence)

            result.append({
                "pattern_id": p_id,
                "name": name,
                "description": desc,
                "status": status.value if hasattr(status, "value") else str(status),
                "support_count": supp,
                "evidence_strength": strength,
                "confidence": conf,
                "cadence": cadence_str,
                "typical_time_window": getattr(p, "typical_time_window", None),
            })
        return result

    def _extract_assessment_change_conditions(
        self,
        situation: Situation,
        current_state: StateRepresentation,
        active_goals: List[Dict[str, Any]],
        uncertainties: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Derives concrete, explicit conditions under which this situational assessment
        or risk level would change, be invalidated, or resolve.
        """
        conditions: List[Dict[str, Any]] = []
        stype = situation.type.lower()
        ctx = situation.context or {}

        # 1. Situation-type specific change conditions
        if "conflict" in stype:
            conditions.append({
                "condition": "If either conflicting calendar event is rescheduled or declined by user",
                "effect": "Schedule conflict is resolved; downgrade priority to INFORMATIONAL",
                "target": "schedule_conflict",
            })
            conditions.append({
                "condition": "If user accepts both overlapping meetings explicitly",
                "effect": "Acknowledge intentional double-booking; suppress warning",
                "target": "schedule_conflict",
            })
        elif "goal_risk" in stype or "risk" in stype:
            conditions.append({
                "condition": "If blocking dependency is cleared or marked completed",
                "effect": "Goal execution path is unblocked; resolve goal_risk situation",
                "target": "goal_risk",
            })
            conditions.append({
                "condition": "If user adjusts goal milestone deadline further out",
                "effect": "Time pressure is relieved; recalculate urgency multiplier",
                "target": "goal_deadline",
            })
        elif "forgotten" in stype or "unresolved" in stype or "action" in stype:
            conditions.append({
                "condition": "If outgoing communication or delivery artifact confirms task completion",
                "effect": "Commitment is satisfied; close unresolved action item situation",
                "target": "action_item",
            })
        elif "gap" in stype:
            conditions.append({
                "condition": "If missing reference resource or document is located via tool query",
                "effect": "Information gap is filled; update reasoning context with factual artifact",
                "target": "information_gap",
            })
        elif "novel" in stype:
            conditions.append({
                "condition": "If multi-domain signal variance returns within normal 14-day baseline parameters",
                "effect": "Novel state anomaly has normalized; resolve novel_situation monitoring frame",
                "target": "novel_situation",
            })
        else:
            conditions.append({
                "condition": f"If user takes affirmative action resolving the underlying '{situation.type}' trigger",
                "effect": "Situation status transitions from OPEN to RESOLVED",
                "target": "general_resolution",
            })

        # 2. Uncertainty-driven change conditions
        for u in uncertainties[:2]:
            u_desc = u.get("description", "")
            conditions.append({
                "condition": f"If clarification tool investigation resolves uncertainty: '{u_desc}'",
                "effect": "Refine confidence and adjust recommendation parameters",
                "target": u.get("uncertainty_id", "uncertainty"),
            })

        return conditions

    def _generate_emerging_hypotheses(
        self,
        situation: Situation,
        current_state: StateRepresentation,
        recent_events: List[Dict[str, Any]],
        cross_domain_domains: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Generates deterministic candidate explanations based on situation context, evidence, and cross-domain interplay."""
        hypotheses = []
        stype = situation.type

        # Check for cross-domain interplay
        domains = cross_domain_domains or []
        if len(domains) >= 3:
            domains_formatted = ", ".join([d.replace("_", " ").title() for d in domains])
            hypotheses.append({
                "hypothesis_id": "hyp-cross-domain-interplay",
                "statement": f"Multi-domain interaction detected across {len(domains)} distinct domains ({domains_formatted}); optimal evaluation requires cross-domain synthesis.",
                "confidence": 0.88,
                "basis": domains,
            })

        if stype == "unusual_state":
            hypotheses.append({
                "hypothesis_id": "hyp-unusual-1",
                "statement": "State features exhibit anomalous variance from baseline; unexpected environmental or routine shift.",
                "confidence": situation.novelty or 0.70,
                "basis": list(situation.context.get("divergent_features", {}).keys()),
            })
        elif stype == "prolonged_activity":
            act = situation.context.get("activity", "activity")
            dur = situation.context.get("duration_minutes", 0)
            hypotheses.append({
                "hypothesis_id": "hyp-prolonged-1",
                "statement": f"Extended engagement in '{act}' ({dur:.0f}m) may displace upcoming scheduled commitments.",
                "confidence": 0.85,
                "basis": ["recent_activity_duration", "current_activity"],
            })
        elif stype == "schedule_conflict":
            hypotheses.append({
                "hypothesis_id": "hyp-conflict-1",
                "statement": "Simultaneous calendar events compete for user presence and require prioritization.",
                "confidence": 0.90,
                "basis": [e["event_id"] for e in recent_events if "conflict" in e["event_type"]],
            })
        elif stype == "possible_goal_risk":
            hypotheses.append({
                "hypothesis_id": "hyp-goal-1",
                "statement": "Active high-priority goals are experiencing execution friction under current state conditions.",
                "confidence": 0.75,
                "basis": situation.related_goals,
            })
        else:
            hypotheses.append({
                "hypothesis_id": "hyp-generic-1",
                "statement": f"Emerging situation of type '{stype}' requires multi-event situational reasoning.",
                "confidence": situation.novelty or 0.60,
                "basis": situation.evidence,
            })

        return hypotheses

    def _extract_similar_past_situations(self, situation: Situation) -> List[Dict[str, Any]]:
        """Queries similar past situations using SituationStore."""
        if not self.situation_store:
            return []

        similar = self.situation_store.find_similar(
            situation_type=situation.type,
            related_goals=situation.related_goals,
            active_only=False,
        )

        filtered = [s for s in similar if s.id != situation.id][:self.max_similar_situations]
        return [
            {
                "situation_id": s.id,
                "type": s.type,
                "status": s.status,
                "priority": s.priority,
                "novelty": s.novelty,
                "created_at": format_iso8601(s.created_at),
            }
            for s in filtered
        ]

    def _extract_recent_episodes(
        self,
        situation: Situation,
        episodes: Optional[List[Any]],
    ) -> List[Dict[str, Any]]:
        """Extracts recent reasoning episode records."""
        if not episodes:
            return []

        sliced = episodes[-self.max_recent_episodes:]
        return [
            {
                "episode_id": getattr(e, "episode_id", str(uuid.uuid4())),
                "trigger_type": getattr(e, "trigger_type", "reasoning_cycle"),
                "status": getattr(e, "status", "completed"),
                "started_at": format_iso8601(getattr(e, "started_at", datetime.now(timezone.utc))),
            }
            for e in sliced
        ]

    def _extract_uncertainties(
        self,
        current_state: StateRepresentation,
        situation: Situation,
        recent_events: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Identifies low-confidence signals, missing data, and ambiguities for Hermes to investigate."""
        uncertainties = []

        # 1. Low confidence state dimensions (< 0.80)
        for name, feat in current_state.features.items():
            if feat.confidence < 0.80:
                uncertainties.append({
                    "uncertainty_id": f"unc-conf-{name}",
                    "type": "low_confidence_signal",
                    "description": f"State feature '{name}' has lower confidence ({feat.confidence:.2f}) from source '{feat.source}'.",
                    "potential_impact": "medium",
                })

        # 2. Ambiguous evidence
        if not situation.evidence and not recent_events:
            uncertainties.append({
                "uncertainty_id": "unc-evidence-missing",
                "type": "missing_data",
                "description": "No direct timeline event records currently corroborate this situation frame.",
                "potential_impact": "high",
            })

        return uncertainties

    # --- Legacy Backwards Compatibility API ---

    def build_investigation_context(
        self,
        objective: str,
        situation: Optional[Situation] = None,
        state: Optional[Any] = None,
        events: Optional[List[Event]] = None,
        goals: Optional[List[Goal]] = None,
        constraints: Optional[List[str]] = None,
    ) -> "HermesInvestigationContext":
        """Legacy helper for backwards compatibility."""
        from personal_intelligence.core.context import HermesInvestigationContext
        return HermesInvestigationContext(
            objective=objective,
            situation=situation,
            relevant_events=events or [],
            relevant_goals=goals or [],
            constraints=constraints or [],
        )

    def format_prompt_for_hermes(self, context: Any) -> str:
        """Legacy prompt formatter."""
        if hasattr(context, "to_prompt_string"):
            return context.to_prompt_string()
        if hasattr(context, "objective") and hasattr(context, "situation"):
            sit_type = context.situation.type if context.situation else "unspecified"
            sit_context = context.situation.context.get("summary", "") if context.situation else ""
            goals_str = "\n".join([f"- {g.name}: {g.description}" for g in (context.relevant_goals or [])])
            constraints_str = "\n".join([f"- {c}" for c in (context.constraints or [])])
            return f"""### Personal Intelligence Investigation Request [{getattr(context, 'investigation_id', 'legacy')}]
**Objective**: {context.objective}
**Target Situation**: {sit_type}
**Situation Context**: {sit_context}

#### Relevant Goals:
{goals_str}

#### Constraints:
{constraints_str}
"""
        return str(context)
