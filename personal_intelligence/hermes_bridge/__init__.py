"""
Hermes Agent integration bridge, reasoning workflows, and plugin tools.
"""

from personal_intelligence.hermes_bridge.client import (
    HermesBridgeError,
    HermesBridgeExecutionMode,
    HermesClient,
    HermesExecutionMode,
    HermesInvocationRequest,
    HermesInvocationResponse,
    HermesRuntimeBridge,
    InvalidResultError,
    MissingCapabilityError,
    MissingRuntimeContextError,
    ToolExecutionFailureError,
    UnauthenticatedCapabilityError,
    get_active_hermes_context,
    set_active_hermes_context,
)
from personal_intelligence.security.guard import UnauthorizedWriteOperationError
from personal_intelligence.hermes_bridge.connection_manager import (
    HermesConnectionManager,
    HermesHealthReport,
    HermesInstallationInfo,
    HermesReachabilityInfo,
)
from personal_intelligence.hermes_bridge.gmail_adapter import (
    ALLOWED_READ_ONLY_GMAIL_TOOLS,
    PROHIBITED_MUTATION_GMAIL_TOOLS,
    GmailCapabilityAdapter,
    GmailCapabilityRequest,
    HermesGmailResult,
)
from personal_intelligence.hermes_bridge.capabilities import (
    CAPABILITY_TOOL_MAPPINGS,
    REQUIRED_CAPABILITIES,
    CapabilityAuthStatus,
    CapabilityAvailability,
    CapabilityStatus,
    HermesCapabilityInspector,
    HermesConnectionStatus,
    HermesRuntimeStatusReport,
)
from personal_intelligence.hermes_bridge.investigation import (
    BoundedInvestigationWorkflow,
    InformationGapRequest,
    InvestigationResult,
    InvestigationTask,
    validate_investigation_result,
)
from personal_intelligence.hermes_bridge.novelty_orchestrator import (
    NoveltyReasoningOrchestrator,
    NoveltyReasoningPipelineResult,
)
from personal_intelligence.hermes_bridge.reasoning import (
    ActionabilityLevel,
    BoundedReasoningRequest,
    EvidenceStrength,
    NovelReasoningSynthesis,
    NovelReasoningWorkflowResult,
    ReasoningWorkflow,
    ReasoningWorkflowResult,
    RelevanceLevel,
    StructuredReasoningSynthesis,
    UrgencyLevel,
    validate_novel_reasoning_synthesis,
    validate_reasoning_synthesis,
)

from personal_intelligence.hermes_bridge.situation_investigation import (
    BoundedInvestigationRequest,
    CrossSourceEvidenceBundle,
    InvestigationOutcome,
    InvestigationPlan,
    InvestigationTerminationReason,
    SituationInvestigator,
)

__all__ = [
    "HermesRuntimeBridge",
    "HermesClient",
    "HermesExecutionMode",
    "HermesInvocationRequest",
    "HermesInvocationResponse",
    "set_active_hermes_context",
    "get_active_hermes_context",
    "HermesConnectionStatus",
    "CapabilityAvailability",
    "CapabilityAuthStatus",
    "CapabilityStatus",
    "HermesRuntimeStatusReport",
    "HermesCapabilityInspector",
    "REQUIRED_CAPABILITIES",
    "CAPABILITY_TOOL_MAPPINGS",
    "BoundedReasoningRequest",
    "ReasoningWorkflow",
    "ReasoningWorkflowResult",
    "StructuredReasoningSynthesis",
    "NovelReasoningSynthesis",
    "NovelReasoningWorkflowResult",
    "validate_novel_reasoning_synthesis",
    "validate_reasoning_synthesis",
    "NoveltyReasoningOrchestrator",
    "NoveltyReasoningPipelineResult",
    "UrgencyLevel",
    "ActionabilityLevel",
    "RelevanceLevel",
    "EvidenceStrength",
    "InformationGapRequest",
    "InvestigationTask",
    "InvestigationResult",
    "BoundedInvestigationWorkflow",
    "validate_investigation_result",
    "BoundedInvestigationRequest",
    "SituationInvestigator",
    "InvestigationOutcome",
    "InvestigationPlan",
    "InvestigationTerminationReason",
    "CrossSourceEvidenceBundle",
    "UnauthorizedWriteOperationError",
]


