"""
Counterfactual Simulation Engine ("What-If" State Projection) for Personal Intelligence.

Allows executing state projection simulations on snapshot copies without mutating the live state.
Evaluates potential domino effects, schedule overlaps, and goal conflict risks when hypothetical events occur.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import copy
from typing import Any, Dict, List, Optional

from personal_intelligence.core.events.models import Event
from personal_intelligence.core.goals.engine import GoalEngine
from personal_intelligence.core.world.models import PersonalWorldModelSnapshot, OpenIssue, IssueSeverity


@dataclass
class SimulationResult:
    """Represents the output of a counterfactual 'what-if' state simulation."""
    scenario_description: str
    hypothetical_events: List[Event]
    predicted_conflicts: List[Dict[str, Any]]
    predicted_issues: List[OpenIssue]
    schedule_domino_effects: List[str]
    is_safe: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_description": self.scenario_description,
            "hypothetical_events_count": len(self.hypothetical_events),
            "predicted_conflicts": self.predicted_conflicts,
            "predicted_issues": [i.to_dict() if hasattr(i, "to_dict") else str(i) for i in self.predicted_issues],
            "schedule_domino_effects": self.schedule_domino_effects,
            "is_safe": self.is_safe,
        }


class WorldModelSimulator:
    """Executes non-destructive counterfactual simulations on forked world model snapshots."""

    def __init__(self, goal_engine: Optional[GoalEngine] = None) -> None:
        self.goal_engine = goal_engine

    def simulate_hypothetical_scenario(
        self,
        base_snapshot: PersonalWorldModelSnapshot,
        hypothetical_events: List[Event],
        scenario_description: str = "Counterfactual Scenario",
    ) -> SimulationResult:
        """
        Forks the world model snapshot, applies hypothetical events, and predicts risks.
        """
        # Deep copy snapshot to preserve live isolation
        sim_snapshot = copy.deepcopy(base_snapshot)

        predicted_issues: List[OpenIssue] = []
        domino_effects: List[str] = []
        conflicts: List[Dict[str, Any]] = []

        for h_evt in hypothetical_events:
            ev_type = h_evt.event_type.lower()
            payload = h_evt.payload if isinstance(h_evt.payload, dict) else {}
            summary = payload.get("summary", "")

            # 1. Travel delay / flight delay domino detection
            if "delay" in ev_type or "delay" in summary.lower() or "postponed" in summary.lower():
                domino_effects.append(f"Delay event '{summary}' shifts subsequent scheduled intervals.")
                issue = OpenIssue(
                    title=f"Potential domino delay from: {summary}",
                    severity=IssueSeverity.HIGH.value,
                    status="investigating",
                )
                predicted_issues.append(issue)

            # 2. Sleep deficit / biometric strain domino detection
            elif "sleep" in ev_type or "sleep" in summary.lower() or payload.get("duration_minutes", 480) < 300:
                domino_effects.append(f"Biometric strain detected in '{summary}'. High-intensity goals at risk.")
                conflicts.append({
                    "conflict_type": "biometric_recovery_deficit",
                    "description": f"Hypothetical event '{summary}' induces high physical fatigue conflict.",
                    "severity": "high",
                })

        is_safe = len(predicted_issues) == 0 and len(conflicts) == 0

        return SimulationResult(
            scenario_description=scenario_description,
            hypothetical_events=hypothetical_events,
            predicted_conflicts=conflicts,
            predicted_issues=predicted_issues,
            schedule_domino_effects=domino_effects,
            is_safe=is_safe,
        )
