"""
Reasoning episode models for preserving the complete lifecycle of reasoning,
investigation, recommendations, interventions, user responses, and outcomes in a unified model.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, List, Optional, Union
import uuid

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)


class EpisodeStatus(str, Enum):
    """Lifecycle state of a reasoning episode."""
    STARTED = "started"
    HERMES_INVOKED = "hermes_invoked"
    REASONING_COMPLETED = "reasoning_completed"
    INTERVENTION_DELIVERED = "intervention_delivered"
    RESPONSE_RECORDED = "response_recorded"
    OUTCOME_RECORDED = "outcome_recorded"
    UNPARSEABLE_REASONING = "unparseable_reasoning"
    UNPARSEABLE = "unparseable_reasoning"
    FAILED = "failed"


class RecommendationResult(str, Enum):
    """
    Standard categorization for user responses and longitudinal recommendation outcomes.
    """
    ACCEPTED = "ACCEPTED"
    DISMISSED = "DISMISSED"
    IGNORED = "IGNORED"
    DEFERRED = "DEFERRED"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    UNKNOWN = "UNKNOWN"


@dataclass
class UserResponseRecord:
    """
    Structured record of a user's interaction with or response to an intervention.
    """
    response: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    feedback_notes: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.timestamp = ensure_timezone_aware(self.timestamp, "timestamp")
        if isinstance(self.response, RecommendationResult):
            self.response = self.response.value
        elif isinstance(self.response, str):
            self.response = self.response.strip().upper()

    def to_dict(self) -> Dict[str, Any]:
        """Serializes user response record to dictionary."""
        return {
            "response": self.response,
            "action_taken": self.metadata.get("action_taken", self.response.lower()),
            "timestamp": format_iso8601(self.timestamp),
            "feedback_notes": self.feedback_notes,
            "feedback": self.feedback_notes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserResponseRecord":
        """Deserializes dictionary to UserResponseRecord."""
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict for UserResponseRecord, got {type(data).__name__}")

        resp_raw = data.get("response") or data.get("action_taken") or RecommendationResult.UNKNOWN.value
        ts_raw = data.get("timestamp") or data.get("responded_at") or datetime.now(timezone.utc)
        return cls(
            response=str(resp_raw),
            timestamp=ensure_timezone_aware(ts_raw, "timestamp"),
            feedback_notes=data.get("feedback_notes") or data.get("feedback"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class OutcomeRecord:
    """
    Structured record of a longitudinal recommendation outcome evaluation.
    """
    outcome_status: str
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    evaluation_notes: Optional[str] = None
    success: Optional[bool] = None
    impact_metrics: Dict[str, Any] = field(default_factory=dict)
    evidence_event_ids: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.observed_at = ensure_timezone_aware(self.observed_at, "observed_at")
        if isinstance(self.outcome_status, RecommendationResult):
            self.outcome_status = self.outcome_status.value
        elif isinstance(self.outcome_status, str):
            self.outcome_status = self.outcome_status.strip().upper()

    def to_dict(self) -> Dict[str, Any]:
        """Serializes outcome record to dictionary."""
        d = {
            "outcome_status": self.outcome_status,
            "status": self.outcome_status.lower(),
            "observed_at": format_iso8601(self.observed_at),
            "evaluation_notes": self.evaluation_notes,
            "evaluation": self.evaluation_notes,
            "success": self.success,
            "impact_metrics": self.impact_metrics,
            "evidence_event_ids": self.evidence_event_ids,
        }
        if isinstance(self.impact_metrics, dict):
            for k, v in self.impact_metrics.items():
                if k not in d:
                    d[k] = v
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutcomeRecord":
        """Deserializes dictionary to OutcomeRecord."""
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict for OutcomeRecord, got {type(data).__name__}")

        status_raw = data.get("outcome_status") or data.get("status") or (
            RecommendationResult.COMPLETED.value if data.get("success") is True else RecommendationResult.UNKNOWN.value
        )
        obs_raw = data.get("observed_at") or data.get("evaluated_at") or datetime.now(timezone.utc)
        return cls(
            outcome_status=str(status_raw),
            observed_at=ensure_timezone_aware(obs_raw, "observed_at"),
            evaluation_notes=data.get("evaluation_notes") or data.get("evaluation"),
            success=data.get("success"),
            impact_metrics=data.get("impact_metrics", {}),
            evidence_event_ids=data.get("evidence_event_ids", []),
        )


@dataclass
class HermesExecutionRecord:
    """Audit record of a specific Hermes execution / tool use session."""
    session_id: str
    prompt: str
    response: str
    tools_used: List[str] = field(default_factory=list)
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class ReasoningEpisode:
    """
    Unified representation preserving the canonical epistemic and action lifecycle:
    OBSERVATION -> INFERENCE -> PREDICTION -> RECOMMENDATION -> USER DECISION -> ACTION

    - OBSERVATION: Direct empirical evidence corroborated by event payloads or state sources.
    - INFERENCE: Logical deductions drawn from observations and active goals.
    - PREDICTION: Forward trajectory forecasts of future state or risk.
    - RECOMMENDATION: Non-intrusive suggested courses of action for the user.
    - USER DECISION: Explicit user interaction (ACCEPTED, DISMISSED, IGNORED, DEFERRED, etc.).
    - ACTION: External execution (V1 has NO autonomous external actions; requires user authorization).
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    situation_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    observations: List[str] = field(default_factory=list)
    inferences: List[str] = field(default_factory=list)
    predictions: List[str] = field(default_factory=list)
    hermes_task: Optional[str] = None
    hermes_result: Optional[Dict[str, Any]] = None
    recommendation: Optional[Any] = None
    urgency: Optional[str] = None
    actionability: Optional[str] = None
    relevance: Optional[str] = None
    evidence_strength: Optional[str] = None
    intervention_decision: Optional[Dict[str, Any]] = None
    user_response: Optional[Dict[str, Any]] = None
    outcome: Optional[Dict[str, Any]] = None
    follow_up_at: Optional[datetime] = None
    status: str = EpisodeStatus.STARTED.value
    # Hermes Invocation Telemetry (Prompt 3)
    reason_for_invocation: Optional[str] = None
    reasoning_budget: Optional[str] = None
    context_size: Optional[int] = None
    investigation_rounds: int = 0
    tool_calls: int = 0
    execution_time_ms: Optional[int] = None
    reason_code: Optional[str] = None
    # Optional backwards compatibility attributes
    episode_id_alias: Optional[str] = None
    trigger_type_alias: Optional[str] = None
    started_at_alias: Optional[datetime] = None

    def __init__(
        self,
        id: Optional[str] = None,
        situation_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
        context_snapshot: Optional[Dict[str, Any]] = None,
        observations: Optional[List[str]] = None,
        inferences: Optional[List[str]] = None,
        predictions: Optional[List[str]] = None,
        hermes_task: Optional[str] = None,
        hermes_result: Optional[Dict[str, Any]] = None,
        recommendation: Optional[Any] = None,
        urgency: Optional[str] = None,
        actionability: Optional[str] = None,
        relevance: Optional[str] = None,
        evidence_strength: Optional[str] = None,
        intervention_decision: Optional[Dict[str, Any]] = None,
        user_response: Optional[Dict[str, Any]] = None,
        outcome: Optional[Dict[str, Any]] = None,
        follow_up_at: Optional[datetime] = None,
        status: str = EpisodeStatus.STARTED.value,
        # Invocation Telemetry (Prompt 3)
        reason_for_invocation: Optional[str] = None,
        reasoning_budget: Optional[str] = None,
        context_size: Optional[int] = None,
        investigation_rounds: int = 0,
        tool_calls: int = 0,
        execution_time_ms: Optional[int] = None,
        reason_code: Optional[str] = None,
        # Backwards compatibility kwargs:
        episode_id: Optional[str] = None,
        trigger_type: Optional[str] = None,
        started_at: Optional[datetime] = None,
        investigation_record: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self.id = str(id or episode_id or uuid.uuid4())
        self.situation_id = situation_id
        dt_val = created_at or started_at or datetime.now(timezone.utc)
        self.created_at = ensure_timezone_aware(dt_val, "created_at")
        self.context_snapshot = context_snapshot or {}
        self.observations = observations or []
        self.inferences = inferences or []
        self.predictions = predictions or []
        self.hermes_task = hermes_task or trigger_type
        self.hermes_result = hermes_result or (investigation_record.__dict__ if investigation_record else None)
        self.recommendation = recommendation

        self._custom_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        self.urgency = urgency or self._custom_metadata.get("urgency")
        self.actionability = actionability or self._custom_metadata.get("actionability")
        self.relevance = relevance or self._custom_metadata.get("relevance")
        self.evidence_strength = evidence_strength or self._custom_metadata.get("evidence_strength")
        self.intervention_decision = intervention_decision
        self.user_response = user_response
        self.outcome = outcome
        self.follow_up_at = ensure_timezone_aware(follow_up_at, "follow_up_at") if follow_up_at else None
        
        stat_val = status.value if hasattr(status, "value") else str(status)
        self.status = stat_val.strip().lower()

        # Telemetry
        self.reason_for_invocation = reason_for_invocation or self._custom_metadata.get("reason_for_invocation")
        self.reasoning_budget = reasoning_budget or self._custom_metadata.get("reasoning_budget")
        self.context_size = context_size or self._custom_metadata.get("context_size")
        self.investigation_rounds = investigation_rounds or self._custom_metadata.get("investigation_rounds", 0)
        self.tool_calls = tool_calls or self._custom_metadata.get("tool_calls", 0)
        self.execution_time_ms = execution_time_ms or self._custom_metadata.get("execution_time_ms")
        self.reason_code = reason_code or self._custom_metadata.get("reason_code")


    @property
    def episode_id(self) -> str:
        """Central learning & audit record identifier."""
        return self.id

    @property
    def timestamp(self) -> datetime:
        """Timestamp when reasoning episode occurred."""
        return self.created_at

    @property
    def observations_used(self) -> List[str]:
        """Direct observations used during reasoning cycle."""
        return self.observations

    @property
    def evidence(self) -> List[str]:
        """Evidence citations linked to this reasoning episode."""
        ev = self.context_snapshot.get("evidence") or self._custom_metadata.get("evidence")
        if isinstance(ev, list):
            return [str(e) for e in ev]
        elif isinstance(ev, str):
            return [ev]
        return list(self.observations)

    @property
    def recommendations(self) -> List[str]:
        """Structured recommendations produced by reasoning cycle."""
        if isinstance(self.recommendation, list):
            return [str(r) for r in self.recommendation]
        elif isinstance(self.recommendation, dict):
            rec_text = self.recommendation.get("action") or self.recommendation.get("recommendation") or self.recommendation.get("text")
            return [str(rec_text)] if rec_text else [str(self.recommendation)]
        elif self.recommendation:
            return [str(self.recommendation)]
        return []

    @property
    def provenance(self) -> List[Dict[str, Any]]:
        """Extracts source provenance records for audit and empirical learning."""
        # 0. Check explicit provenance in context snapshot or metadata
        if isinstance(self.context_snapshot, dict) and "provenance" in self.context_snapshot:
            explicit_prov = self.context_snapshot["provenance"]
            if isinstance(explicit_prov, list):
                return explicit_prov
        if hasattr(self, "_custom_metadata") and isinstance(self._custom_metadata, dict):
            if "provenance" in self._custom_metadata and isinstance(self._custom_metadata["provenance"], list):
                return self._custom_metadata["provenance"]

        prov_list: List[Dict[str, Any]] = []
        if isinstance(self.context_snapshot, dict):
            # 1. Observed facts provenance
            for f in self.context_snapshot.get("observed_facts", []):
                if isinstance(f, dict) and ("provenance" in f or "source" in f):
                    prov_list.append({
                        "source": f.get("provenance") or f.get("source"),
                        "timestamp": f.get("timestamp"),
                        "confidence": f.get("confidence", "high"),
                    })
            # 2. Timeline events provenance
            for ev in self.context_snapshot.get("timeline_events", []):
                if isinstance(ev, dict) and "id" in ev:
                    prov_list.append({
                        "source": f"event:{ev['id']}",
                        "timestamp": ev.get("timestamp") or ev.get("event_time"),
                        "event_type": ev.get("event_type"),
                    })
        # If empty, derive from observations
        if not prov_list and self.observations:
            for obs in self.observations:
                prov_list.append({"source": "observation", "statement": str(obs)})
        return prov_list

    @property
    def runtime_metadata(self) -> Dict[str, Any]:
        """Model and runtime execution audit metadata."""
        meta: Dict[str, Any] = {
            "hermes_task": self.hermes_task,
            "status": self.status,
            "parse_status": self.parse_status,
        }
        if isinstance(self.hermes_result, dict):
            for k in ["session_id", "duration_ms", "tools_used", "attempts", "model"]:
                if k in self.hermes_result:
                    meta[k] = self.hermes_result[k]
        if hasattr(self, "_custom_metadata") and isinstance(self._custom_metadata, dict):
            for k, v in self._custom_metadata.items():
                if k not in meta:
                    meta[k] = v
        return meta

    @property
    def model_metadata(self) -> Dict[str, Any]:
        """Alias for runtime_metadata."""
        return self.runtime_metadata

    @property
    def parse_status(self) -> str:
        """Parse and schema validation status of reasoning output."""
        if self.status in (EpisodeStatus.UNPARSEABLE.value, EpisodeStatus.UNPARSEABLE_REASONING.value, "unparseable_reasoning", "unparseable"):
            return "unparseable_reasoning"
        if self.status == EpisodeStatus.FAILED.value:
            return "failed"
        return "valid"

    @property
    def trigger_type(self) -> str:
        """Backwards compatible alias for hermes_task or trigger_type."""
        return self.hermes_task or "situation_reasoning"

    @property
    def started_at(self) -> datetime:
        """Backwards compatible alias for created_at."""
        return self.created_at

    @property
    def outcome_success(self) -> bool:
        """Backwards compatible check for outcome success."""
        if isinstance(self.outcome, dict) and "success" in self.outcome:
            return bool(self.outcome["success"])
        return self.status not in (EpisodeStatus.FAILED.value, EpisodeStatus.UNPARSEABLE.value, "unparseable", "failed")

    @property
    def metadata(self) -> Dict[str, Any]:
        """Backwards compatible metadata view."""
        raw_resp = ""
        val_errors = []
        if isinstance(self.hermes_result, dict):
            raw_resp = self.hermes_result.get("response", "")
            if self.hermes_result.get("error_message"):
                val_errors = [self.hermes_result["error_message"]]
        elif isinstance(self.hermes_result, str):
            raw_resp = self.hermes_result

        if isinstance(self.outcome, dict) and "validation_errors" in self.outcome:
            val_errors = self.outcome["validation_errors"]

        res = {
            "task": self.hermes_task,
            "situation_id": self.situation_id,
            "raw_response": raw_resp,
            "validation_errors": val_errors,
            "urgency": self.urgency,
            "actionability": self.actionability,
            "relevance": self.relevance,
            "evidence_strength": self.evidence_strength,
            "parse_status": self.parse_status,
        }
        if hasattr(self, "_custom_metadata") and isinstance(self._custom_metadata, dict):
            res.update(self._custom_metadata)
        return res

    @metadata.setter
    def metadata(self, val: Dict[str, Any]) -> None:
        self._custom_metadata = dict(val) if isinstance(val, dict) else {}

    def get_user_response_record(self) -> Optional[UserResponseRecord]:
        """Returns structured UserResponseRecord if user response is present."""
        if not self.user_response:
            return None
        return UserResponseRecord.from_dict(self.user_response)

    def get_outcome_record(self) -> Optional[OutcomeRecord]:
        """Returns structured OutcomeRecord if outcome is present."""
        if not self.outcome:
            return None
        return OutcomeRecord.from_dict(self.outcome)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes episode into a dictionary."""
        return {
            "id": self.id,
            "episode_id": self.id,
            "situation_id": self.situation_id,
            "created_at": format_iso8601(self.created_at),
            "timestamp": format_iso8601(self.created_at),
            "context_snapshot": self.context_snapshot,
            "observations": self.observations,
            "observations_used": self.observations,
            "evidence": self.evidence,
            "inferences": self.inferences,
            "predictions": self.predictions,
            "hermes_task": self.hermes_task,
            "hermes_result": self.hermes_result,
            "recommendation": self.recommendation,
            "recommendations": self.recommendations,
            "urgency": self.urgency,
            "actionability": self.actionability,
            "relevance": self.relevance,
            "evidence_strength": self.evidence_strength,
            "intervention_decision": self.intervention_decision,
            "user_response": self.user_response,
            "outcome": self.outcome,
            "provenance": self.provenance,
            "runtime_metadata": self.runtime_metadata,
            "parse_status": self.parse_status,
            "follow_up_at": format_iso8601(self.follow_up_at) if self.follow_up_at else None,
            "status": self.status,
            # Telemetry
            "reason_for_invocation": self.reason_for_invocation,
            "reasoning_budget": self.reasoning_budget,
            "context_size": self.context_size,
            "investigation_rounds": self.investigation_rounds,
            "tool_calls": self.tool_calls,
            "execution_time_ms": self.execution_time_ms,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReasoningEpisode":
        """Constructs a ReasoningEpisode from a dictionary."""
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict for ReasoningEpisode, got {type(data).__name__}")

        ep_id = data.get("id") or data.get("episode_id") or str(uuid.uuid4())
        created_at_raw = data.get("created_at") or data.get("started_at") or datetime.now(timezone.utc)
        follow_up_raw = data.get("follow_up_at")

        return cls(
            id=str(ep_id),
            situation_id=data.get("situation_id"),
            created_at=ensure_timezone_aware(created_at_raw, "created_at"),
            context_snapshot=data.get("context_snapshot", {}),
            observations=data.get("observations", []),
            inferences=data.get("inferences", []),
            predictions=data.get("predictions", []),
            hermes_task=data.get("hermes_task") or data.get("trigger_type"),
            hermes_result=data.get("hermes_result"),
            recommendation=data.get("recommendation"),
            urgency=data.get("urgency"),
            actionability=data.get("actionability"),
            relevance=data.get("relevance"),
            evidence_strength=data.get("evidence_strength"),
            intervention_decision=data.get("intervention_decision"),
            user_response=data.get("user_response"),
            outcome=data.get("outcome"),
            follow_up_at=ensure_timezone_aware(follow_up_raw, "follow_up_at") if follow_up_raw else None,
            status=str(data.get("status", EpisodeStatus.STARTED.value)),
            reason_for_invocation=data.get("reason_for_invocation"),
            reasoning_budget=data.get("reasoning_budget"),
            context_size=data.get("context_size"),
            investigation_rounds=data.get("investigation_rounds", 0),
            tool_calls=data.get("tool_calls", 0),
            execution_time_ms=data.get("execution_time_ms"),
            reason_code=data.get("reason_code"),
        )
