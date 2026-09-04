"""
Reasoning Eligibility Gate and Reasoning Budget for Personal Intelligence.

Implements a deterministic semantic decision filter between SituationEngine and Hermes:
  EVENT -> STATE CHANGE -> SIGNIFICANCE -> SITUATION -> REASONING ELIGIBILITY -> HERMES

Architectural Concept:
  "Should PI spend reasoning resources on this situation?"
  rather than:
  "Does this situation fit a token budget?"

Evaluates signals including:
  - Personal significance
  - Uncertainty / Information gaps
  - Actionability
  - Novelty / Change (non-mandatory)
  - Current user context
  - Existing reasoning history & duplication
  - Potential value of additional reasoning
  - Available computational/attention cost class

Token budget remains an implementation constraint (ReasoningBudget) but does not define
the conceptual architecture.

Blueprint Reference: §6 Reasoning Eligibility Gate, Change 2 & 3.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from personal_intelligence.core.events.models import ensure_timezone_aware, format_iso8601
from personal_intelligence.core.significance.models import SignificanceAssessment, SignificanceLevel
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus


class ReasoningEligibility(str, Enum):
    """Categorical reasoning eligibility decision (backward compatible)."""
    NO_REASONING = "no_reasoning"
    LOCAL_REASONING = "local_reasoning"
    HERMES_REASONING = "hermes_reasoning"
    HERMES_INVESTIGATION_AND_REASONING = "hermes_investigation_and_reasoning"


class ReasoningValueLevel(str, Enum):
    """Estimated value of additional reasoning for a situation."""
    NEGLIGIBLE = "negligible"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReasoningCostClass(str, Enum):
    """Tier of computational/attention resource cost."""
    NONE = "none"
    LOCAL_ONLY = "local_only"
    STANDARD = "standard"
    DEEP_INVESTIGATION = "deep_investigation"


class ReasoningBudgetLevel(str, Enum):
    """Tier of reasoning resource budget."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ReasoningBudget:
    """
    Deterministic implementation budget controlling LLM invocation and external investigation tools.
    Implementation constraint supporting the semantic reasoning decision.
    """
    budget_level: str = ReasoningBudgetLevel.MEDIUM.value
    allow_hermes_call: bool = True
    max_investigation_rounds: int = 0
    max_tool_calls: int = 0
    max_context_tokens: int = 1000
    reasoning_depth: str = "standard"  # shallow, standard, deep

    @classmethod
    def low(cls) -> "ReasoningBudget":
        """No Hermes call; local/rule-based processing only."""
        return cls(
            budget_level=ReasoningBudgetLevel.LOW.value,
            allow_hermes_call=False,
            max_investigation_rounds=0,
            max_tool_calls=0,
            max_context_tokens=500,
            reasoning_depth="shallow",
        )

    @classmethod
    def medium(cls) -> "ReasoningBudget":
        """Hermes reasoning with standard bounded context; no external tool calls."""
        return cls(
            budget_level=ReasoningBudgetLevel.MEDIUM.value,
            allow_hermes_call=True,
            max_investigation_rounds=0,
            max_tool_calls=0,
            max_context_tokens=1000,
            reasoning_depth="standard",
        )

    @classmethod
    def high(cls) -> "ReasoningBudget":
        """Hermes reasoning with bounded external investigation (up to 2 rounds, 4 tools)."""
        return cls(
            budget_level=ReasoningBudgetLevel.HIGH.value,
            allow_hermes_call=True,
            max_investigation_rounds=2,
            max_tool_calls=4,
            max_context_tokens=1500,
            reasoning_depth="deep",
        )

    @classmethod
    def critical(cls) -> "ReasoningBudget":
        """Hermes reasoning with full bounded investigation (up to 3 rounds, 5 tools)."""
        return cls(
            budget_level=ReasoningBudgetLevel.CRITICAL.value,
            allow_hermes_call=True,
            max_investigation_rounds=3,
            max_tool_calls=5,
            max_context_tokens=2000,
            reasoning_depth="deep",
        )

    @classmethod
    def for_significance(cls, level: str, has_info_gap: bool = False) -> "ReasoningBudget":
        """Factory creating the appropriate budget for a given significance level."""
        lvl = str(level).lower()
        if lvl == SignificanceLevel.CRITICAL.value or lvl == "critical":
            return cls.critical()
        elif lvl == SignificanceLevel.HIGH.value or lvl == "high":
            return cls.high()
        elif lvl == SignificanceLevel.MEDIUM.value or lvl == "medium":
            if has_info_gap:
                return cls.high()
            return cls.medium()
        else:
            return cls.low()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "budget_level": self.budget_level,
            "allow_hermes_call": self.allow_hermes_call,
            "max_investigation_rounds": self.max_investigation_rounds,
            "max_tool_calls": self.max_tool_calls,
            "max_context_tokens": self.max_context_tokens,
            "reasoning_depth": self.reasoning_depth,
        }


@dataclass
class ReasoningEligibilityResult:
    """
    Structured outcome of reasoning eligibility evaluation.
    
    Conceptual Question Answered:
      "Should PI spend reasoning resources on this situation?"
    """
    eligible: bool = True
    reason: str = ""
    priority: str = "medium"
    estimated_reasoning_value: str = ReasoningValueLevel.MEDIUM.value
    cost_class: str = ReasoningCostClass.STANDARD.value
    eligibility: str = ReasoningEligibility.HERMES_REASONING.value
    budget: ReasoningBudget = field(default_factory=ReasoningBudget.medium)
    significance_level: str = SignificanceLevel.MEDIUM.value
    situation_id: Optional[str] = None
    uncertainty_present: bool = False
    actionability: str = "medium"
    is_duplicate: bool = False
    is_stale: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.timestamp = ensure_timezone_aware(self.timestamp, "ReasoningEligibilityResult timestamp")
        if isinstance(self.eligibility, ReasoningEligibility):
            self.eligibility = self.eligibility.value
        if isinstance(self.estimated_reasoning_value, ReasoningValueLevel):
            self.estimated_reasoning_value = self.estimated_reasoning_value.value
        if isinstance(self.cost_class, ReasoningCostClass):
            self.cost_class = self.cost_class.value

    @property
    def requires_hermes(self) -> bool:
        """Indicates whether external Hermes LLM reasoning is required."""
        if not self.eligible:
            return False
        return self.cost_class in (
            ReasoningCostClass.STANDARD.value,
            ReasoningCostClass.DEEP_INVESTIGATION.value,
        ) or self.eligibility in (
            ReasoningEligibility.HERMES_REASONING.value,
            ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value,
        )

    @property
    def requires_investigation(self) -> bool:
        """Indicates whether external tool investigation is required prior to reasoning."""
        if not self.eligible:
            return False
        return (
            self.cost_class == ReasoningCostClass.DEEP_INVESTIGATION.value
            or self.eligibility == ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes eligibility result to dictionary."""
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "priority": self.priority,
            "estimated_reasoning_value": self.estimated_reasoning_value,
            "cost_class": self.cost_class,
            "eligibility": self.eligibility,
            "budget": self.budget.to_dict(),
            "significance_level": self.significance_level,
            "situation_id": self.situation_id,
            "uncertainty_present": self.uncertainty_present,
            "actionability": self.actionability,
            "is_duplicate": self.is_duplicate,
            "is_stale": self.is_stale,
            "timestamp": format_iso8601(self.timestamp),
            "requires_hermes": self.requires_hermes,
            "requires_investigation": self.requires_investigation,
        }


class ReasoningEligibilityGate:
    """
    Deterministic gate that evaluates whether PI should spend reasoning resources on a situation.

    Replaces token-budget centric gating with multi-signal resource allocation:
      - Personal significance
      - Uncertainty / Information gaps
      - Actionability
      - Novelty / Change (non-mandatory)
      - Current user context
      - Existing reasoning history & duplication
      - Potential value of additional reasoning
      - Available computational/attention cost class
    """

    def evaluate(
        self,
        situation: Situation,
        significance: SignificanceAssessment,
        is_new_situation: bool = False,
        has_new_events: bool = False,
        is_due_reevaluation: bool = False,
        user_context: Optional[str] = None,
        reasoning_history: Optional[List[Any]] = None,
        actionability: Optional[str] = None,
        uncertainty: Optional[str] = None,
        as_of: Optional[datetime] = None,
        is_cross_context: bool = False,
    ) -> ReasoningEligibilityResult:
        """
        Determines semantic eligibility, estimated value, and cost tier for situational reasoning.
        """
        ref_dt = as_of or datetime.now(timezone.utc)
        sig_lvl = str(significance.level).lower()
        prio = str(situation.priority).lower()
        has_gap = bool(situation.information_required) or (
            uncertainty is not None and str(uncertainty).lower() in ("high", "unresolved", "open")
        )
        actionable_val = actionability or "medium"

        # Detect cross-context characteristics from situation type or explicit flag
        cross_context = is_cross_context or getattr(situation, "is_cross_context", False) or (
            situation.type in ("cross_context_conflict", "cross_domain_emergence", "multi_domain_shift")
        )

        # ---------------------------------------------------------------------
        # 1. Closed or resolved situations -> REJECT (No reasoning needed)
        # ---------------------------------------------------------------------
        if situation.status in (
            SituationStatus.RESOLVED.value,
            SituationStatus.DISMISSED.value,
            SituationStatus.CLOSED.value,
            "resolved",
            "dismissed",
            "closed",
        ):
            return ReasoningEligibilityResult(
                eligible=False,
                reason=f"Situation {situation.id} is {situation.status}; reasoning skipped.",
                priority=prio,
                estimated_reasoning_value=ReasoningValueLevel.NEGLIGIBLE.value,
                cost_class=ReasoningCostClass.NONE.value,
                eligibility=ReasoningEligibility.NO_REASONING.value,
                budget=ReasoningBudget.low(),
                significance_level=sig_lvl,
                situation_id=situation.id,
                actionability="none",
            )

        # ---------------------------------------------------------------------
        # 2. Stale or expired situations -> REJECT / DEFER
        # ---------------------------------------------------------------------
        is_stale = False
        if hasattr(situation, "compute_freshness"):
            freshness_val = situation.compute_freshness(as_of=ref_dt)
            freshness_str = freshness_val.value if hasattr(freshness_val, "value") else str(freshness_val)
            if freshness_str.lower() in ("stale", "expired"):
                is_stale = True

        if is_stale and not is_new_situation and not has_new_events:
            return ReasoningEligibilityResult(
                eligible=False,
                reason=f"Situation {situation.id} is stale/expired; reasoning resources withheld for expired context.",
                priority=prio,
                estimated_reasoning_value=ReasoningValueLevel.NEGLIGIBLE.value,
                cost_class=ReasoningCostClass.NONE.value,
                eligibility=ReasoningEligibility.NO_REASONING.value,
                budget=ReasoningBudget.low(),
                significance_level=sig_lvl,
                situation_id=situation.id,
                is_stale=True,
            )

        # ---------------------------------------------------------------------
        # 3. Insignificant noise -> REJECT (Even if statistically novel!)
        # ---------------------------------------------------------------------
        if sig_lvl == SignificanceLevel.NOT_SIGNIFICANT.value and not is_due_reevaluation and not has_gap and not cross_context:
            return ReasoningEligibilityResult(
                eligible=False,
                reason="Change evaluated as NOT_SIGNIFICANT; insignificant noise rejected from reasoning.",
                priority=prio,
                estimated_reasoning_value=ReasoningValueLevel.NEGLIGIBLE.value,
                cost_class=ReasoningCostClass.NONE.value,
                eligibility=ReasoningEligibility.NO_REASONING.value,
                budget=ReasoningBudget.low(),
                significance_level=sig_lvl,
                situation_id=situation.id,
            )

        # ---------------------------------------------------------------------
        # 4. Duplicate reasoning / Low-value repeated analysis -> REJECT / DEFER
        # ---------------------------------------------------------------------
        is_duplicate = False
        if not is_new_situation and not has_new_events and not is_due_reevaluation:
            is_duplicate = True

        # Check explicit reasoning history if supplied
        if reasoning_history and not has_new_events and not is_due_reevaluation:
            for ep in reasoning_history:
                ep_sit_id = getattr(ep, "situation_id", None) or (ep.get("situation_id") if isinstance(ep, dict) else None)
                if ep_sit_id == situation.id:
                    is_duplicate = True
                    break

        if is_duplicate:
            return ReasoningEligibilityResult(
                eligible=False,
                reason="Situation already evaluated; no new material observations or changes present.",
                priority=prio,
                estimated_reasoning_value=ReasoningValueLevel.LOW.value,
                cost_class=ReasoningCostClass.NONE.value,
                eligibility=ReasoningEligibility.NO_REASONING.value,
                budget=ReasoningBudget.low(),
                significance_level=sig_lvl,
                situation_id=situation.id,
                is_duplicate=True,
            )

        # ---------------------------------------------------------------------
        # 5. Critical Significance -> ALLOW (Critical budget & high reasoning value)
        # ---------------------------------------------------------------------
        if sig_lvl == SignificanceLevel.CRITICAL.value or prio == "critical":
            if has_gap:
                return ReasoningEligibilityResult(
                    eligible=True,
                    reason=f"Critical significance ({sig_lvl}) with open information gap warrants bounded investigation & deep reasoning.",
                    priority="critical",
                    estimated_reasoning_value=ReasoningValueLevel.CRITICAL.value,
                    cost_class=ReasoningCostClass.DEEP_INVESTIGATION.value,
                    eligibility=ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value,
                    budget=ReasoningBudget.critical(),
                    significance_level=sig_lvl,
                    situation_id=situation.id,
                    uncertainty_present=True,
                    actionability=actionable_val,
                )
            return ReasoningEligibilityResult(
                eligible=True,
                reason="Critical situation warrants Hermes deep reasoning resources.",
                priority="critical",
                estimated_reasoning_value=ReasoningValueLevel.CRITICAL.value,
                cost_class=ReasoningCostClass.STANDARD.value,
                eligibility=ReasoningEligibility.HERMES_REASONING.value,
                budget=ReasoningBudget.critical(),
                significance_level=sig_lvl,
                situation_id=situation.id,
                actionability=actionable_val,
            )

        # ---------------------------------------------------------------------
        # 6. High Significance & Unresolved Uncertainty -> ALLOW
        # ---------------------------------------------------------------------
        if sig_lvl == SignificanceLevel.HIGH.value or prio == "high":
            if has_gap:
                return ReasoningEligibilityResult(
                    eligible=True,
                    reason=f"High significance ({sig_lvl}) with open information gap warrants bounded investigation & reasoning.",
                    priority="high",
                    estimated_reasoning_value=ReasoningValueLevel.HIGH.value,
                    cost_class=ReasoningCostClass.DEEP_INVESTIGATION.value,
                    eligibility=ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value,
                    budget=ReasoningBudget.high(),
                    significance_level=sig_lvl,
                    situation_id=situation.id,
                    uncertainty_present=True,
                    actionability=actionable_val,
                )
            return ReasoningEligibilityResult(
                eligible=True,
                reason=f"High significance ({sig_lvl}) situation warrants Hermes reasoning resources.",
                priority="high",
                estimated_reasoning_value=ReasoningValueLevel.HIGH.value,
                cost_class=ReasoningCostClass.STANDARD.value,
                eligibility=ReasoningEligibility.HERMES_REASONING.value,
                budget=ReasoningBudget.high(),
                significance_level=sig_lvl,
                situation_id=situation.id,
                actionability=actionable_val,
            )

        # ---------------------------------------------------------------------
        # 7. High-Value Cross-Context Situation -> ALLOW
        # ---------------------------------------------------------------------
        if cross_context:
            return ReasoningEligibilityResult(
                eligible=True,
                reason="Meaningful cross-context situation where reasoning materially synthesizes disparate domains.",
                priority="high" if prio in ("high", "critical") else "medium",
                estimated_reasoning_value=ReasoningValueLevel.HIGH.value,
                cost_class=ReasoningCostClass.DEEP_INVESTIGATION.value if has_gap else ReasoningCostClass.STANDARD.value,
                eligibility=ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value if has_gap else ReasoningEligibility.HERMES_REASONING.value,
                budget=ReasoningBudget.high(),
                significance_level=sig_lvl,
                situation_id=situation.id,
                uncertainty_present=has_gap,
                actionability=actionable_val,
            )

        # ---------------------------------------------------------------------
        # 8. Novel combination with moderate+ significance -> ALLOW
        # ---------------------------------------------------------------------
        if getattr(significance, "novelty_impact", None) in ("novel_combination", "highly_unusual"):
            return ReasoningEligibilityResult(
                eligible=True,
                reason=f"Novel combination ({significance.novelty_impact}) warrants Hermes exploratory reasoning.",
                priority="medium",
                estimated_reasoning_value=ReasoningValueLevel.MEDIUM.value,
                cost_class=ReasoningCostClass.STANDARD.value,
                eligibility=ReasoningEligibility.HERMES_REASONING.value,
                budget=ReasoningBudget.high(),
                significance_level=sig_lvl,
                situation_id=situation.id,
                actionability=actionable_val,
            )

        # ---------------------------------------------------------------------
        # 9. Medium Significance or New Actionable Situation -> ALLOW
        # ---------------------------------------------------------------------
        if sig_lvl == SignificanceLevel.MEDIUM.value or prio == "medium" or is_new_situation:
            if has_gap:
                return ReasoningEligibilityResult(
                    eligible=True,
                    reason="Medium significance situation with information gap warrants bounded investigation.",
                    priority="medium",
                    estimated_reasoning_value=ReasoningValueLevel.MEDIUM.value,
                    cost_class=ReasoningCostClass.DEEP_INVESTIGATION.value,
                    eligibility=ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value,
                    budget=ReasoningBudget.high(),
                    significance_level=sig_lvl,
                    situation_id=situation.id,
                    uncertainty_present=True,
                    actionability=actionable_val,
                )
            return ReasoningEligibilityResult(
                eligible=True,
                reason="Medium significance situation warrants standard Hermes reasoning resources.",
                priority="medium",
                estimated_reasoning_value=ReasoningValueLevel.MEDIUM.value,
                cost_class=ReasoningCostClass.STANDARD.value,
                eligibility=ReasoningEligibility.HERMES_REASONING.value,
                budget=ReasoningBudget.medium(),
                significance_level=sig_lvl,
                situation_id=situation.id,
                actionability=actionable_val,
            )

        # ---------------------------------------------------------------------
        # 10. Low Significance / Routine -> LOCAL ONLY (no Hermes call needed)
        # ---------------------------------------------------------------------
        return ReasoningEligibilityResult(
            eligible=True,  # Eligible for local rule updates
            reason="Low significance situation handled via local deterministic updates without Hermes invocation.",
            priority="low",
            estimated_reasoning_value=ReasoningValueLevel.LOW.value,
            cost_class=ReasoningCostClass.LOCAL_ONLY.value,
            eligibility=ReasoningEligibility.LOCAL_REASONING.value,
            budget=ReasoningBudget.low(),
            significance_level=sig_lvl,
            situation_id=situation.id,
            actionability=actionable_val,
        )
