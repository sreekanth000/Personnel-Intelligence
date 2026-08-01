from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


class EntityType(str, Enum):
    PERSON = "Person"
    ORGANIZATION = "Organization"
    PROJECT = "Project"
    MEETING = "Meeting"
    DOCUMENT = "Document"
    EMAIL = "Email"
    TASK = "Task"
    GOAL = "Goal"
    KNOWLEDGE = "Knowledge"
    COMMITMENT = "Commitment"
    TOPIC = "Topic"
    SKILL = "Skill"
    FOLDER = "Folder"
    FILE = "File"
    TECHNOLOGY = "Technology"
    EVENT = "Event"
    DECISION = "Decision"
    QUESTION = "Question"
    PREFERENCE = "Preference"
    INSIGHT = "Insight"
    RECOMMENDATION = "Recommendation"
    READINESS_ASSESSMENT = "ReadinessAssessment"
    NOTIFICATION = "Notification"
    BILL = "Bill"
    FINANCIAL_TRANSACTION = "FinancialTransaction"
    BANK_ACCOUNT = "BankAccount"


class OriginType(str, Enum):
    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"
    USER_CONFIRMED = "USER_CONFIRMED"


class Provenance(BaseModel):
    source_connector: str = "Unknown"
    source_item_id: Optional[str] = None
    source_url: Optional[str] = None
    supporting_text: Optional[str] = None
    extraction_model: Optional[str] = None
    extraction_timestamp: datetime = Field(default_factory=datetime.utcnow)
    origin_type: OriginType = OriginType.EXTRACTED


class Relationship(BaseModel):
    target_entity_id: str
    relationship_type: str  # e.g., "WORKS_ON", "BELONGS_TO", "MENTIONS"
    properties: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    observed_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    occurred_at: Optional[datetime] = None
    last_confirmed_at: Optional[datetime] = None
    timezone: Optional[str] = None
    recurrence: Optional[str] = None
    provenance: Provenance = Field(default_factory=Provenance)


class Entity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: EntityType
    status: str = "Active"
    properties: Dict[str, Any] = Field(default_factory=dict)
    aliases: List[str] = Field(default_factory=list)
    canonical_id: Optional[str] = None
    identifiers: Dict[str, str] = Field(default_factory=dict)
    relationships: List[Relationship] = Field(default_factory=list)
    confidence: float = 1.0
    created_time: datetime = Field(default_factory=datetime.utcnow)
    updated_time: datetime = Field(default_factory=datetime.utcnow)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    observed_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    occurred_at: Optional[datetime] = None
    last_confirmed_at: Optional[datetime] = None
    timezone: Optional[str] = None
    recurrence: Optional[str] = None
    provenance: Provenance = Field(default_factory=Provenance)
    source: str  # e.g., "Gmail", "Local_FS"
    version: int = 1
    importance: float = 0.5


# Base Event model for the pipeline
class EventType(str, Enum):
    CREATED = "CREATED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"


class PipelineEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    raw_data: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)
