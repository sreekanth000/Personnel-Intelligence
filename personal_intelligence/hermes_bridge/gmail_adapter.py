"""
Hermes-Owned Read-Only Gmail Capability Adapter.

Provides declarative, bounded access to Gmail data exclusively through the host
Hermes Agent runtime without direct Google API SDKs, OAuth tokens, or credential handling.

Guarantees:
- Personal Intelligence requests Gmail through generic capability requests.
- Strictly read-only operations (searches, metadata, thread summaries).
- Explicitly rejects send, delete, archive, label, draft, and modification operations.
- Returns a normalized Hermes Gmail result schema.
- Reports capability unavailable if Hermes does not expose Gmail.
- Reports unauthenticated if Hermes reports incomplete authentication.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from personal_intelligence.hermes_bridge.capabilities import (
    CapabilityAuthStatus,
    CapabilityAvailability,
    HermesCapabilityInspector,
)
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesRuntimeBridge,
    MissingCapabilityError,
    MissingRuntimeContextError,
    UnauthenticatedCapabilityError,
)
from personal_intelligence.security.guard import UnauthorizedWriteOperationError

logger = logging.getLogger(__name__)

# Permitted read-only Gmail tool operations
ALLOWED_READ_ONLY_GMAIL_TOOLS: Set[str] = {
    "gmail_search",
    "gmail_get_thread",
    "gmail_get_message_metadata",
    "gmail_list_messages",
    "gmail_get_message_summary",
}

# Forbidden mutation tool operations
PROHIBITED_MUTATION_GMAIL_TOOLS: Set[str] = {
    "send_email",
    "gmail_send",
    "send",
    "delete",
    "gmail_delete",
    "archive",
    "gmail_archive",
    "label",
    "gmail_add_label",
    "gmail_remove_label",
    "draft",
    "gmail_create_draft",
    "modify",
    "gmail_modify",
    "trash",
    "gmail_trash",
}


@dataclass
class GmailCapabilityRequest:
    """Generic declarative request payload for Gmail inquiry."""
    query: str
    max_results: int = 10
    time_range_days: Optional[int] = None
    sender_filter: Optional[str] = None
    read_only: bool = True


@dataclass
class HermesGmailResult:
    """Normalized Hermes Gmail result schema."""
    status: str  # 'success', 'unavailable', 'unauthenticated', 'error', 'rejected'
    findings: List[str] = field(default_factory=list)
    message_references: List[str] = field(default_factory=list)
    thread_references: List[str] = field(default_factory=list)
    timestamps: List[str] = field(default_factory=list)
    safe_summaries: List[str] = field(default_factory=list)
    provenance: List[str] = field(default_factory=list)
    tools_executed: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GmailCapabilityAdapter:
    """
    Adapter interfacing Personal Intelligence with the host Hermes Gmail capability.
    Delegates all execution and authentication to Hermes while enforcing read-only bounds.
    """

    def __init__(
        self,
        bridge: Optional[HermesRuntimeBridge] = None,
        inspector: Optional[HermesCapabilityInspector] = None,
    ) -> None:
        self.bridge = bridge or HermesRuntimeBridge()
        self.inspector = inspector or HermesCapabilityInspector()

    def validate_tool_operation(self, tool_name: str) -> Tuple[bool, Optional[str]]:
        """
        Validates that a requested Gmail tool operation is strictly read-only.
        Rejects all mutation, send, delete, archive, label, draft, and modify actions.
        """
        tool_clean = tool_name.strip().lower()

        # Check prohibited write/mutation list
        if tool_clean in PROHIBITED_MUTATION_GMAIL_TOOLS:
            denial = (
                f"Unauthorized Gmail write operation '{tool_name}'. "
                "Personal Intelligence enforces strictly read-only access to Gmail. "
                "Send, delete, archive, label, draft, and modify operations are blocked."
            )
            return False, denial

        # Ensure tool is in explicit read-only whitelist
        if tool_clean not in ALLOWED_READ_ONLY_GMAIL_TOOLS:
            denial = (
                f"Unrecognized or non-read-only Gmail tool '{tool_name}'. "
                f"Allowed read-only tools: {sorted(list(ALLOWED_READ_ONLY_GMAIL_TOOLS))}"
            )
            return False, denial

        return True, None

    def execute_query(
        self,
        request: GmailCapabilityRequest,
        tool_name: str = "gmail_search",
    ) -> HermesGmailResult:
        """
        Executes a declarative Gmail capability request via the host Hermes runtime.
        Returns a normalized HermesGmailResult schema.
        """
        # 1. Validate read-only tool constraint
        is_allowed, denial_reason = self.validate_tool_operation(tool_name)
        if not is_allowed:
            logger.warning("GmailCapabilityAdapter rejected operation: %s", denial_reason)
            raise UnauthorizedWriteOperationError(denial_reason or "Prohibited Gmail mutation")

        # 2. In DEMO mode, return deterministic demo findings visibly marked
        if self.bridge.execution_mode == HermesBridgeExecutionMode.DEMO:
            now_iso = datetime.now(timezone.utc).isoformat()
            return HermesGmailResult(
                status="success",
                findings=[
                    "[DEMO MODE] Project deliverable review discussion thread from lead architect.",
                    "[DEMO MODE] Meeting action item follow-up email.",
                ],
                message_references=["demo://gmail/msg_101", "demo://gmail/msg_102"],
                thread_references=["demo://gmail/thread_201"],
                timestamps=[now_iso],
                safe_summaries=[
                    "[DEMO MODE] Deliverable review thread with pending draft approval.",
                    "[DEMO MODE] Follow-up inquiry regarding architectural baseline.",
                ],
                provenance=["demo_gmail_search:demo://gmail/msg_101", "demo_gmail_search:demo://gmail/msg_102"],
                tools_executed=[tool_name],
                error=None,
            )

        # 3. Probe capability readiness via Hermes capability contract
        status_report = self.inspector.probe_capability(
            capability="gmail",
            runtime_context=self.bridge.runtime_context,
            is_demo=False,
        )

        # Check for unavailable state
        if status_report.availability == CapabilityAvailability.UNAVAILABLE:
            err_msg = status_report.error_message or "Hermes does not expose Gmail capability or host context is not attached."
            return HermesGmailResult(
                status="unavailable",
                findings=[],
                message_references=[],
                thread_references=[],
                timestamps=[],
                safe_summaries=[],
                provenance=[],
                tools_executed=[],
                error=err_msg,
            )

        # Check for unauthenticated or unknown auth state
        # UNKNOWN means no auth probe confirmed authentication — treat conservatively as unauthenticated.
        if status_report.authenticated_status in (
            CapabilityAuthStatus.UNAUTHENTICATED,
            CapabilityAuthStatus.UNKNOWN,
        ):
            auth_state = status_report.authenticated_status.value
            err_msg = (
                f"Gmail capability is unauthenticated in host Hermes (auth_status={auth_state}). "
                "Run 'hermes auth google' in Hermes to connect your Google Workspace account."
            )
            return HermesGmailResult(
                status="unauthenticated",
                findings=[],
                message_references=[],
                thread_references=[],
                timestamps=[],
                safe_summaries=[],
                provenance=[],
                tools_executed=[],
                error=err_msg,
            )

        # 4. Build sanitized tool arguments for Hermes
        tool_args: Dict[str, Any] = {
            "query": request.query,
            "max_results": request.max_results,
        }
        if request.sender_filter:
            tool_args["sender"] = request.sender_filter
        if request.time_range_days:
            tool_args["time_range_days"] = request.time_range_days

        # 5. Invoke host Hermes tool execution
        try:
            raw_output = self.bridge.execute_tool(tool_name, tool_args)
            return self._normalize_output(raw_output, tool_name=tool_name)
        except MissingRuntimeContextError as ex:
            return HermesGmailResult(status="unavailable", error=f"Missing Hermes runtime context: {ex}")
        except MissingCapabilityError as ex:
            return HermesGmailResult(status="unavailable", error=f"Missing Gmail capability in Hermes: {ex}")
        except UnauthenticatedCapabilityError as ex:
            return HermesGmailResult(status="unauthenticated", error=f"Unauthenticated Gmail capability: {ex}")
        except UnauthorizedWriteOperationError:
            raise
        except Exception as ex:
            logger.error("Hermes Gmail tool execution failed: %s", ex)
            return HermesGmailResult(
                status="error",
                error=f"Hermes Gmail tool '{tool_name}' execution error: {ex}",
                tools_executed=[tool_name],
            )

    def _normalize_output(self, raw_output: Any, tool_name: str) -> HermesGmailResult:
        """
        Normalizes arbitrary Hermes host Gmail tool outputs into the standard schema.
        Extracts findings, message references, timestamps, and safe summaries.
        """
        findings: List[str] = []
        message_refs: List[str] = []
        thread_refs: List[str] = []
        timestamps: List[str] = []
        safe_summaries: List[str] = []
        provenance: List[str] = []

        if isinstance(raw_output, dict):
            # Extract messages list if provided (handling nested result wrapper)
            inner = raw_output.get("result") if isinstance(raw_output.get("result"), dict) else raw_output
            messages = inner.get("messages") or inner.get("items") or inner.get("results") or raw_output.get("messages") or []
            if isinstance(messages, list):
                for idx, msg in enumerate(messages):
                    if isinstance(msg, dict):
                        m_id = str(msg.get("id") or msg.get("message_id") or f"msg_{idx}")
                        t_id = str(msg.get("thread_id") or msg.get("threadId") or f"thread_{idx}")
                        ts = str(msg.get("date") or msg.get("timestamp") or msg.get("time") or datetime.now(timezone.utc).isoformat())
                        subj = str(msg.get("subject") or msg.get("title") or msg.get("snippet") or f"Email observation {m_id}")
                        sender = str(msg.get("from") or msg.get("sender") or "collaborator")

                        message_refs.append(f"gmail:{m_id}")
                        if t_id and f"gmail:thread:{t_id}" not in thread_refs:
                            thread_refs.append(f"gmail:thread:{t_id}")
                        timestamps.append(ts)
                        safe_summary = f"[{sender}] {subj}"
                        safe_summaries.append(safe_summary)
                        findings.append(safe_summary)
                        provenance.append(f"{tool_name}:gmail:{m_id}")
                    elif isinstance(msg, str):
                        findings.append(msg)
                        safe_summaries.append(msg)
                        ref = f"gmail:msg_{idx}"
                        message_refs.append(ref)
                        provenance.append(f"{tool_name}:{ref}")

            # Extract top-level findings or summaries if present
            if "findings" in raw_output and isinstance(raw_output["findings"], list):
                for f in raw_output["findings"]:
                    if str(f) not in findings:
                        findings.append(str(f))

            if "summary" in raw_output and isinstance(raw_output["summary"], str):
                if raw_output["summary"] not in safe_summaries:
                    safe_summaries.append(raw_output["summary"])
                    findings.append(raw_output["summary"])

            # Check for error field
            err = raw_output.get("error") if raw_output.get("status") in ("error", "failed") else None
            status = "error" if err else "success"

        elif isinstance(raw_output, list):
            for idx, item in enumerate(raw_output):
                if isinstance(item, dict):
                    m_id = str(item.get("id") or f"msg_{idx}")
                    subj = str(item.get("subject") or item.get("snippet") or "Observation")
                    message_refs.append(f"gmail:{m_id}")
                    safe_summaries.append(subj)
                    findings.append(subj)
                    provenance.append(f"{tool_name}:gmail:{m_id}")
                else:
                    findings.append(str(item))
                    safe_summaries.append(str(item))
            status = "success"
            err = None
        elif isinstance(raw_output, str):
            findings.append(raw_output)
            safe_summaries.append(raw_output)
            status = "success"
            err = None
        else:
            status = "success"
            err = None

        return HermesGmailResult(
            status=status,
            findings=findings,
            message_references=message_refs,
            thread_references=thread_refs,
            timestamps=timestamps,
            safe_summaries=safe_summaries,
            provenance=provenance,
            tools_executed=[tool_name],
            error=err,
        )
