"""
Situation Lifecycle Manager.
Coordinates situation states (OPEN, MONITORING, RESOLVED, EXPIRED, SUPPRESSED),
guarantees identity preservation across repeated evaluations without duplicate creation,
and drives scheduled future re-evaluations.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Tuple

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.goals.models import Goal
from personal_intelligence.core.situations.models import (
    Situation,
    SituationStatus,
)
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.storage.db import DatabaseManager


@dataclass
class SituationReevaluationResult:
    """Outcome of a scheduled situation re-evaluation cycle."""
    situation: Situation
    bounded_context: Any
    workflow_result: Optional[Any] = None
    status_changed: bool = False
    previous_status: str = ""
    new_status: str = ""
    next_evaluation_at: Optional[datetime] = None


class SituationLifecycleManager:
    """
    Manages the end-to-end lifecycle and identity preservation of situations.
    Deduplicates active situations, schedules future re-evaluations, and drives
    automated re-evaluation passes with fresh state retrieval and context rebuilding.
    """

    def __init__(
        self,
        situation_store: Optional[SituationStore] = None,
        context_builder: Optional[Any] = None,
        db_manager: Optional[DatabaseManager] = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.situation_store = situation_store or SituationStore(db_manager=self.db_manager)
        if context_builder is None:
            from personal_intelligence.core.context.builder import ContextBuilder
            self.context_builder = ContextBuilder(situation_store=self.situation_store)
        else:
            self.context_builder = context_builder

    def register_or_update(
        self,
        candidate_situation: Situation,
        current_state: Optional[StateRepresentation] = None,
        timeline: Optional[Timeline] = None,
        goals: Optional[List[Goal]] = None,
        next_evaluation_at: Optional[datetime] = None,
    ) -> Tuple[Situation, bool]:
        """
        Registers a new situation or updates an existing active situation of the same type.
        Maintains situation identity across evaluations to prevent duplicate situations.
        Returns (situation, is_new: bool).
        """
        now = datetime.now(timezone.utc)

        # 1. Check for existing active situation of the same type
        existing = self.situation_store.find_active_by_type(
            situation_type=candidate_situation.type,
            related_goals=candidate_situation.related_goals,
        )

        if existing is not None:
            # Maintain identity: merge evidence, update context, advance timestamps
            merged_evidence = list(existing.evidence)
            for ev in candidate_situation.evidence:
                if ev not in merged_evidence:
                    merged_evidence.append(ev)

            merged_goals = list(existing.related_goals)
            for rg in candidate_situation.related_goals:
                if rg not in merged_goals:
                    merged_goals.append(rg)

            merged_context = dict(existing.context)
            merged_context.update(candidate_situation.context)
            merged_context["last_candidate_evaluation"] = format_iso8601(now)

            new_next_eval = next_evaluation_at if next_evaluation_at is not None else existing.next_evaluation_at
            new_status = existing.status
            if next_evaluation_at is not None and existing.status == SituationStatus.OPEN.value:
                new_status = SituationStatus.MONITORING.value

            updated = self.situation_store.update(
                situation_id=existing.id,
                status=new_status,
                priority=candidate_situation.priority or existing.priority,
                novelty=max(existing.novelty, candidate_situation.novelty),
                context=merged_context,
                evidence=merged_evidence,
                related_goals=merged_goals,
                last_evaluated_at=now,
                next_evaluation_at=new_next_eval,
                expires_at=candidate_situation.expires_at or existing.expires_at,
            )
            return (updated or existing, False)

        # 2. No active situation exists: Persist new situation
        init_status = candidate_situation.status or SituationStatus.OPEN.value
        if next_evaluation_at is not None and init_status == SituationStatus.OPEN.value:
            init_status = SituationStatus.MONITORING.value

        new_sit = self.situation_store.create(
            type=candidate_situation.type,
            priority=candidate_situation.priority,
            novelty=candidate_situation.novelty,
            context=candidate_situation.context,
            evidence=candidate_situation.evidence,
            related_goals=candidate_situation.related_goals,
            expires_at=candidate_situation.expires_at,
            next_evaluation_at=next_evaluation_at,
            status=init_status,
            situation_id=candidate_situation.id,
        )
        return (new_sit, True)

    def schedule_reevaluation(
        self,
        situation_id: str,
        next_evaluation_at: datetime,
    ) -> Optional[Situation]:
        """Schedules future re-evaluation and transitions situation to MONITORING status."""
        return self.situation_store.schedule_reevaluation(situation_id, next_evaluation_at)

    def process_due_reevaluations(
        self,
        current_state: StateRepresentation,
        timeline: Optional[Timeline] = None,
        goals: Optional[List[Goal]] = None,
        as_of: Optional[datetime] = None,
        reasoning_workflow: Optional[Any] = None,
        resolution_checker: Optional[Callable[[Situation, StateRepresentation, Any], bool]] = None,
    ) -> List[SituationReevaluationResult]:
        """
        Drives the scheduled re-evaluation cycle:
        1. Queries due situations whose next_evaluation_at <= as_of.
        2. Retrieves fresh state and timeline slices.
        3. Rebuilds bounded reasoning context.
        4. Evaluates with Hermes reasoning if reasoning_workflow is provided.
        5. Updates situation state, identity, and next schedule.
        """
        ref_dt = as_of if as_of is not None else datetime.now(timezone.utc)
        ref_dt = ensure_timezone_aware(ref_dt, "as_of")

        due_situations = self.situation_store.get_due_reevaluations(as_of=ref_dt)
        results: List[SituationReevaluationResult] = []

        for sit in due_situations:
            prev_status = sit.status

            # 1. Rebuild fresh bounded context
            bounded_ctx = self.context_builder.build_bounded_context(
                situation=sit,
                current_state=current_state,
                timeline=timeline,
                goals=goals,
                objective=f"Scheduled re-evaluation of {sit.type} situation",
            )

            # 2. Check if condition resolved via custom checker or expiration
            is_resolved = False
            if resolution_checker:
                is_resolved = resolution_checker(sit, current_state, bounded_ctx)

            workflow_res = None
            if not is_resolved and reasoning_workflow:
                try:
                    workflow_res = reasoning_workflow.run_workflow(
                        situation=sit,
                        current_state=current_state,
                        timeline=timeline,
                        goals=goals,
                        objective=f"Scheduled re-evaluation cycle for active situation '{sit.type}'",
                    )
                    # If recommendations indicate resolution or risk ceased
                    if workflow_res and hasattr(workflow_res, "synthesis"):
                        synth = workflow_res.synthesis
                        if getattr(synth, "urgency", "low") == "low" and not getattr(synth, "requires_follow_up", True):
                            # Condition cleared
                            is_resolved = True
                except Exception:
                    pass

            # 3. Update Situation Status & Schedule
            if is_resolved:
                updated_sit = self.situation_store.resolve(
                    situation_id=sit.id,
                    resolution_notes=f"Resolved during scheduled re-evaluation at {format_iso8601(ref_dt)}",
                )
                final_sit = updated_sit or sit
                status_changed = (final_sit.status != prev_status)
                results.append(SituationReevaluationResult(
                    situation=final_sit,
                    bounded_context=bounded_ctx,
                    workflow_result=workflow_res,
                    status_changed=status_changed,
                    previous_status=prev_status,
                    new_status=final_sit.status,
                    next_evaluation_at=None,
                ))
            else:
                # Still active: advance last_evaluated_at and keep in MONITORING
                new_context = dict(sit.context)
                new_context["last_reevaluation_at"] = format_iso8601(ref_dt)
                updated_sit = self.situation_store.update(
                    situation_id=sit.id,
                    status=SituationStatus.MONITORING.value,
                    last_evaluated_at=ref_dt,
                    context=new_context,
                )
                final_sit = updated_sit or sit
                status_changed = (final_sit.status != prev_status)
                results.append(SituationReevaluationResult(
                    situation=final_sit,
                    bounded_context=bounded_ctx,
                    workflow_result=workflow_res,
                    status_changed=status_changed,
                    previous_status=prev_status,
                    new_status=final_sit.status,
                    next_evaluation_at=final_sit.next_evaluation_at,
                ))

        return results

    def resolve_situation(
        self,
        situation_id: str,
        resolution_notes: Optional[str] = None,
    ) -> Optional[Situation]:
        """Resolves an active situation."""
        return self.situation_store.resolve(situation_id, resolution_notes)

    def suppress_situation(
        self,
        situation_id: str,
        suppress_until: Optional[datetime] = None,
        reason: Optional[str] = None,
    ) -> Optional[Situation]:
        """Suppresses a situation temporarily."""
        return self.situation_store.suppress(situation_id, suppress_until, reason)

    def expire_due_situations(
        self,
        as_of: Optional[datetime] = None,
    ) -> List[Situation]:
        """Sweeps expired situations."""
        return self.situation_store.expire(as_of_time=as_of)
