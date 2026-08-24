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
from typing import Any, Dict, Optional, Set

from personal_intelligence.core.policy.models import (
    PolicyAction,
    PolicyEvaluationResult,
    UserContext,
)


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
        UserContext.SLEEPING.value,
        UserContext.SLEEP.value,
        UserContext.DEEP_WORK.value,
        UserContext.DO_NOT_DISTURB.value,
        UserContext.DND.value,
        "meeting",
        "driving",
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
        if raw in ("deep_work", "deep work", "focus", "focus_mode"):
            return UserContext.DEEP_WORK.value
        if raw in ("sleeping", "sleep", "asleep", "bedtime"):
            return UserContext.SLEEPING.value
        if raw in ("driving", "in_transit", "traveling", "commute"):
            return UserContext.DRIVING.value
        if raw in ("do_not_disturb", "dnd", "do not disturb", "silent", "do-not-disturb"):
            return UserContext.DO_NOT_DISTURB.value
        if raw in ("busy", "working"):
            return UserContext.BUSY.value
        if raw in ("available", "idle", "online", "free"):
            return UserContext.AVAILABLE.value
        return raw

    def evaluate(
        self,
        urgency: str,
        actionability: str,
        evidence_strength: str,
        user_context: str,
        relevance: Optional[str] = "high",
        already_notified: bool = False,
        recently_dismissed: bool = False,
        situation_freshness: Optional[str] = "fresh",
    ) -> PolicyEvaluationResult:
        """
        Evaluates categorical inputs and returns a deterministic PolicyEvaluationResult.
        Hermes must NOT decide whether to interrupt the user.
        Personal Intelligence decides: INTERRUPT, BRIEFING, DEFER, SUPPRESS, DISCARD.
        """
        # Normalize inputs
        norm_urgency = urgency.value if hasattr(urgency, "value") else str(urgency)
        norm_urgency = norm_urgency.strip().lower()

        norm_actionability = actionability.value if hasattr(actionability, "value") else str(actionability)
        norm_actionability = norm_actionability.strip().lower()

        norm_relevance = relevance.value if hasattr(relevance, "value") else str(relevance or "high")
        norm_relevance = norm_relevance.strip().lower()

        norm_evidence = evidence_strength.value if hasattr(evidence_strength, "value") else str(evidence_strength)
        norm_evidence = norm_evidence.strip().lower()

        norm_context = self.normalize_user_context(user_context)

        norm_freshness = situation_freshness.value if hasattr(situation_freshness, "value") else str(situation_freshness or "fresh")
        norm_freshness = norm_freshness.strip().lower()

        now = datetime.now(timezone.utc)

        # 1. CRITICAL Priority: Always INTERRUPT (overrides user context, hard suppression, and freshness)
        if norm_urgency == "critical":
            return PolicyEvaluationResult(
                action=PolicyAction.INTERRUPT.value,
                reason="Critical urgency overrides user context, hard suppression, and freshness.",
                urgency=norm_urgency,
                actionability=norm_actionability,
                relevance=norm_relevance,
                evidence_strength=norm_evidence,
                user_context=norm_context,
                situation_freshness=norm_freshness,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                timestamp=now,
            )

        # 2. De-duplication check: Already notified
        if already_notified:
            return PolicyEvaluationResult(
                action=PolicyAction.DISCARD.value,
                reason="User has already been notified for this situation; avoiding duplicate alert.",
                urgency=norm_urgency,
                actionability=norm_actionability,
                relevance=norm_relevance,
                evidence_strength=norm_evidence,
                user_context=norm_context,
                situation_freshness=norm_freshness,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                timestamp=now,
            )

        # 3. Situation Freshness: Stale or expired situations
        if norm_freshness in ("stale", "expired"):
            return PolicyEvaluationResult(
                action=PolicyAction.DISCARD.value,
                reason=f"Situation is {norm_freshness} and no longer temporally fresh for intervention.",
                urgency=norm_urgency,
                actionability=norm_actionability,
                relevance=norm_relevance,
                evidence_strength=norm_evidence,
                user_context=norm_context,
                situation_freshness=norm_freshness,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                timestamp=now,
            )

        # 4. User feedback cooldown: Recently dismissed
        if recently_dismissed:
            return PolicyEvaluationResult(
                action=PolicyAction.SUPPRESS.value,
                reason="User recently dismissed this intervention; respecting feedback suppression cooldown.",
                urgency=norm_urgency,
                actionability=norm_actionability,
                relevance=norm_relevance,
                evidence_strength=norm_evidence,
                user_context=norm_context,
                situation_freshness=norm_freshness,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                timestamp=now,
            )

        # 5. LOW Urgency: Always DISCARD (silent across all contexts)
        if norm_urgency == "low":
            return PolicyEvaluationResult(
                action=PolicyAction.DISCARD.value,
                reason="Low urgency situations are silently discarded without user notification.",
                urgency=norm_urgency,
                actionability=norm_actionability,
                relevance=norm_relevance,
                evidence_strength=norm_evidence,
                user_context=norm_context,
                situation_freshness=norm_freshness,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                timestamp=now,
            )

        # 6. Low Relevance: Discard or route to briefing (never interrupt)
        if norm_relevance == "low":
            if norm_urgency == "high" and norm_actionability in ("high", "medium") and norm_context == UserContext.AVAILABLE.value:
                return PolicyEvaluationResult(
                    action=PolicyAction.BRIEFING.value,
                    reason="Low relevance situation routed to briefing digest rather than direct interruption.",
                    urgency=norm_urgency,
                    actionability=norm_actionability,
                    relevance=norm_relevance,
                    evidence_strength=norm_evidence,
                    user_context=norm_context,
                    situation_freshness=norm_freshness,
                    already_notified=already_notified,
                    recently_dismissed=recently_dismissed,
                    timestamp=now,
                )
            return PolicyEvaluationResult(
                action=PolicyAction.DISCARD.value,
                reason="Low relevance situation is discarded without notifying.",
                urgency=norm_urgency,
                actionability=norm_actionability,
                relevance=norm_relevance,
                evidence_strength=norm_evidence,
                user_context=norm_context,
                situation_freshness=norm_freshness,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                timestamp=now,
            )

        # 7. Hard Suppression Contexts (meeting, deep work, sleep, driving, DND)
        if norm_context in self.HARD_SUPPRESSION_CONTEXTS:
            # Actionable high/medium situations can be deferred when context allows (meeting, deep work)
            if norm_urgency in ("high", "medium") and norm_actionability in ("high", "medium"):
                if norm_context in (UserContext.MEETING.value, UserContext.DEEP_WORK.value, "meeting", "deep work", "deep_work"):
                    return PolicyEvaluationResult(
                        action=PolicyAction.DEFER.value,
                        reason=f"Actionable {norm_urgency} situation deferred until user exits {norm_context}.",
                        urgency=norm_urgency,
                        actionability=norm_actionability,
                        relevance=norm_relevance,
                        evidence_strength=norm_evidence,
                        user_context=norm_context,
                        situation_freshness=norm_freshness,
                        already_notified=already_notified,
                        recently_dismissed=recently_dismissed,
                        timestamp=now,
                    )
            return PolicyEvaluationResult(
                action=PolicyAction.SUPPRESS.value,
                reason=f"Intervention suppressed due to hard suppression user context ({norm_context}).",
                urgency=norm_urgency,
                actionability=norm_actionability,
                relevance=norm_relevance,
                evidence_strength=norm_evidence,
                user_context=norm_context,
                situation_freshness=norm_freshness,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                timestamp=now,
            )

        # 8. Soft Busy State (not hard suppressed, but user is busy)
        if norm_context == UserContext.BUSY.value:
            if norm_urgency in ("high", "medium") and norm_actionability in ("high", "medium"):
                return PolicyEvaluationResult(
                    action=PolicyAction.DEFER.value,
                    reason=f"Actionable {norm_urgency} situation deferred while user is busy.",
                    urgency=norm_urgency,
                    actionability=norm_actionability,
                    relevance=norm_relevance,
                    evidence_strength=norm_evidence,
                    user_context=norm_context,
                    situation_freshness=norm_freshness,
                    already_notified=already_notified,
                    recently_dismissed=recently_dismissed,
                    timestamp=now,
                )
            return PolicyEvaluationResult(
                action=PolicyAction.DISCARD.value,
                reason="Non-urgent or low-actionability situation discarded during busy state.",
                urgency=norm_urgency,
                actionability=norm_actionability,
                relevance=norm_relevance,
                evidence_strength=norm_evidence,
                user_context=norm_context,
                situation_freshness=norm_freshness,
                already_notified=already_notified,
                recently_dismissed=recently_dismissed,
                timestamp=now,
            )

        # 9. User Available State
        if norm_context == UserContext.AVAILABLE.value:
            # High Urgency
            if norm_urgency == "high":
                if norm_actionability == "high" and norm_evidence == "strong" and norm_relevance in ("high", "medium"):
                    return PolicyEvaluationResult(
                        action=PolicyAction.INTERRUPT.value,
                        reason="High urgency with high actionability and strong evidence triggers immediate interrupt when user is available.",
                        urgency=norm_urgency,
                        actionability=norm_actionability,
                        relevance=norm_relevance,
                        evidence_strength=norm_evidence,
                        user_context=norm_context,
                        situation_freshness=norm_freshness,
                        already_notified=already_notified,
                        recently_dismissed=recently_dismissed,
                        timestamp=now,
                    )
                else:
                    return PolicyEvaluationResult(
                        action=PolicyAction.BRIEFING.value,
                        reason="High urgency with moderate actionability/evidence routed to briefing digest.",
                        urgency=norm_urgency,
                        actionability=norm_actionability,
                        relevance=norm_relevance,
                        evidence_strength=norm_evidence,
                        user_context=norm_context,
                        situation_freshness=norm_freshness,
                        already_notified=already_notified,
                        recently_dismissed=recently_dismissed,
                        timestamp=now,
                    )

            # Medium Urgency
            if norm_urgency == "medium":
                if norm_actionability in ("high", "medium") and norm_relevance in ("high", "medium"):
                    return PolicyEvaluationResult(
                        action=PolicyAction.BRIEFING.value,
                        reason="Medium urgency situation queued silently for upcoming briefing digest.",
                        urgency=norm_urgency,
                        actionability=norm_actionability,
                        relevance=norm_relevance,
                        evidence_strength=norm_evidence,
                        user_context=norm_context,
                        situation_freshness=norm_freshness,
                        already_notified=already_notified,
                        recently_dismissed=recently_dismissed,
                        timestamp=now,
                    )
                else:
                    return PolicyEvaluationResult(
                        action=PolicyAction.DISCARD.value,
                        reason="Medium urgency with low actionability or low relevance is discarded without notifying.",
                        urgency=norm_urgency,
                        actionability=norm_actionability,
                        relevance=norm_relevance,
                        evidence_strength=norm_evidence,
                        user_context=norm_context,
                        situation_freshness=norm_freshness,
                        already_notified=already_notified,
                        recently_dismissed=recently_dismissed,
                        timestamp=now,
                    )

        # Fallback for unexpected context
        return PolicyEvaluationResult(
            action=PolicyAction.DISCARD.value,
            reason=f"Unrecognized user context '{norm_context}'; defaulting to silent discard.",
            urgency=norm_urgency,
            actionability=norm_actionability,
            relevance=norm_relevance,
            evidence_strength=norm_evidence,
            user_context=norm_context,
            situation_freshness=norm_freshness,
            already_notified=already_notified,
            recently_dismissed=recently_dismissed,
            timestamp=now,
        )

