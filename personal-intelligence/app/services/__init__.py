"""Services package — application services and component interfaces.

Defines the core architectural boundaries:
- connectors & sync
- observation ingestion
- extraction
- evidence
- world model
- reconciliation
- context
"""

from app.services.context import BaseContextEngine, ContextEngine
from app.services.entity_resolution import EntityResolver
from app.services.evidence import BaseEvidenceService, EvidenceService
from app.services.extraction import (
    BaseExtractionService,
    ExtractionResult,
    GPT41Extractor,
    StructuredExtraction,
)
from app.services.gmail_sync import GmailSyncService, SyncCursor, SyncResult
from app.services.ingestion import BaseIngestionService, ObservationIngestionService
from app.services.pipeline import GmailPipelineService
from app.services.privacy_filter import PrivacyFilter
from app.services.reasoning import GPT41ReasoningService
from app.services.reconciliation import BaseReconciliationEngine, ReconciliationEngine
from app.services.world_model import BaseWorldModelService, WorldModelService

__all__ = [
    "BaseContextEngine",
    "BaseEvidenceService",
    "BaseExtractionService",
    "BaseIngestionService",
    "BaseReconciliationEngine",
    "BaseWorldModelService",
    "ContextEngine",
    "EntityResolver",
    "EvidenceService",
    "ExtractionResult",
    "GPT41Extractor",
    "GPT41ReasoningService",
    "GmailPipelineService",
    "GmailSyncService",
    "ObservationIngestionService",
    "PrivacyFilter",
    "ReconciliationEngine",
    "StructuredExtraction",
    "SyncCursor",
    "SyncResult",
    "WorldModelService",
]
