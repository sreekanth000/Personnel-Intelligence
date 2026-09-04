"""
Hermes Agent Native Runtime Bridge.

Provides native in-process interfaces to invoke the Hermes Agent runtime for
situational reasoning, external investigations, and tool execution without
external subprocesses, duplicate API clients, or gateway HTTP endpoints.

Execution Modes:
- LIVE: Requires a real Hermes runtime connection and fails clearly when unavailable.
- DEMO: Uses deterministic fixture data, visibly labelled [DEMO MODE].
- TEST: Uses mocked runtime contexts, callable hooks, and tool overrides.

Guarantees:
- Zero silent success fallbacks in LIVE mode.
- Strict typed errors for missing context, missing capability, unauthenticated state, tool failure.
- Safe diagnostic logging without recording email contents, credentials, or raw sensitive payloads.
- Zero OAuth token / credential storage.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Active Hermes runtime context singleton (set upon plugin registration)
_active_hermes_context: Optional[Any] = None


def set_active_hermes_context(context: Any) -> None:
    """Sets the active Hermes agent runtime context for native in-process execution."""
    global _active_hermes_context
    _active_hermes_context = context


def get_active_hermes_context() -> Optional[Any]:
    """Retrieves the active Hermes agent runtime context."""
    return _active_hermes_context


class HermesBridgeExecutionMode(str, Enum):
    """Explicit operational execution modes for the Hermes bridge."""
    LIVE = "live"
    DEMO = "demo"
    TEST = "test"
    # Backward compatibility aliases
    NATIVE = "live"
    CLI = "test"
    PYTHON_API = "test"
    GATEWAY = "test"


# Backward-compatible alias for existing codebase
HermesExecutionMode = HermesBridgeExecutionMode


# =============================================================================
# Typed Exception Hierarchy
# =============================================================================

class HermesBridgeError(Exception):
    """Base exception for all Hermes bridge errors."""
    def __init__(self, message: str, safe_diagnostics: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.safe_diagnostics = safe_diagnostics or {}


class MissingRuntimeContextError(HermesBridgeError):
    """Raised in LIVE mode when no active host Hermes runtime context is bound."""
    pass


class MissingCapabilityError(HermesBridgeError):
    """Raised when a requested capability or tool is not declared or available in Hermes."""
    pass


class UnauthenticatedCapabilityError(HermesBridgeError):
    """Raised when a capability exists in Hermes but the external service is unauthenticated."""
    pass


class ToolExecutionFailureError(HermesBridgeError):
    """Raised when a Hermes tool execution fails on the host runtime."""
    pass


class InvalidResultError(HermesBridgeError):
    """Raised when Hermes returns an unparseable or invalid schema result."""
    pass


# =============================================================================
# Invocation Payloads
# =============================================================================

@dataclass
class HermesInvocationRequest:
    """Request payload sent to Hermes for reasoning or investigation."""
    prompt: str
    session_id: Optional[str] = None
    skills: Optional[List[str]] = None
    timeout_seconds: int = 120
    quiet_mode: bool = True
    context_data: Optional[Dict[str, Any]] = None


@dataclass
class HermesInvocationResponse:
    """Response returned from Hermes after execution."""
    raw_response: str
    session_id: Optional[str] = None
    tools_executed: Optional[List[str]] = None
    duration_ms: int = 0
    success: bool = True
    error: Optional[str] = None
    is_demo: bool = False
    safe_diagnostics: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Hermes Runtime Bridge
# =============================================================================

class HermesRuntimeBridge:
    """
    Native in-process bridge for interfacing Personal Intelligence with the
    host Hermes Agent runtime without spawning subprocesses or opening network sockets.
    
    Responsibilities:
    - Enforce explicit execution modes: LIVE, DEMO, and TEST.
    - LIVE mode requires a real Hermes runtime connection and fails clearly when unavailable.
    - DEMO mode returns visibly labelled synthetic fixture responses.
    - TEST mode allows mocked contexts and tool overrides.
    - Enforce OperationSafetyGuard (read-only external access & no autonomous writes).
    - Provide typed error handling without silent success fallbacks.
    - Capture safe diagnostic telemetry without logging sensitive email or payload data.
    """

    def __init__(
        self,
        mode: Union[HermesBridgeExecutionMode, str] = HermesBridgeExecutionMode.LIVE,
        runtime_context: Optional[Any] = None,
        llm_callable: Optional[Callable[[str], str]] = None,
        allowed_directory_roots: Optional[List[str]] = None,
    ) -> None:
        if isinstance(mode, str):
            try:
                self.execution_mode = HermesBridgeExecutionMode(mode.lower())
            except ValueError:
                self.execution_mode = HermesBridgeExecutionMode.LIVE
        else:
            self.execution_mode = mode

        self._runtime_context = runtime_context
        self._llm_callable = llm_callable
        self._tool_overrides: Dict[str, Callable[..., Any]] = {}
        from personal_intelligence.security.guard import OperationSafetyGuard
        self.safety_guard = OperationSafetyGuard(allowed_directory_roots=allowed_directory_roots)

    @property
    def mode(self) -> HermesBridgeExecutionMode:
        """Backward-compatible mode accessor."""
        return self.execution_mode

    @mode.setter
    def mode(self, val: Union[HermesBridgeExecutionMode, str]) -> None:
        if isinstance(val, str):
            try:
                self.execution_mode = HermesBridgeExecutionMode(val.lower())
            except ValueError:
                self.execution_mode = HermesBridgeExecutionMode.LIVE
        else:
            self.execution_mode = val

    @property
    def runtime_context(self) -> Optional[Any]:
        """Returns injected or global active Hermes runtime context."""
        return self._runtime_context or get_active_hermes_context()

    def bind_context(self, context: Any) -> None:
        """Binds a Hermes Agent runtime context to this bridge instance."""
        self._runtime_context = context

    def set_llm_callable(self, callable_fn: Callable[[str], str]) -> None:
        """Sets an in-process callable for direct LLM reasoning generation."""
        self._llm_callable = callable_fn

    def register_tool_override(self, tool_name: str, handler: Callable[..., Any]) -> None:
        """
        Registers a custom handler for a specific tool name.

        RESTRICTED TO TEST MODE ONLY. Raises RuntimeError in LIVE or DEMO mode
        to prevent stubbed tool handlers from masking missing real Hermes connections.
        """
        if self.execution_mode not in (HermesBridgeExecutionMode.TEST,):
            raise RuntimeError(
                f"register_tool_override() is restricted to TEST mode. "
                f"Current mode: {self.execution_mode.value}. "
                "Tool overrides cannot be used in LIVE or DEMO mode."
            )
        self._tool_overrides[tool_name] = handler

    # -------------------------------------------------------------------------
    # Diagnostic Sanitizer Helper
    # -------------------------------------------------------------------------
    def _sanitize_diagnostics(self, tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Builds safe diagnostic metadata without recording email bodies, credentials,
        passwords, access tokens, or raw sensitive payloads.
        """
        args = tool_args or {}
        arg_keys = list(args.keys())
        sanitized_summary: Dict[str, Any] = {
            "tool": tool_name,
            "execution_mode": self.execution_mode.value,
            "argument_keys": arg_keys,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # Include non-sensitive query metadata if present
        if "max_results" in args:
            sanitized_summary["max_results"] = args["max_results"]
        if "limit" in args:
            sanitized_summary["limit"] = args["limit"]
        return sanitized_summary

    # -------------------------------------------------------------------------
    # Reasoning Invocation
    # -------------------------------------------------------------------------
    def invoke_reasoning(
        self,
        request: HermesInvocationRequest,
    ) -> HermesInvocationResponse:
        """
        Executes a situational reasoning or investigation prompt.
        - In LIVE mode: Requires an active runtime context or LLM callable; fails clearly if missing.
        - In DEMO mode: Returns deterministic fixture output visibly labelled [DEMO MODE].
        - In TEST mode: Uses mocked callable or test fallback.
        """
        start_time = datetime.now(timezone.utc)

        # 0. Pre-LLM Boundary Hook Validation
        from personal_intelligence.hermes_bridge.plugin.hooks import on_pre_llm_call
        pre_check = on_pre_llm_call(prompt=request.prompt, session_id=request.session_id)
        if pre_check.get("action") == "reject":
            return HermesInvocationResponse(
                raw_response="",
                session_id=request.session_id,
                success=False,
                error=pre_check.get("reason", "Pre-LLM call hook rejected request due to boundary violations."),
                safe_diagnostics={"invoker": "pre_llm_hook", "reason": pre_check.get("reason")},
            )

        # 1. Direct LLM callable delegation (e.g. injected model or test hook)
        if self._llm_callable is not None:
            try:
                res_text = self._llm_callable(request.prompt)
                duration = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                return HermesInvocationResponse(
                    raw_response=res_text,
                    session_id=request.session_id,
                    tools_executed=[],
                    duration_ms=duration,
                    success=True,
                    is_demo=(self.execution_mode == HermesBridgeExecutionMode.DEMO),
                    safe_diagnostics={"invoker": "llm_callable", "mode": self.execution_mode.value},
                )
            except Exception as ex:
                logger.error("LLM callable execution error: %s", ex)
                return HermesInvocationResponse(
                    raw_response="",
                    session_id=request.session_id,
                    success=False,
                    error=str(ex),
                    safe_diagnostics={"invoker": "llm_callable", "error": type(ex).__name__},
                )

        # 2. DEMO MODE execution
        if self.execution_mode == HermesBridgeExecutionMode.DEMO:
            demo_response = (
                "```json\n"
                "{\n"
                '  "findings": ["[DEMO MODE] Cross-source deliverable review scheduled for tomorrow morning."],\n'
                '  "source_references": ["demo://gmail/thread-101", "demo://drive/doc-v3"],\n'
                '  "structured_data": {"status": "demo_verified", "is_demo": true},\n'
                '  "uncertainty": ["Synthetic demonstration parameters."],\n'
                '  "expiration_time": "2026-08-23T18:00:00Z"\n'
                "}\n"
                "```"
            )
            return HermesInvocationResponse(
                raw_response=demo_response,
                session_id=request.session_id,
                tools_executed=["demo_search"],
                duration_ms=5,
                success=True,
                is_demo=True,
                safe_diagnostics={"invoker": "demo_fixture", "mode": "demo"},
            )

        # 3. Host Hermes runtime context delegation
        ctx = self.runtime_context
        if ctx is not None:
            if hasattr(ctx, "prompt_llm") and callable(ctx.prompt_llm):
                try:
                    res_text = ctx.prompt_llm(request.prompt)
                    duration = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                    return HermesInvocationResponse(
                        raw_response=res_text,
                        session_id=request.session_id,
                        tools_executed=[],
                        duration_ms=duration,
                        success=True,
                        is_demo=False,
                        safe_diagnostics={"invoker": "host_hermes_prompt_llm", "mode": self.execution_mode.value},
                    )
                except Exception as ex:
                    logger.error("Hermes runtime prompt_llm error: %s", ex)
                    return HermesInvocationResponse(
                        raw_response="",
                        session_id=request.session_id,
                        success=False,
                        error=f"Hermes host reasoning failed: {ex}",
                        safe_diagnostics={"invoker": "host_hermes_prompt_llm", "error": type(ex).__name__},
                    )

            if hasattr(ctx, "call_agent") and callable(ctx.call_agent):
                try:
                    res_text = ctx.call_agent(request.prompt)
                    duration = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                    return HermesInvocationResponse(
                        raw_response=res_text,
                        session_id=request.session_id,
                        tools_executed=[],
                        duration_ms=duration,
                        success=True,
                        is_demo=False,
                        safe_diagnostics={"invoker": "host_hermes_call_agent", "mode": self.execution_mode.value},
                    )
                except Exception as ex:
                    logger.error("Hermes runtime call_agent error: %s", ex)
                    return HermesInvocationResponse(
                        raw_response="",
                        session_id=request.session_id,
                        success=False,
                        error=f"Hermes host call_agent failed: {ex}",
                        safe_diagnostics={"invoker": "host_hermes_call_agent", "error": type(ex).__name__},
                    )

        # 4. TEST MODE fallback
        if self.execution_mode == HermesBridgeExecutionMode.TEST:
            return HermesInvocationResponse(
                raw_response="[TEST MODE execution stub]",
                session_id=request.session_id,
                tools_executed=[],
                duration_ms=0,
                success=True,
                is_demo=False,
                safe_diagnostics={"invoker": "test_stub", "mode": "test"},
            )

        # 5. LIVE MODE failure (No silent success fallback allowed)
        diag = {"mode": "live", "runtime_context_attached": False}
        err_msg = "Cannot execute reasoning: Host Hermes runtime context is not attached in LIVE mode."
        logger.warning(err_msg)
        return HermesInvocationResponse(
            raw_response="",
            session_id=request.session_id,
            tools_executed=[],
            duration_ms=0,
            success=False,
            error=err_msg,
            is_demo=False,
            safe_diagnostics=diag,
        )

    # -------------------------------------------------------------------------
    # Tool Execution
    # -------------------------------------------------------------------------
    def execute_tool(
        self,
        tool_name: str,
        tool_args: Optional[Dict[str, Any]] = None,
        user_approved: bool = False,
    ) -> Any:
        """
        Executes an existing Hermes native tool (Workspace, Meet, Filesystem, Browser)
        through the host runtime context without duplicating API clients.
        
        Guarantees:
        - Strict OperationSafetyGuard (read-only external access; blocks autonomous write operations unless user-approved).
        - In LIVE mode: Fails with typed errors when runtime context, tool, or authentication is missing.
        - In DEMO mode: Returns fixture data visibly labelled [DEMO].
        - In TEST mode: Executes tool overrides or mocked context.
        """
        args = tool_args or {}
        diag = self._sanitize_diagnostics(tool_name, args)

        # 1. Enforce operation safety policy (read-only and no autonomous write operations unless user_approved)
        if hasattr(self, "safety_guard") and self.safety_guard is not None:
            is_allowed, denial_reason = self.safety_guard.validate_tool_execution(
                tool_name,
                args,
                is_user_approved=user_approved,
            )
            if not is_allowed:
                from personal_intelligence.security.guard import UnauthorizedWriteOperationError
                logger.warning("OperationSafetyGuard blocked tool '%s': %s", tool_name, denial_reason)
                raise UnauthorizedWriteOperationError(denial_reason)

        # 2. Check registered tool overrides (TEST mode ONLY)
        if tool_name in self._tool_overrides:
            if self.execution_mode != HermesBridgeExecutionMode.TEST:
                raise RuntimeError(
                    f"Tool override for '{tool_name}' is registered but execution mode is "
                    f"'{self.execution_mode.value}'. Tool overrides are restricted to TEST mode."
                )
            try:
                return self._tool_overrides[tool_name](**args)
            except Exception as ex:
                raise ToolExecutionFailureError(f"Tool override for '{tool_name}' failed: {ex}", safe_diagnostics=diag) from ex

        # 3. DEMO MODE tool execution
        if self.execution_mode == HermesBridgeExecutionMode.DEMO:
            return {
                "status": "success",
                "tool": tool_name,
                "is_demo": True,
                "demo_label": f"[DEMO MODE] Synthetic observation from {tool_name}",
                "data": {"sample": True, "tool_executed": tool_name},
                "safe_diagnostics": diag,
            }

        # 4. Host runtime context delegation
        ctx = self.runtime_context

        # LIVE MODE: Missing context check
        if ctx is None:
            if self.execution_mode == HermesBridgeExecutionMode.TEST:
                return {
                    "status": "test_stub",
                    "tool": tool_name,
                    "is_test": True,
                    "safe_diagnostics": diag,
                }
            raise MissingRuntimeContextError(
                f"Cannot execute tool '{tool_name}': Host Hermes runtime context is not attached in LIVE mode.",
                safe_diagnostics=diag,
            )

        # LIVE MODE: Missing capability check
        if hasattr(ctx, "available_tools") and isinstance(getattr(ctx, "available_tools"), (list, set, tuple)):
            if tool_name not in ctx.available_tools:
                raise MissingCapabilityError(
                    f"Tool '{tool_name}' is not in available Hermes tools: {list(ctx.available_tools)}",
                    safe_diagnostics=diag,
                )
        elif hasattr(ctx, "has_tool") and callable(getattr(ctx, "has_tool")):
            try:
                if not bool(ctx.has_tool(tool_name)):
                    raise MissingCapabilityError(
                        f"Tool '{tool_name}' is not declared or available in the active Hermes runtime context.",
                        safe_diagnostics=diag,
                    )
            except HermesBridgeError:
                raise
            except Exception:
                pass

        # LIVE MODE: Capability authentication check
        # Rule: absent auth probe → UNKNOWN, never AUTHENTICATED.
        # Priority order (matching _probe_auth_status in capabilities.py):
        #   1. auth_status dict (explicit dict) — highest priority
        #   2. is_capability_authenticated callable
        #   3. No probe at all → UNKNOWN → refuse for external caps
        cap_key = tool_name.split("_")[0]
        if hasattr(ctx, "auth_status") and isinstance(getattr(ctx, "auth_status"), dict):
            raw = ctx.auth_status.get(cap_key)
            if raw == "authenticated" or raw == "not_required":
                pass  # Explicitly confirmed — proceed
            elif raw == "unauthenticated":
                raise UnauthenticatedCapabilityError(
                    f"Capability '{cap_key}' for tool '{tool_name}' is unauthenticated in host Hermes.",
                    safe_diagnostics=diag,
                )
            elif raw is None:
                # Key absent from dict → UNKNOWN → refuse for external workspace tools
                if cap_key not in ("filesystem", "reasoning", "web"):
                    raise UnauthenticatedCapabilityError(
                        f"Capability '{cap_key}' authentication status is absent from host context "
                        f"auth_status dict for tool '{tool_name}'. Refusing to execute.",
                        safe_diagnostics={**diag, "raw_auth_value": "None"},
                    )
            else:
                # Unrecognised value → UNKNOWN
                raise UnauthenticatedCapabilityError(
                    f"Capability '{cap_key}' authentication status is unknown for tool '{tool_name}'. "
                    f"Unrecognised auth value: '{raw}'.",
                    safe_diagnostics={**diag, "raw_auth_value": str(raw)},
                )
        elif hasattr(ctx, "is_capability_authenticated") and callable(getattr(ctx, "is_capability_authenticated")):
            try:
                res = ctx.is_capability_authenticated(cap_key)
                if res is True or res == "authenticated":
                    pass  # Explicitly authenticated — proceed
                elif res is False or res == "unauthenticated":
                    raise UnauthenticatedCapabilityError(
                        f"Capability '{cap_key}' for tool '{tool_name}' is unauthenticated in host Hermes.",
                        safe_diagnostics=diag,
                    )
                else:
                    # None, 0, MagicMock, or unexpected value → UNKNOWN → refuse
                    raise UnauthenticatedCapabilityError(
                        f"Capability '{cap_key}' authentication status is unknown for tool '{tool_name}'. "
                        "Hermes returned an unrecognised auth response. Refusing to execute.",
                        safe_diagnostics={**diag, "auth_probe_result": type(res).__name__},
                    )
            except HermesBridgeError:
                raise
            except Exception as probe_ex:
                # Exception during probe → UNKNOWN → refuse to execute
                raise UnauthenticatedCapabilityError(
                    f"Capability '{cap_key}' authentication probe raised an error for tool '{tool_name}': {probe_ex}",
                    safe_diagnostics={**diag, "probe_error": type(probe_ex).__name__},
                ) from probe_ex
        # No auth probe available at all: for external workspace tools, refuse to execute
        elif cap_key not in ("filesystem", "reasoning", "web"):
            raise UnauthenticatedCapabilityError(
                f"Cannot verify authentication for capability '{cap_key}' (tool '{tool_name}'). "
                "The runtime context provides no auth probe. "
                "Refusing to execute external workspace tool without confirmed authentication.",
                safe_diagnostics=diag,
            )

        # Execute on host context
        try:
            if hasattr(ctx, "execute_tool") and callable(ctx.execute_tool):
                return ctx.execute_tool(tool_name, args)
            elif hasattr(ctx, "call_tool") and callable(ctx.call_tool):
                return ctx.call_tool(tool_name, args)
        except Exception as ex:
            raise ToolExecutionFailureError(
                f"Tool '{tool_name}' failed during Hermes host execution: {ex}",
                safe_diagnostics=diag,
            ) from ex

        # If context has no execution entrypoint in TEST mode
        if self.execution_mode == HermesBridgeExecutionMode.TEST:
            return {"status": "test_stub", "tool": tool_name, "safe_diagnostics": diag}

        raise MissingCapabilityError(
            f"Host Hermes runtime context does not expose an execution handler for tool '{tool_name}'.",
            safe_diagnostics=diag,
        )

    # -------------------------------------------------------------------------
    # Capability Contract Probing
    # -------------------------------------------------------------------------
    def probe_capabilities(self, is_demo: Optional[bool] = None) -> Any:
        """
        Probes all capabilities against the active runtime context using the capability contract.
        """
        from personal_intelligence.hermes_bridge.capabilities import HermesCapabilityInspector
        inspector = HermesCapabilityInspector()
        demo_flag = (self.execution_mode == HermesBridgeExecutionMode.DEMO) if is_demo is None else is_demo
        return inspector.probe_all(runtime_context=self.runtime_context, is_demo=demo_flag)

    def get_connection_status(self, is_demo: Optional[bool] = None) -> Any:
        """
        Returns the current HermesConnectionStatus for this bridge.
        """
        from personal_intelligence.hermes_bridge.capabilities import (
            HermesCapabilityInspector,
            HermesConnectionStatus,
        )
        demo_flag = (self.execution_mode == HermesBridgeExecutionMode.DEMO) if is_demo is None else is_demo
        if demo_flag:
            return HermesConnectionStatus.DEMO
        if self.runtime_context is None:
            return HermesConnectionStatus.DISCONNECTED
        inspector = HermesCapabilityInspector()
        report = inspector.probe_all(runtime_context=self.runtime_context, is_demo=demo_flag)
        return report.connection_status


# Backward-compatible alias for existing codebase and test suites
HermesClient = HermesRuntimeBridge
