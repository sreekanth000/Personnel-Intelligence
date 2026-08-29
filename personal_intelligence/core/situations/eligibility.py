"""
Reasoning Eligibility Gate and Reasoning Budget for Personal Intelligence.

Implements a deterministic filter between SituationEngine and Hermes:
  EVENT -> STATE CHANGE -> SIGNIFICANCE -> SITUATION -> REASONING ELIGIBILITY -> HERMES

Decides whether, when, and with what tool/token budget to invoke Hermes LLM reasoning,
preventing unnecessary or wasteful API calls on trivial routine events.

Blueprint Reference: §6 Reasoning Eligibility Gate, Change 2 & 3.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from personal_intelligence.core.events.models import ensure_timezone_aware, format_iso8601
from personal_intelligence.core.significance.models import SignificanceAssessment, SignificanceLevel
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus


class ReasoningEligibility(str, Enum):
    """Categorical reasoning eligibility decision."""
    NO_REASONING = "no_reasoning"
    LOCAL_REASONING = "local_reasoning"
    HERMES_REASONING = "hermes_reasoning"
    HERMES_INVESTIGATION_AND_REASONING = "hermes_investigation_and_reasoning"


class ReasoningBudgetLevel(str, Enum):
    """Tier of reasoning resource budget."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ReasoningBudget:
    """
    Deterministic budget controlling LLM invocation and external investigation tools.
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
    """Outcome of reasoning eligibility evaluation."""
    eligibility: str  # ReasoningEligibility enum value
    budget: ReasoningBudget
    reason: str
    significance_level: str = SignificanceLevel.MEDIUM.value
    situation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.timestamp = ensure_timezone_aware(self.timestamp, "ReasoningEligibilityResult timestamp")
        if isinstance(self.eligibility, ReasoningEligibility):
            self.eligibility = self.eligibility.value

    @property
    def requires_hermes(self) -> bool:
        return self.eligibility in (
            ReasoningEligibility.HERMES_REASONING.value,
            ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value,
        )

    @property
    def requires_investigation(self) -> bool:
        return self.eligibility == ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eligibility": self.eligibility,
            "budget": self.budget.to_dict(),
            "reason": self.reason,
            "significance_level": self.significance_level,
            "situation_id": self.situation_id,
            "timestamp": format_iso8601(self.timestamp),
        }


class ReasoningEligibilityGate:
    """
    Deterministic gate that evaluates whether a situation warrants Hermes reasoning.
    """

    def evaluate(
        self,
        situation: Situation,
        significance: SignificanceAssessment,
        is_new_situation: bool = False,
        has_new_events: bool = False,
        is_due_reevaluation: bool = False,
    ) -> ReasoningEligibilityResult:
        """
        Determines eligibility and budget for situational reasoning.
        """
        sig_lvl = significance.level.lower()
        prio = str(situation.priority).lower()
        has_gap = bool(situation.information_required)

        # 1. Closed or resolved situations never reason
        if situation.status in (SituationStatus.RESOLVED.value, SituationStatus.DISMISSED.value, SituationStatus.CLOSED.value):
            return ReasoningEligibilityResult(
                eligibility=ReasoningEligibility.NO_REASONING.value,
                budget=ReasoningBudget.low(),
                reason=f"Situation {situation.id} is {situation.status}; reasoning skipped.",
                significance_level=sig_lvl,
                situation_id=situation.id,
            )

        # 2. Insignificant changes -> NO_REASONING
        if sig_lvl == SignificanceLevel.NOT_SIGNIFICANT.value and not is_due_reevaluation and not has_gap:
            return ReasoningEligibilityResult(
                eligibility=ReasoningEligibility.NO_REASONING.value,
                budget=ReasoningBudget.low(),
                reason="Change evaluated as NOT_SIGNIFICANT; skipping LLM invocation.",
                significance_level=sig_lvl,
                situation_id=situation.id,
            )

        # 3. Already evaluated situation with no new events and not due -> NO_REASONING
        if not is_new_situation and not has_new_events and not is_due_reevaluation:
            return ReasoningEligibilityResult(
                eligibility=ReasoningEligibility.NO_REASONING.value,
                budget=ReasoningBudget.low(),
                reason="Situation already evaluated and no new material observations present.",
                significance_level=sig_lvl,
                situation_id=situation.id,
            )

        # 4. Critical or High Significance with Information Gap -> HERMES_INVESTIGATION_AND_REASONING
        if has_gap and (sig_lvl in (SignificanceLevel.CRITICAL.value, SignificanceLevel.HIGH.value) or prio in ("critical", "high")):
            budget = ReasoningBudget.critical() if sig_lvl == SignificanceLevel.CRITICAL.value else ReasoningBudget.high()
            return ReasoningEligibilityResult(
                eligibility=ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value,
                budget=budget,
                reason=f"High/Critical significance ({sig_lvl}) with open information gap warrants bounded investigation & reasoning.",
                significance_level=sig_lvl,
                situation_id=situation.id,
            )

        # 5. Critical or High Significance without Gap -> HERMES_REASONING (High/Critical budget)
        if sig_lvl == SignificanceLevel.CRITICAL.value or prio == "critical":
            return ReasoningEligibilityResult(
                eligibility=ReasoningEligibility.HERMES_REASONING.value,
                budget=ReasoningBudget.critical(),
                reason="Critical situation warrants Hermes deep reasoning.",
                significance_level=sig_lvl,
                situation_id=situation.id,
            )

        if sig_lvl == SignificanceLevel.HIGH.value or prio == "high" or significance.novelty_impact in ("novel_combination", "highly_unusual"):
            return ReasoningEligibilityResult(
                eligibility=ReasoningEligibility.HERMES_REASONING.value,
                budget=ReasoningBudget.high(),
                reason=f"High significance ({sig_lvl}) or novel combination warrants Hermes reasoning.",
                significance_level=sig_lvl,
                situation_id=situation.id,
            )

        # 6. Medium Significance -> HERMES_REASONING (Standard Medium budget)
        if sig_lvl == SignificanceLevel.MEDIUM.value or prio == "medium" or is_new_situation:
            if has_gap:
                return ReasoningEligibilityResult(
                    eligibility=ReasoningEligibility.HERMES_INVESTIGATION_AND_REASONING.value,
                    budget=ReasoningBudget.high(),
                    reason="Medium significance situation with information gap warrants bounded investigation.",
                    significance_level=sig_lvl,
                    situation_id=situation.id,
                )
            return ReasoningEligibilityResult(
                eligibility=ReasoningEligibility.HERMES_REASONING.value,
                budget=ReasoningBudget.medium(),
                reason="Medium significance situation warrants standard Hermes reasoning.",
                significance_level=sig_lvl,
                situation_id=situation.id,
            )

        # 7. Low Significance -> LOCAL_REASONING (no Hermes call needed)
        return ReasoningEligibilityResult(
            eligibility=ReasoningEligibility.LOCAL_REASONING.value,
            budget=ReasoningBudget.low(),
            reason="Low significance situation handled via local deterministic updates without Hermes invocation.",
            significance_level=sig_lvl,
            situation_id=situation.id,
        )
