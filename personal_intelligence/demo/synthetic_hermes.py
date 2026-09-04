"""
Synthetic Hermes Runtime for Demo and Testing.

Provides a faithful simulation of the Hermes Agent runtime boundary.
Accepts strictly bounded reasoning contexts and returns structured outputs
matching ReasoningWorkflow and NovelReasoningWorkflow schemas.

Modes Supported:
1. DETERMINISTIC: Stable, reproducible responses for regression tests.
2. REALISTIC_SEMANTIC: Rich, context-aware LLM-like interpretations for demo mode.
3. MALFORMED_JSON: Broken JSON output to test validation and retry loops.
4. INCOMPLETE_INVESTIGATION: Returns requires_follow_up=True and explicit information gaps.
5. CONTRADICTORY_EVIDENCE: Detects and highlights conflicting evidence signals.

Architectural Invariant:
- Personal Intelligence retains sole authority for evidence calculation, provenance,
  world model state, situation lifecycle, intervention policy, and SQLite persistence.
- Hermes remains responsible for semantic interpretation and recommendation synthesis.
- Reasoning is NOT moved into SituationEngine.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Set, Union

from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesInvocationRequest,
    HermesInvocationResponse,
)

logger = logging.getLogger(__name__)


class SyntheticHermesMode(str, Enum):
    """Operational mode for the Synthetic Hermes Runtime."""
    DETERMINISTIC = "deterministic"
    REALISTIC_SEMANTIC = "realistic_semantic"
    MALFORMED_JSON = "malformed_json"
    INCOMPLETE_INVESTIGATION = "incomplete_investigation"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"


class SyntheticHermesRuntime:
    """
    Synthetic implementation of the Hermes Agent runtime boundary.
    Can be used directly as a reasoning engine or bound to HermesRuntimeBridge as an active context.
    """

    def __init__(
        self,
        mode: Union[SyntheticHermesMode, str] = SyntheticHermesMode.DETERMINISTIC,
        seed: int = 42,
        fail_attempts: int = 0,
    ) -> None:
        if isinstance(mode, str):
            self.mode = SyntheticHermesMode(mode.lower())
        else:
            self.mode = mode

        self.seed = seed
        self.fail_attempts = fail_attempts
        self._call_count = 0
        self.invocations_history: List[Dict[str, Any]] = []

        # Capability and tool inspection attributes for HermesRuntimeBridge compatibility
        self.available_tools: Set[str] = {
            "search", "fetch", "query", "reasoning", "personal_investigation", "gmail_search", "calendar_query"
        }
        self.auth_status: Dict[str, str] = {
            "search": "authenticated",
            "fetch": "authenticated",
            "query": "authenticated",
            "reasoning": "authenticated",
            "personal": "authenticated",
            "gmail": "authenticated",
            "calendar": "authenticated",
            "filesystem": "not_required",
            "web": "not_required",
        }

    # -------------------------------------------------------------------------
    # Hermes Host Context Protocol (for bridge.bind_context(runtime))
    # -------------------------------------------------------------------------
    def prompt_llm(self, prompt: str) -> str:
        """Host Hermes context interface: prompt the LLM."""
        return self._generate_response_string(prompt)

    def call_agent(self, prompt: str) -> str:
        """Host Hermes context interface: call agent with prompt."""
        return self._generate_response_string(prompt)

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Host Hermes context interface: execute tool handler."""
        return {
            "status": "success",
            "tool": tool_name,
            "args": args,
            "synthetic_result": f"Executed {tool_name} successfully.",
        }

    def has_tool(self, tool_name: str) -> bool:
        """Host Hermes context interface: check tool availability."""
        return tool_name in self.available_tools

    def is_capability_authenticated(self, cap_key: str) -> bool:
        """Host Hermes context interface: probe capability authentication."""
        status = self.auth_status.get(cap_key)
        return status in ("authenticated", "not_required")

    # -------------------------------------------------------------------------
    # Direct Client Interface (for workflow.hermes_client.invoke_reasoning)
    # -------------------------------------------------------------------------
    def invoke_reasoning(self, request: HermesInvocationRequest) -> HermesInvocationResponse:
        """Direct Hermes invocation interface matching HermesClient."""
        start_time = datetime.now(timezone.utc)
        self._call_count += 1

        raw_text = self._generate_response_string(request.prompt)

        duration = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        self.invocations_history.append({
            "call_index": self._call_count,
            "prompt_length": len(request.prompt),
            "session_id": request.session_id,
            "response_length": len(raw_text),
            "mode": self.mode.value,
        })

        return HermesInvocationResponse(
            raw_response=raw_text,
            session_id=request.session_id,
            tools_executed=["synthetic_reasoner"],
            duration_ms=duration,
            success=True,
            is_demo=(self.mode == SyntheticHermesMode.REALISTIC_SEMANTIC),
            safe_diagnostics={"mode": self.mode.value, "call_index": self._call_count},
        )

    # -------------------------------------------------------------------------
    # Internal Prompt Dispatcher & Schema Generators
    # -------------------------------------------------------------------------
    def _is_novel_prompt(self, prompt: str) -> bool:
        """Detects whether the prompt requests the novel situation schema."""
        return "Novel Situation Investigation" in prompt or "what_appears_unusual" in prompt

    def _generate_response_string(self, prompt: str) -> str:
        """Generates schema-compliant string output based on mode and prompt type."""
        is_novel = self._is_novel_prompt(prompt)

        # Check if fail_attempts is configured and currently applicable
        if self.mode == SyntheticHermesMode.MALFORMED_JSON:
            if self.fail_attempts <= 0 or self._call_count <= self.fail_attempts:
                return self._gen_malformed_json()

        if self.mode == SyntheticHermesMode.INCOMPLETE_INVESTIGATION:
            return self._gen_incomplete_investigation(prompt, is_novel)

        if self.mode == SyntheticHermesMode.CONTRADICTORY_EVIDENCE:
            return self._gen_contradictory_evidence(prompt, is_novel)

        if self.mode == SyntheticHermesMode.REALISTIC_SEMANTIC:
            return self._gen_realistic_semantic(prompt, is_novel)

        # Default: DETERMINISTIC
        return self._gen_deterministic(prompt, is_novel)

    def _extract_keywords_and_facts(self, prompt: str) -> Dict[str, Any]:
        """Extracts bounded facts, goals, and situation summaries from the prompt."""
        sit_match = re.search(r"Situation:\s*([^\n\r]+)", prompt, re.IGNORECASE)
        situation_text = sit_match.group(1).strip() if sit_match else "Unspecified situation"

        goals = re.findall(r"Goal:\s*([^\n\r]+)", prompt)
        facts = re.findall(r"-\s*Fact:\s*([^\n\r]+)", prompt) or re.findall(r"-\s*([^\n\r]+)", prompt)
        
        return {
            "situation": situation_text,
            "goals": goals or ["General productivity"],
            "facts": facts[:5] if facts else ["Standard activity recorded."],
        }

    # 1. Deterministic Mode Generator
    def _gen_deterministic(self, prompt: str, is_novel: bool) -> str:
        ctx = self._extract_keywords_and_facts(prompt)
        prompt_hash = hashlib.sha256(f"{self.seed}-{prompt[:200]}".encode("utf-8")).hexdigest()[:8]

        if is_novel:
            data = {
                "what_appears_unusual": f"Divergence detected in {ctx['situation']} (ref: {prompt_hash}).",
                "possible_interpretations": [
                    f"Behavioral shift affecting goals: {', '.join(ctx['goals'])}",
                    "Transient external variance requiring monitoring."
                ],
                "relevant_goals": ctx["goals"],
                "possible_risks": ["Potential schedule slippage or goal delay if divergence continues."],
                "possible_opportunities": ["Opportunity to adapt routine and improve pacing."],
                "what_is_uncertain": ["Longitudinal persistence beyond immediate window."],
                "additional_observation_needed": False,
                "recommendations": [f"Monitor next activity window for {ctx['situation']}."],
                "urgency": "medium",
                "actionability": "medium",
                "relevance": "high",
                "evidence_strength": "moderate",
            }
        else:
            data = {
                "what_is_happening": f"Observed situation: {ctx['situation']} (ref: {prompt_hash}).",
                "observations_used": ctx["facts"][:3],
                "evidence_references": ["obs_ref_01", "obs_ref_02"],
                "evidence_summary": ctx["facts"][:3],
                "inferences": [f"Current dynamics influence {ctx['goals'][0] if ctx['goals'] else 'goals'}."],
                "predictions": ["State will stabilize if active commitments are maintained."],
                "uncertainties": ["Exact timeline of downstream dependencies."],
                "what_would_change_assessment": ["Receipt of conflicting telemetry or cancelation."],
                "recommendations": ["Review current status and maintain planned commitment."],
                "requires_follow_up": False,
                "urgency": "medium",
                "actionability": "medium",
                "relevance": "high",
                "evidence_strength": "moderate",
            }

        return f"```json\n{json.dumps(data, indent=2)}\n```"

    # 2. Realistic Semantic Mode Generator
    def _gen_realistic_semantic(self, prompt: str, is_novel: bool) -> str:
        ctx = self._extract_keywords_and_facts(prompt)
        sit = ctx["situation"]

        if is_novel:
            data = {
                "what_appears_unusual": f"Statistically significant divergence in {sit}: activity pattern departs from personal baseline.",
                "possible_interpretations": [
                    "User is engaged in intensive ad-hoc task requiring acute focus.",
                    "External disruption or unexpected environmental factor shifted user routine.",
                ],
                "relevant_goals": ctx["goals"],
                "possible_risks": [
                    "Accumulated cognitive fatigue and downstream schedule conflict.",
                    "Unintended deadline pressure on adjacent high-priority deliverables.",
                ],
                "possible_opportunities": [
                    "Rapid completion of high-value milestone through focused deep work.",
                ],
                "what_is_uncertain": [
                    "Whether user intentionally adjusted schedule without calendar sync.",
                    "Impact on subsequent rest and recovery intervals.",
                ],
                "additional_observation_needed": False,
                "recommendations": [
                    "Check upcoming calendar commitments for today's afternoon block.",
                    "Suggest a brief 10-minute restorative break before the next meeting.",
                ],
                "urgency": "medium",
                "actionability": "high",
                "relevance": "high",
                "evidence_strength": "moderate",
            }
        else:
            data = {
                "what_is_happening": f"Analysis confirms active situational dynamics regarding {sit}.",
                "observations_used": ctx["facts"][:4],
                "evidence_references": ["source_event_primary", "source_event_telemetry"],
                "evidence_summary": ctx["facts"][:4],
                "inferences": [
                    "Current pace indicates milestone completion is achievable with minor adjustments.",
                    "Interlocking commitments require proactive attention to prevent deadline risk.",
                ],
                "predictions": [
                    "If unadjusted, current trajectory will compress the buffer before the next deliverable.",
                    "Target goal will be satisfied once pending action items are concluded.",
                ],
                "uncertainties": [
                    "Response status of external collaborators.",
                    "Potential transport or network delays in transit.",
                ],
                "what_would_change_assessment": [
                    "Confirmation of meeting reschedule by counterpart.",
                    "Direct user acknowledgement of goal completion.",
                ],
                "recommendations": [
                    f"Prioritize key deliverable for {ctx['goals'][0] if ctx['goals'] else 'main goal'}.",
                    "Defer discretionary secondary tasks until primary commitment is complete.",
                ],
                "requires_follow_up": False,
                "urgency": "high" if "deadline" in sit.lower() or "risk" in sit.lower() else "medium",
                "actionability": "high",
                "relevance": "high",
                "evidence_strength": "strong",
            }

        return f"```json\n{json.dumps(data, indent=2)}\n```"

    # 3. Malformed JSON Mode Generator
    def _gen_malformed_json(self) -> str:
        """Returns syntactically broken JSON to test schema validation and retry loops."""
        return '```json\n{\n  "what_is_happening": "Incomplete synthesis due to network truncation,\n  "observations_used": ["fact_01",\n```'

    # 4. Incomplete Investigation Mode Generator
    def _gen_incomplete_investigation(self, prompt: str, is_novel: bool) -> str:
        ctx = self._extract_keywords_and_facts(prompt)

        if is_novel:
            data = {
                "what_appears_unusual": "insufficient evidence",
                "possible_interpretations": ["Available observation window is too short to distinguish anomaly from noise."],
                "relevant_goals": ctx["goals"],
                "possible_risks": ["Potential unmonitored goal risk."],
                "possible_opportunities": [],
                "what_is_uncertain": [
                    "Missing secondary biometric signals.",
                    "Absence of recent calendar schedule context.",
                ],
                "additional_observation_needed": True,
                "recommendations": ["Await subsequent observation batch before issuing recommendations."],
                "urgency": "low",
                "actionability": "low",
                "relevance": "medium",
                "evidence_strength": "weak",
            }
        else:
            data = {
                "what_is_happening": "Preliminary observation noted; evidence is currently incomplete for definitive synthesis.",
                "observations_used": ctx["facts"][:1],
                "evidence_references": ["partial_obs_01"],
                "evidence_summary": ctx["facts"][:1],
                "inferences": ["Signals suggest emerging activity but lack corroborating cross-domain sources."],
                "predictions": ["Trajectory cannot be reliably projected with partial telemetry."],
                "uncertainties": [
                    "External confirmation from relevant parties.",
                    "Timestamps of planned intermediate milestones.",
                ],
                "what_would_change_assessment": [
                    "Receipt of updated calendar or communication records.",
                ],
                "recommendations": [
                    "Query source capabilities for updated status.",
                ],
                "requires_follow_up": True,
                "urgency": "low",
                "actionability": "low",
                "relevance": "medium",
                "evidence_strength": "insufficient_evidence",
            }

        return f"```json\n{json.dumps(data, indent=2)}\n```"

    # 5. Contradictory Evidence Mode Generator
    def _gen_contradictory_evidence(self, prompt: str, is_novel: bool) -> str:
        ctx = self._extract_keywords_and_facts(prompt)

        if is_novel:
            data = {
                "what_appears_unusual": "Contradictory state signals: sensor and calendar telemetry conflict directly.",
                "possible_interpretations": [
                    "Calendar event was not updated to reflect physical location change.",
                    "Telemetry device was left behind while user attended scheduled session.",
                ],
                "relevant_goals": ctx["goals"],
                "possible_risks": ["Intervention based on incorrect state assumption would disturb user."],
                "possible_opportunities": [],
                "what_is_uncertain": [
                    "True physical location vs scheduled calendar location.",
                    "Which conflicting data source accurately reflects current ground truth.",
                ],
                "additional_observation_needed": True,
                "recommendations": [
                    "Hold intrusive notifications until contradictory evidence is reconciled.",
                ],
                "urgency": "high",
                "actionability": "low",
                "relevance": "high",
                "evidence_strength": "conflicted",
            }
        else:
            data = {
                "what_is_happening": "Conflicting evidence detected across independent observation channels.",
                "observations_used": ctx["facts"][:3],
                "evidence_references": ["obs_conflict_a", "obs_conflict_b"],
                "evidence_summary": ctx["facts"][:3],
                "inferences": [
                    "Direct contradiction and conflicting signals detected between observation sources.",
                    "High probability that one source represents stale or un-synchronized state.",
                ],

                "predictions": [
                    "Autonomous intervention would carry high risk of false-positive distraction.",
                ],
                "uncertainties": [
                    "Ground truth status of scheduled vs physical activity.",
                    "Latency of the slower reporting channel.",
                ],
                "what_would_change_assessment": [
                    "Consistent corroborated signal from a third independent source.",
                ],
                "recommendations": [
                    "Suppress active intervention and request user clarification if critical.",
                ],
                "requires_follow_up": True,
                "urgency": "high",
                "actionability": "medium",
                "relevance": "high",
                "evidence_strength": "conflicted",
            }

        return f"```json\n{json.dumps(data, indent=2)}\n```"
