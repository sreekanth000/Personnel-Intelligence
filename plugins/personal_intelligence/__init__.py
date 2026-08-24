"""
Hermes Plugin Entrypoint for Personal Intelligence.
Exports plugin registration and tool hooks for Hermes Agent runtime.
"""

from personal_intelligence.hermes_bridge.plugin import (
    register as register_plugin,
)
from personal_intelligence.hermes_bridge.plugin.schemas import (
    EVALUATE_CANDIDATE_SITUATIONS_SCHEMA,
    EXECUTE_PI_COMMAND_SCHEMA,
    GET_PERSONAL_WORLD_MODEL_SCHEMA,
    PLUGIN_TOOL_SCHEMAS,
    RECORD_OBSERVATION_SCHEMA,
)
from personal_intelligence.hermes_bridge.plugin.tools import (
    evaluate_candidate_situations,
    execute_pi_command,
    get_active_goals,
    get_current_personal_state,
    get_personal_timeline,
    get_personal_world_model,
    get_reasoning_context,
    get_situation,
    record_observation,
    store_reasoning_episode,
)
from personal_intelligence.storage.local_store import LocalStateStore


from typing import Optional
from personal_intelligence.storage.db import DatabaseManager


def register(ctx: object, db_manager: Optional[DatabaseManager] = None) -> None:
    """
    Standard entrypoint called by Hermes Agent plugin loader.
    Binds the Personal Intelligence tools, /pi commands, and pre/post tool hooks.
    """
    register_plugin(ctx, db_manager=db_manager)



__all__ = [
    "register",
    "LocalStateStore",
    "get_current_personal_state",
    "get_personal_timeline",
    "get_active_goals",
    "get_situation",
    "get_reasoning_context",
    "store_reasoning_episode",
    "record_observation",
    "get_personal_world_model",
    "evaluate_candidate_situations",
    "execute_pi_command",
    "PLUGIN_TOOL_SCHEMAS",
    "RECORD_OBSERVATION_SCHEMA",
    "GET_PERSONAL_WORLD_MODEL_SCHEMA",
    "EVALUATE_CANDIDATE_SITUATIONS_SCHEMA",
    "EXECUTE_PI_COMMAND_SCHEMA",
]

