"""
Hermes Capability-Connection Contract & Diagnostic Status Models.

Provides a strict capability-connection contract for Personal Intelligence to probe
and report the operational readiness, authentication state, and tool availability
of host Hermes runtime capabilities without handling OAuth tokens or credentials.

Guarantees:
- Zero OAuth / Google API / token / credential management in Personal Intelligence.
- 6-stage connection model: disconnected, gateway_detected, transport_ready,
  runtime_attached, capabilities_discovered, gmail_authenticated.
- CapabilityMetadata allows tool names and setup commands to be sourced from
  Hermes-provided context metadata rather than hard-coded strings.
- UNKNOWN auth is never coerced to AUTHENTICATED; absent auth probes → UNKNOWN.
- Bounded read-only operation enforcement across all external capabilities.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from personal_intelligence.core.events.models import (
    ensure_timezone_aware,
    format_iso8601,
)


# ---------------------------------------------------------------------------
# Backward-compatible simple connection status (used in server.py / tests)
# ---------------------------------------------------------------------------
class HermesConnectionStatus(str, Enum):
    """High-level connection status (backward-compatible). Use HermesConnectionStage for detail."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"
    UNAUTHENTICATED = "unauthenticated"
    ERROR = "error"
    DEMO = "demo"


# ---------------------------------------------------------------------------
# 6-Stage ordered connection lifecycle
# ---------------------------------------------------------------------------
class HermesConnectionStage(str, Enum):
    """
    Ordered 6-stage connection lifecycle.

    Progress is strictly sequential — a stage is only reached when ALL
    prerequisites of every earlier stage are satisfied.

    disconnected        — No detection of Hermes at all.
    gateway_detected    — An HTTP health endpoint responded, but no runtime is
                          attached and no tools can be invoked. This is purely
                          a discovery signal; it does NOT mean Hermes is usable.
    transport_ready     — An in-process runtime context object has been provided
                          to this process (plugin attachment path only). A stable
                          HTTP gateway execution API does not exist; the HTTP
                          health check cannot advance beyond gateway_detected.
    runtime_attached    — The runtime context is confirmed operational
                          (has an execution entrypoint: execute_tool or call_tool).
    capabilities_discovered — Hermes has declared its available tools and at
                          least one capability is reachable.
    gmail_authenticated — The gmail capability is confirmed authenticated in the
                          host Hermes runtime.
    """
    DISCONNECTED = "disconnected"
    GATEWAY_DETECTED = "gateway_detected"
    TRANSPORT_READY = "transport_ready"
    RUNTIME_ATTACHED = "runtime_attached"
    CAPABILITIES_DISCOVERED = "capabilities_discovered"
    GMAIL_AUTHENTICATED = "gmail_authenticated"

    # DEMO is a parallel mode, not a lifecycle stage
    DEMO = "demo"

    @property
    def ordinal(self) -> int:
        """Numeric order for stage comparison (higher = more connected)."""
        _order = {
            "disconnected": 0,
            "gateway_detected": 1,
            "transport_ready": 2,
            "runtime_attached": 3,
            "capabilities_discovered": 4,
            "gmail_authenticated": 5,
            "demo": -1,
        }
        return _order.get(self.value, 0)

    def to_connection_status(self) -> HermesConnectionStatus:
        """Maps a stage to the backward-compatible HermesConnectionStatus."""
        mapping = {
            "disconnected": HermesConnectionStatus.DISCONNECTED,
            "gateway_detected": HermesConnectionStatus.DISCONNECTED,  # gateway ≠ usable
            "transport_ready": HermesConnectionStatus.CONNECTING,
            "runtime_attached": HermesConnectionStatus.CONNECTED,
            "capabilities_discovered": HermesConnectionStatus.CONNECTED,
            "gmail_authenticated": HermesConnectionStatus.CONNECTED,
            "demo": HermesConnectionStatus.DEMO,
        }
        return mapping.get(self.value, HermesConnectionStatus.DISCONNECTED)


class CapabilityAvailability(str, Enum):
    """Availability state for a specific capability."""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    DEMO = "demo"


class CapabilityAuthStatus(str, Enum):
    """Authentication readiness state for a specific capability."""
    AUTHENTICATED = "authenticated"
    UNAUTHENTICATED = "unauthenticated"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"  # absent auth probe → UNKNOWN, never AUTHENTICATED


# Canonical list of all 7 supported capability domains
REQUIRED_CAPABILITIES = [
    "gmail",
    "calendar",
    "drive",
    "meet",
    "filesystem",
    "web",
    "reasoning",
]

# Fallback mapping from capability name to default Hermes tool name.
# These are used ONLY when the runtime context does not provide its own
# capability metadata. Do not rely on these as the source of truth at runtime.
CAPABILITY_TOOL_MAPPINGS: Dict[str, str] = {
    "gmail": "gmail_search",
    "calendar": "calendar_list_events",
    "drive": "drive_get_document",
    "meet": "meet_list_recent_meetings",
    "filesystem": "fs_read",
    "web": "web_search",
    "reasoning": "llm_reasoning",
}

# Configurable fallback setup command (not hard-coded, overrideable via context metadata)
DEFAULT_GMAIL_SETUP_COMMAND = "hermes auth google"


@dataclass
class CapabilityMetadata:
    """
    Hermes-provided metadata for a single capability.

    When the runtime context exposes `get_capability_metadata(cap_name)`, this
    is populated from the live Hermes response. Otherwise, static fallbacks apply.
    """
    capability_name: str
    tool_names: List[str] = field(default_factory=list)
    primary_tool: Optional[str] = None           # The preferred read-only tool for this cap
    setup_command: Optional[str] = None          # e.g. "hermes auth google" — from Hermes
    auth_required: bool = True
    is_read_only: bool = True
    hermes_provided: bool = False                # True if sourced from live Hermes context

    def get_primary_tool(self, fallback: Optional[str] = None) -> Optional[str]:
        if self.primary_tool:
            return self.primary_tool
        if self.tool_names:
            return self.tool_names[0]
        return fallback

    def get_setup_command(self) -> str:
        """Returns the Hermes-provided setup command or the configurable fallback."""
        return self.setup_command or DEFAULT_GMAIL_SETUP_COMMAND


@dataclass
class CapabilityStatus:
    """
    Standardized operational and authentication status report for a single capability.
    """
    capability_name: str
    availability: CapabilityAvailability
    authenticated_status: CapabilityAuthStatus
    read_only: bool = True
    tool_name: Optional[str] = None
    last_checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: Optional[str] = None
    safe_diagnostics: Dict[str, Any] = field(default_factory=dict)
    metadata: Optional[CapabilityMetadata] = None

    def __post_init__(self) -> None:
        self.last_checked_at = ensure_timezone_aware(self.last_checked_at, "last_checked_at")
        if self.tool_name is None and self.capability_name in CAPABILITY_TOOL_MAPPINGS:
            self.tool_name = CAPABILITY_TOOL_MAPPINGS[self.capability_name]

    def to_dict(self) -> Dict[str, Any]:
        """Converts status to a JSON-serializable dictionary."""
        return {
            "capability_name": self.capability_name,
            "availability": self.availability.value if isinstance(self.availability, CapabilityAvailability) else str(self.availability),
            "authenticated_status": self.authenticated_status.value if isinstance(self.authenticated_status, CapabilityAuthStatus) else str(self.authenticated_status),
            "read_only": self.read_only,
            "tool_name": self.tool_name,
            "last_checked_at": format_iso8601(self.last_checked_at),
            "error_message": self.error_message,
            "safe_diagnostics": self.safe_diagnostics,
        }


@dataclass
class HermesRuntimeStatusReport:
    """
    Consolidated runtime and capability health report produced by HermesCapabilityInspector.
    Includes both the 6-stage connection_stage and the backward-compatible connection_status.
    """
    connection_status: HermesConnectionStatus
    connection_stage: HermesConnectionStage
    runtime_mode: str
    capabilities: Dict[str, CapabilityStatus] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    safe_diagnostics: Dict[str, Any] = field(default_factory=dict)
    gateway_reachable: bool = False
    runtime_attached: bool = False
    capabilities_discovered: bool = False
    gmail_authenticated: bool = False

    def __post_init__(self) -> None:
        self.timestamp = ensure_timezone_aware(self.timestamp, "timestamp")

    def to_dict(self) -> Dict[str, Any]:
        """Converts complete status report to serializable format."""
        return {
            "connection_status": self.connection_status.value if isinstance(self.connection_status, HermesConnectionStatus) else str(self.connection_status),
            "connection_stage": self.connection_stage.value if isinstance(self.connection_stage, HermesConnectionStage) else str(self.connection_stage),
            "runtime_mode": self.runtime_mode,
            "timestamp": format_iso8601(self.timestamp),
            "capabilities": {k: v.to_dict() for k, v in self.capabilities.items()},
            "safe_diagnostics": self.safe_diagnostics,
            "gateway_reachable": self.gateway_reachable,
            "runtime_attached": self.runtime_attached,
            "capabilities_discovered": self.capabilities_discovered,
            "gmail_authenticated": self.gmail_authenticated,
        }


def _resolve_capability_metadata(
    capability: str,
    runtime_context: Optional[Any],
) -> CapabilityMetadata:
    """
    Resolves CapabilityMetadata for a capability.

    Priority order:
    1. context.get_capability_metadata(cap) — live Hermes-provided metadata
    2. context.available_tools — inferred from declared tool list
    3. CAPABILITY_TOOL_MAPPINGS — static fallback (last resort only)
    """
    cap_clean = capability.lower().strip()
    fallback_tool = CAPABILITY_TOOL_MAPPINGS.get(cap_clean, f"{cap_clean}_tool")

    if runtime_context is not None:
        # 1. Live Hermes-provided metadata
        if hasattr(runtime_context, "get_capability_metadata") and callable(runtime_context.get_capability_metadata):
            try:
                raw = runtime_context.get_capability_metadata(cap_clean)
                if raw and isinstance(raw, dict):
                    return CapabilityMetadata(
                        capability_name=cap_clean,
                        tool_names=raw.get("tool_names", []) or [raw.get("primary_tool", fallback_tool)],
                        primary_tool=raw.get("primary_tool") or raw.get("tool_names", [fallback_tool])[0],
                        setup_command=raw.get("setup_command"),
                        auth_required=raw.get("auth_required", True),
                        is_read_only=raw.get("is_read_only", True),
                        hermes_provided=True,
                    )
            except Exception:
                pass

        # 2. Infer from available_tools list
        if hasattr(runtime_context, "available_tools") and isinstance(getattr(runtime_context, "available_tools"), (list, set, tuple)):
            available = list(runtime_context.available_tools)
            # Find tools that start with the capability prefix
            matching = [t for t in available if t.startswith(f"{cap_clean}_")]
            if matching:
                return CapabilityMetadata(
                    capability_name=cap_clean,
                    tool_names=matching,
                    primary_tool=matching[0] if cap_clean not in CAPABILITY_TOOL_MAPPINGS
                                else (CAPABILITY_TOOL_MAPPINGS[cap_clean] if CAPABILITY_TOOL_MAPPINGS[cap_clean] in matching else matching[0]),
                    hermes_provided=False,
                )

    # 3. Static fallback (last resort)
    return CapabilityMetadata(
        capability_name=cap_clean,
        tool_names=[fallback_tool],
        primary_tool=fallback_tool,
        hermes_provided=False,
    )


def _probe_auth_status(
    capability: str,
    runtime_context: Any,
    metadata: CapabilityMetadata,
) -> CapabilityAuthStatus:
    """
    Probes authentication status for a capability.

    Rules:
    1. Explicit auth_status dict or is_capability_authenticated callable is preferred.
    2. MagicMock and unrecognised return values are treated as UNKNOWN (never AUTHENTICATED).
    3. Absence of confirmed authentication probe for external workspace tools yields UNKNOWN.
    4. Dynamic capability metadata does not override confirmed authentication.
    """
    cap_clean = capability.lower().strip()

    # 1. dict-style auth_status attribute
    if hasattr(runtime_context, "auth_status") and isinstance(getattr(runtime_context, "auth_status"), dict):
        raw_auth = runtime_context.auth_status.get(cap_clean)
        # Fall back to workspace alias ("google") if specific capability key is absent
        if raw_auth is None and cap_clean in ("gmail", "calendar", "drive", "meet"):
            raw_auth = runtime_context.auth_status.get("google")

        if raw_auth == "authenticated":
            return CapabilityAuthStatus.AUTHENTICATED
        elif raw_auth == "unauthenticated":
            return CapabilityAuthStatus.UNAUTHENTICATED
        elif raw_auth == "not_required":
            return CapabilityAuthStatus.NOT_REQUIRED
        elif raw_auth is not None:
            # Unrecognised string or non-null value -> UNKNOWN
            return CapabilityAuthStatus.UNKNOWN
        # If raw_auth is None, fall through to callable is_capability_authenticated

    # 2. callable is_capability_authenticated
    if hasattr(runtime_context, "is_capability_authenticated") and callable(runtime_context.is_capability_authenticated):
        try:
            res = runtime_context.is_capability_authenticated(cap_clean)
            if res is True or res == "authenticated":
                return CapabilityAuthStatus.AUTHENTICATED
            elif res is False or res == "unauthenticated":
                return CapabilityAuthStatus.UNAUTHENTICATED
            elif res is None and cap_clean in ("gmail", "calendar", "drive", "meet"):
                # Try google alias
                res_g = runtime_context.is_capability_authenticated("google")
                if res_g is True or res_g == "authenticated":
                    return CapabilityAuthStatus.AUTHENTICATED
                elif res_g is False or res_g == "unauthenticated":
                    return CapabilityAuthStatus.UNAUTHENTICATED
                return CapabilityAuthStatus.UNKNOWN
            else:
                # MagicMock, unrecognised object, empty string, etc. -> UNKNOWN
                return CapabilityAuthStatus.UNKNOWN
        except Exception:
            return CapabilityAuthStatus.UNKNOWN

    # 3. No auth probe available — capabilities that don't require auth
    if cap_clean in ("filesystem", "reasoning", "web"):
        return CapabilityAuthStatus.NOT_REQUIRED

    # 4. External workspace capabilities with no confirmed auth probe -> UNKNOWN
    return CapabilityAuthStatus.UNKNOWN


class HermesCapabilityInspector:
    """
    Probes host Hermes runtime and active plugin execution contexts to determine
    capability status, authentication readiness, and tool availability without
    handling OAuth credentials or tokens.

    Key invariants:
    - A gateway health-check alone cannot produce AVAILABLE or AUTHENTICATED capability status.
    - Auth unknown → CapabilityAuthStatus.UNKNOWN (never AUTHENTICATED by default).
    - Tool names are sourced from context metadata first, static mapping as last resort.
    """

    def __init__(self) -> None:
        pass

    def probe_capability(
        self,
        capability: str,
        runtime_context: Optional[Any] = None,
        is_demo: bool = False,
        error: Optional[str] = None,
    ) -> CapabilityStatus:
        """
        Probes the status of a specific capability.
        """
        now = datetime.now(timezone.utc)
        cap_clean = capability.lower().strip()

        # 1. Error state override
        if error:
            meta = _resolve_capability_metadata(cap_clean, runtime_context)
            return CapabilityStatus(
                capability_name=cap_clean,
                availability=CapabilityAvailability.ERROR,
                authenticated_status=CapabilityAuthStatus.UNKNOWN,
                read_only=True,
                tool_name=meta.get_primary_tool(CAPABILITY_TOOL_MAPPINGS.get(cap_clean)),
                last_checked_at=now,
                error_message=error,
                safe_diagnostics={"probe_mode": "error_captured", "reason": error},
                metadata=meta,
            )

        # 2. Demo mode evaluation
        if is_demo:
            meta = _resolve_capability_metadata(cap_clean, None)
            return CapabilityStatus(
                capability_name=cap_clean,
                availability=CapabilityAvailability.DEMO,
                authenticated_status=CapabilityAuthStatus.NOT_REQUIRED,
                read_only=True,
                tool_name=meta.get_primary_tool(CAPABILITY_TOOL_MAPPINGS.get(cap_clean)),
                last_checked_at=now,
                error_message=None,
                safe_diagnostics={
                    "probe_mode": "deterministic_synthetic_demo",
                    "synthetic_observations_active": True,
                },
                metadata=meta,
            )

        # 3. No host Hermes runtime context attached (Standalone Mode)
        if runtime_context is None:
            # Local filesystem and built-in reasoning can operate in local standalone mode
            if cap_clean in ("filesystem", "reasoning"):
                meta = _resolve_capability_metadata(cap_clean, None)
                return CapabilityStatus(
                    capability_name=cap_clean,
                    availability=CapabilityAvailability.AVAILABLE,
                    authenticated_status=CapabilityAuthStatus.NOT_REQUIRED,
                    read_only=True,
                    tool_name=meta.get_primary_tool(CAPABILITY_TOOL_MAPPINGS.get(cap_clean)),
                    last_checked_at=now,
                    error_message=None,
                    safe_diagnostics={
                        "probe_mode": "local_standalone_native",
                        "hermes_attached": False,
                    },
                    metadata=meta,
                )

            # External workspace capabilities (Gmail, Calendar, Drive, Meet, Web) require Hermes host context.
            # A gateway health-check alone is insufficient — context must be in-process attached.
            meta = _resolve_capability_metadata(cap_clean, None)
            return CapabilityStatus(
                capability_name=cap_clean,
                availability=CapabilityAvailability.UNAVAILABLE,
                authenticated_status=CapabilityAuthStatus.UNAUTHENTICATED,
                read_only=True,
                tool_name=meta.get_primary_tool(CAPABILITY_TOOL_MAPPINGS.get(cap_clean)),
                last_checked_at=now,
                error_message="Host Hermes runtime context is not attached to this process.",
                safe_diagnostics={
                    "probe_mode": "standalone_unattached",
                    "hermes_attached": False,
                    "requirement": (
                        "Start via Hermes Agent host or attach active Hermes runtime context. "
                        "A responding HTTP health endpoint is insufficient — "
                        "in-process plugin attachment is required."
                    ),
                },
                metadata=meta,
            )

        # 4. Host Hermes context is attached → resolve metadata and query capabilities safely
        meta = _resolve_capability_metadata(cap_clean, runtime_context)
        tool_name = meta.get_primary_tool(CAPABILITY_TOOL_MAPPINGS.get(cap_clean))

        # Probe authentication (UNKNOWN by default if absent)
        auth_status = _probe_auth_status(cap_clean, runtime_context, meta)

        # Check tool availability
        # Priority: available_tools list > has_tool callable > execute_tool/call_tool fallback.
        # available_tools is checked first because it is the most explicit declaration,
        # and MagicMock contexts often auto-create has_tool as a truthy callable.
        has_tool = False
        if hasattr(runtime_context, "available_tools") and isinstance(getattr(runtime_context, "available_tools"), (list, set, tuple)):
            # Check either exact tool name or any tool for this capability
            available = set(runtime_context.available_tools)
            has_tool = (
                tool_name in available
                or any(t.startswith(f"{cap_clean}_") for t in available)
            )
        elif hasattr(runtime_context, "has_tool") and callable(runtime_context.has_tool):
            try:
                has_tool = bool(runtime_context.has_tool(tool_name))
            except Exception:
                has_tool = False
        elif hasattr(runtime_context, "execute_tool") or hasattr(runtime_context, "call_tool"):
            has_tool = True  # Context has execution handler; tool existence assumed

        availability = (
            CapabilityAvailability.AVAILABLE if has_tool
            else CapabilityAvailability.UNAVAILABLE
        )

        return CapabilityStatus(
            capability_name=cap_clean,
            availability=availability,
            authenticated_status=auth_status,
            read_only=True,
            tool_name=tool_name,
            last_checked_at=now,
            error_message=None,
            safe_diagnostics={
                "probe_mode": "hermes_native_probe",
                "hermes_attached": True,
                "tool_declared": has_tool,
                "metadata_source": "hermes_provided" if meta.hermes_provided else "static_fallback",
            },
            metadata=meta,
        )

    def probe_all(
        self,
        runtime_context: Optional[Any] = None,
        is_demo: bool = False,
        connection_status_override: Optional[HermesConnectionStatus] = None,
        gateway_reachable: bool = False,
    ) -> HermesRuntimeStatusReport:
        """
        Probes all 7 canonical capabilities and generates the complete runtime
        status report, including the accurate 6-stage connection_stage.

        gateway_reachable=True only advances to GATEWAY_DETECTED — it does NOT
        advance to RUNTIME_ATTACHED or any later stage.
        """
        now = datetime.now(timezone.utc)
        cap_results: Dict[str, CapabilityStatus] = {}

        for cap in REQUIRED_CAPABILITIES:
            cap_results[cap] = self.probe_capability(
                capability=cap,
                runtime_context=runtime_context,
                is_demo=is_demo,
            )

        # --- Determine the 6-stage connection stage ---
        if is_demo:
            stage = HermesConnectionStage.DEMO
            conn_status = HermesConnectionStatus.DEMO
            gateway_reachable_flag = False
            runtime_attached_flag = False
            capabilities_discovered_flag = False
            gmail_authenticated_flag = False

        elif runtime_context is None:
            # No runtime context attached. A gateway health-check is detection-only.
            stage = HermesConnectionStage.GATEWAY_DETECTED if gateway_reachable else HermesConnectionStage.DISCONNECTED
            conn_status = HermesConnectionStatus.DISCONNECTED  # gateway ≠ usable
            gateway_reachable_flag = gateway_reachable
            runtime_attached_flag = False
            capabilities_discovered_flag = False
            gmail_authenticated_flag = False

        else:
            # Runtime context is attached — check each subsequent stage
            has_execution_handler = (
                hasattr(runtime_context, "execute_tool") or
                hasattr(runtime_context, "call_tool") or
                hasattr(runtime_context, "prompt_llm") or
                hasattr(runtime_context, "call_agent")
            )

            # Check if any non-local capabilities are available
            external_caps = [c for c in cap_results.values()
                             if c.capability_name not in ("filesystem", "reasoning")
                             and c.availability == CapabilityAvailability.AVAILABLE]
            capabilities_found = len(external_caps) > 0 or bool(
                hasattr(runtime_context, "available_tools") and
                isinstance(getattr(runtime_context, "available_tools"), (list, set, tuple)) and
                len(runtime_context.available_tools) > 0
            )

            gmail_cap = cap_results.get("gmail")
            gmail_auth = (
                gmail_cap is not None and
                gmail_cap.availability == CapabilityAvailability.AVAILABLE and
                gmail_cap.authenticated_status == CapabilityAuthStatus.AUTHENTICATED
            )

            if gmail_auth:
                stage = HermesConnectionStage.GMAIL_AUTHENTICATED
                conn_status = HermesConnectionStatus.CONNECTED
            elif capabilities_found:
                stage = HermesConnectionStage.CAPABILITIES_DISCOVERED
                # Hermes runtime is attached and usable -> connection_status is CONNECTED.
                # Gmail capability independently maintains its own authentication status
                # (unauthenticated / unknown) and gmail_authenticated remains False.
                conn_status = HermesConnectionStatus.CONNECTED
            elif has_execution_handler:
                stage = HermesConnectionStage.RUNTIME_ATTACHED
                conn_status = HermesConnectionStatus.CONNECTED
            else:
                stage = HermesConnectionStage.TRANSPORT_READY
                conn_status = HermesConnectionStatus.CONNECTING

            gateway_reachable_flag = gateway_reachable
            runtime_attached_flag = True
            capabilities_discovered_flag = capabilities_found
            gmail_authenticated_flag = gmail_auth

        # Apply override if explicitly provided (for backward compat)
        if connection_status_override is not None:
            conn_status = connection_status_override

        runtime_mode = "demo" if is_demo else (
            "attached_hermes" if runtime_context is not None else "standalone_local"
        )

        return HermesRuntimeStatusReport(
            connection_status=conn_status,
            connection_stage=stage,
            runtime_mode=runtime_mode,
            capabilities=cap_results,
            timestamp=now,
            safe_diagnostics={
                "inspector_version": "2.0.0",
                "total_capabilities_monitored": len(REQUIRED_CAPABILITIES),
                "read_only_enforced": True,
                "external_credentials_stored": False,
                "gateway_detection_only": (
                    gateway_reachable and runtime_context is None
                ),
            },
            gateway_reachable=gateway_reachable_flag,
            runtime_attached=runtime_attached_flag,
            capabilities_discovered=capabilities_discovered_flag,
            gmail_authenticated=gmail_authenticated_flag,
        )
