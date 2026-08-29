"""
Unified SQLite-backed store for ReasoningEpisodes.
Persists the complete reasoning lifecycle (Situation -> Reasoning -> Recommendation ->
Intervention -> User response -> Outcome) in ONE single table.
"""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional, Union
import uuid

from personal_intelligence.core.episodes.models import (
    EpisodeStatus,
    OutcomeRecord,
    ReasoningEpisode,
    RecommendationResult,
    UserResponseRecord,
)
from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.storage.db import DatabaseManager


class EpisodeStore:
    """
    Unified store for managing reasoning episodes across the full reasoning lifecycle.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return self.db_manager.get_connection()

    def _row_to_episode(self, row: sqlite3.Row) -> ReasoningEpisode:
        """Converts an SQLite row to a ReasoningEpisode object."""
        def safe_json_load(val: Optional[str], default: Any) -> Any:
            if not val:
                return default
            try:
                return json.loads(val)
            except Exception:
                return default

        created_at_dt = ensure_timezone_aware(row["created_at"], "created_at")
        follow_up_raw = row["follow_up_at"]
        follow_up_dt = ensure_timezone_aware(follow_up_raw, "follow_up_at") if follow_up_raw else None
        ctx = safe_json_load(row["context_snapshot_json"], {})
        telemetry = ctx.get("_telemetry", {}) if isinstance(ctx, dict) else {}

        return ReasoningEpisode(
            id=row["id"],
            situation_id=row["situation_id"],
            created_at=created_at_dt,
            context_snapshot=ctx,
            observations=safe_json_load(row["observations_json"], []),
            inferences=safe_json_load(row["inferences_json"], []),
            predictions=safe_json_load(row["predictions_json"], []),
            hermes_task=row["hermes_task"],
            hermes_result=safe_json_load(row["hermes_result_json"], None),
            recommendation=safe_json_load(row["recommendation_json"], None),
            urgency=row["urgency"],
            actionability=row["actionability"],
            relevance=row["relevance"],
            evidence_strength=row["evidence_strength"],
            intervention_decision=safe_json_load(row["intervention_decision_json"], None),
            user_response=safe_json_load(row["user_response_json"], None),
            outcome=safe_json_load(row["outcome_json"], None),
            follow_up_at=follow_up_dt,
            status=row["status"],
            reason_for_invocation=telemetry.get("reason_for_invocation"),
            reasoning_budget=telemetry.get("reasoning_budget"),
            context_size=telemetry.get("context_size"),
            investigation_rounds=telemetry.get("investigation_rounds", 0),
            tool_calls=telemetry.get("tool_calls", 0),
            execution_time_ms=telemetry.get("execution_time_ms"),
            reason_code=telemetry.get("reason_code"),
        )

    def create_episode(
        self,
        situation_id: Optional[Union[ReasoningEpisode, str]] = None,
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
        episode_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
        # Central audit and learning record aliases:
        observations_used: Optional[List[str]] = None,
        evidence: Optional[Union[List[str], str]] = None,
        recommendations: Optional[Any] = None,
        timestamp: Optional[datetime] = None,
        provenance: Optional[List[Dict[str, Any]]] = None,
        runtime_metadata: Optional[Dict[str, Any]] = None,
        model_metadata: Optional[Dict[str, Any]] = None,
        parse_status: Optional[str] = None,
        # Backwards compatibility kwargs:
        trigger_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ReasoningEpisode:
        """
        Creates and persists a new reasoning episode record as the central learning/audit record.
        """
        if isinstance(situation_id, ReasoningEpisode):
            ep = situation_id
        else:
            now = ensure_timezone_aware(timestamp or created_at or datetime.now(timezone.utc), "created_at")
            ep_id = episode_id or str(uuid.uuid4())

            # If metadata is passed (legacy/workflow), extract fields
            meta = dict(metadata or {})
            if runtime_metadata:
                meta.update(runtime_metadata)
            if model_metadata:
                meta.update(model_metadata)
            if provenance:
                meta["provenance"] = provenance

            eff_task = hermes_task or meta.get("task") or trigger_type
            eff_obs = observations_used or observations or meta.get("observations") or meta.get("observations_used", [])
            eff_inf = inferences or meta.get("inferences", [])
            eff_pred = predictions or meta.get("predictions", [])
            eff_rec = recommendations or recommendation or meta.get("recommendation") or meta.get("recommendations")
            eff_urg = urgency or meta.get("urgency")
            eff_act = actionability or meta.get("actionability")
            eff_rel = relevance or meta.get("relevance")
            eff_evs = evidence_strength or meta.get("evidence_strength")
            eff_interv = intervention_decision or meta.get("intervention_decision")
            eff_user_resp = user_response or meta.get("user_response")
            eff_outcome = outcome or meta.get("outcome")

            ctx = dict(context_snapshot or meta.get("context_snapshot", {}))
            if evidence:
                ctx["evidence"] = [str(e) for e in evidence] if isinstance(evidence, list) else [str(evidence)]
            if provenance:
                ctx["provenance"] = provenance

            # Preserve invocation telemetry in context snapshot
            telemetry = dict(ctx.get("_telemetry", {})) if isinstance(ctx.get("_telemetry"), dict) else {}
            for k in ["reason_for_invocation", "reasoning_budget", "context_size", "investigation_rounds", "tool_calls", "execution_time_ms", "reason_code"]:
                if k in kwargs and kwargs[k] is not None:
                    telemetry[k] = kwargs[k]
            if telemetry:
                ctx["_telemetry"] = telemetry

            stat_val = parse_status or status
            if stat_val == "unparseable_reasoning" or stat_val == "unparseable":
                stat_val = EpisodeStatus.UNPARSEABLE_REASONING.value

            # Redact sensitive values and credentials from stored episode
            try:
                from personal_intelligence.security.redactor import SensitivePayloadRedactor
                redactor = SensitivePayloadRedactor()
                eff_obs = redactor.sanitize(eff_obs)
                eff_inf = redactor.sanitize(eff_inf)
                eff_pred = redactor.sanitize(eff_pred)
                eff_rec = redactor.sanitize(eff_rec)
                ctx = redactor.sanitize(ctx)
                meta = redactor.sanitize(meta)
            except Exception:
                pass

            ep = ReasoningEpisode(
                id=ep_id,
                situation_id=situation_id,
                created_at=now,
                context_snapshot=ctx,
                observations=eff_obs,
                inferences=eff_inf,
                predictions=eff_pred,
                hermes_task=eff_task,
                hermes_result=hermes_result or meta.get("hermes_result"),
                recommendation=eff_rec,
                urgency=eff_urg,
                actionability=eff_act,
                relevance=eff_rel,
                evidence_strength=eff_evs,
                intervention_decision=eff_interv,
                user_response=eff_user_resp,
                outcome=eff_outcome,
                follow_up_at=ensure_timezone_aware(follow_up_at, "follow_up_at") if follow_up_at else None,
                status=stat_val,
                metadata=meta,
            )


        query = """
            INSERT INTO reasoning_episodes (
                id, situation_id, created_at, context_snapshot_json,
                observations_json, inferences_json, predictions_json,
                hermes_task, hermes_result_json, recommendation_json,
                urgency, actionability, relevance, evidence_strength,
                intervention_decision_json, user_response_json, outcome_json,
                follow_up_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        urgency_val = ep.urgency.value if hasattr(ep.urgency, "value") else (str(ep.urgency) if ep.urgency else None)
        actionability_val = ep.actionability.value if hasattr(ep.actionability, "value") else (str(ep.actionability) if ep.actionability else None)
        relevance_val = ep.relevance.value if hasattr(ep.relevance, "value") else (str(ep.relevance) if ep.relevance else None)
        evidence_strength_val = ep.evidence_strength.value if hasattr(ep.evidence_strength, "value") else (str(ep.evidence_strength) if ep.evidence_strength else None)
        status_val = ep.status.value if hasattr(ep.status, "value") else str(ep.status)

        intervention_dict = ep.intervention_decision.to_dict() if hasattr(ep.intervention_decision, "to_dict") else ep.intervention_decision
        user_response_dict = ep.user_response.to_dict() if hasattr(ep.user_response, "to_dict") else ep.user_response
        outcome_dict = ep.outcome.to_dict() if hasattr(ep.outcome, "to_dict") else ep.outcome

        params = (
            ep.id,
            ep.situation_id,
            format_iso8601(ep.created_at),
            json.dumps(ep.context_snapshot, ensure_ascii=False) if ep.context_snapshot else None,
            json.dumps(ep.observations, ensure_ascii=False) if ep.observations else None,
            json.dumps(ep.inferences, ensure_ascii=False) if ep.inferences else None,
            json.dumps(ep.predictions, ensure_ascii=False) if ep.predictions else None,
            ep.hermes_task,
            json.dumps(ep.hermes_result, ensure_ascii=False) if ep.hermes_result else None,
            json.dumps(ep.recommendation, ensure_ascii=False) if ep.recommendation else None,
            urgency_val,
            actionability_val,
            relevance_val,
            evidence_strength_val,
            json.dumps(intervention_dict, ensure_ascii=False) if intervention_dict else None,
            json.dumps(user_response_dict, ensure_ascii=False) if user_response_dict else None,
            json.dumps(outcome_dict, ensure_ascii=False) if outcome_dict else None,
            format_iso8601(ep.follow_up_at) if ep.follow_up_at else None,
            status_val,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return ep
        finally:
            conn.close()

    def record_user_response(
        self,
        episode_id: str,
        response: Union[RecommendationResult, str],
        feedback_notes: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: Optional[str] = EpisodeStatus.RESPONSE_RECORDED.value,
    ) -> Optional[ReasoningEpisode]:
        """
        Records the user's interaction or response to an intervention recommendation.
        Validates response against allowed RecommendationResult states.
        """
        existing = self.get_episode(episode_id)
        if existing is None:
            return None

        # Validate response
        valid_states = {e.value for e in RecommendationResult}
        resp_val = response.value if isinstance(response, RecommendationResult) else str(response).strip().upper()
        if resp_val not in valid_states:
            raise ValueError(f"Invalid recommendation response '{response}'. Must be one of {sorted(list(valid_states))}")

        record = UserResponseRecord(
            response=resp_val,
            timestamp=ensure_timezone_aware(timestamp or datetime.now(timezone.utc), "timestamp"),
            feedback_notes=feedback_notes,
            metadata=metadata or {},
        )

        new_status = status if status is not None else EpisodeStatus.RESPONSE_RECORDED.value
        query = """
            UPDATE reasoning_episodes
            SET user_response_json = ?, status = ?
            WHERE id = ?;
        """
        params = (
            json.dumps(record.to_dict(), ensure_ascii=False),
            new_status,
            existing.id,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return self.get_episode(episode_id)
        finally:
            conn.close()

    def update_response(
        self,
        episode_id: str,
        user_response: Dict[str, Any],
        status: Optional[str] = EpisodeStatus.RESPONSE_RECORDED.value,
    ) -> Optional[ReasoningEpisode]:
        """
        Updates user response dictionary for an episode.
        """
        resp_raw = user_response.get("response") or user_response.get("action_taken") or RecommendationResult.UNKNOWN.value
        synonyms = {
            "acknowledged": RecommendationResult.ACCEPTED.value,
            "accepted": RecommendationResult.ACCEPTED.value,
            "accept": RecommendationResult.ACCEPTED.value,
            "dismissed": RecommendationResult.DISMISSED.value,
            "dismiss": RecommendationResult.DISMISSED.value,
            "ignored": RecommendationResult.IGNORED.value,
            "ignore": RecommendationResult.IGNORED.value,
            "deferred": RecommendationResult.DEFERRED.value,
            "defer": RecommendationResult.DEFERRED.value,
            "completed": RecommendationResult.COMPLETED.value,
            "complete": RecommendationResult.COMPLETED.value,
            "partially_completed": RecommendationResult.PARTIALLY_COMPLETED.value,
        }
        if str(resp_raw).lower() in synonyms:
            resp_raw = synonyms[str(resp_raw).lower()]
        elif str(resp_raw).upper() not in {e.value for e in RecommendationResult}:
            resp_raw = RecommendationResult.UNKNOWN.value

        fb_raw = user_response.get("feedback_notes") or user_response.get("feedback")
        ts_raw = user_response.get("timestamp") or user_response.get("responded_at")
        ts = ensure_timezone_aware(ts_raw, "timestamp") if ts_raw else None
        meta = dict(user_response.get("metadata", {}))
        if "action_taken" in user_response:
            meta["action_taken"] = user_response["action_taken"]

        return self.record_user_response(
            episode_id=episode_id,
            response=resp_raw,
            feedback_notes=fb_raw,
            timestamp=ts,
            metadata=meta,
            status=status,
        )

    def record_outcome(
        self,
        episode_id: str,
        outcome_status: Union[RecommendationResult, str],
        evaluation_notes: Optional[str] = None,
        success: Optional[bool] = None,
        observed_at: Optional[datetime] = None,
        impact_metrics: Optional[Dict[str, Any]] = None,
        evidence_event_ids: Optional[List[str]] = None,
        status: Optional[str] = EpisodeStatus.OUTCOME_RECORDED.value,
    ) -> Optional[ReasoningEpisode]:
        """
        Records the empirical longitudinal outcome of a recommendation.
        Validates outcome_status against allowed RecommendationResult states.
        """
        existing = self.get_episode(episode_id)
        if existing is None:
            return None

        # Validate outcome status
        valid_states = {e.value for e in RecommendationResult}
        out_val = outcome_status.value if isinstance(outcome_status, RecommendationResult) else str(outcome_status).strip().upper()
        if out_val not in valid_states:
            raise ValueError(f"Invalid outcome status '{outcome_status}'. Must be one of {sorted(list(valid_states))}")

        record = OutcomeRecord(
            outcome_status=out_val,
            observed_at=ensure_timezone_aware(observed_at or datetime.now(timezone.utc), "observed_at"),
            evaluation_notes=evaluation_notes,
            success=success,
            impact_metrics=impact_metrics or {},
            evidence_event_ids=evidence_event_ids or [],
        )

        new_status = status if status is not None else EpisodeStatus.OUTCOME_RECORDED.value
        query = """
            UPDATE reasoning_episodes
            SET outcome_json = ?, status = ?
            WHERE id = ?;
        """
        params = (
            json.dumps(record.to_dict(), ensure_ascii=False),
            new_status,
            existing.id,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return self.get_episode(episode_id)
        finally:
            conn.close()

    def update_outcome(
        self,
        episode_id: str,
        outcome: Dict[str, Any],
        status: Optional[str] = EpisodeStatus.OUTCOME_RECORDED.value,
    ) -> Optional[ReasoningEpisode]:
        """
        Updates outcome dictionary for an episode.
        """
        status_raw = outcome.get("outcome_status") or outcome.get("status") or (
            RecommendationResult.COMPLETED.value if outcome.get("success") is True else RecommendationResult.UNKNOWN.value
        )
        notes_raw = outcome.get("evaluation_notes") or outcome.get("evaluation")
        success_raw = outcome.get("success")
        obs_raw = outcome.get("observed_at") or outcome.get("evaluated_at")
        obs_dt = ensure_timezone_aware(obs_raw, "observed_at") if obs_raw else None
        metrics_raw = dict(outcome.get("impact_metrics", {}))
        standard_keys = {"outcome_status", "status", "evaluation_notes", "evaluation", "success", "observed_at", "evaluated_at", "impact_metrics", "evidence_event_ids"}
        for k, v in outcome.items():
            if k not in standard_keys:
                metrics_raw[k] = v
        ev_ids = outcome.get("evidence_event_ids", [])

        return self.record_outcome(
            episode_id=episode_id,
            outcome_status=status_raw,
            evaluation_notes=notes_raw,
            success=success_raw,
            observed_at=obs_dt,
            impact_metrics=metrics_raw,
            evidence_event_ids=ev_ids,
            status=status,
        )

    def update_episode(
        self,
        episode_id: str,
        situation_id: Optional[str] = None,
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
        status: Optional[str] = None,
        # Central audit and learning record aliases:
        observations_used: Optional[List[str]] = None,
        evidence: Optional[Union[List[str], str]] = None,
        recommendations: Optional[Any] = None,
        provenance: Optional[List[Dict[str, Any]]] = None,
        runtime_metadata: Optional[Dict[str, Any]] = None,
        model_metadata: Optional[Dict[str, Any]] = None,
        parse_status: Optional[str] = None,
        # Backwards compatibility kwargs:
        outcome_evaluation: Optional[str] = None,
        outcome_success: Optional[bool] = None,
        lessons_learned: Optional[List[str]] = None,
        investigation_record: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ended_at: Optional[datetime] = None,
        **kwargs: Any,
    ) -> Optional[ReasoningEpisode]:
        """
        Updates arbitrary fields of an existing reasoning episode.
        """
        existing = self.get_episode(episode_id)
        if existing is None:
            return None

        meta = dict(metadata or {})
        if runtime_metadata:
            meta.update(runtime_metadata)
        if model_metadata:
            meta.update(model_metadata)
        if provenance:
            meta["provenance"] = provenance

        new_sit = situation_id if situation_id is not None else existing.situation_id
        new_ctx = dict(context_snapshot) if context_snapshot is not None else dict(existing.context_snapshot)
        if evidence:
            new_ctx["evidence"] = [str(e) for e in evidence] if isinstance(evidence, list) else [str(evidence)]
        if provenance:
            new_ctx["provenance"] = provenance

        # Preserve invocation telemetry in context snapshot
        telemetry = dict(new_ctx.get("_telemetry", {})) if isinstance(new_ctx.get("_telemetry"), dict) else {}
        for k in ["reason_for_invocation", "reasoning_budget", "context_size", "investigation_rounds", "tool_calls", "execution_time_ms", "reason_code"]:
            if k in kwargs and kwargs[k] is not None:
                telemetry[k] = kwargs[k]
            elif hasattr(existing, k) and getattr(existing, k) is not None:
                telemetry[k] = getattr(existing, k)
        if telemetry:
            new_ctx["_telemetry"] = telemetry

        new_obs = observations_used or observations if (observations_used is not None or observations is not None) else (meta.get("observations") or meta.get("observations_used") or existing.observations)
        new_inf = inferences if inferences is not None else (meta.get("inferences") or existing.inferences)
        new_pred = predictions if predictions is not None else (meta.get("predictions") or existing.predictions)
        new_task = hermes_task if hermes_task is not None else (meta.get("task") or existing.hermes_task)
        new_res = hermes_result if hermes_result is not None else (
            investigation_record.__dict__ if investigation_record else (meta.get("hermes_result") or existing.hermes_result)
        )
        new_rec = recommendations or recommendation if (recommendations is not None or recommendation is not None) else (meta.get("recommendation") or meta.get("recommendations") or lessons_learned or existing.recommendation)
        new_urg = urgency if urgency is not None else (meta.get("urgency") or existing.urgency)
        new_act = actionability if actionability is not None else (meta.get("actionability") or existing.actionability)
        new_rel = relevance if relevance is not None else (meta.get("relevance") or existing.relevance)
        new_evs = evidence_strength if evidence_strength is not None else (meta.get("evidence_strength") or existing.evidence_strength)
        new_int = intervention_decision if intervention_decision is not None else (meta.get("intervention_decision") or existing.intervention_decision)
        new_resp = user_response if user_response is not None else (meta.get("user_response") or existing.user_response)
        
        # Outcome synthesis
        eff_outcome = outcome if outcome is not None else meta.get("outcome")
        if eff_outcome is None:
            if outcome_evaluation is not None or outcome_success is not None:
                if existing.outcome and isinstance(existing.outcome, dict):
                    eff_outcome = dict(existing.outcome)
                    if outcome_evaluation is not None:
                        eff_outcome["evaluation_notes"] = outcome_evaluation
                    if outcome_success is not None:
                        eff_outcome["success"] = outcome_success
                        eff_outcome["outcome_status"] = RecommendationResult.COMPLETED.value if outcome_success else RecommendationResult.DISMISSED.value
                else:
                    eff_outcome = {
                        "outcome_status": RecommendationResult.COMPLETED.value if outcome_success else (RecommendationResult.DISMISSED.value if outcome_success is False else RecommendationResult.UNKNOWN.value),
                        "evaluation_notes": outcome_evaluation,
                        "success": outcome_success,
                    }
        new_out = eff_outcome if eff_outcome is not None else existing.outcome



        new_fu = ensure_timezone_aware(follow_up_at, "follow_up_at") if follow_up_at is not None else existing.follow_up_at
        
        stat_val = status.value if hasattr(status, "value") else (str(status) if status is not None else existing.status)

        query = """
            UPDATE reasoning_episodes
            SET situation_id = ?, context_snapshot_json = ?,
                observations_json = ?, inferences_json = ?, predictions_json = ?,
                hermes_task = ?, hermes_result_json = ?, recommendation_json = ?,
                urgency = ?, actionability = ?, relevance = ?, evidence_strength = ?,
                intervention_decision_json = ?, user_response_json = ?, outcome_json = ?,
                follow_up_at = ?, status = ?
            WHERE id = ?;
        """
        params = (
            new_sit,
            json.dumps(new_ctx, ensure_ascii=False) if new_ctx else None,
            json.dumps(new_obs, ensure_ascii=False) if new_obs else None,
            json.dumps(new_inf, ensure_ascii=False) if new_inf else None,
            json.dumps(new_pred, ensure_ascii=False) if new_pred else None,
            new_task,
            json.dumps(new_res, default=str, ensure_ascii=False) if new_res else None,
            json.dumps(new_rec, ensure_ascii=False) if new_rec else None,
            new_urg,
            new_act,
            new_rel,
            new_evs,
            json.dumps(new_int, ensure_ascii=False) if new_int else None,
            json.dumps(new_resp, ensure_ascii=False) if new_resp else None,
            json.dumps(new_out, ensure_ascii=False) if new_out else None,
            format_iso8601(new_fu) if new_fu else None,
            stat_val,
            existing.id,
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query, params)
            return self.get_episode(episode_id)
        finally:
            conn.close()

    def get_episode(self, episode_id: str) -> Optional[ReasoningEpisode]:
        """Retrieves a reasoning episode by its ID."""
        if not episode_id:
            return None

        query = "SELECT * FROM reasoning_episodes WHERE id = ? LIMIT 1;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (episode_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_episode(row)
            return None
        finally:
            conn.close()

    def list_recent(self, limit: int = 10) -> List[ReasoningEpisode]:
        """Lists recent reasoning episodes ordered by created_at DESC."""
        query = "SELECT * FROM reasoning_episodes ORDER BY created_at DESC LIMIT ?;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
            return [self._row_to_episode(r) for r in rows]
        finally:
            conn.close()

    def list_recent_episodes(self, limit: int = 10) -> List[ReasoningEpisode]:
        """Backwards compatibility alias for list_recent."""
        return self.list_recent(limit=limit)

    def list_by_situation(self, situation_id: str, limit: int = 50) -> List[ReasoningEpisode]:
        """Lists reasoning episodes for a specific situation ID ordered by created_at DESC."""
        if not situation_id:
            return []

        query = "SELECT * FROM reasoning_episodes WHERE situation_id = ? ORDER BY created_at DESC LIMIT ?;"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (situation_id, limit))
            rows = cursor.fetchall()
            return [self._row_to_episode(r) for r in rows]
        finally:
            conn.close()
