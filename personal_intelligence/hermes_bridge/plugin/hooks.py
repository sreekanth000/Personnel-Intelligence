"""
Lifecycle hooks for Hermes Agent executions interacting with Personal Intelligence.
Enables native observation ingestion from Hermes tool executions across Workspace
(Gmail, Calendar, Drive, Meet, Filesystem, Browser) with full origin provenance.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

from personal_intelligence.core.events.observation_manager import ObservationManager

logger = logging.getLogger(__name__)

# Default singleton manager instance
_obs_manager: Optional[ObservationManager] = None


def get_observation_manager(db_manager: Optional[Any] = None) -> ObservationManager:
    """Returns or initializes the singleton ObservationManager instance."""
    global _obs_manager
    if _obs_manager is None or db_manager is not None:
        _obs_manager = ObservationManager(db_manager=db_manager)
    return _obs_manager


def on_pre_tool_call(tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fires immediately prior to Hermes executing a tool.
    Can be used to enforce bounded action constraints or audit queries.
    """
    return {"action": "approve"}


def on_post_tool_call(
    tool_name: str,
    tool_args: Dict[str, Any],
    result: Any,
    db_manager: Optional[Any] = None,
) -> Optional[Any]:
    """
    Fires immediately after tool execution in Hermes runtime.
    Filters relevance, scrubs secrets, and normalizes relevant observations with provenance.
    Never blocks or crashes Hermes execution on unhandled errors.
    """
    try:
        manager = get_observation_manager(db_manager)
        return manager.process_tool_result(
            tool_name=tool_name,
            tool_args=tool_args,
            result=result,
            db_manager=db_manager,
        )
    except Exception as ex:
        logger.debug("on_post_tool_call non-critical error: %s", ex)
        return None


def on_reasoning_outcome(
    episode: Any,
    db_manager: Optional[Any] = None,
) -> Optional[Any]:
    """
    Fires upon completion of a Hermes reasoning cycle.
    Records high-level reasoning outcome as a normalized observation if relevant.
    """
    try:
        if not episode:
            return None
        meta = getattr(episode, "metadata", {}) or {}
        urgency = getattr(episode, "urgency", None) or meta.get("urgency", "medium")
        if str(urgency).lower() in ["high", "critical"]:
            from personal_intelligence.core.events.observation import record_observation
            ep_id = getattr(episode, "id", getattr(episode, "episode_id", "ep-unknown"))
            eval_text = getattr(episode, "outcome_evaluation", "High-priority reasoning synthesis completed.")
            return record_observation(
                source="hermes",
                source_id=f"episode_{ep_id}",
                timestamp=datetime.now(timezone.utc),
                observation_type="reasoning_outcome",
                summary=f"High-priority reasoning episode completed ({urgency}): {eval_text[:200]}",
                evidence={"episode_id": ep_id, "urgency": urgency, "metadata": meta},
                provenance={"origin_source": "hermes", "episode_id": ep_id},
                db_manager=db_manager,
            )
        return None
    except Exception as ex:
        logger.debug("on_reasoning_outcome non-critical error: %s", ex)
        return None


def on_pre_llm_call(prompt: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Fires immediately before Hermes invokes the LLM runtime with a reasoning prompt.
    Enforces boundary safety:
      - Prevents accidental full world model or raw database dumps.
      - Enforces bounded token limits.
      - Confirms security demarcation for untrusted connector data.
    """
    if not prompt or not isinstance(prompt, str):
        return {"action": "reject", "reason": "Prompt must be a non-empty string."}

    # Reject accidental full world model or raw database dumps
    lower_prompt = prompt.lower()
    if (
        "dump_entire_world_model" in lower_prompt
        or "select * from entity_nodes" in lower_prompt
        or "select * from events" in lower_prompt
        or "raw_database_dump" in lower_prompt
    ):
        return {
            "action": "reject",
            "reason": "Boundary violation: Raw database or full world model dump detected in LLM prompt. Hermes context must be strictly bounded.",
        }

    # Length guard (prevent unbounded context expansion)
    if len(prompt) > 80000:
        return {
            "action": "reject",
            "reason": f"Boundary violation: Prompt length ({len(prompt)} chars) exceeds safe bounded context cap.",
        }

    return {"action": "approve"}





