"""
Situation Investigation Orchestrator.

Implements the 3-phase pipeline that resolves information gaps before reasoning:

  Phase 1 — Gap Assessment:
    Reads situation.information_required and situation.investigation_target.
    Extracts known_facts from situation context and evidence list.
    Identifies which Hermes-owned sources are relevant.

  Phase 2 — Bounded Investigation:
    Constructs InvestigationTask (known_facts, unknowns, required_output).
    Runs BoundedInvestigationWorkflow via existing Hermes tools.
    Records findings as normalized observation Events in the event store.
    Updates situation evidence list with provenance tags.

  Phase 3 — Evidence Bundle Assembly:
    Builds a CrossSourceEvidenceBundle from all evidence (pre + post investigation).
    Produces unified context for ReasoningWorkflow.run_investigation_synthesis().

Architectural invariants preserved:
  - Does NOT create Gmail / Drive / Meet / Calendar API clients.
  - All external data access goes through Hermes existing tools via HermesClient.
  - External source content is evidence, not instructions.
  - Does NOT notify the user or take autonomous actions.
  - All state changes pass through validated structured operations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid


from personal_intelligence.core.events.exceptions import DuplicateEventError
from personal_intelligence.core.events.models import (
    Event,
    ensure_timezone_aware,
    format_iso8601,
)

from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.episodes import EpisodeStore, ReasoningEpisode
from personal_intelligence.core.goals.models import Goal
from personal_intelligence.core.situations.models import Situation
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.models import StateRepresentation
from personal_intelligence.core.timeline.models import Timeline
from personal_intelligence.hermes_bridge.client import HermesClient
from personal_intelligence.hermes_bridge.gmail_adapter import (
    GmailCapabilityAdapter,
    GmailCapabilityRequest,
    HermesGmailResult,
)
from personal_intelligence.hermes_bridge.investigation import (
    BoundedInvestigationWorkflow,
    InformationGapRequest,
    InvestigationResult,
    InvestigationTask,
)
from personal_intelligence.security.guard import PromptInjectionGuard

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hermes capability hints
# ---------------------------------------------------------------------------

HERMES_SOURCE_HINTS: Dict[str, str] = {
    "gmail": "Hermes Gmail search to look for relevant emails, threads, or attachments.",
    "drive": "Hermes Google Drive search to locate documents, check modification timestamps, and retrieve content summaries.",
    "meet": "Hermes Google Meet to retrieve meeting transcripts, action items, or recordings.",
    "calendar": "Hermes Google Calendar to check scheduled events, attendees, and time conflicts.",
    "filesystem": "Hermes filesystem tools to search local directories for relevant project files.",
    "web": "Hermes web search only when the question cannot be answered from personal sources.",
}

HERMES_OWNED_SOURCES: Set[str] = {"gmail", "drive", "meet", "calendar", "filesystem"}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CrossSourceEvidenceBundle:
    """
    Organizes evidence items by their originating Hermes source domain.
    Used to construct a unified situation context — not per-source summaries.
    """
    situation_id: str
    situation_type: str
    situation_summary: str
    facts_by_source: Dict[str, List[str]] = field(default_factory=dict)
    remaining_unknowns: List[str] = field(default_factory=list)
    hermes_tools_used: List[str] = field(default_factory=list)
    source_references: List[str] = field(default_factory=list)
    related_goals: List[str] = field(default_factory=list)
    uncertainty_notes: List[str] = field(default_factory=list)
    investigation_task_ids: List[str] = field(default_factory=list)

    def all_facts(self) -> List[str]:
        """Returns all facts across all sources as a flat tagged list."""
        facts = []
        for source, items in self.facts_by_source.items():
            for item in items:
                facts.append(f"[{source.upper()}] {item}")
        return facts

    def to_unified_context_string(self) -> str:
        """
        Builds a single unified situation narrative across all sources.
        Does NOT produce per-source summaries.
        """
        lines = [
            f"=== UNIFIED SITUATION CONTEXT: {self.situation_type} ===",
            f"Situation: {self.situation_summary}",
            "",
            "--- CROSS-SOURCE EVIDENCE ---",
        ]

        all_f = self.all_facts()
        if all_f:
            for f in all_f:
                lines.append(f"  * {f}")
        else:
            lines.append("  (No evidence collected yet from external sources)")

        if self.source_references:
            lines.append("")
            lines.append("--- SOURCE PROVENANCE ---")
            for ref in self.source_references:
                lines.append(f"  - {ref}")

        if self.remaining_unknowns:
            lines.append("")
            lines.append("--- UNRESOLVED INFORMATION GAPS ---")
            for unk in self.remaining_unknowns:
                lines.append(f"  ? {unk}")

        if self.uncertainty_notes:
            lines.append("")
            lines.append("--- INVESTIGATION UNCERTAINTY ---")
            for note in self.uncertainty_notes:
                lines.append(f"  ! {note}")

        if self.related_goals:
            lines.append("")
            lines.append("--- RELATED USER GOALS ---")
            for g in self.related_goals:
                lines.append(f"  -> {g}")

        if self.hermes_tools_used:
            lines.append("")
            lines.append(f"--- HERMES TOOLS USED: {', '.join(self.hermes_tools_used)} ---")

        return "\n".join(lines)


class InvestigationTerminationReason(str, Enum):
    """Reason why an information gap investigation terminated."""
    GAP_RESOLVED = "gap_resolved"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NO_RELEVANT_EVIDENCE = "no_relevant_evidence"
    ERROR = "error"


@dataclass
class InvestigationPlan:
    """
    Plan constructed during Phase 1 (Gap Assessment).
    Specifies WHAT INFORMATION IS NEEDED, not HOW TO ACCESS THE SOURCE.
    Hermes determines how to retrieve information within max_tool_calls bound.
    """
    situation_id: str
    situation_type: str
    investigation_target: str
    information_gap: Optional[str] = None
    known_facts: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    relevant_hermes_sources: List[str] = field(default_factory=list)
    preferred_capabilities: List[str] = field(default_factory=list)
    max_tool_calls: int = 5
    max_rounds: int = 3
    max_context_size: int = 32000
    required_output_schema: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_investigation_task_kwargs(self) -> Dict[str, Any]:
        """Returns kwargs to pass to InvestigationTask / InformationGapRequest constructor."""
        return {
            "question_to_investigate": self.information_gap or self.investigation_target,
            "information_gap": self.information_gap or self.investigation_target,
            "preferred_capabilities": self.preferred_capabilities or self.relevant_hermes_sources or ["drive", "gmail", "meet"],
            "max_tool_calls": self.max_tool_calls,
            "known_facts": self.known_facts,
            "unknowns": self.unknowns,
            "required_output": self.required_output_schema or {
                "findings": "list of factual findings from Hermes sources",
                "source_references": "list of source document IDs or references",
                "uncertainty": "list of remaining unknowns after investigation",
                "expiration_time": "ISO 8601 UTC timestamp",
            },
            "situation_id": self.situation_id,
        }


@dataclass
class InvestigationOutcome:
    """
    Complete result of the situation investigation pipeline.
    """
    situation: Situation
    plan: InvestigationPlan
    investigation_result: Optional[InvestigationResult]
    evidence_bundle: CrossSourceEvidenceBundle
    evidence_observations_recorded: List[str]
    episode: Optional[ReasoningEpisode]
    investigation_succeeded: bool
    gap_resolved: bool
    remaining_unknowns: List[str] = field(default_factory=list)
    rounds_executed: int = 1
    total_tool_calls: int = 0
    termination_reason: str = InvestigationTerminationReason.GAP_RESOLVED.value
    requires_user_input: bool = False
    contradiction_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "situation_id": self.situation.id,
            "situation_type": self.situation.type,
            "plan_unknowns": self.plan.unknowns,
            "investigation_succeeded": self.investigation_succeeded,
            "gap_resolved": self.gap_resolved,
            "evidence_observations_recorded": self.evidence_observations_recorded,
            "remaining_unknowns": self.remaining_unknowns,
            "rounds_executed": self.rounds_executed,
            "total_tool_calls": self.total_tool_calls,
            "termination_reason": self.termination_reason,
            "requires_user_input": self.requires_user_input,
            "contradiction_notes": self.contradiction_notes,
            "investigation_task_id": (
                self.investigation_result.task_id if self.investigation_result else None
            ),
        }


# ---------------------------------------------------------------------------
# SituationInvestigator
# ---------------------------------------------------------------------------

class SituationInvestigator:
    """
    Orchestrates bounded information gap investigations through native Hermes runtime capabilities.

    Invariants:
    - Never implements direct external APIs (Gmail, Drive, Calendar, Meet, Filesystem).
    - Enforces strict investigation limits:
        * max_rounds (default 3)
        * max_tool_calls (configurable per round / total)
        * max_context_size (configurable payload limit)
    - Stops immediately upon:
        1. Gap resolved
        2. Contradictory evidence (flags requires_user_input)
        3. Investigation budget exhausted
        4. No relevant evidence exists
    - Normalizes findings into canonical Observation records with provenance.
    - Returns structured CrossSourceEvidenceBundle directly to ContextBuilder / ReasoningWorkflow.
    """

    def __init__(
        self,
        event_store: Optional[EventStore] = None,
        situation_store: Optional[SituationStore] = None,
        episode_store: Optional[EpisodeStore] = None,
        hermes_client: Optional[HermesClient] = None,
        investigation_workflow: Optional[BoundedInvestigationWorkflow] = None,
        max_rounds: int = 3,
        max_tool_calls: int = 5,
        max_context_size: int = 32000,
    ) -> None:
        self.event_store = event_store or EventStore()
        self.situation_store = situation_store or SituationStore()
        self.episode_store = episode_store or EpisodeStore()
        self.hermes_client = hermes_client or HermesClient()
        self.investigation_workflow = investigation_workflow or BoundedInvestigationWorkflow(
            hermes_client=self.hermes_client,
            situation_store=self.situation_store,
        )
        self.gmail_adapter = GmailCapabilityAdapter(bridge=self.hermes_client)
        self.max_rounds = max(1, min(max_rounds, 10))
        self.max_tool_calls = max(1, min(max_tool_calls, 20))
        self.max_context_size = max(1000, max_context_size)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def investigate_gmail_gap(
        self,
        gap_question: str,
        query: Optional[str] = None,
        max_results: int = 5,
        time_range_days: int = 7,
        sender_filter: Optional[str] = None,
        reference_time: Optional[datetime] = None,
    ) -> HermesGmailResult:
        """
        Executes a bounded Gmail investigation strictly when a concrete information gap exists.
        
        Guarantees:
        - Limits tool calls (1 bounded query), result count (bounded <= 5), and time window (<= 14d).
        - Requests metadata and concise summaries, never entire mailboxes.
        - Treats all Gmail content as untrusted input and applies PromptInjectionGuard sanitization.
        - Converts verified findings into normalized observation events in EventStore.
        - Strictly read-only: does not send, archive, draft, or modify email.
        """
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        bounded_max_results = max(1, min(max_results, 10))
        bounded_time_days = max(1, min(time_range_days, 14))
        search_query = (query or gap_question).strip()

        req = GmailCapabilityRequest(
            query=search_query,
            max_results=bounded_max_results,
            time_range_days=bounded_time_days,
            sender_filter=sender_filter,
            read_only=True,
        )

        result = self.gmail_adapter.execute_query(req)

        if result.status == "success":
            sanitized_findings: List[str] = []
            sanitized_summaries: List[str] = []

            for idx, summary in enumerate(result.safe_summaries):
                clean_text = PromptInjectionGuard.sanitize_untrusted_text(summary, max_chars=1000)
                sanitized_summaries.append(clean_text)
                sanitized_findings.append(clean_text)

                m_ref = result.message_references[idx] if idx < len(result.message_references) else f"gmail:msg_{idx}"
                t_ref = result.thread_references[0] if result.thread_references else f"gmail:thread_{idx}"
                ts_str = result.timestamps[idx] if idx < len(result.timestamps) else ref_dt.isoformat()

                try:
                    event_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except Exception:
                    event_time = ref_dt

                obs_event = Event(
                    id=f"evt-gmail-obs-{uuid.uuid4().hex[:8]}",
                    source="gmail",
                    source_id=m_ref,
                    observation_type="gmail_evidence_observation",
                    timestamp=event_time,
                    summary=clean_text,
                    structured_data={
                        "summary": clean_text,
                        "gap_question": gap_question,
                        "message_reference": m_ref,
                        "thread_reference": t_ref,
                        "is_untrusted_input": True,
                    },
                    provenance={
                        "tool": "gmail_search",
                        "query": search_query,
                        "source_id": m_ref,
                        "is_untrusted_input": True,
                        "epistemic_tag": "FACT",
                    },
                    confidence_category="high",
                )
                try:
                    self.event_store.append(obs_event)
                except DuplicateEventError:
                    pass

            result.findings = sanitized_findings
            result.safe_summaries = sanitized_summaries

        return result

    def investigate_information_gap(
        self,
        information_gap: str,
        known_facts: Optional[List[str]] = None,
        preferred_capabilities: Optional[List[str]] = None,
        reference_time: Optional[datetime] = None,
    ) -> InvestigationOutcome:
        """
        Direct entry point to investigate a standalone information gap without a pre-existing Situation.
        """
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        dummy_situation = Situation(
            id=f"sit_gap_{uuid.uuid4().hex[:8]}",
            type="information_gap",
            priority="medium",
            novelty=0.5,
            status="open",
            information_required=True,
            investigation_target=information_gap,
            context={"description": information_gap, "known_facts": known_facts or []},
            created_at=ref_dt,
            updated_at=ref_dt,
        )
        return self.investigate(situation=dummy_situation, reference_time=ref_dt)

    def investigate(
        self,
        situation: Situation,
        current_state: Optional[StateRepresentation] = None,
        timeline: Optional[Timeline] = None,
        goals: Optional[List[Goal]] = None,
        reference_time: Optional[datetime] = None,
    ) -> InvestigationOutcome:
        """
        Runs bounded multi-round investigation for a situation.
        Enforces max_rounds, max_tool_calls, max_context_size and checks termination conditions.
        """
        ref_dt = ensure_timezone_aware(
            reference_time or datetime.now(timezone.utc), "reference_time"
        )
        goals_list = goals or []

        # Phase 1: Gap Assessment
        plan = self._assess_gaps(situation, goals_list, ref_dt)

        # If no gap, skip investigation — just build evidence bundle
        if not situation.information_required or not plan.unknowns:
            bundle = self._build_evidence_bundle(situation, [], goals_list)
            return InvestigationOutcome(
                situation=situation,
                plan=plan,
                investigation_result=None,
                evidence_bundle=bundle,
                evidence_observations_recorded=[],
                episode=None,
                investigation_succeeded=True,
                gap_resolved=True,
                rounds_executed=0,
                total_tool_calls=0,
                termination_reason=InvestigationTerminationReason.GAP_RESOLVED.value,
            )

        # Phase 2: Multi-Round Bounded Investigation Loop
        all_results: List[InvestigationResult] = []
        all_observation_ids: List[str] = []
        current_unknowns = list(plan.unknowns)
        current_knowns = list(plan.known_facts)
        total_tool_calls = 0
        rounds_executed = 0
        termination_reason = InvestigationTerminationReason.BUDGET_EXHAUSTED.value
        gap_resolved = False
        requires_user_input = False
        contradiction_notes: List[str] = []
        current_situation = situation

        for round_idx in range(1, self.max_rounds + 1):
            rounds_executed = round_idx

            # Build bounded task kwargs
            task_kwargs = plan.to_investigation_task_kwargs()
            task_kwargs["unknowns"] = current_unknowns[:5]
            task_kwargs["known_facts"] = current_knowns[:10]
            task_kwargs["max_tool_calls"] = self.max_tool_calls

            try:
                task = self.investigation_workflow.create_task(**task_kwargs)
                result = self.investigation_workflow.execute_investigation(task)
            except Exception as ex:
                logger.error("Investigation task failed in round %d: %s", round_idx, ex)
                result = InvestigationResult(
                    task_id=f"task-err-{uuid.uuid4().hex[:6]}",
                    findings=[f"Investigation failed in round {round_idx}: {str(ex)}"],
                    source_references=[],
                    uncertainty=current_unknowns,
                    expiration_time=ref_dt + timedelta(minutes=15),
                    is_valid=False,
                )

            all_results.append(result)
            total_tool_calls += self.max_tool_calls

            # Record normalized observations with provenance
            recorded_ids = self._record_investigation_observations(
                investigation_result=result,
                situation=current_situation,
                ref_dt=ref_dt,
            )
            all_observation_ids.extend(recorded_ids)

            # Update situation findings
            current_situation = self._update_situation_with_findings(
                situation=current_situation,
                investigation_result=result,
                ref_dt=ref_dt,
            )

            # Check Termination Condition 1: No Relevant Evidence Exists
            if self._is_no_relevant_evidence(result):
                termination_reason = InvestigationTerminationReason.NO_RELEVANT_EVIDENCE.value
                gap_resolved = False
                break

            # Check Termination Condition 2: Contradictory Evidence Detected
            has_contradiction, contra_details = self._detect_contradictory_evidence(result, all_results)
            if has_contradiction:
                termination_reason = InvestigationTerminationReason.CONTRADICTORY_EVIDENCE.value
                requires_user_input = True
                contradiction_notes.extend(contra_details)
                gap_resolved = False
                break

            # Check Termination Condition 3: Information Gap Resolved
            if self._is_gap_resolved(result, current_unknowns):
                termination_reason = InvestigationTerminationReason.GAP_RESOLVED.value
                gap_resolved = True
                current_unknowns = []
                break

            # Update remaining unknowns for next round
            if result.uncertainty:
                current_unknowns = list(result.uncertainty)
            for f in result.findings:
                current_knowns.append(f"Discovered: {f}")

        # Phase 3: Assemble unified cross-source evidence bundle
        bundle = self._build_evidence_bundle(
            situation=current_situation,
            investigation_results=all_results,
            goals=goals_list,
        )

        return InvestigationOutcome(
            situation=current_situation,
            plan=plan,
            investigation_result=all_results[-1] if all_results else None,
            evidence_bundle=bundle,
            evidence_observations_recorded=all_observation_ids,
            episode=None,
            investigation_succeeded=any(r.is_valid for r in all_results),
            gap_resolved=gap_resolved,
            remaining_unknowns=current_unknowns if not gap_resolved else [],
            rounds_executed=rounds_executed,
            total_tool_calls=total_tool_calls,
            termination_reason=termination_reason,
            requires_user_input=requires_user_input,
            contradiction_notes=contradiction_notes,
        )

    def _is_no_relevant_evidence(self, result: InvestigationResult) -> bool:
        """Determines if the tools returned zero matching / relevant items."""
        if not result.findings:
            return True
        joined = " ".join(result.findings).lower()
        no_evidence_keywords = [
            "no relevant evidence",
            "no matching",
            "no documents found",
            "no emails found",
            "no calendar events found",
            "not found in any queried",
            "zero results",
        ]
        return any(k in joined for k in no_evidence_keywords)

    def _detect_contradictory_evidence(
        self, current_result: InvestigationResult, all_results: List[InvestigationResult]
    ) -> Tuple[bool, List[str]]:
        """
        Detects conflicting or contradictory findings across tools/sources.
        Returns (has_contradiction, contradiction_notes).
        """
        all_findings = []
        for r in all_results:
            all_findings.extend(r.findings)

        joined = " ".join(all_findings).lower()
        notes: List[str] = []

        # Conflict pattern 1: Completed vs Cancelled/Blocked
        has_pos = any(k in joined for k in ["completed", "ready", "approved", "finalized", "sent"])
        has_neg = any(k in joined for k in ["cancelled", "canceled", "rejected", "blocked", "postponed", "overdue"])
        if has_pos and has_neg:
            notes.append("Conflicting status signals detected across sources (e.g. approved/ready vs cancelled/blocked).")

        # Conflict pattern 2: Explicit contradiction markers
        if "contradict" in joined or "conflict" in joined or "discrepancy" in joined:
            notes.append("Explicit evidentiary discrepancy identified between communication channels and artifacts.")

        return bool(notes), notes

    def _is_gap_resolved(
        self, result: InvestigationResult, unknowns: List[str]
    ) -> bool:
        """Checks if findings provide a validated factual answer resolving the information gap."""
        if not result.is_valid or not result.findings:
            return False
        if all("Investigation failed" in f for f in result.findings):
            return False
        return len(result.findings) >= 1




    # ------------------------------------------------------------------
    # Phase 1: Gap Assessment
    # ------------------------------------------------------------------

    def _assess_gaps(
        self,
        situation: Situation,
        goals: List[Goal],
        ref_dt: datetime,
    ) -> InvestigationPlan:
        """
        Extracts known facts from situation context and constructs InvestigationPlan.
        """
        known_facts: List[str] = []
        ctx = situation.context or {}

        # Pull readable facts from context fields
        _fact_fields = [
            ("description", "Situation description: {v}"),
            ("title", "Event/item title: {v}"),
            ("start_time", "Scheduled at: {v}"),
            ("due_at", "Due at: {v}"),
            ("hours_until", "Hours until event: {v}"),
            ("origin_source", "Originally detected from: {v}"),
        ]
        for key, tmpl in _fact_fields:
            v = ctx.get(key)
            if v:
                known_facts.append(tmpl.format(v=v))

        # Existing evidence references
        for ev in situation.evidence[:8]:
            ev_str = str(ev)
            if not ev_str.startswith(("external_investigation:", "finding:")):
                known_facts.append(f"Evidence reference: {ev_str}")

        # Related goal descriptions
        for goal in goals:
            if goal.id in situation.related_goals:
                known_facts.append(
                    f"Related user goal: '{goal.name}' (priority: {goal.priority})"
                )

        if not known_facts:
            known_facts.append(
                f"Situation type '{situation.type}' detected at {format_iso8601(ref_dt)}"
            )

        # Build unknowns
        unknowns: List[str] = []
        if situation.investigation_target:
            unknowns.append(situation.investigation_target)
        for unk in self._infer_unknowns_from_type(situation.type, ctx):
            if unk not in unknowns:
                unknowns.append(unk)
        if not unknowns:
            unknowns.append(f"Resolve information gap for {situation.type} situation")

        relevant_sources = self._identify_relevant_sources(
            situation.investigation_target or "", situation.type, ctx
        )

        required_output = {
            "findings": "List of factual findings discovered from Hermes sources",
            "source_references": "List of document IDs, message IDs, or URLs discovered",
            "uncertainty": "List of unknowns that could not be resolved",
            "expiration_time": "ISO 8601 UTC expiration timestamp for findings validity",
        }

        gap = situation.investigation_target or (
            f"Determine the current status and resolution details for {situation.type} situation."
        )


        return InvestigationPlan(
            situation_id=situation.id,
            situation_type=situation.type,
            investigation_target=gap,
            information_gap=gap,
            known_facts=known_facts,
            unknowns=unknowns,
            relevant_hermes_sources=relevant_sources,
            preferred_capabilities=relevant_sources,
            max_tool_calls=5,
            required_output_schema=required_output,
            created_at=ref_dt,
        )


    def _infer_unknowns_from_type(
        self, situation_type: str, context: Dict[str, Any]
    ) -> List[str]:
        """Adds inferred unknowns based on generic situation type."""
        unknowns = []
        t = situation_type.lower()
        if "commitment" in t or "deliverable" in t:
            desc = context.get("description", "the deliverable")
            unknowns.append(f"Was '{desc}' already completed or sent?")
            unknowns.append(f"Is there a newer version of '{desc}'?")
        elif "preparation" in t or "prep" in t:
            title = context.get("title", "the upcoming event")
            unknowns.append(f"Are preparation materials ready for '{title}'?")
            unknowns.append(f"Were any unresolved action items discussed about '{title}'?")
        elif "unresolved" in t or "issue" in t or "blocker" in t:
            title = context.get("title", "the issue")
            unknowns.append(f"Is the blocker '{title}' resolved in recent communications?")
        elif "information_gap" in t:
            unknowns.append("Can the referenced document or attachment be retrieved?")
        return unknowns

    def _identify_relevant_sources(
        self, target: str, situation_type: str, context: Dict[str, Any]
    ) -> List[str]:
        """Identifies which Hermes-owned sources are likely to resolve the unknowns."""
        sources: List[str] = []
        combined = f"{target} {situation_type} {str(context)}".lower()

        if any(k in combined for k in [
            "gmail", "email", "send", "message", "thread", "attachment"
        ]):
            sources.append("gmail")
        if any(k in combined for k in [
            "drive", "document", "doc", "file", "sheet", "slide", "folder"
        ]):
            sources.append("drive")
        if any(k in combined for k in [
            "meet", "meeting", "transcript", "recording", "action item"
        ]):
            sources.append("meet")
        if any(k in combined for k in [
            "calendar", "review", "scheduled", "event", "invite"
        ]):
            sources.append("calendar")
        if any(k in combined for k in [
            "local", "filesystem", "project", "directory"
        ]):
            sources.append("filesystem")

        return sources if sources else ["gmail", "drive"]

    # ------------------------------------------------------------------
    # Phase 2: Record observations
    # ------------------------------------------------------------------

    def _record_investigation_observations(
        self,
        investigation_result: InvestigationResult,
        situation: Situation,
        ref_dt: datetime,
    ) -> List[str]:
        """
        Records each validated finding as a normalized observation Event.
        Only concise factual findings are stored — no raw web HTML or API dumps.
        """
        recorded_ids: List[str] = []

        from personal_intelligence.security.guard import PromptInjectionGuard

        for i, finding in enumerate(investigation_result.findings[:10]):
            safe_finding = PromptInjectionGuard.sanitize_untrusted_text(str(finding), max_chars=500)
            evt_id = f"obs-inv-{investigation_result.task_id[:8]}-{i}-{uuid.uuid4().hex[:4]}"
            first_source = investigation_result.source_references[0] if investigation_result.source_references else "hermes_investigation"


            evt = Event(
                id=evt_id,
                observation_type="investigation_finding",
                source="hermes_investigation",
                timestamp=ref_dt,
                summary=safe_finding,
                source_id=first_source,
                structured_data={
                    "summary": safe_finding,
                    "situation_id": situation.id,
                    "task_id": investigation_result.task_id,
                    "source_references": investigation_result.source_references[:5],
                    "is_valid": investigation_result.is_valid,
                    "provenance": {
                        "tool": "BoundedInvestigationWorkflow",
                        "investigation_target": str(
                            situation.investigation_target or ""
                        )[:200],
                        "situation_type": situation.type,
                    },
                },
                provenance={
                    "tool": "BoundedInvestigationWorkflow",
                    "query": str(situation.investigation_target or "")[:200],
                    "task_id": investigation_result.task_id,
                    "situation_id": situation.id,
                },
                confidence_category="high" if investigation_result.is_valid else "moderate",
            )

            try:
                self.event_store.append(evt)
                recorded_ids.append(evt_id)
            except DuplicateEventError:
                recorded_ids.append(evt_id)
            except Exception as ex:
                logger.warning(
                    "Investigation observation %s could not be appended: %s",
                    evt_id, ex,
                )



        return recorded_ids

    def _update_situation_with_findings(
        self,
        situation: Situation,
        investigation_result: InvestigationResult,
        ref_dt: datetime,
    ) -> Situation:
        """Updates situation evidence and context with investigation findings."""
        updated_evidence = list(situation.evidence)
        evidence_tag = f"external_investigation:{investigation_result.task_id}"
        if evidence_tag not in updated_evidence:
            updated_evidence.append(evidence_tag)

        for finding in investigation_result.findings[:5]:
            tag = f"finding:{str(finding)[:80]}"
            if tag not in updated_evidence:
                updated_evidence.append(tag)

        updated_context = dict(situation.context)
        inv_summary = {
            "task_id": investigation_result.task_id,
            "findings": investigation_result.findings,
            "sources": investigation_result.source_references,
            "uncertainty": investigation_result.uncertainty,
            "valid_until": format_iso8601(investigation_result.expiration_time),
            "is_valid": investigation_result.is_valid,
            "ingested_at": format_iso8601(ref_dt),
        }
        if "external_investigations" not in updated_context:
            updated_context["external_investigations"] = []
        updated_context["external_investigations"].append(inv_summary)
        updated_context["latest_investigation_findings"] = investigation_result.findings
        updated_context["investigation_status"] = (
            "resolved" if investigation_result.is_valid else "inconclusive"
        )

        updated = self.situation_store.update(
            situation_id=situation.id,
            context=updated_context,
            evidence=updated_evidence,
            last_evaluated_at=ref_dt,
        )
        return updated or situation

    # ------------------------------------------------------------------
    # Phase 3: Cross-source evidence bundle
    # ------------------------------------------------------------------

    def _build_evidence_bundle(
        self,
        situation: Situation,
        investigation_results: List[InvestigationResult],
        goals: List[Goal],
    ) -> CrossSourceEvidenceBundle:
        """
        Assembles CrossSourceEvidenceBundle from situation evidence + investigation results.
        Evidence is tagged by originating Hermes source. Produces unified narrative context.
        """
        facts_by_source: Dict[str, List[str]] = {}
        source_references: List[str] = []
        uncertainty_notes: List[str] = []
        hermes_tools_used: List[str] = []
        investigation_task_ids: List[str] = []

        # Classify existing evidence
        for ev in situation.evidence:
            ev_str = str(ev)
            if ev_str.startswith("external_investigation:"):
                investigation_task_ids.append(ev_str.split(":", 1)[1])
            elif ev_str.startswith("finding:"):
                src = "hermes_investigation"
                if src not in facts_by_source:
                    facts_by_source[src] = []
                facts_by_source[src].append(ev_str[8:])

        # Extract findings from investigation results
        for result in investigation_results:
            if result.task_id not in investigation_task_ids:
                investigation_task_ids.append(result.task_id)

            for finding in result.findings:
                src = self._infer_finding_source(finding)
                if src not in facts_by_source:
                    facts_by_source[src] = []
                if finding not in facts_by_source[src]:
                    facts_by_source[src].append(finding)

            source_references.extend(result.source_references)
            uncertainty_notes.extend(result.uncertainty)
            if result.is_valid:
                hermes_tools_used.append("BoundedInvestigationWorkflow")

        # Add origin source context
        ctx = situation.context or {}
        origin_source = ctx.get("origin_source", "")
        if origin_source and origin_source in HERMES_OWNED_SOURCES:
            if origin_source not in facts_by_source:
                facts_by_source[origin_source] = []
            desc = ctx.get("description", "") or ctx.get("title", "")
            if desc:
                facts_by_source[origin_source].append(
                    f"Detected from {origin_source}: {desc}"
                )

        goal_names = [g.name for g in goals if g.id in situation.related_goals]
        situation_summary = (
            ctx.get("description") or ctx.get("title")
            or f"{situation.type} situation detected"
        )

        return CrossSourceEvidenceBundle(
            situation_id=situation.id,
            situation_type=situation.type,
            situation_summary=str(situation_summary),
            facts_by_source=facts_by_source,
            remaining_unknowns=list(uncertainty_notes),
            hermes_tools_used=hermes_tools_used,
            source_references=list(set(source_references))[:20],
            related_goals=goal_names,
            uncertainty_notes=uncertainty_notes,
            investigation_task_ids=investigation_task_ids,
        )

    def _infer_finding_source(self, finding: str) -> str:
        """Infers the Hermes source that produced a finding string."""
        fl = finding.lower()
        if any(k in fl for k in ["gmail", "email", "inbox", "thread", "message"]):
            return "gmail"
        if any(k in fl for k in ["drive", "document", "doc", ".docx", ".pdf", "sheet"]):
            return "drive"
        if any(k in fl for k in ["meet", "transcript", "recording", "meeting"]):
            return "meet"
        if any(k in fl for k in ["calendar", "event", "scheduled", "invite"]):
            return "calendar"
        if any(k in fl for k in ["file", "directory", "local", "filesystem", "path"]):
            return "filesystem"
        return "hermes_investigation"
