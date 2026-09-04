"""
Personal Intelligence Intervention Policy Engine.
Pure categorical, deterministic evaluation governing when to INTERRUPT, BRIEFING,
DEFER, SUPPRESS, or DISCARD without numerical scores or fake confidence values.

Canonical Epistemic & Action Chain:
OBSERVATION -> INFERENCE -> PREDICTION -> RECOMMENDATION -> USER DECISION -> ACTION

V1 has NO autonomous external actions. Recommendations may be shown to the user.
External side effects require explicit user approval (USER DECISION).
InterventionPolicyEngine decides presentation mode ONLY (INTERRUPT, BRIEFING, DEFER, SUPPRESS, DISCARD).
It does NOT execute external actions.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, Union

from personal_intelligence.core.policy.models import (
    InvestigationStatus,
    PolicyAction,
    PolicyEvaluationResult,
    PresentationAction,
    PresentationDecision,
    SituationFreshness,
    UserContext,
)


def decide_presentation(
    urgency: Any,
    actionability: Any = "high",
    relevance: Any = "high",
    evidence_quality: Any = None,
    personal_significance: Any = None,
    user_context: Any = "available",
    dnd: bool = False,
    freshness: Any = "fresh",
    duplicate: bool = False,
    situation_status: Any = "open",
    investigation_status: Any = "complete",
    recently_notified: bool = False,
    recently_dismissed: bool = False,
    critical_bypass_dnd: bool = False,
    evidence_strength: Any = None,
    attention_state: Any = None,
    **kwargs: Any,
) -> PresentationDecision:
    """
    Pure deterministic public function deciding presentation routing with zero LLM calls or randomness.
    
    Target Architectural Contract:
    PI makes a presentation-routing decision with exactly five canonical outcomes:
      - INTERRUPT: Proactively present recommendation to the user immediately.
      - BRIEFING: Queue recommendation silently for the next scheduled briefing/digest.
      - DEFER: Defer presentation until the user becomes available or evidence strengthens.
      - SUPPRESS: Suppress presentation due to focus mode, quiet hours, or dismissal cooldown.
      - DISCARD: Silently discard recommendation (low value, duplicate, resolved, or stale).

    Internal precedence rules (hygiene, evidence validity, attention context, urgency)
    are encapsulated cleanly behind this public PresentationDecision API.
    """
    engine = InterventionPolicyEngine()
    eff_ctx = attention_state if attention_state is not None else user_context
    ctx = UserContext.DND.value if dnd else eff_ctx
    sit_resolved = str(situation_status).strip().lower() in ("resolved", "closed")
    ev_val = evidence_quality if evidence_quality is not None else (evidence_strength if evidence_strength is not None else "strong")

    return engine.evaluate(
        urgency=urgency,
        actionability=actionability,
        evidence_quality=ev_val,
        evidence_strength=ev_val,
        personal_significance=personal_significance,
        user_context=ctx,
        relevance=relevance,
        already_notified=recently_notified or duplicate,
        recently_dismissed=recently_dismissed,
        situation_freshness=freshness,
        situation_resolved=sit_resolved,
        investigation_status=investigation_status,
        critical_bypass_dnd=critical_bypass_dnd,
        **kwargs,
    )


# Backward-compatible alias
decide_intervention = decide_presentation


class InterventionPolicyEngine:
    """
    Deterministic categorical intervention policy evaluator.
    Decides whether, when, and how to present recommendations to the user based on
    situation urgency, actionability, evidence strength, user context, and repetition history.
    
    Allowed decisions:
    - INTERRUPT: Proactively present recommendation to the user immediately.
    - BRIEFING: Queue recommendation silently for the next scheduled briefing/digest.
    - DEFER: Defer presentation until the user becomes available.
    - SUPPRESS: Suppress presentation due to focus mode or dismissal.
    - DISCARD: Silently discard recommendation (low urgency, already notified, or not actionable).

    Does NOT execute external actions. All side effects require explicit user approval.
    """

    HARD_SUPPRESSION_CONTEXTS: Set[str] = {
        UserContext.MEETING.value,
        UserContext.DRIVING.value,
        UserContext.TRANSIT.value,
        UserContext.SLEEPING.value,
        UserContext.SLEEP.value,
        UserContext.DEEP_WORK.value,
        UserContext.DO_NOT_DISTURB.value,
        UserContext.DND.value,
        "meeting",
        "driving",
        "transit",
        "sleeping",
        "sleep",
        "deep_work",
        "deep work",
        "do_not_disturb",
        "dnd",
    }

    @classmethod
    def normalize_user_context(cls, ctx: Any) -> str:
        """Normalizes freeform or enum user context into standard categorical strings."""
        if hasattr(ctx, "value"):
            raw = str(ctx.value).strip().lower()
        else:
            raw = str(ctx or "available").strip().lower()

        if raw in ("meeting", "in_meeting", "calendar_meeting"):
            return UserContext.MEETING.value
        if raw in ("deep_work", "deep work", "flow_state", "focus", "focus_mode"):
            return UserContext.DEEP_WORK.value
        if raw in ("focused", "task_focus"):
            return UserContext.FOCUSED.value
        if raw in ("sleeping", "sleep", "asleep", "bedtime"):
            return UserContext.SLEEPING.value
        if raw in ("driving", "in_car", "commute"):
            return UserContext.DRIVING.value
        if raw in ("transit", "in_transit", "traveling", "train", "flight"):
            return UserContext.TRANSIT.value
        if raw in ("do_not_disturb", "dnd", "do not disturb", "silent", "do-not-disturb"):
            return UserContext.DO_NOT_DISTURB.value
        if raw in ("busy", "working"):
            return UserContext.BUSY.value
        if raw in ("idle", "away", "inactive"):
            return UserContext.IDLE.value
        if raw in ("available", "online", "free"):
            return UserContext.AVAILABLE.value
        if raw in ("unknown", "unspecified"):
            return UserContext.UNKNOWN.value
        return raw

    def decide_presentation(
        self,
        urgency: str,
        actionability: str,
        evidence_quality: Optional[str] = None,
        personal_significance: Optional[str] = None,
        user_context: str = "available",
        relevance: Optional[str] = "high",
        already_notified: bool = False,
        recently_dismissed: bool = False,
        situation_freshness: Optional[str] = "fresh",
        situation_resolved: bool = False,
        critical_bypass_dnd: bool = False,
        investigation_status: Optional[str] = "complete",
        interaction_patterns: Optional[Any] = None,
        interaction_preferences: Optional[Dict[str, Any]] = None,
        evidence_strength: Optional[str] = None,
        **kwargs: Any,
    ) -> PresentationDecision:
        """Alias for evaluate() returning canonical PresentationDecision."""
        return self.evaluate(
            urgency=urgency,
            actionability=actionability,
            evidence_strength=evidence_strength,
            user_context=user_context,
            relevance=relevance,
            already_notified=already_notified,
            recently_dismissed=recently_dismissed,
            situation_freshness=situation_freshness,
            situation_resolved=situation_resolved,
            critical_bypass_dnd=critical_bypass_dnd,
            investigation_status=investigation_status,
            interaction_patterns=interaction_patterns,
            interaction_preferences=interaction_preferences,
            evidence_quality=evidence_quality,
            personal_significance=personal_significance,
            **kwargs,
        )

    def evaluate(
        self,
        urgency: str,
        actionability: str,
        evidence_strength: Optional[str] = None,
        user_context: str = "available",
        relevance: Optional[str] = "high",
        already_notified: bool = False,
        recently_dismissed: bool = False,
        situation_freshness: Optional[str] = "fresh",
        situation_resolved: bool = False,
        critical_bypass_dnd: bool = False,
        investigation_status: Optional[str] = "complete",
        interaction_patterns: Optional[Any] = None,
        interaction_preferences: Optional[Dict[str, Any]] = None,
        evidence_quality: Optional[str] = None,
        personal_significance: Optional[str] = None,
        **kwargs: Any,
    ) -> PresentationDecision:
        """
        Evaluates categorical inputs and returns a deterministic PresentationDecision.
        Evaluates evidence quality (support level) rather than claiming objective conclusion certainty.

        Precedence Order:
          1. Resolved situation -> DISCARD
          2. Duplicate / already notified -> SUPPRESS (or DISCARD if duplicate)
          3. Evidence conflicted -> DEFER if consequential, SUPPRESS if non-consequential
          4. Investigation incomplete -> DEFER if high/critical consequence, SUPPRESS/BRIEFING if low
          5. Recently dismissed -> SUPPRESS
          6. Stale or expired -> DISCARD
          7. Critical urgency -> INTERRUPT (respects DND/meeting unless bypass; defers on weak evidence quality)
          8. High urgency -> INTERRUPT when actionable, evidence quality strong/moderate, available; otherwise DEFER
          9. Medium urgency -> BRIEFING (defers when busy/in-meeting/deep-work)
          10. Low urgency -> BRIEFING if actionable & fresh; otherwise SUPPRESS / DISCARD
        """
        # Normalize inputs
        norm_urgency = urgency.value if hasattr(urgency, "value") else str(urgency)
        norm_urgency = norm_urgency.strip().lower()

        norm_actionability = actionability.value if hasattr(actionability, "value") else str(actionability)
        norm_actionability = norm_actionability.strip().lower()

        norm_relevance = relevance.value if hasattr(relevance, "value") else str(relevance or "high")
        norm_relevance = norm_relevance.strip().lower()

        norm_significance = (
            personal_significance.value
            if hasattr(personal_significance, "value")
            else str(personal_significance or "")
        ).strip().lower() if personal_significance is not None else None

        raw_ev = evidence_quality if evidence_quality is not None else (evidence_strength if evidence_strength is not None else "strong")
        norm_evidence = raw_ev.value if hasattr(raw_ev, "value") else str(raw_ev)
        norm_evidence = norm_evidence.strip().lower()

        norm_context = self.normalize_user_context(user_context)

        norm_freshness = situation_freshness.value if hasattr(situation_freshness, "value") else str(situation_freshness or "fresh")
        norm_freshness = norm_freshness.strip().lower()

        norm_inv_status = investigation_status.value if hasattr(investigation_status, "value") else str(investigation_status or "complete")
        norm_inv_status = norm_inv_status.strip().upper()

        now = datetime.now(timezone.utc)

        def _result(action: str, reason: str) -> PresentationDecision:
            return PresentationDecision(
                action=action,
                reason=reason,
                urgency=norm_urgency,
                actionability=norm_actionability,
                relevance=norm_relevance,
                personal_significance=norm_significance,
                evidence_quality=norm_evidence,
                evidence_strength=norm_evidence,
                user_context=norm_context,
                situation_freshness=norm_freshness,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                timestamp=now,
            )

        # ---------------------------------------------------------------
        # 1. Resolved situation -> DISCARD
        # ---------------------------------------------------------------
        if situation_resolved:
            return _result(
                PolicyAction.DISCARD.value,
                "Situation is already resolved; discarding intervention.",
            )

        # ---------------------------------------------------------------
        # 2. De-duplication check: Already notified / Duplicate -> SUPPRESS / DISCARD
        # ---------------------------------------------------------------
        if already_notified:
            return _result(
                PolicyAction.DISCARD.value,
                "User has already been notified for this situation; avoiding duplicate alert.",
            )

        # ---------------------------------------------------------------
        # 3. CONFLICTED evidence -> DEFER if consequential, SUPPRESS if non-consequential
        # ---------------------------------------------------------------
        if norm_evidence == "conflicted":
            if norm_urgency in ("critical", "high") or (norm_urgency == "medium" and norm_actionability in ("high", "medium")):
                return _result(
                    PolicyAction.DEFER.value,
                    "Evidence is conflicted on a consequential situation; deferring until evidence clarifies.",
                )
            return _result(
                PolicyAction.SUPPRESS.value,
                "Evidence is conflicted on a non-consequential situation; suppressing intervention.",
            )

        # ---------------------------------------------------------------
        # 4. Investigation Incomplete State
        # ---------------------------------------------------------------
        if norm_inv_status in (InvestigationStatus.INCOMPLETE.value, "INVESTIGATION_INCOMPLETE"):
            if norm_urgency in ("critical", "high") or norm_actionability == "high":
                return _result(
                    PolicyAction.DEFER.value,
                    "Investigation is incomplete with open information gaps; deferring consequential situation for future evaluation.",
                )
            if norm_actionability in ("medium", "high") and norm_context == UserContext.AVAILABLE.value:
                return _result(
                    PolicyAction.BRIEFING.value,
                    "Investigation incomplete for low-consequence situation; routing partial findings to briefing digest.",
                )
            return _result(
                PolicyAction.SUPPRESS.value,
                "Investigation incomplete for low-consequence situation; suppressing notification.",
            )

        # ---------------------------------------------------------------
        # 5. User feedback cooldown: Recently dismissed -> SUPPRESS
        # ---------------------------------------------------------------
        if recently_dismissed:
            return _result(
                PolicyAction.SUPPRESS.value,
                "User recently dismissed this intervention; respecting feedback suppression cooldown.",
            )

        # ---------------------------------------------------------------
        # 6. Situation Freshness: Stale or expired situations -> DISCARD
        # ---------------------------------------------------------------
        if norm_freshness in (SituationFreshness.STALE.value.lower(), "stale", "expired"):
            return _result(
                PolicyAction.DISCARD.value,
                f"Situation is {norm_freshness} and no longer temporally fresh for intervention.",
            )

        # ---------------------------------------------------------------
        # 7. CRITICAL Urgency: INTERRUPT (respects suppression/focus unless user bypass; defers on weak evidence)
        # ---------------------------------------------------------------
        if norm_urgency == "critical":
            if norm_evidence in ("weak", "insufficient_evidence", "conflicted"):
                return _result(
                    PolicyAction.DEFER.value,
                    "Critical urgency with weak/insufficient evidence; deferring until evidence strengthens.",
                )
            if norm_actionability in ("low", "none", "not_actionable"):
                return _result(
                    PolicyAction.BRIEFING.value,
                    "Critical urgency with low or no immediate actionability routed to briefing digest; Hermes cannot force interrupt.",
                )
            dnd_contexts = {
                UserContext.DO_NOT_DISTURB.value,
                UserContext.DND.value,
                UserContext.SLEEPING.value,
                UserContext.SLEEP.value,
                UserContext.DEEP_WORK.value,
                "dnd",
                "do_not_disturb",
                "sleep",
                "sleeping",
                "deep_work",
                "deep work",
            }
            if norm_context in dnd_contexts and not critical_bypass_dnd:
                return _result(
                    PolicyAction.DEFER.value,
                    f"Critical situation deferred due to suppression/focus context ({norm_context}). Hermes cannot force interrupt.",
                )
            return _result(
                PolicyAction.INTERRUPT.value,
                "Critical urgency overrides standard attention constraints to trigger immediate interrupt.",
            )

        # ---------------------------------------------------------------
        # 8. HIGH Urgency: Actionable + Strong/Moderate Evidence + Available -> INTERRUPT; otherwise DEFER
        # ---------------------------------------------------------------
        if norm_urgency == "high":
            if norm_context in self.HARD_SUPPRESSION_CONTEXTS:
                return _result(
                    PolicyAction.DEFER.value,
                    f"High urgency situation deferred while user is in hard suppression context ({norm_context}).",
                )
            if norm_context == UserContext.BUSY.value:
                return _result(
                    PolicyAction.DEFER.value,
                    "High urgency situation deferred while user is busy.",
                )
            if norm_evidence in ("weak", "insufficient_evidence"):
                return _result(
                    PolicyAction.DEFER.value,
                    "High urgency situation with weak evidence; deferring until evidence strengthens.",
                )
            if norm_actionability in ("high", "medium") and norm_relevance in ("high", "medium"):
                return _result(
                    PolicyAction.INTERRUPT.value,
                    "High urgency with high actionability and strong evidence triggers immediate interrupt.",
                )
            return _result(
                PolicyAction.BRIEFING.value,
                "High urgency with low actionability routed to briefing digest.",
            )

        # ---------------------------------------------------------------
        # 8.5 Learned Interaction Preferences (Timing & Low-Urgency Dismissal)
        # ---------------------------------------------------------------
        prefs = dict(interaction_preferences or {})
        if interaction_patterns and isinstance(interaction_patterns, list):
            for ip in interaction_patterns:
                ip_desc = getattr(ip, "description", "").lower()
                if "low-urgency" in ip_desc or "busy" in ip_desc:
                    prefs["dismisses_low_urgency_interruptions"] = True
                if "morning" in ip_desc:
                    prefs["preferred_timing_window"] = "morning"

        if prefs.get("dismisses_low_urgency_interruptions") and norm_urgency in ("low", "medium") and norm_context in (UserContext.BUSY.value, UserContext.FOCUSED.value):
            return _result(
                PolicyAction.DEFER.value,
                "Non-critical intervention deferred due to learned user preference dismissing low-urgency interruptions during busy/focused states.",
            )

        # ---------------------------------------------------------------
        # 9. MEDIUM Urgency: BRIEFING unless attention state warrants DEFER
        # ---------------------------------------------------------------
        if norm_urgency == "medium":
            if norm_context in self.HARD_SUPPRESSION_CONTEXTS or norm_context == UserContext.BUSY.value:
                if norm_actionability in ("high", "medium") and norm_relevance in ("high", "medium"):
                    return _result(
                        PolicyAction.DEFER.value,
                        f"Actionable medium urgency situation deferred until user exits {norm_context}.",
                    )
                return _result(
                    PolicyAction.SUPPRESS.value,
                    f"Medium urgency situation suppressed due to user context ({norm_context}).",
                )
            if norm_actionability in ("high", "medium") and norm_relevance in ("high", "medium"):
                return _result(
                    PolicyAction.BRIEFING.value,
                    "Medium urgency situation queued silently for upcoming briefing digest.",
                )
            return _result(
                PolicyAction.DISCARD.value,
                "Medium urgency with low actionability or low relevance is silently discarded.",
            )

        # ---------------------------------------------------------------
        # 10. LOW Urgency: BRIEFING if actionable/useful; otherwise SUPPRESS / DISCARD
        # ---------------------------------------------------------------
        if norm_urgency == "low":
            if norm_context in self.HARD_SUPPRESSION_CONTEXTS:
                return _result(
                    PolicyAction.SUPPRESS.value,
                    f"Low urgency situation suppressed during {norm_context}.",
                )
            if norm_actionability in ("high", "medium") and norm_relevance in ("high", "medium") and norm_freshness in ("fresh", "aging"):
                return _result(
                    PolicyAction.BRIEFING.value,
                    "Actionable low urgency recommendation routed to briefing digest.",
                )
            return _result(
                PolicyAction.DISCARD.value,
                "Low urgency situation without high actionability is silently discarded.",
            )

        # ---------------------------------------------------------------
        # Fallback for unexpected context
        # ---------------------------------------------------------------
        return _result(
            PolicyAction.DISCARD.value,
            f"Unrecognized user context '{norm_context}'; defaulting to silent discard.",
        )

    def evaluate_recommendation(
        self,
        recommendation: Any,
        user_context: Any = "available",
        evidence_strength: Any = "strong",
        situation_freshness: Any = "fresh",
        situation_resolved: bool = False,
        recently_notified: bool = False,
        recently_dismissed: bool = False,
        dnd: bool = False,
        **kwargs: Any,
    ) -> PolicyEvaluationResult:
        """
        Evaluates a recommendation or Hermes reasoning output strictly through PI Intervention Policy.

        Guarantees:
          1. Policy cannot be bypassed: Forced actions or bypass flags passed by Hermes/LLM are ignored.
          2. Critical Hermes output cannot force interruption: Evaluated against user context, evidence, and actionability.
          3. Presentation-only decision: Policy decides INTERRUPT, BRIEFING, DEFER, SUPPRESS, or DISCARD.
        """
        norm_urg = "medium"
        norm_act = "medium"
        norm_rel = "high"

        norm_sig = None
        if isinstance(recommendation, dict):
            norm_urg = recommendation.get("urgency") or recommendation.get("priority") or "medium"
            norm_act = recommendation.get("actionability") or "medium"
            norm_rel = recommendation.get("relevance") or "high"
            norm_sig = recommendation.get("personal_significance") or recommendation.get("significance")
        elif hasattr(recommendation, "urgency"):
            norm_urg = getattr(recommendation, "urgency", "medium")
            norm_act = getattr(recommendation, "actionability", "medium")
            norm_rel = getattr(recommendation, "relevance", "high")
            norm_sig = getattr(recommendation, "personal_significance", getattr(recommendation, "significance", None))
        else:
            norm_sig = kwargs.get("personal_significance") or kwargs.get("significance")

        ctx = UserContext.DND.value if dnd else user_context

        # Hermes or external LLM cannot force critical_bypass_dnd
        return self.evaluate(
            urgency=norm_urg,
            actionability=norm_act,
            evidence_strength=evidence_strength,
            personal_significance=norm_sig,
            user_context=ctx,
            relevance=norm_rel,
            already_notified=recently_notified,
            recently_dismissed=recently_dismissed,
            situation_freshness=situation_freshness,
            situation_resolved=situation_resolved,
            critical_bypass_dnd=False,
            **kwargs,
        )
