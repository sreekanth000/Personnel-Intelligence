"""
Hermes Plugin Registration Entrypoint for Personal Intelligence.

When loaded into Hermes runtime, Hermes invokes register(ctx) to bind tools and hooks.
"""

from personal_intelligence.hermes_bridge.plugin.hooks import (
    on_post_tool_call,
    on_pre_tool_call,
)
from personal_intelligence.hermes_bridge.plugin.schemas import (
    EVALUATE_CANDIDATE_SITUATIONS_SCHEMA,
    EXECUTE_PI_COMMAND_SCHEMA,
    GET_ACTIVE_GOALS_SCHEMA,
    GET_CURRENT_PERSONAL_STATE_SCHEMA,
    GET_PERSONAL_TIMELINE_SCHEMA,
    GET_PERSONAL_WORLD_MODEL_SCHEMA,
    GET_REASONING_CONTEXT_SCHEMA,
    GET_SITUATION_SCHEMA,
    RECORD_OBSERVATION_SCHEMA,
    STORE_REASONING_EPISODE_SCHEMA,
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
from typing import Optional

from personal_intelligence.hermes_bridge.client import set_active_hermes_context
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore


def register(ctx: object, db_manager: Optional[DatabaseManager] = None) -> None:
    """
    Registers the Personal Intelligence tools, /pi commands, and lifecycle hooks with the Hermes runtime.
    Initializes SQLite storage layer and binds active runtime context.
    """
    set_active_hermes_context(ctx)
    if hasattr(ctx, "register_tool"):

        ctx.register_tool(
            name=GET_CURRENT_PERSONAL_STATE_SCHEMA["name"],
            schema=GET_CURRENT_PERSONAL_STATE_SCHEMA,
            handler=lambda **kw: get_current_personal_state(db_manager=db_manager, **kw) if db_manager else get_current_personal_state(**kw),
        )
        ctx.register_tool(
            name=GET_PERSONAL_TIMELINE_SCHEMA["name"],
            schema=GET_PERSONAL_TIMELINE_SCHEMA,
            handler=lambda **kw: get_personal_timeline(db_manager=db_manager, **kw) if db_manager else get_personal_timeline(**kw),
        )
        ctx.register_tool(
            name=GET_ACTIVE_GOALS_SCHEMA["name"],
            schema=GET_ACTIVE_GOALS_SCHEMA,
            handler=lambda **kw: get_active_goals(db_manager=db_manager, **kw) if db_manager else get_active_goals(**kw),
        )
        ctx.register_tool(
            name=GET_SITUATION_SCHEMA["name"],
            schema=GET_SITUATION_SCHEMA,
            handler=lambda **kw: get_situation(db_manager=db_manager, **kw) if db_manager else get_situation(**kw),
        )
        ctx.register_tool(
            name=GET_REASONING_CONTEXT_SCHEMA["name"],
            schema=GET_REASONING_CONTEXT_SCHEMA,
            handler=lambda **kw: get_reasoning_context(db_manager=db_manager, **kw) if db_manager else get_reasoning_context(**kw),
        )
        ctx.register_tool(
            name=STORE_REASONING_EPISODE_SCHEMA["name"],
            schema=STORE_REASONING_EPISODE_SCHEMA,
            handler=lambda **kw: store_reasoning_episode(db_manager=db_manager, **kw) if db_manager else store_reasoning_episode(**kw),
        )
        ctx.register_tool(
            name=RECORD_OBSERVATION_SCHEMA["name"],
            schema=RECORD_OBSERVATION_SCHEMA,
            handler=lambda **kw: record_observation(db_manager=db_manager, **kw) if db_manager else record_observation(**kw),
        )
        ctx.register_tool(
            name=GET_PERSONAL_WORLD_MODEL_SCHEMA["name"],
            schema=GET_PERSONAL_WORLD_MODEL_SCHEMA,
            handler=lambda **kw: get_personal_world_model(db_manager=db_manager, **kw) if db_manager else get_personal_world_model(**kw),
        )
        ctx.register_tool(
            name=EVALUATE_CANDIDATE_SITUATIONS_SCHEMA["name"],
            schema=EVALUATE_CANDIDATE_SITUATIONS_SCHEMA,
            handler=lambda **kw: evaluate_candidate_situations(db_manager=db_manager, **kw) if db_manager else evaluate_candidate_situations(**kw),
        )
        ctx.register_tool(
            name=EXECUTE_PI_COMMAND_SCHEMA["name"],
            schema=EXECUTE_PI_COMMAND_SCHEMA,
            handler=lambda **kw: execute_pi_command(db_manager=db_manager, **kw) if db_manager else execute_pi_command(**kw),
        )

    if hasattr(ctx, "register_command"):
        from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
        _handler = PersonalIntelligenceCommandHandler(db_manager=db_manager)
        ctx.register_command(
            name="/pi",
            description="Personal Intelligence command (modes: what_matters, status, investigate, patterns, timeline, goals, situations, briefing)",
            handler=lambda args="what_matters": _handler.execute(f"/pi {args}"),
        )

    if hasattr(ctx, "register_hook"):
        ctx.register_hook("pre_tool_call", on_pre_tool_call)
        ctx.register_hook("post_tool_call", lambda tn, ta, res: on_post_tool_call(tn, ta, res, db_manager=db_manager) if db_manager else on_post_tool_call(tn, ta, res))


