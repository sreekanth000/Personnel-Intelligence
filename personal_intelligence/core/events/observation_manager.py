"""
Observation Manager for Personal Intelligence.

Decides whether Hermes tool execution results and lifecycle events are relevant
to the Personal World Model. For relevant events, it normalizes and records
concise observations with provenance while strictly filtering out secrets,
transient noise, and unnecessary full content dumps.
"""

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from personal_intelligence.core.events.models import (
    Event,
    ensure_timezone_aware,
    format_iso8601,
)
from personal_intelligence.core.events.observation import record_observation
from personal_intelligence.storage.db import DatabaseManager

logger = logging.getLogger(__name__)

# Patterns for identifying and redacting sensitive data / secrets
SECRET_PATTERNS = [
    (re.compile(r'(?i)(api[_-]?key|apikey|secret|token|password|passwd|auth[_-]?token|bearer)\s*[:=]\s*["\']?([^"\'\s,;]{8,})["\']?'), r'\1=[REDACTED]'),
    (re.compile(r'(?i)bearer\s+[a-zA-Z0-9_\-\.]{15,}'), 'Bearer [REDACTED]'),
    (re.compile(r'ghp_[a-zA-Z0-9]{36}'), '[REDACTED_GITHUB_TOKEN]'),
    (re.compile(r'AIza[0-9A-Za-z-_]{35}'), '[REDACTED_GOOGLE_API_KEY]'),
    (re.compile(r'-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----'), '[REDACTED_PRIVATE_KEY]'),
]

# Irrelevant tools and query patterns that should NEVER create observations
IRRELEVANT_TOOL_PATTERNS = [
    "ping", "echo", "health", "status_check", "get_schema", "list_skills",
    "help", "version", "system_info", "noop", "sleep", "heartbeat",
]

# File extensions and paths that are internal noise
NOISE_PATH_SUBSTRINGS = [
    "node_modules", ".git/", "__pycache__", ".venv", "site-packages",
    "tmp/", "temp/", ".cache", ".gemini", ".idea", ".vscode",
]

# Maximum length for observation summaries
MAX_OBSERVATION_SUMMARY_LEN = 500
# Maximum size for sanitized structured evidence
MAX_STRUCTURED_DATA_SIZE = 16384


class ObservationManager:
    """
    Evaluates tool executions and lifecycle signals to decide what should be
    observed and ingested into the Personal World Model.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager

    # -------------------------------------------------------------------------
    # Secret Scrubbing & Sanitization
    # -------------------------------------------------------------------------

    @classmethod
    def sanitize_secrets(cls, value: Any) -> Any:
        """
        Recursively scrubs API keys, auth tokens, passwords, and private keys from data.
        """
        if isinstance(value, str):
            cleaned = value
            for pattern, repl in SECRET_PATTERNS:
                cleaned = pattern.sub(repl, cleaned)
            return cleaned
        elif isinstance(value, dict):
            cleaned_dict = {}
            for k, v in value.items():
                k_lower = str(k).lower()
                if any(sec in k_lower for sec in ["secret", "password", "token", "auth_header", "apikey", "api_key", "private_key"]):
                    cleaned_dict[k] = "[REDACTED]"
                else:
                    cleaned_dict[k] = cls.sanitize_secrets(v)
            return cleaned_dict
        elif isinstance(value, list):
            return [cls.sanitize_secrets(item) for item in value]
        return value

    # -------------------------------------------------------------------------
    # Relevance Decision
    # -------------------------------------------------------------------------

    def should_observe(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Determines whether a tool execution contains meaningful personal signals.
        Returns: (is_relevant, source_domain, observation_type)
        """
        if not tool_name or not result:
            return False, None, None

        t_name = tool_name.lower().strip()

        # 1. Filter out known transient utility tools
        if any(irr in t_name for irr in IRRELEVANT_TOOL_PATTERNS):
            return False, None, None

        # 2. Filter empty result payloads
        if result == {} or result == [] or result == "" or result is None:
            return False, None, None
        if isinstance(result, dict):
            # Check for empty container results
            if result.get("items") == [] or result.get("messages") == [] or result.get("files") == []:
                return False, None, None
            if result.get("status") == "error" or result.get("found") is False:
                return False, None, None

        # 3. Domain classification and relevance detection

        # A. Gmail / Communication
        if any(k in t_name for k in ["gmail", "email", "mail", "message"]):
            # Check if it has actual message content or search hits
            res_str = str(result).lower()
            if any(sig in res_str for sig in ["subject", "from", "deadline", "milestone", "review", "approved", "attached", "meeting", "invite"]):
                return True, "gmail", "possible_commitment"
            return True, "gmail", "email_received"

        # B. Calendar / Schedule
        if any(k in t_name for k in ["calendar", "event", "schedule", "meeting_schedule"]):
            res_str = str(result).lower()
            if any(sig in res_str for sig in ["conflict", "overlap", "reschedule", "cancelled", "urgent"]):
                return True, "calendar", "conflicting_commitments"
            return True, "calendar", "upcoming_milestone"

        # C. Drive / Documents
        if any(k in t_name for k in ["drive", "doc", "sheet", "slide", "file_search"]):
            # Filter noise paths
            args_str = str(tool_args).lower()
            if any(n in args_str for n in NOISE_PATH_SUBSTRINGS):
                return False, None, None
            return True, "drive", "document_changed"

        # D. Meet / Transcripts
        if any(k in t_name for k in ["meet", "transcript", "meeting_note"]):
            res_str = str(result).lower()
            if any(sig in res_str for sig in ["decision", "action item", "next step", "agreed", "assigned"]):
                return True, "meet", "meeting_decision"
            return True, "meet", "meeting_decision"

        # E. Filesystem
        if any(k in t_name for k in ["filesystem", "file", "workspace", "read_file", "write_file"]):
            args_str = str(tool_args).lower()
            # Discard transient or noise paths
            if any(n in args_str for n in NOISE_PATH_SUBSTRINGS):
                return False, None, None
            path_val = str(tool_args.get("path") or tool_args.get("file_path") or tool_args.get("TargetFile") or "")
            if path_val.endswith((".lock", ".tmp", ".log", ".pyc", ".map")):
                return False, None, None
            return True, "filesystem", "document_changed"

        return False, None, None

    # -------------------------------------------------------------------------
    # Observation Extraction & Normalization
    # -------------------------------------------------------------------------

    def extract_normalized_observation(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        source_domain: str,
        observation_type: str,
    ) -> Dict[str, Any]:
        """
        Extracts a clean, normalized observation representation from tool data.
        Enforces minimization by distilling salient metadata rather than copying full blobs.
        """
        now = datetime.now(timezone.utc)
        sanitized_args = self.sanitize_secrets(tool_args)
        sanitized_result = self.sanitize_secrets(result)

        # Determine source_id
        source_id = f"hermes_tool_{tool_name}_{now.strftime('%Y%m%d%H%M%S')}"
        if isinstance(sanitized_result, dict):
            source_id = str(
                sanitized_result.get("id")
                or sanitized_result.get("message_id")
                or sanitized_result.get("event_id")
                or sanitized_result.get("file_id")
                or sanitized_args.get("id")
                or sanitized_args.get("path")
                or source_id
            )
        elif isinstance(sanitized_args, dict):
            source_id = str(sanitized_args.get("path") or sanitized_args.get("query") or source_id)

        # Distill structured evidence without raw bloat
        structured_evidence: Dict[str, Any] = {}
        summary_text = f"Observed {source_domain} activity via Hermes tool '{tool_name}'."

        if isinstance(sanitized_result, dict):
            # Extract common metadata attributes
            for key in ["title", "subject", "from", "to", "sender", "date", "status", "action_items", "summary", "snippet", "path", "start_time", "end_time"]:
                if key in sanitized_result:
                    val = sanitized_result[key]
                    if isinstance(val, str) and len(val) > 300:
                        val = val[:300] + "..."
                    structured_evidence[key] = val

            if "subject" in sanitized_result:
                summary_text = f"Email: '{sanitized_result['subject']}'"
            elif "title" in sanitized_result:
                summary_text = f"{source_domain.title()}: '{sanitized_result['title']}'"
            elif "summary" in sanitized_result:
                summary_text = str(sanitized_result["summary"])[:MAX_OBSERVATION_SUMMARY_LEN]
            elif "snippet" in sanitized_result:
                summary_text = str(sanitized_result["snippet"])[:MAX_OBSERVATION_SUMMARY_LEN]
        elif isinstance(sanitized_result, list):
            structured_evidence["item_count"] = len(sanitized_result)
            sample_items = []
            for item in sanitized_result[:3]:
                if isinstance(item, dict):
                    sample_items.append({k: str(v)[:150] for k, v in item.items() if k in ["title", "subject", "id", "name", "summary"]})
                else:
                    sample_items.append(str(item)[:150])
            structured_evidence["samples"] = sample_items
            summary_text = f"Found {len(sanitized_result)} {source_domain} items matching query."
        else:
            raw_str = str(sanitized_result)
            summary_text = raw_str[:MAX_OBSERVATION_SUMMARY_LEN]
            structured_evidence["content_snippet"] = raw_str[:300]

        # Formulate provenance retrieval coordinates
        provenance = {
            "origin_source": source_domain,
            "tool": tool_name,
            "tool_name": tool_name,
            "tool_args": sanitized_args,
            "recorded_at": format_iso8601(now),
        }


        from personal_intelligence.security.guard import PromptInjectionGuard

        # Sanitize summary and evidence to defang prompt injection attempts
        safe_summary_text = PromptInjectionGuard.sanitize_untrusted_text(summary_text, max_chars=MAX_OBSERVATION_SUMMARY_LEN)
        safe_structured_evidence = {}
        for ek, ev in structured_evidence.items():
            if isinstance(ev, str):
                safe_structured_evidence[ek] = PromptInjectionGuard.sanitize_untrusted_text(ev, max_chars=1000)
            elif isinstance(ev, list):
                safe_structured_evidence[ek] = [PromptInjectionGuard.sanitize_untrusted_text(str(item), max_chars=300) for item in ev]
            else:
                safe_structured_evidence[ek] = ev

        return {
            "source": source_domain,
            "source_id": source_id,
            "timestamp": now,
            "observation_type": observation_type,
            "summary": safe_summary_text,
            "evidence": safe_structured_evidence,
            "provenance": provenance,
            "confidence_category": "high",
        }


    # -------------------------------------------------------------------------
    # Main Processing Entrypoint
    # -------------------------------------------------------------------------

    def process_tool_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        db_manager: Optional[DatabaseManager] = None,
    ) -> Optional[Event]:
        """
        Main hook entrypoint. Evaluates relevance, strips secrets,
        and records a normalized observation if relevant.
        Never throws exceptions to avoid disrupting normal Hermes execution.
        """
        try:
            is_relevant, source_domain, obs_type = self.should_observe(tool_name, tool_args, result)
            if not is_relevant or not source_domain or not obs_type:
                # Irrelevant: Do NOT persist raw content
                return None

            obs_data = self.extract_normalized_observation(
                tool_name=tool_name,
                tool_args=tool_args,
                result=result,
                source_domain=source_domain,
                observation_type=obs_type,
            )

            effective_db = db_manager or self.db_manager
            from personal_intelligence.core.events.store import EventStore
            store = EventStore(db_manager=effective_db)
            existing_obs = store.get_by_source_id(obs_data["source"], obs_data["source_id"])
            if existing_obs and existing_obs.payload.get("summary") == obs_data["summary"]:
                logger.info("Observation for source '%s' and id '%s' already recorded. Skipping duplicate.", obs_data["source"], obs_data["source_id"])
                return existing_obs

            event = record_observation(
                source=obs_data["source"],
                source_id=obs_data["source_id"],
                timestamp=obs_data["timestamp"],
                observation_type=obs_data["observation_type"],
                summary=obs_data["summary"],
                evidence=obs_data["evidence"],
                provenance=obs_data["provenance"],
                db_manager=effective_db,
                event_store=store,
            )

            logger.info("Recorded observation '%s' from tool '%s'", event.id, tool_name)
            return event

        except Exception as ex:
            logger.warning("ObservationManager non-blocking hook error: %s", ex)
            return None
