"""
Tool schemas exposed by the Personal Intelligence plugin to the Hermes reasoning runtime.
"""

GET_CURRENT_PERSONAL_STATE_SCHEMA = {
    "name": "get_current_personal_state",
    "description": "Query the user's current multi-dimensional state representation (time_of_day, location, activity, event_density, duration, routine_deviation, goal_pressure).",
    "parameters": {
        "type": "object",
        "properties": {
            "subject_id": {
                "type": "string",
                "description": "Optional subject ID to filter state features for (defaults to primary user).",
            },
        },
        "required": [],
    },
}

GET_PERSONAL_TIMELINE_SCHEMA = {
    "name": "get_personal_timeline",
    "description": "Query a bounded, chronological slice of recent personal events from the timeline source of truth.",
    "parameters": {
        "type": "object",
        "properties": {
            "last_n_minutes": {
                "type": "integer",
                "description": "Query events in the last N minutes.",
            },
            "last_n_hours": {
                "type": "integer",
                "description": "Query events in the last N hours.",
            },
            "start_time": {
                "type": "string",
                "description": "ISO timestamp for start of query window.",
            },
            "end_time": {
                "type": "string",
                "description": "ISO timestamp for end of query window.",
            },
            "subject_id": {
                "type": "string",
                "description": "Filter timeline for a specific subject ID.",
            },
            "event_type": {
                "type": "string",
                "description": "Filter timeline for a specific event type.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum events to return (default 20).",
                "default": 20,
            },
        },
        "required": [],
    },
}

GET_ACTIVE_GOALS_SCHEMA = {
    "name": "get_active_goals",
    "description": "Query active personal goals, priorities, and contextual objectives from GoalStore.",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "paused", "completed", "archived", "all"],
                "description": "Filter goals by status (defaults to active).",
                "default": "active",
            },
        },
        "required": [],
    },
}

GET_SITUATION_SCHEMA = {
    "name": "get_situation",
    "description": "Query a specific situation context frame by ID to retrieve its status, priority, novelty, context, and evidence references.",
    "parameters": {
        "type": "object",
        "properties": {
            "situation_id": {
                "type": "string",
                "description": "Unique identifier of the situation.",
            },
        },
        "required": ["situation_id"],
    },
}

GET_REASONING_CONTEXT_SCHEMA = {
    "name": "get_reasoning_context",
    "description": "Construct a bounded, relevance-filtered reasoning context for a Situation. Returns relevant timeline events, active goals, emerging hypotheses, and uncertainties.",
    "parameters": {
        "type": "object",
        "properties": {
            "situation_id": {
                "type": "string",
                "description": "Unique identifier of the situation to construct bounded context for.",
            },
            "objective": {
                "type": "string",
                "description": "Optional specific investigation objective or focus question.",
            },
        },
        "required": ["situation_id"],
    },
}

STORE_REASONING_EPISODE_SCHEMA = {
    "name": "store_reasoning_episode",
    "description": "Record the outcome of a Hermes situational reasoning investigation back to the audit history. Explicitly tracks observations, inferences, predictions, recommendations, and uncertainties.",
    "parameters": {
        "type": "object",
        "properties": {
            "situation_id": {
                "type": "string",
                "description": "ID of the situation investigated.",
            },
            "trigger_type": {
                "type": "string",
                "description": "Investigation trigger type (default: situation_investigation).",
                "default": "situation_investigation",
            },
            "outcome_evaluation": {
                "type": "string",
                "description": "Synthesized reasoning evaluation and summary of findings.",
            },
            "outcome_success": {
                "type": "boolean",
                "description": "Whether the reasoning investigation succeeded.",
                "default": True,
            },
            "lessons_learned": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key takeaways, routine insights, or patterns discovered.",
            },
            "observations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Direct factual observations verified from provided context.",
            },
            "inferences": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Logical inferences deduced from observations and state.",
            },
            "predictions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Probabilistic forward-looking predictions.",
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Proposed system or user action candidates.",
            },
            "uncertainties_identified": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit uncertainties, gaps, or assumptions identified during reasoning.",
            },
            "evidence_references": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of event IDs, state keys, or goal IDs backing the conclusions.",
            },
        },
        "required": ["situation_id"],
    },
}

RECORD_OBSERVATION_SCHEMA = {
    "name": "record_observation",
    "description": "Record a normalized personal observation encountered during Hermes tool execution. Does NOT store raw multi-megabyte external documents; stores concise summaries and salient evidence while preserving retrieval provenance.",
    "parameters": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "enum": ["gmail", "drive", "calendar", "meet", "filesystem", "hermes", "user"],
                "description": "Originating source of the observation.",
            },
            "source_id": {
                "type": "string",
                "description": "Unique identifier of the record in originating system (e.g. message_id, doc_id, event_id, file_path).",
            },
            "timestamp": {
                "type": "string",
                "description": "ISO 8601 timestamp when the event/observation occurred.",
            },
            "observation_type": {
                "type": "string",
                "description": "Normalized category (e.g. email_received, deadline_detected, document_changed, calendar_event, action_item_detected, routine_change, unusual_state).",
            },
            "summary": {
                "type": "string",
                "description": "Concise derived summary (e.g. 'Email indicates a possible deadline.', 'Architecture document modified.').",
            },
            "evidence": {
                "type": "object",
                "description": "Salient extracted facts or key-value attributes (not raw email/document bodies).",
            },
            "provenance": {
                "type": "object",
                "description": "Origin metadata (tool, query, path) sufficient for Hermes to retrieve original information if needed.",
            },
        },
        "required": ["source", "source_id", "timestamp", "observation_type", "summary", "provenance"],
    },
}

GET_PERSONAL_WORLD_MODEL_SCHEMA = {
    "name": "get_personal_world_model",
    "description": "Retrieve the structured snapshot of the Personal World Model derived from observations: CURRENT STATE (commitments, upcoming events, open issues, recent activity, goals, active situations), TIMELINE, GOALS, OPEN SITUATIONS, KNOWN PATTERNS, and EMERGING HYPOTHESES.",
    "parameters": {
        "type": "object",
        "properties": {
            "include_timeline_hours": {
                "type": "integer",
                "description": "Hours of recent timeline events to include (default 24).",
                "default": 24,
            },
        },
        "required": [],
    },
}

EVALUATE_CANDIDATE_SITUATIONS_SCHEMA = {
    "name": "evaluate_candidate_situations",
    "description": "Synthesizes the Personal World Model signals (current state, observations, timeline, goals, patterns, hypotheses) to discover candidate situations across generic categories (forgotten commitments, preparation needs, conflicts, issues, changes, risks, opportunities, information gaps, novelty).",
    "parameters": {
        "type": "object",
        "properties": {
            "save_to_store": {
                "type": "boolean",
                "description": "Whether to automatically persist discovered active situations into SituationStore (default true).",
                "default": True,
            },
        },
        "required": [],
    },
}

EXECUTE_PI_COMMAND_SCHEMA = {
    "name": "execute_pi_command",
    "description": "Execute a Hermes Personal Intelligence (/pi) command mode: what_matters, status, what_changed, investigate, why, patterns, timeline, goals, situations, or briefing.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": "The /pi command mode to execute: 'what_matters', 'status', 'what_changed', 'investigate', 'why', 'patterns', 'timeline', 'goals', 'situations', or 'briefing'.",
                "enum": ["what_matters", "status", "what_changed", "investigate", "why", "patterns", "timeline", "goals", "situations", "briefing", "help"],
                "default": "what_matters",
            },
            "situation_id": {
                "type": "string",
                "description": "Optional situation ID when running 'investigate' or 'why' modes.",
            },

            "limit": {
                "type": "integer",
                "description": "Optional limit for timeline or what_matters recommendations count (default 5 for recommendations).",
                "default": 5,
            },
            "user_context": {
                "type": "string",
                "description": "Optional user context override ('available', 'busy', 'meeting', 'deep_work', 'sleep', 'driving', 'dnd').",
                "default": "available",
            },
        },
        "required": [],
    },
}

PLUGIN_TOOL_SCHEMAS = [
    GET_CURRENT_PERSONAL_STATE_SCHEMA,
    GET_PERSONAL_TIMELINE_SCHEMA,
    GET_ACTIVE_GOALS_SCHEMA,
    GET_SITUATION_SCHEMA,
    GET_REASONING_CONTEXT_SCHEMA,
    STORE_REASONING_EPISODE_SCHEMA,
    RECORD_OBSERVATION_SCHEMA,
    GET_PERSONAL_WORLD_MODEL_SCHEMA,
    EVALUATE_CANDIDATE_SITUATIONS_SCHEMA,
    EXECUTE_PI_COMMAND_SCHEMA,
]

