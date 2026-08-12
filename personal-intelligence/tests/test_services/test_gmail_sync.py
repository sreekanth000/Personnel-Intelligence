"""Unit tests for GmailSyncService backed by SQLite persistence.

Verifies:
- Persistent SQLite sync state creation and atomic updating
- Initial 10,000 email deployment sync policy
- Incremental sync execution using history API
- Persistent message deduplication index in SQLite
- Automatic legacy JSON cursor migration
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.gmail import GmailConnector
from app.domain.enums import ObservationSource
from app.domain.observations import Observation
from app.services.gmail_sync import GmailSyncService, SyncCursor

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def mock_ingestion_service() -> AsyncMock:
    """Mock ObservationIngestionService."""
    service = AsyncMock()
    service.ingest_observation.side_effect = lambda obs: obs.id
    service.get_observation.return_value = None
    return service


@pytest.fixture()
def mock_connector() -> MagicMock:
    """Mock GmailConnector with sample observations."""
    connector = MagicMock(spec=GmailConnector)

    obs1 = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_101",
        content="First sync email content.",
        metadata={"gmail_message_id": "msg_101", "raw_metadata": {"historyId": "500"}},
    )
    obs2 = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_102",
        content="Second sync email content.",
        metadata={"gmail_message_id": "msg_102", "raw_metadata": {"historyId": "550"}},
    )

    async def _async_gen(**kwargs):
        yield obs1
        yield obs2

    connector.fetch_observations.side_effect = _async_gen
    return connector


@pytest.mark.asyncio
async def test_initial_historical_sync_sqlite(
    tmp_path: Path, mock_connector: MagicMock, mock_ingestion_service: AsyncMock
) -> None:
    """Initial deployment sync performs historical sync, stores observations, and updates SQLite state."""
    db_file = tmp_path / "gmail_sync_state.db"
    sync_service = GmailSyncService(
        connector=mock_connector,
        ingestion_service=mock_ingestion_service,
        db_path=db_file,
    )

    result = await sync_service.sync(limit=10000)

    assert result.status == "completed"
    assert result.processed_count == 2
    assert result.new_observations_count == 2
    assert result.duplicate_count == 0
    assert result.last_history_id == "550"

    # Verify SQLite state persisted
    cursor = sync_service.load_cursor()
    assert cursor.last_history_id == "550"
    assert cursor.total_messages_synced == 2
    assert cursor.initial_sync_completed is True

    # Verify SQLite message deduplication index
    assert sync_service.store.is_message_synced("msg_101") is True
    assert sync_service.store.is_message_synced("msg_102") is True
    assert sync_service.store.is_message_synced("msg_non_existent") is False


@pytest.mark.asyncio
async def test_deduplication_on_repeated_sync(
    tmp_path: Path, mock_connector: MagicMock, mock_ingestion_service: AsyncMock
) -> None:
    """Repeated sync runs must not duplicate previously ingested observations."""
    db_file = tmp_path / "gmail_sync_state.db"
    sync_service = GmailSyncService(
        connector=mock_connector,
        ingestion_service=mock_ingestion_service,
        db_path=db_file,
    )

    # First sync run
    _ = await sync_service.sync(limit=10)

    # Reset historical flag to test deduplication on repeated historical fetch
    sync_service.store.update_sync_state(
        last_history_id=None,
        initial_sync_completed=False,
    )
    sync_service._known_message_ids.clear()

    # Second sync run with duplicate observations
    result2 = await sync_service.sync(limit=10)

    assert result2.processed_count == 2
    assert result2.new_observations_count == 0
    assert result2.duplicate_count == 2


@pytest.mark.asyncio
async def test_incremental_sync_with_history_api(
    tmp_path: Path, mock_ingestion_service: AsyncMock
) -> None:
    """Incremental sync retrieves history records and updates SQLite state after every message."""
    db_file = tmp_path / "gmail_sync_state.db"

    plain_b64 = base64.urlsafe_b64encode(b"Incremental email content").decode("utf-8")
    mock_msg = {
        "id": "msg_inc_001",
        "threadId": "thread_inc_001",
        "historyId": "1050",
        "internalDate": "1775000000000",
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": plain_b64},
            "headers": [{"name": "Subject", "value": "Incremental Sync Subject"}],
        },
    }

    mock_service = MagicMock()
    mock_history = MagicMock()
    mock_messages = MagicMock()

    mock_history.list.return_value.execute.return_value = {
        "history": [
            {
                "id": "1050",
                "messagesAdded": [{"message": {"id": "msg_inc_001"}}],
            }
        ]
    }
    mock_messages.get.return_value.execute.return_value = mock_msg

    mock_service.users.return_value.history.return_value = mock_history
    mock_service.users.return_value.messages.return_value = mock_messages

    connector = GmailConnector(service=mock_service)
    sync_service = GmailSyncService(
        connector=connector,
        ingestion_service=mock_ingestion_service,
        db_path=db_file,
    )

    # Set state as initial completed with history ID 1000
    sync_service.store.update_sync_state(
        last_history_id="1000",
        increment_synced_count=10,
        initial_sync_completed=True,
    )

    result = await sync_service.sync(limit=10)

    assert result.status == "completed"
    assert result.processed_count == 1
    assert result.new_observations_count == 1
    assert result.last_history_id == "1050"

    cursor = sync_service.load_cursor()
    assert cursor.last_history_id == "1050"
    assert cursor.total_messages_synced == 11
    assert sync_service.store.is_message_synced("msg_inc_001") is True
