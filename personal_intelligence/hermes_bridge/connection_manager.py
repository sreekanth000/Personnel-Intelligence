"""
Hermes Connection Manager for Personal Intelligence.

Provides runtime detection, lifecycle connection, dynamic capability discovery,
and health inspection between Personal Intelligence and the host Hermes Agent runtime.

Connection Stage Model (strictly sequential):
  disconnected        — No Hermes runtime detectable.
  gateway_detected    — An HTTP health endpoint responded. DETECTION ONLY.
                        A responding health endpoint DOES NOT mean Hermes is usable,
                        tools are invocable, or capabilities are authenticated.
                        No stable gateway HTTP execution API exists.
  transport_ready     — In-process runtime context provided; transport confirmed.
  runtime_attached    — Runtime context confirmed operational (has execution handler).
  capabilities_discovered — Hermes declared available tools; ≥1 capability reachable.
  gmail_authenticated — Gmail capability confirmed authenticated in host Hermes.

Guarantees:
- A gateway health-check alone NEVER advances beyond gateway_detected.
- Never manages OAuth tokens, refresh tokens, or client credentials in Personal Intelligence.
- Auth setup command sourced from Hermes-provided context metadata when available,
  with a configurable constant fallback — NOT a hard-coded string in logic.
- All external workspace tools (Gmail, Calendar, Drive, Meet) operate strictly read-only.
- Clear, actionable instructions when Hermes is offline or disconnected.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
import os
import shutil
import socket
from typing import Any, Dict, Optional
import urllib.error
import urllib.request

from personal_intelligence.hermes_bridge.capabilities import (
    DEFAULT_GMAIL_SETUP_COMMAND,
    REQUIRED_CAPABILITIES,
    CapabilityAuthStatus,
    CapabilityAvailability,
    HermesCapabilityInspector,
    HermesConnectionStatus,
    HermesConnectionStage,
    HermesRuntimeStatusReport,
    _resolve_capability_metadata,
)
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesRuntimeBridge,
    get_active_hermes_context,
    set_active_hermes_context,
)

logger = logging.getLogger(__name__)

DEFAULT_HERMES_GATEWAY_URL = "http://127.0.0.1:8642"


class HermesFailureCategory(str, Enum):
    """
    Standardized safe failure categories for Hermes connection diagnostics.
    Never exposes private credentials, tokens, email contents, or stack traces.
    """
    NONE = "none"
    CONNECTION_REFUSED = "connection_refused"
    TIMEOUT = "timeout"
    UNSUPPORTED_ENDPOINT = "unsupported_endpoint"
    INVALID_RESPONSE = "invalid_response"
    RUNTIME_NOT_ATTACHED = "runtime_not_attached"
    CAPABILITY_NOT_DECLARED = "capability_not_declared"
    AUTH_UNKNOWN = "auth_unknown"
    UNAUTHENTICATED = "unauthenticated"


RECOMMENDED_NEXT_ACTIONS: Dict[str, str] = {
    HermesFailureCategory.CONNECTION_REFUSED.value: (
        "Start Hermes locally with 'hermes agent start' or ensure the daemon is running on the configured port."
    ),
    HermesFailureCategory.TIMEOUT.value: (
        "Hermes gateway timed out. Check if Hermes is overloaded or unresponsive and restart the daemon."
    ),
    HermesFailureCategory.UNSUPPORTED_ENDPOINT.value: (
        "Configured Hermes gateway endpoint returned 404/501. Verify the Hermes gateway version and endpoint path."
    ),
    HermesFailureCategory.INVALID_RESPONSE.value: (
        "Received an unexpected response from Hermes gateway. Verify daemon health and gateway compatibility."
    ),
    HermesFailureCategory.RUNTIME_NOT_ATTACHED.value: (
        "A Hermes gateway endpoint was detected, but no in-process runtime is attached. Attach the Hermes plugin context to execute tools."
    ),
    HermesFailureCategory.CAPABILITY_NOT_DECLARED.value: (
        "The required capability is not declared in Hermes available tools. Enable it in your Hermes configuration."
    ),
    HermesFailureCategory.AUTH_UNKNOWN.value: (
        "Hermes returned an unverified authentication status. Open Hermes and verify capability credentials."
    ),
    HermesFailureCategory.UNAUTHENTICATED.value: (
        "Open Hermes and connect/configure its capability credentials, then refresh this page."
    ),
}


def get_failure_recommended_action(category: Optional[str]) -> Optional[str]:
    """Returns a sanitized plain-language recommended next action for a given failure category."""
    if not category:
        return None
    return RECOMMENDED_NEXT_ACTIONS.get(category)


@dataclass
class HermesInstallationInfo:
    """Detection status of Hermes binary or local runtime packages."""
    is_installed: bool
    binary_path: Optional[str] = None
    detection_mechanism: str = "none"
    version_info: Optional[str] = None


@dataclass
class HermesReachabilityInfo:
    """
    Reachability status of the local Hermes daemon or in-process context.

    IMPORTANT: mechanism='gateway' means an HTTP health endpoint responded.
    This is DETECTION ONLY. It does not mean Hermes is attached, tools are
    invocable, or capabilities are usable.
    """
    is_reachable: bool
    mechanism: str  # 'in_process', 'gateway' (detection-only), 'none'
    gateway_url: Optional[str] = None
    details: Optional[str] = None
    execution_capable: bool = False
    failure_category: Optional[str] = None
    recommended_action: Optional[str] = None


@dataclass
class HermesHealthReport:
    """
    Consolidated diagnostic report of Hermes connection, readiness, and capabilities.

    connection_stage is the authoritative status. connection_status is kept for
    backward compatibility but MUST be derived from connection_stage.

    Key separate flags:
      gateway_reachable       — HTTP health endpoint responded (detection-only).
      runtime_attached        — In-process runtime context is bound (execution-capable).
      capabilities_discovered — Tools declared by Hermes context.
      gmail_authenticated     — Gmail confirmed authenticated in host Hermes.
    """
    connection_status: HermesConnectionStatus
    connection_stage: HermesConnectionStage
    is_installed: bool
    is_reachable: bool
    reachability_mechanism: str
    active_mode: str
    capabilities: Dict[str, Dict[str, Any]]
    actionable_instructions: Optional[str] = None
    gmail_auth_status: str = "unknown"
    failure_category: Optional[str] = None
    recommended_action: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    safe_diagnostics: Dict[str, Any] = field(default_factory=dict)
    gateway_reachable: bool = False
    runtime_attached: bool = False
    capabilities_discovered: bool = False
    gmail_authenticated: bool = False


class HermesConnectionManager:
    """
    Manager responsible for detecting Hermes, attaching runtime contexts,
    discovering capabilities dynamically, and providing health inspection.

    Critical invariant: gateway_detected ≠ runtime_attached.
    A responding HTTP health endpoint does not grant the ability to invoke
    Hermes tools. Only an in-process plugin attachment (bind_context) does.
    """

    def __init__(
        self,
        bridge: Optional[Any] = None,
        gateway_url: str = DEFAULT_HERMES_GATEWAY_URL,
    ) -> None:
        if bridge is not None and hasattr(bridge, "bridge") and isinstance(getattr(bridge, "bridge"), HermesRuntimeBridge):
            self.bridge = bridge.bridge
        else:
            self.bridge = bridge or HermesRuntimeBridge()
        self.gateway_url = gateway_url
        self.inspector = HermesCapabilityInspector()

    # -------------------------------------------------------------------------
    # 1. Detection: Installation & Reachability
    # -------------------------------------------------------------------------
    def detect_installation(self) -> HermesInstallationInfo:
        """
        Detects whether Hermes is installed on the local system.
        Checks PATH for the 'hermes' binary or environment hints.
        """
        # 1. Check system PATH
        binary = shutil.which("hermes")
        if binary:
            return HermesInstallationInfo(
                is_installed=True,
                binary_path=binary,
                detection_mechanism="system_path",
            )

        # 2. Check standard user configuration or virtualenv paths
        home = os.path.expanduser("~")
        candidate_paths = [
            os.path.join(home, ".hermes", "bin", "hermes"),
            os.path.join(home, ".hermes", "bin", "hermes.exe"),
            os.path.join(home, "AppData", "Roaming", "Python", "Scripts", "hermes.exe"),
            os.path.join(home, ".local", "bin", "hermes"),
        ]
        for path in candidate_paths:
            if os.path.exists(path):
                return HermesInstallationInfo(
                    is_installed=True,
                    binary_path=path,
                    detection_mechanism="candidate_directory",
                )

        # 3. Check if in-process context is attached despite binary absent from PATH
        if self.bridge.runtime_context is not None or get_active_hermes_context() is not None:
            return HermesInstallationInfo(
                is_installed=True,
                binary_path=None,
                detection_mechanism="in_process_runtime_attached",
            )

        return HermesInstallationInfo(
            is_installed=False,
            binary_path=None,
            detection_mechanism="not_found",
        )

    def check_reachability(self, gateway_url: Optional[str] = None) -> HermesReachabilityInfo:
        """
        Checks whether Hermes is reachable via active in-process context or HTTP probe.

        CRITICAL: mechanism='gateway' is DETECTION ONLY.
        A responding HTTP health endpoint does NOT mean Hermes runtime is attached,
        tools are available, or capabilities are authenticated.
        Only mechanism='in_process' is execution_capable=True.
        """
        # 1. In-process attached runtime context is the ONLY execution-capable path
        if self.bridge.runtime_context is not None or get_active_hermes_context() is not None:
            return HermesReachabilityInfo(
                is_reachable=True,
                mechanism="in_process",
                details="Active in-process Hermes runtime context is bound.",
                execution_capable=True,
                failure_category=None,
                recommended_action=None,
            )

        # 2. HTTP health endpoint probe — DETECTION ONLY, NOT execution-capable
        target_url = (gateway_url or self.gateway_url).rstrip("/")
        try:
            req = urllib.request.Request(
                f"{target_url}/v1/health",
                headers={"User-Agent": "Personal-Intelligence-ConnectionManager/1.0"},
            )
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return HermesReachabilityInfo(
                        is_reachable=True,
                        mechanism="gateway",
                        gateway_url=target_url,
                        details=(
                            f"HTTP health endpoint at {target_url} responded. "
                            "DETECTION ONLY — runtime context is not attached. "
                            "No stable gateway execution API exists; "
                            "in-process plugin attachment is required to invoke tools."
                        ),
                        execution_capable=False,
                        failure_category=HermesFailureCategory.RUNTIME_NOT_ATTACHED.value,
                        recommended_action=get_failure_recommended_action(HermesFailureCategory.RUNTIME_NOT_ATTACHED.value),
                    )
                else:
                    return HermesReachabilityInfo(
                        is_reachable=False,
                        mechanism="none",
                        gateway_url=target_url,
                        details=f"Gateway health probe returned unexpected HTTP status {resp.status}.",
                        execution_capable=False,
                        failure_category=HermesFailureCategory.INVALID_RESPONSE.value,
                        recommended_action=get_failure_recommended_action(HermesFailureCategory.INVALID_RESPONSE.value),
                    )
        except urllib.error.HTTPError as ex:
            if ex.code in (404, 501):
                fail_cat = HermesFailureCategory.UNSUPPORTED_ENDPOINT.value
            else:
                fail_cat = HermesFailureCategory.INVALID_RESPONSE.value
            return HermesReachabilityInfo(
                is_reachable=False,
                mechanism="none",
                gateway_url=target_url,
                details=f"HTTP probe returned status {ex.code}.",
                execution_capable=False,
                failure_category=fail_cat,
                recommended_action=get_failure_recommended_action(fail_cat),
            )
        except urllib.error.URLError as ex:
            reason_str = str(ex.reason).lower()
            if isinstance(ex.reason, (TimeoutError, socket.timeout)) or "timed out" in reason_str:
                fail_cat = HermesFailureCategory.TIMEOUT.value
            elif (
                isinstance(ex.reason, ConnectionRefusedError)
                or "connection refused" in reason_str
                or "10061" in reason_str
                or "111" in reason_str
            ):
                fail_cat = HermesFailureCategory.CONNECTION_REFUSED.value
            else:
                fail_cat = HermesFailureCategory.CONNECTION_REFUSED.value
            return HermesReachabilityInfo(
                is_reachable=False,
                mechanism="none",
                gateway_url=target_url,
                details=f"Gateway network probe error: {ex.reason.__class__.__name__}.",
                execution_capable=False,
                failure_category=fail_cat,
                recommended_action=get_failure_recommended_action(fail_cat),
            )
        except (TimeoutError, socket.timeout):
            fail_cat = HermesFailureCategory.TIMEOUT.value
            return HermesReachabilityInfo(
                is_reachable=False,
                mechanism="none",
                gateway_url=target_url,
                details="Gateway reachability probe timed out.",
                execution_capable=False,
                failure_category=fail_cat,
                recommended_action=get_failure_recommended_action(fail_cat),
            )
        except Exception as ex:
            fail_cat = HermesFailureCategory.INVALID_RESPONSE.value
            return HermesReachabilityInfo(
                is_reachable=False,
                mechanism="none",
                gateway_url=target_url,
                details=f"Reachability probe failed safely: {ex.__class__.__name__}.",
                execution_capable=False,
                failure_category=fail_cat,
                recommended_action=get_failure_recommended_action(fail_cat),
            )

    # -------------------------------------------------------------------------
    # 2. Connection Lifecycle
    # -------------------------------------------------------------------------
    def connect(
        self,
        runtime_context: Optional[Any] = None,
        is_demo: bool = False,
    ) -> HermesRuntimeStatusReport:
        """
        Connects Personal Intelligence to the active Hermes runtime context.
        If runtime_context is provided, binds it to the bridge.

        IMPORTANT: Without a runtime_context, this cannot advance beyond
        gateway_detected even if the HTTP health endpoint is reachable.
        """
        if is_demo:
            self.bridge.execution_mode = HermesBridgeExecutionMode.DEMO
        elif runtime_context is not None:
            set_active_hermes_context(runtime_context)
            self.bridge.bind_context(runtime_context)
            self.bridge.execution_mode = HermesBridgeExecutionMode.LIVE

        reach = self.check_reachability()
        report = self.discover_capabilities(
            is_demo=is_demo,
            gateway_reachable=reach.is_reachable and reach.mechanism == "gateway",
        )
        logger.info(
            "HermesConnectionManager.connect — Stage: %s, Mode: %s, Execution-Capable: %s",
            report.connection_stage.value,
            report.runtime_mode,
            reach.execution_capable,
        )
        return report

    def disconnect(self) -> HermesRuntimeStatusReport:
        """
        Disconnects the active runtime context from Personal Intelligence.
        """
        set_active_hermes_context(None)
        self.bridge.bind_context(None)
        return self.discover_capabilities(is_demo=False)

    # -------------------------------------------------------------------------
    # 3. Dynamic Capability Discovery
    # -------------------------------------------------------------------------
    def discover_capabilities(
        self,
        is_demo: Optional[bool] = None,
        gateway_reachable: bool = False,
    ) -> HermesRuntimeStatusReport:
        """
        Discovers all available Hermes tools and capabilities dynamically.

        gateway_reachable=True only advances stage to GATEWAY_DETECTED.
        It does NOT advance to RUNTIME_ATTACHED or any later stage.
        """
        demo_flag = (self.bridge.execution_mode == HermesBridgeExecutionMode.DEMO) if is_demo is None else is_demo
        return self.inspector.probe_all(
            runtime_context=self.bridge.runtime_context,
            is_demo=demo_flag,
            gateway_reachable=gateway_reachable,
        )

    # -------------------------------------------------------------------------
    # 4. Actionable Instructions & Setup Guides
    # -------------------------------------------------------------------------
    def get_launch_instructions(self) -> str:
        """
        Provides clear, actionable terminal instructions for launching Hermes locally.
        """
        inst = self.detect_installation()
        if not inst.is_installed:
            return (
                "Hermes is not detected on your system.\n\n"
                "To install Hermes:\n"
                "  1. Run: pip install hermes-agent\n"
                "  2. Or visit: https://github.com/NousResearch/Hermes-Function-Calling\n\n"
                "To start Hermes locally:\n"
                "  hermes agent start\n"
                "or run Personal Intelligence inside a Hermes agent host environment."
            )

        binary = inst.binary_path or "hermes"
        return (
            f"Hermes is installed ({inst.detection_mechanism}) but not running or attached.\n\n"
            f"To launch Hermes:\n"
            f"  {binary} agent start\n\n"
            "Then click 'Connect Hermes' in the Personal Intelligence dashboard."
        )

    def get_gmail_setup_instructions(self) -> Dict[str, Any]:
        """
        Provides Hermes Google Workspace setup instructions.

        The setup command is sourced from:
        1. Runtime context capability metadata (Hermes-provided) — official host command.
        2. DEFAULT_GMAIL_SETUP_COMMAND constant — clearly labelled as example/fallback.

        When no live command is provided by Hermes, instructs user to configure
        Gmail in Hermes directly without claiming an unsupported command is official.
        """
        ctx = self.bridge.runtime_context
        setup_cmd = None
        metadata_source = "example_fallback"

        if ctx is not None:
            meta = _resolve_capability_metadata("gmail", ctx)
            if meta.hermes_provided and meta.setup_command:
                setup_cmd = meta.setup_command
                metadata_source = "hermes_provided"

        if metadata_source == "hermes_provided" and setup_cmd:
            instruction = (
                "Gmail authentication is owned and managed exclusively by your host Hermes Agent.\n\n"
                "To connect your Google Workspace account in Hermes:\n"
                "  1. Open your terminal\n"
                f"  2. Run: {setup_cmd}\n"
                "  3. Follow the browser prompt in Hermes to grant read-only access to Gmail, Calendar, and Drive.\n"
                "  4. Return here and click 'Test Sources' or 'Connect Hermes'.\n\n"
                "Note: Personal Intelligence never asks for, stores, or refreshes Google OAuth tokens."
            )
            cmd_label = "Hermes Host Setup Command"
        else:
            setup_cmd = DEFAULT_GMAIL_SETUP_COMMAND
            instruction = (
                "Gmail authentication is owned and managed exclusively by your host Hermes Agent.\n\n"
                "Open Hermes and connect/configure its Gmail capability, then refresh this page.\n\n"
                f"(Example / environment-specific command: {setup_cmd})\n\n"
                "Note: Personal Intelligence never asks for, stores, or refreshes Google OAuth tokens."
            )
            cmd_label = "example / environment-specific command"

        return {
            "title": "Connect Gmail in Hermes",
            "instruction": instruction,
            "command": setup_cmd,
            "command_source": metadata_source,
            "command_label": cmd_label,
            "is_official_command": metadata_source == "hermes_provided",
            "read_only_enforced": True,
            "zero_oauth_guarantee": True,
        }

    # -------------------------------------------------------------------------
    # 5. Consolidated Health Report
    # -------------------------------------------------------------------------
    def check_health(self) -> HermesHealthReport:
        """
        Generates a consolidated diagnostic health report for the dashboard and API.

        Reports gateway_reachable, runtime_attached, capabilities_discovered, and
        gmail_authenticated as separate flags so callers understand the exact stage.
        """
        inst = self.detect_installation()
        reach = self.check_reachability()
        cap_report = self.discover_capabilities(
            gateway_reachable=reach.is_reachable and reach.mechanism == "gateway",
        )

        # Check Gmail status specifically
        gmail_cap = cap_report.capabilities.get("gmail")
        gmail_auth_str = "unknown"
        if gmail_cap:
            gmail_auth_str = gmail_cap.authenticated_status.value

        # Generate contextual instructions based on stage
        instructions = None
        stage = cap_report.connection_stage
        if stage in (HermesConnectionStage.DISCONNECTED, HermesConnectionStage.GATEWAY_DETECTED):
            instructions = self.get_launch_instructions()
            if stage == HermesConnectionStage.GATEWAY_DETECTED:
                instructions = (
                    "A Hermes gateway endpoint was detected, but no runtime context is attached.\n"
                    "Personal Intelligence requires in-process plugin attachment to invoke tools.\n\n"
                    + instructions
                )
        elif stage in (HermesConnectionStage.RUNTIME_ATTACHED, HermesConnectionStage.TRANSPORT_READY):
            instructions = (
                "Hermes runtime context is attached. Capability discovery is in progress."
            )
        elif stage == HermesConnectionStage.CAPABILITIES_DISCOVERED and gmail_auth_str != "authenticated":
            instructions = self.get_gmail_setup_instructions()["instruction"]
        elif stage == HermesConnectionStage.GMAIL_AUTHENTICATED:
            instructions = None  # Fully operational — no instructions needed

        # Compute diagnostic failure category & recommended next action
        failure_cat: Optional[str] = None
        rec_action: Optional[str] = None

        if cap_report.runtime_mode == "demo":
            failure_cat = None
            rec_action = None
        elif stage == HermesConnectionStage.DISCONNECTED:
            failure_cat = reach.failure_category or HermesFailureCategory.CONNECTION_REFUSED.value
            rec_action = reach.recommended_action or get_failure_recommended_action(failure_cat)
        elif stage == HermesConnectionStage.GATEWAY_DETECTED:
            failure_cat = HermesFailureCategory.RUNTIME_NOT_ATTACHED.value
            rec_action = get_failure_recommended_action(failure_cat)
        elif stage in (HermesConnectionStage.TRANSPORT_READY, HermesConnectionStage.RUNTIME_ATTACHED):
            has_avail = any(
                c.availability == CapabilityAvailability.AVAILABLE
                for c in cap_report.capabilities.values()
            )
            if not has_avail or not cap_report.capabilities_discovered:
                failure_cat = HermesFailureCategory.CAPABILITY_NOT_DECLARED.value
                rec_action = get_failure_recommended_action(failure_cat)
        elif stage == HermesConnectionStage.CAPABILITIES_DISCOVERED:
            if gmail_cap and gmail_cap.availability == CapabilityAvailability.UNAVAILABLE:
                failure_cat = HermesFailureCategory.CAPABILITY_NOT_DECLARED.value
                rec_action = get_failure_recommended_action(failure_cat)
            elif gmail_auth_str == "unauthenticated":
                failure_cat = HermesFailureCategory.UNAUTHENTICATED.value
                rec_action = get_failure_recommended_action(failure_cat)
            elif gmail_auth_str == "unknown":
                failure_cat = HermesFailureCategory.AUTH_UNKNOWN.value
                rec_action = get_failure_recommended_action(failure_cat)
        elif stage == HermesConnectionStage.GMAIL_AUTHENTICATED:
            failure_cat = None
            rec_action = None

        serialized_caps = {
            k: asdict(v) if hasattr(v, "__dataclass_fields__") else v
            for k, v in cap_report.capabilities.items()
        }
        # Strip non-serialisable metadata field and annotate diagnostics
        for c_name, cap_dict in serialized_caps.items():
            if isinstance(cap_dict, dict):
                cap_dict.pop("metadata", None)
                if "last_checked_at" in cap_dict and isinstance(cap_dict["last_checked_at"], datetime):
                    cap_dict["last_checked_at"] = cap_dict["last_checked_at"].isoformat()

                # Add safe capability-specific failure category
                c_avail = cap_dict.get("availability")
                c_auth = cap_dict.get("authenticated_status")
                if c_avail == "unavailable":
                    cap_dict["failure_category"] = HermesFailureCategory.CAPABILITY_NOT_DECLARED.value
                    cap_dict["recommended_action"] = get_failure_recommended_action(HermesFailureCategory.CAPABILITY_NOT_DECLARED.value)
                elif c_auth == "unauthenticated":
                    cap_dict["failure_category"] = HermesFailureCategory.UNAUTHENTICATED.value
                    cap_dict["recommended_action"] = get_failure_recommended_action(HermesFailureCategory.UNAUTHENTICATED.value)
                elif c_auth == "unknown":
                    cap_dict["failure_category"] = HermesFailureCategory.AUTH_UNKNOWN.value
                    cap_dict["recommended_action"] = get_failure_recommended_action(HermesFailureCategory.AUTH_UNKNOWN.value)
                else:
                    cap_dict["failure_category"] = None
                    cap_dict["recommended_action"] = None

        return HermesHealthReport(
            connection_status=cap_report.connection_status,
            connection_stage=stage,
            is_installed=inst.is_installed,
            is_reachable=reach.is_reachable,
            reachability_mechanism=reach.mechanism,
            active_mode=cap_report.runtime_mode,
            capabilities=serialized_caps,
            actionable_instructions=instructions,
            gmail_auth_status=gmail_auth_str,
            failure_category=failure_cat,
            recommended_action=rec_action,
            safe_diagnostics={
                "inspector_version": "2.0.0",
                "total_capabilities": len(REQUIRED_CAPABILITIES),
                "read_only_enforced": True,
                "zero_oauth_stored": True,
                "execution_capable": reach.execution_capable,
                "gateway_detection_only": (
                    reach.is_reachable and reach.mechanism == "gateway"
                ),
                "failure_category": failure_cat,
                "recommended_action": rec_action,
            },
            gateway_reachable=cap_report.gateway_reachable,
            runtime_attached=cap_report.runtime_attached,
            capabilities_discovered=cap_report.capabilities_discovered,
            gmail_authenticated=cap_report.gmail_authenticated,
        )
