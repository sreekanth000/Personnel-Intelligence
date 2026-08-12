"""Unit tests for multi-source connectors (Google Calendar & Google Drive/Notes) and unified pipeline integration.

Verifies:
- Calendar & Drive Observation creation & payload formatting
- Unified multi-source pipeline ingestion (Calendar & Drive -> Evidence & Reconciliation)
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.calendar import GoogleCalendarConnector, format_calendar_event_as_text
from app.connectors.drive import GoogleDriveConnector, format_drive_file_as_text
from app.domain import (
    ConfidenceScore,
    Entity,
    EntityType,
    EvidenceSpan,
    Observation,
    ObservationSource,
    Relationship,
    RelationshipType,
)
from app.services.extraction import StructuredExtraction
from app.services.pipeline import GmailPipelineService


def test_calendar_event_payload_formatting() -> None:
    """Verifies calendar event payload formatting into structured observation content."""
    sample_event = {
        "id": "evt_101",
        "summary": "Architecture Review",
        "description": "Discuss Personal Intelligence multi-source pipeline.",
        "location": "Conference Room A",
        "start": {"dateTime": "2026-08-15T10:00:00Z"},
        "end": {"dateTime": "2026-08-15T11:00:00Z"},
        "organizer": {"email": "alice@acme.com", "displayName": "Alice Smith"},
        "attendees": [
            {"email": "alice@acme.com", "displayName": "Alice Smith"},
            {"email": "bob@acme.com", "displayName": "Bob Jones"},
        ],
    }

    text = format_calendar_event_as_text(sample_event)
    assert "Event Title: Architecture Review" in text
    assert "Organizer: alice@acme.com" in text
    assert "Location: Conference Room A" in text
    assert "Attendees: Alice Smith <alice@acme.com>, Bob Jones <bob@acme.com>" in text
    assert "Discuss Personal Intelligence multi-source pipeline." in text

    connector = GoogleCalendarConnector()
    obs = connector.event_to_observation(sample_event)
    assert obs.source == ObservationSource.GOOGLE_CALENDAR
    assert obs.source_identifier == "calendar:evt_101"
    assert obs.metadata["summary"] == "Architecture Review"


def test_drive_file_payload_formatting() -> None:
    """Verifies Drive file payload formatting into structured observation content."""
    filename = "Personal_Intelligence_Blueprint.md"
    content = "# Blueprint\nMulti-source pipeline supporting Calendar, Drive, and Gmail."
    text = format_drive_file_as_text(
        filename=filename,
        content=content,
        mime_type="text/markdown",
        author="Sreekanth",
        modified_time="2026-08-12T17:00:00Z",
    )

    assert "Document Title: Personal_Intelligence_Blueprint.md" in text
    assert "Author / Owner: Sreekanth" in text
    assert "Multi-source pipeline supporting Calendar, Drive, and Gmail." in text

    connector = GoogleDriveConnector()
    obs = connector.file_to_observation(
        file_id="file_abc123",
        filename=filename,
        content=content,
        mime_type="text/markdown",
        author="Sreekanth",
        modified_time="2026-08-12T17:00:00Z",
    )

    assert obs.source == ObservationSource.GOOGLE_DRIVE
    assert obs.source_identifier == "drive:file_abc123"
    assert obs.metadata["filename"] == filename


@pytest.mark.asyncio
async def test_unified_pipeline_calendar_and_drive_ingestion() -> None:
    """Verifies that Calendar and Drive observations feed into the same evidence & reconciliation pipeline."""
    mock_extractor = AsyncMock()

    # 1. Calendar Event Observation
    cal_obs = Observation(
        source=ObservationSource.GOOGLE_CALENDAR,
        source_identifier="calendar:evt_999",
        content="Event Title: Strategy Session\nOrganizer: founder@startup.io\nDescription: Meeting with Alice regarding Project Alpha.",
        metadata={"summary": "Strategy Session", "organizer": "founder@startup.io"},
    )

    span = EvidenceSpan(
        text_snippet="Meeting with Alice regarding Project Alpha.",
        confidence=ConfidenceScore.from_score(0.95),
    )

    cal_extraction = StructuredExtraction(
        source_observation_id=cal_obs.id,
        entities=[
            Entity(id="e_alice", name="Alice", entity_type=EntityType.PERSON, confidence=ConfidenceScore.from_score(0.95)),
            Entity(id="e_pa", name="Project Alpha", entity_type=EntityType.PROJECT, confidence=ConfidenceScore.from_score(0.95)),
        ],
        relationships=[
            Relationship(
                id="r_alice_pa",
                subject="Alice",
                predicate=RelationshipType.RESPONSIBLE_FOR,
                object="Project Alpha",
                confidence=ConfidenceScore.from_score(0.90),
                evidence_span=span,
                source_observation_id=cal_obs.id,
            )
        ],
    )

    mock_extractor.extract_from_observation.return_value = cal_extraction

    pipeline = GmailPipelineService(extractor=mock_extractor)
    report = await pipeline.process_observation(cal_obs)

    assert report.success is True
    assert report.raw_observation_id == cal_obs.id
    assert report.entities_new == 2
    assert report.relationships_by_status["NEW"] == 1

    # 2. Drive Note Observation
    drive_obs = Observation(
        source=ObservationSource.GOOGLE_DRIVE,
        source_identifier="drive:file_888",
        content="Document Title: Project Alpha Notes\nAuthor: Sreekanth\nContent: Alice transferred leadership of Project Alpha to Bob.",
        metadata={"filename": "Project Alpha Notes", "author": "Sreekanth"},
    )

    drive_span = EvidenceSpan(
        text_snippet="Alice transferred leadership of Project Alpha to Bob.",
        confidence=ConfidenceScore.from_score(0.95),
    )

    drive_extraction = StructuredExtraction(
        source_observation_id=drive_obs.id,
        entities=[
            Entity(id="e_alice", name="Alice", entity_type=EntityType.PERSON, confidence=ConfidenceScore.from_score(0.95)),
            Entity(id="e_bob", name="Bob", entity_type=EntityType.PERSON, confidence=ConfidenceScore.from_score(0.95)),
            Entity(id="e_pa", name="Project Alpha", entity_type=EntityType.PROJECT, confidence=ConfidenceScore.from_score(0.95)),
        ],
        relationships=[
            Relationship(
                id="r_bob_pa",
                subject="Bob",
                predicate=RelationshipType.RESPONSIBLE_FOR,
                object="Project Alpha",
                confidence=ConfidenceScore.from_score(0.95),
                evidence_span=drive_span,
                source_observation_id=drive_obs.id,
            )
        ],
    )

    mock_extractor.extract_from_observation.return_value = drive_extraction

    report2 = await pipeline.process_observation(drive_obs)
    assert report2.success is True
    assert report2.relationships_by_status["NEW"] == 1
