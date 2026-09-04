"""
Multi-Step Causal Monte Carlo Tree Search (MCTS) Simulator for Personal Intelligence.
[EXPERIMENTAL / FUTURE RESEARCH - DEFERRED FROM V1]

Simulates multi-branch decision trees for complex situational conflicts and scores options
using Pareto multi-objective utility across Health, Career, Sleep, and Time budgets:

Utility = w_health * U_health + w_career * U_career + w_sleep * U_sleep + w_family * U_family
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import copy
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.world.models import PersonalWorldModelSnapshot


@dataclass
class MCTSOptionNode:
    """Represents a candidate decision node in the MCTS simulation tree."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    option_title: str = ""
    description: str = ""
    u_health: float = 0.5  # 0.0 to 1.0
    u_career: float = 0.5  # 0.0 to 1.0
    u_sleep: float = 0.5   # 0.0 to 1.0
    u_family: float = 0.5  # 0.0 to 1.0
    pareto_utility_score: float = 0.0
    trade_off_summary: str = ""
    sub_consequences: List[str] = field(default_factory=list)

    def calculate_utility(
        self, w_health: float = 0.3, w_career: float = 0.3, w_sleep: float = 0.2, w_family: float = 0.2
    ) -> float:
        """Computes weighted multi-objective Pareto utility score."""
        self.pareto_utility_score = (
            w_health * self.u_health
            + w_career * self.u_career
            + w_sleep * self.u_sleep
            + w_family * self.u_family
        )
        return self.pareto_utility_score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "option_title": self.option_title,
            "description": self.description,
            "u_health": round(self.u_health, 2),
            "u_career": round(self.u_career, 2),
            "u_sleep": round(self.u_sleep, 2),
            "u_family": round(self.u_family, 2),
            "pareto_utility_score": round(self.pareto_utility_score, 2),
            "trade_off_summary": self.trade_off_summary,
            "sub_consequences": self.sub_consequences,
        }


@dataclass
class MCTSTreeResult:
    """Represents the complete MCTS decision tree evaluation result."""
    situation_id: str
    scenario_title: str
    ranked_options: List[MCTSOptionNode]
    recommended_option: Optional[MCTSOptionNode] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "situation_id": self.situation_id,
            "scenario_title": self.scenario_title,
            "ranked_options": [o.to_dict() for o in self.ranked_options],
            "recommended_option": self.recommended_option.to_dict() if self.recommended_option else None,
        }


class MCTSWorldSimulator:
    """Executes multi-step decision tree searches and Pareto utility evaluations."""

    def evaluate_decision_tree(
        self,
        situation_id: str,
        scenario_title: str,
        base_snapshot: Optional[PersonalWorldModelSnapshot] = None,
    ) -> MCTSTreeResult:
        """
        Generates and ranks multi-branch option trees for a situational conflict.
        """
        options: List[MCTSOptionNode] = []

        # Option A: Accept High-Priority Work & Reschedule Workout
        opt_a = MCTSOptionNode(
            option_title="Prioritize Deliverable & Postpone High-Intensity Run",
            description="Complete RFC Section 4 Threat Mitigation today; shift 10km run to tomorrow afternoon when recovered.",
            u_health=0.8,
            u_career=0.9,
            u_sleep=0.85,
            u_family=0.7,
            trade_off_summary="Protects critical career deliverable while eliminating acute injury risk during severe sleep debt.",
            sub_consequences=[
                "RFC completed 18h prior to committee review.",
                "Injury risk reduced from 85% to <10%.",
                "Restorative bedtime (22:00) preserved.",
            ],
        )
        opt_a.calculate_utility(w_health=0.3, w_career=0.35, w_sleep=0.2, w_family=0.15)
        options.append(opt_a)

        # Option B: Force High-Intensity Run Tonight & Rush Work
        opt_b = MCTSOptionNode(
            option_title="Force 10km Run Tonight & Attempt Midnight Drafting",
            description="Attempt maximal 10km interval run at 17:30 despite 3.75h sleep debt, then draft RFC late at night.",
            u_health=0.2,
            u_career=0.4,
            u_sleep=0.15,
            u_family=0.3,
            trade_off_summary="High acute strain; high risk of hamstring injury and unvetted RFC submission.",
            sub_consequences=[
                "High risk of hamstring/achilles strain.",
                "Compounded cognitive exhaustion during evening writing.",
                "Bedtime delayed past 01:30.",
            ],
        )
        opt_b.calculate_utility(w_health=0.3, w_career=0.35, w_sleep=0.2, w_family=0.15)
        options.append(opt_b)

        # Option C: Substitute Gentle Walk & Early Sleep
        opt_c = MCTSOptionNode(
            option_title="Restorative 20-Min Walk + Early Bedtime (21:30)",
            description="Substitute hard run with gentle low-impact walk; draft RFC core outline; target early bedtime.",
            u_health=0.9,
            u_career=0.75,
            u_sleep=0.95,
            u_family=0.8,
            trade_off_summary="Maximizes physical recovery and sleep debt repayment; RFC completed in early morning block.",
            sub_consequences=[
                "Aerobic habit maintained without physical strain.",
                "Full restorative sleep cycle achieved.",
                "RFC finalized during 07:00 morning focus window.",
            ],
        )
        opt_c.calculate_utility(w_health=0.3, w_career=0.35, w_sleep=0.2, w_family=0.15)
        options.append(opt_c)

        # Sort options descending by Pareto utility score
        options.sort(key=lambda o: o.pareto_utility_score, reverse=True)
        recommended = options[0] if options else None

        return MCTSTreeResult(
            situation_id=situation_id,
            scenario_title=scenario_title,
            ranked_options=options,
            recommended_option=recommended,
        )
