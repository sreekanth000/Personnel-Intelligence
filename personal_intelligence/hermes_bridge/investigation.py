"""
Bounded External Investigation Module.
Formulates structured information gap tasks (known_facts, unknowns, question_to_investigate, required_output),
invokes Hermes with bounded tool instructions, validates structured responses (findings, source_references, uncertainty, expiration_time),
and integrates derived evidence with provenance into situations and event logs without storing raw web clutter.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from personal_intelligence.core.events.models import (
    Event,
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.situations.models import Situation
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.hermes_bridge.client import (
    HermesClient,
    HermesInvocationRequest,
)


@dataclass
class InformationGapRequest:
    """
    Generic capability-request specification submitted by Personal Intelligence to Hermes.
    Specifies WHAT INFORMATION IS NEEDED, not HOW TO ACCESS THE SOURCE.
    Hermes host runtime determines which native tools to call to resolve the gap.
    """
    information_gap: str
    preferred_capabilities: List[str] = field(default_factory=lambda: ["drive", "gmail", "meet"])
    max_tool_calls: int = 5
    known_facts: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    required_output: Dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    situation_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_duration_minutes: int = 60

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validates that the capability request is strictly bounded."""
        if not self.information_gap or not isinstance(self.information_gap, str) or not self.information_gap.strip():
            raise ValueError("information_gap must be a non-empty string.")
        if not isinstance(self.preferred_capabilities, list) or not self.preferred_capabilities:
            raise ValueError("preferred_capabilities must be a non-empty list of Hermes capabilities.")
        if not (1 <= self.max_tool_calls <= 10):
            raise ValueError(f"max_tool_calls must be between 1 and 10, got {self.max_tool_calls}.")
        self.created_at = ensure_timezone_aware(self.created_at, "created_at")

    @property
    def question_to_investigate(self) -> str:
        """Compatibility property mapping to information_gap."""
        return self.information_gap

    def to_dict(self) -> Dict[str, Any]:
        """Serializes capability request to dictionary."""
        return {
            "task_id": self.task_id,
            "situation_id": self.situation_id,
            "information_gap": self.information_gap,
            "preferred_capabilities": self.preferred_capabilities,
            "max_tool_calls": self.max_tool_calls,
            "known_facts": self.known_facts,
            "unknowns": self.unknowns,
            "required_output": self.required_output,
            "created_at": format_iso8601(self.created_at),
            "valid_duration_minutes": self.valid_duration_minutes,
        }


class InvestigationTask(InformationGapRequest):
    """
    Explicit specification of an information gap to be investigated by Hermes.
    Prohibits unbounded or broad search queries by defining known context and target schema.
    Maintains full backward compatibility with question_to_investigate keyword argument.
    """
    def __init__(
        self,
        question_to_investigate: Optional[str] = None,
        information_gap: Optional[str] = None,
        known_facts: Optional[List[str]] = None,
        unknowns: Optional[List[str]] = None,
        required_output: Optional[Dict[str, Any]] = None,
        preferred_capabilities: Optional[List[str]] = None,
        max_tool_calls: int = 5,
        task_id: Optional[str] = None,
        situation_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
        valid_duration_minutes: int = 60,
    ) -> None:
        gap = information_gap or question_to_investigate or ""
        super().__init__(
            information_gap=gap,
            preferred_capabilities=preferred_capabilities or ["drive", "gmail", "meet"],
            max_tool_calls=max_tool_calls,
            known_facts=known_facts if known_facts is not None else [],
            unknowns=unknowns if unknowns is not None else [],
            required_output=required_output if required_output is not None else {},
            task_id=task_id or str(uuid.uuid4()),
            situation_id=situation_id,
            created_at=created_at or datetime.now(timezone.utc),
            valid_duration_minutes=valid_duration_minutes,
        )
        self.validate()

    def validate(self) -> None:
        """Enforces non-empty context bounds for InvestigationTask."""
        super().validate()
        if not isinstance(self.known_facts, list) or not self.known_facts:
            raise ValueError("known_facts must be a non-empty list of known factual context.")
        if not isinstance(self.unknowns, list) or not self.unknowns:
            raise ValueError("unknowns must be a non-empty list of specific information gaps.")
        if not isinstance(self.required_output, dict) or not self.required_output:
            raise ValueError("required_output must be a non-empty dictionary defining expected fields.")




@dataclass
class InvestigationResult:
    """
    Validated outcome of a bounded external investigation by Hermes.
    Contains findings, provenance source references, uncertainty, and expiration time.
    """
    task_id: str
    findings: List[str]
    source_references: List[str]
    uncertainty: List[str]
    expiration_time: datetime
    structured_data: Dict[str, Any] = field(default_factory=dict)
    situation_id: Optional[str] = None
    is_valid: bool = True
    raw_response: Optional[str] = None
    validation_errors: List[str] = field(default_factory=list)
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.expiration_time = ensure_timezone_aware(self.expiration_time, "expiration_time")
        self.completed_at = ensure_timezone_aware(self.completed_at, "completed_at")

    def is_expired(self, as_of: Optional[datetime] = None) -> bool:
        """Checks if the external findings have expired."""
        ref = as_of if as_of is not None else datetime.now(timezone.utc)
        ref_tz = ensure_timezone_aware(ref, "as_of")
        return self.expiration_time <= ref_tz

    def to_dict(self) -> Dict[str, Any]:
        """Serializes investigation result to dictionary."""
        return {
            "task_id": self.task_id,
            "situation_id": self.situation_id,
            "findings": self.findings,
            "source_references": self.source_references,
            "uncertainty": self.uncertainty,
            "expiration_time": format_iso8601(self.expiration_time),
            "structured_data": self.structured_data,
            "is_valid": self.is_valid,
            "raw_response": self.raw_response,
            "validation_errors": self.validation_errors,
            "completed_at": format_iso8601(self.completed_at),
        }


def validate_investigation_result(data: Any) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Validates Hermes JSON output against strict InvestigationResult schema.
    Returns (is_valid, validation_errors, parsed_dict).
    """
    errors: List[str] = []
    if not isinstance(data, dict):
        return False, ["Root response must be a JSON object."], {}

    # 1. Validate findings
    if "findings" not in data:
        errors.append("Missing required field 'findings'.")
    elif not isinstance(data["findings"], list) or not data["findings"]:
        errors.append("'findings' must be a non-empty list of strings.")
    elif not all(isinstance(f, str) and f.strip() for f in data["findings"]):
        errors.append("All items in 'findings' must be non-empty strings.")

    # 2. Validate source_references (evidence / source references)
    if "source_references" not in data and "evidence_references" not in data and "sources" not in data:
        errors.append("Missing required field 'source_references'.")
    else:
        srcs = data.get("source_references") or data.get("evidence_references") or data.get("sources")
        if not isinstance(srcs, list) or not srcs:
            errors.append("'source_references' must be a non-empty list of source/URL strings.")
        elif not all(isinstance(s, str) and s.strip() for s in srcs):
            errors.append("All items in 'source_references' must be non-empty strings.")
        data["source_references"] = srcs

    # 3. Validate uncertainty
    if "uncertainty" not in data and "uncertainties" not in data:
        errors.append("Missing required field 'uncertainty'.")
    else:
        unc = data.get("uncertainty") if "uncertainty" in data else data.get("uncertainties")
        if not isinstance(unc, list):
            errors.append("'uncertainty' must be a list of strings.")
        else:
            data["uncertainty"] = unc

    # 4. Validate expiration_time
    exp = data.get("expiration_time") or data.get("expires_at") or data.get("valid_until")
    if not exp:
        errors.append("Missing required field 'expiration_time'.")
    else:
        try:
            if isinstance(exp, (int, float)):
                # Relative timestamp or unix timestamp
                if exp < 100000:  # relative minutes
                    parsed_exp = datetime.now(timezone.utc) + timedelta(minutes=exp)
                else:
                    parsed_exp = datetime.fromtimestamp(exp, tz=timezone.utc)
            elif isinstance(exp, str):
                parsed_exp = ensure_timezone_aware(exp, "expiration_time")
            elif isinstance(exp, datetime):
                parsed_exp = ensure_timezone_aware(exp, "expiration_time")
            else:
                raise ValueError("Invalid expiration format")
            data["expiration_time"] = parsed_exp
        except Exception as e:
            errors.append(f"Invalid 'expiration_time' format: {str(e)}")

    is_valid = (len(errors) == 0)
    return is_valid, errors, data


class BoundedInvestigationWorkflow:
    """
    Executes bounded external research via Hermes.
    Enforces strict prompt bounding, validation retry loops, and clean storage integration.
    """

    def __init__(
        self,
        hermes_client: Optional[HermesClient] = None,
        hermes_bridge: Optional[Any] = None,
        situation_store: Optional[SituationStore] = None,
        event_buffer: Optional[Any] = None,
    ) -> None:
        self.hermes_client = hermes_client or hermes_bridge or HermesClient()
        self.situation_store = situation_store or SituationStore()
        self.event_buffer = event_buffer

    def investigate(self, task: InvestigationTask, max_retries: int = 2) -> InvestigationResult:
        """Executes bounded investigation (alias for execute_investigation)."""
        return self.execute_investigation(task=task, max_retries=max_retries)

    def create_task(
        self,
        question_to_investigate: Optional[str] = None,
        information_gap: Optional[str] = None,
        known_facts: Optional[List[str]] = None,
        unknowns: Optional[List[str]] = None,
        required_output: Optional[Dict[str, Any]] = None,
        preferred_capabilities: Optional[List[str]] = None,
        max_tool_calls: int = 5,
        situation_id: Optional[str] = None,
        valid_duration_minutes: int = 60,
    ) -> InvestigationTask:
        """Constructs and validates a bounded capability-request investigation task."""
        return InvestigationTask(
            question_to_investigate=question_to_investigate,
            information_gap=information_gap,
            known_facts=known_facts,
            unknowns=unknowns,
            required_output=required_output,
            preferred_capabilities=preferred_capabilities or ["drive", "gmail", "meet"],
            max_tool_calls=max_tool_calls,
            situation_id=situation_id,
            valid_duration_minutes=valid_duration_minutes,
        )

    def format_investigation_prompt(self, task: InvestigationTask, retry_errors: Optional[List[str]] = None) -> str:
        """
        Builds the bounded investigation prompt for Hermes.
        Specifies WHAT INFORMATION IS NEEDED, not HOW TO ACCESS THE SOURCE.
        Hermes host runtime determines which tools to call within max_tool_calls bound.
        """
        known_str = "\n".join([f"- {k}" for k in task.known_facts])
        unknowns_str = "\n".join([f"- {u}" for u in task.unknowns])
        caps_str = ", ".join(task.preferred_capabilities) if task.preferred_capabilities else "drive, gmail, meet"
        req_out_str = json.dumps(task.required_output, indent=2)

        retry_section = ""
        if retry_errors:
            err_list = "\n".join([f"- {e}" for e in retry_errors])
            retry_section = f"""
### VALIDATION ERRORS ON PREVIOUS ATTEMPT:
{err_list}
Please correct the schema output to fix the errors above.
"""

        prompt = f"""### Bounded Capability Request [{task.task_id}]

You are executing a bounded capability request on behalf of Personal Intelligence.
Target Situation: {task.situation_id or "Direct Query"}

#### 1. WHAT INFORMATION IS NEEDED (Information Gap):
"{task.information_gap or task.question_to_investigate}"

#### 2. PREFERRED HERMES CAPABILITIES:
[{caps_str}]

#### 3. EXECUTION CONSTRAINTS & BOUNDS:
- Maximum tool calls allowed: {task.max_tool_calls}
- Arbitrary tool execution is prohibited.
- Hermes determines which native tools to call to resolve the gap.
- Personal Intelligence specifies WHAT INFORMATION IS NEEDED, not HOW TO ACCESS THE SOURCE.

#### 4. KNOWN LOCAL FACTS (Do not re-investigate these):
{known_str}

#### 5. SPECIFIC INFORMATION GAPS (Unknowns):
{unknowns_str}

#### 6. REQUIRED OUTPUT SCHEMA:
Expected structured payload fields:

{req_out_str}
{retry_section}
#### CRITICAL INVESTIGATION CONSTRAINTS:
1. Do NOT search broadly or browse unrelated topics.
2. Investigate ONLY the specific bounded question.
3. Return ONLY valid JSON matching the schema below.
4. Do NOT store raw web HTML dumps; extract and cite concise factual findings with source references.
5. Provide a realistic expiration timestamp (ISO 8601 UTC) after which these external findings should not be trusted.


#### EXPECTED JSON FORMAT:
```json
{{
  "findings": [
    "Fact 1 discovered from external source...",
    "Fact 2..."
  ],
  "source_references": [
    "https://api.transit.com/status/line-a",
    "https://weather.gov/report"
  ],
  "structured_data": {req_out_str},
  "uncertainty": [
    "Any remaining unverified details or caveats..."
  ],
  "expiration_time": "2026-08-22T18:30:00Z"
}}
```
"""
        return prompt

    def execute_investigation(
        self,
        task: InvestigationTask,
        max_retries: int = 2,
    ) -> InvestigationResult:
        """
        Runs the bounded investigation through Hermes with strict validation and retry loops.
        """
        last_raw_response = ""
        last_errors: List[str] = []

        for attempt in range(1, max_retries + 2):
            prompt = self.format_investigation_prompt(
                task=task,
                retry_errors=last_errors if attempt > 1 else None,
            )

            response = self.hermes_client.invoke_reasoning(
                request=HermesInvocationRequest(
                    prompt=prompt,
                    skills=["personal_investigation"],
                )
            )
            raw_text = response.raw_response
            last_raw_response = raw_text

            # Parse JSON
            parsed_json = self._extract_json(raw_text)
            if parsed_json is None:
                last_errors = ["Response was not valid JSON or could not be parsed."]
                continue

            # Schema Validation
            is_valid, errors, validated_data = validate_investigation_result(parsed_json)
            if is_valid:
                exp_time = validated_data["expiration_time"]
                structured_data = validated_data.get("structured_data", {})

                return InvestigationResult(
                    task_id=task.task_id,
                    situation_id=task.situation_id,
                    findings=validated_data["findings"],
                    source_references=validated_data["source_references"],
                    uncertainty=validated_data["uncertainty"],
                    expiration_time=exp_time,
                    structured_data=structured_data,
                    is_valid=True,
                    raw_response=raw_text,
                    validation_errors=[],
                )
            else:
                last_errors = errors

        # Permanent failure fallback
        default_exp = datetime.now(timezone.utc) + timedelta(minutes=task.valid_duration_minutes)
        return InvestigationResult(
            task_id=task.task_id,
            situation_id=task.situation_id,
            findings=[],
            source_references=[],
            uncertainty=last_errors or ["Failed to validate external investigation output."],
            expiration_time=default_exp,
            structured_data={},
            is_valid=False,
            raw_response=last_raw_response,
            validation_errors=last_errors,
        )

    def integrate_investigation_into_situation(
        self,
        result: InvestigationResult,
        situation: Situation,
        situation_store: Optional[SituationStore] = None,
        event_buffer: Optional[Any] = None,
    ) -> Situation:
        """
        Integrates derived external evidence and provenance into the situation context
        and emits a derived event without storing arbitrary web clutter or failure strings.
        """
        store = situation_store or self.situation_store
        buf = event_buffer or self.event_buffer
        now = datetime.now(timezone.utc)

        if not result.is_valid or not result.findings:
            updated_context = dict(situation.context or {})
            if "investigation_uncertainties" not in updated_context:
                updated_context["investigation_uncertainties"] = []
            updated_context["investigation_uncertainties"].extend(result.uncertainty)
            if store:
                return store.update(situation_id=situation.id, context=updated_context) or situation
            return situation

        # 1. Update situation evidence with concise findings & provenance
        evidence_tag = f"external_investigation:{result.task_id}"
        updated_evidence = list(situation.evidence)
        if evidence_tag not in updated_evidence:
            updated_evidence.append(evidence_tag)

        for finding in result.findings:
            summary_ev = f"finding:{finding[:100]}"
            if summary_ev not in updated_evidence:
                updated_evidence.append(summary_ev)

        # 2. Update situation context with derived findings, source refs, and TTL (NO raw web dumps)
        updated_context = dict(situation.context)
        investigation_summary = {
            "task_id": result.task_id,
            "findings": result.findings,
            "sources": result.source_references,
            "uncertainty": result.uncertainty,
            "valid_until": format_iso8601(result.expiration_time),
            "structured_data": result.structured_data,
            "ingested_at": format_iso8601(now),
        }
        if "external_investigations" not in updated_context:
            updated_context["external_investigations"] = []
        updated_context["external_investigations"].append(investigation_summary)
        updated_context["latest_external_findings"] = result.findings

        # 3. Emit structured derived event to EventBuffer if present
        if buf is not None:
            derived_event = Event(
                id=f"evt-ext-inv-{result.task_id[:8]}",
                event_type="external_investigation_finding",
                source="hermes_investigation",
                event_time=now,
                payload={
                    "task_id": result.task_id,
                    "situation_id": situation.id,
                    "findings": result.findings,
                    "source_references": result.source_references,
                    "valid_until": format_iso8601(result.expiration_time),
                },
            )
            if hasattr(buf, "push"):
                buf.push(derived_event)
            elif hasattr(buf, "append"):
                buf.append(derived_event)

        # 4. Save to SituationStore
        updated_situation = store.update(
            situation_id=situation.id,
            context=updated_context,
            evidence=updated_evidence,
            last_evaluated_at=now,
        )
        return updated_situation or situation

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Safely parses JSON from text, including markdown code block wrapped JSON."""
        if not text or not isinstance(text, str):
            return None

        # 1. Direct JSON parse
        try:
            return json.loads(text.strip())
        except Exception:
            pass

        # 2. Markdown fenced block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except Exception:
                pass

        # 3. First '{' to last '}'
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1].strip())
            except Exception:
                pass

        return None
