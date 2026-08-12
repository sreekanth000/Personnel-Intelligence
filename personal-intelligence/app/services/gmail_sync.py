"""Gmail Synchronization Service.

Orchestrates historical and incremental synchronization of Gmail messages into Observations.
Maintains an SQLite database (data/gmail_sync_state.db) for state persistence and message deduplication.

Sync Strategy:
1. Initial Deployment Sync: Fetches up to the latest 10,000 emails matching filter policies.
2. Incremental Sync: Uses startHistoryId to retrieve newly added messages.
3. Fallback: If historyId expires (>30 days), falls back to timestamp-filtered sync.
4. Deduplication: Checks persistent SQLite synced_messages index before saving.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.config.logging import get_logger
from app.persistence.sqlite_sync_store import SQLiteSyncStore, SyncState

if TYPE_CHECKING:
    from app.connectors.gmail import GmailConnector
    from app.services.ingestion import BaseIngestionService

logger = get_logger(__name__)


# Backwards compatible Pydantic model for SyncCursor
class SyncCursor(BaseModel):
    """Sync cursor state snapshot."""

    last_history_id: str | None = Field(default=None, description="Gmail historyId marker.")
    last_sync_timestamp: str | None = Field(default=None, description="ISO timestamp of last sync.")
    total_messages_synced: int = Field(default=0, description="Total cumulative messages synced.")
    initial_sync_completed: bool = Field(default=False, description="Initial deployment sync flag.")


class SyncResult(BaseModel):
    """Summary of a sync execution run."""

    processed_count: int = Field(default=0, description="Number of messages evaluated.")
    new_observations_count: int = Field(default=0, description="New observations stored.")
    duplicate_count: int = Field(default=0, description="Duplicate messages skipped.")
    last_history_id: str | None = Field(default=None, description="Updated historyId cursor.")
    status: str = Field(default="completed", description="Sync status (completed, failed).")


class GmailSyncService:
    """Service managing Gmail observation synchronization backed by SQLite."""

    def __init__(
        self,
        connector: GmailConnector,
        ingestion_service: BaseIngestionService,
        db_path: Path | str | None = None,
        cursor_path: Path | str | None = None,  # Backward compatibility parameter
    ) -> None:
        self._connector = connector
        self._ingestion_service = ingestion_service

        # Prefer db_path or cursor_path directory for SQLite database
        if db_path is not None:
            target_path = Path(db_path)
        elif cursor_path is not None:
            p = Path(cursor_path)
            target_path = p.parent / "gmail_sync_state.db" if p.suffix == ".json" else p
        else:
            target_path = Path(__file__).resolve().parent.parent.parent / "data" / "gmail_sync_state.db"

        self._store = SQLiteSyncStore(db_path=target_path)
        self._known_message_ids: set[str] = set()

    @property
    def store(self) -> SQLiteSyncStore:
        """Return the underlying SQLite store."""
        return self._store

    def load_cursor(self) -> SyncCursor:
        """Load sync cursor state from SQLite."""
        state = self._store.get_sync_state()
        return SyncCursor(
            last_history_id=state.last_history_id,
            last_sync_timestamp=state.last_sync_timestamp,
            total_messages_synced=state.total_messages_synced,
            initial_sync_completed=state.initial_sync_completed,
        )

    def save_cursor(self, cursor: SyncCursor) -> None:
        """Persist sync cursor state to SQLite."""
        self._store.update_sync_state(
            last_history_id=cursor.last_history_id,
            last_sync_timestamp=cursor.last_sync_timestamp,
            initial_sync_completed=cursor.initial_sync_completed,
        )

    async def sync(self, limit: int = 10000) -> SyncResult:
        """Perform synchronization (incremental if initial sync completed, historical otherwise)."""
        state = self._store.get_sync_state()

        if state.initial_sync_completed and state.last_history_id:
            logger.info("gmail_sync.starting_incremental", history_id=state.last_history_id)
            try:
                return await self._incremental_sync(state, limit=limit)
            except Exception as e:
                logger.warning("gmail_sync.incremental_failed_falling_back", error=str(e))
                return await self._historical_sync(state, limit=limit)
        else:
            # On first deployment, default to 10,000 emails unless custom limit specified
            initial_limit = limit if limit != 100 else state.initial_sync_max_limit
            logger.info("gmail_sync.starting_initial_historical_deployment", limit=initial_limit)
            return await self._historical_sync(state, limit=initial_limit)

    async def _historical_sync(self, state: SyncState, limit: int = 10000) -> SyncResult:
        """Execute historical message sync (up to limit emails, default 10,000)."""
        started_at = datetime.now(UTC).isoformat()
        result = SyncResult()
        max_history_id: int = (
            int(state.last_history_id) if state.last_history_id and state.last_history_id.isdigit() else 0
        )

        since = state.last_sync_timestamp

        async for obs in self._connector.fetch_observations(since=since, limit=limit):
            result.processed_count += 1
            msg_id = obs.source_identifier

            # O(1) deduplication check using memory cache + SQLite
            if msg_id in self._known_message_ids or self._store.is_message_synced(msg_id):
                self._known_message_ids.add(msg_id)
                result.duplicate_count += 1
                continue

            existing = await self._ingestion_service.get_observation(msg_id)
            if existing is not None:
                self._known_message_ids.add(msg_id)
                self._store.record_synced_message(msg_id, status="existing")
                result.duplicate_count += 1
                continue

            # Ingest observation
            await self._ingestion_service.ingest_observation(obs)
            self._known_message_ids.add(msg_id)
            result.new_observations_count += 1

            # Extract historyId if present
            raw_meta = obs.metadata.get("raw_metadata", {})
            h_id = raw_meta.get("historyId")
            thread_id = obs.metadata.get("gmail_thread_id") or raw_meta.get("threadId")
            if h_id and str(h_id).isdigit():
                max_history_id = max(max_history_id, int(h_id))

            # Atomic record in SQLite after each ingested email
            self._store.record_synced_message(
                message_id=msg_id,
                thread_id=thread_id,
                history_id=str(h_id) if h_id else None,
                status="synced",
            )
            self._store.update_sync_state(
                last_history_id=str(max_history_id) if max_history_id > 0 else state.last_history_id,
                last_sync_timestamp=datetime.now(UTC).isoformat(),
                increment_synced_count=1,
            )

        # Mark initial deployment sync completed
        updated_state = self._store.update_sync_state(
            last_history_id=str(max_history_id) if max_history_id > 0 else state.last_history_id,
            last_sync_timestamp=datetime.now(UTC).isoformat(),
            initial_sync_completed=True,
        )

        result.last_history_id = updated_state.last_history_id
        result.status = "completed"

        self._store.log_sync_run(
            sync_type="initial_historical",
            processed_count=result.processed_count,
            new_observations_count=result.new_observations_count,
            duplicate_count=result.duplicate_count,
            status="completed",
            started_at=started_at,
        )

        logger.info(
            "gmail_sync.historical_complete",
            processed=result.processed_count,
            new=result.new_observations_count,
            duplicates=result.duplicate_count,
            history_id=result.last_history_id,
        )
        return result

    async def _incremental_sync(self, state: SyncState, limit: int = 1000) -> SyncResult:
        """Execute incremental sync using Gmail history API."""
        started_at = datetime.now(UTC).isoformat()
        service = self._connector.get_service()
        history_client = service.users().history()

        start_history_id = state.last_history_id
        hist_resp = history_client.list(
            userId="me",
            startHistoryId=start_history_id,
            maxResults=min(limit, 500),
        ).execute()

        history_records = hist_resp.get("history", [])
        result = SyncResult()
        max_history_id = (
            int(start_history_id) if start_history_id and start_history_id.isdigit() else 0
        )

        messages_client = service.users().messages()

        for record in history_records:
            rec_history_id = record.get("id")
            if rec_history_id and str(rec_history_id).isdigit():
                max_history_id = max(max_history_id, int(rec_history_id))

            added_msgs = record.get("messagesAdded", [])
            for item in added_msgs:
                msg_meta = item.get("message", {})
                msg_id = msg_meta.get("id")
                if not msg_id:
                    continue

                result.processed_count += 1
                if msg_id in self._known_message_ids or self._store.is_message_synced(msg_id):
                    self._known_message_ids.add(msg_id)
                    result.duplicate_count += 1
                    continue

                existing = await self._ingestion_service.get_observation(msg_id)
                if existing is not None:
                    self._known_message_ids.add(msg_id)
                    self._store.record_synced_message(msg_id, status="existing")
                    result.duplicate_count += 1
                    continue

                full_msg = messages_client.get(userId="me", id=msg_id, format="full").execute()
                obs = self._connector.message_to_observation(full_msg)
                await self._ingestion_service.ingest_observation(obs)
                self._known_message_ids.add(msg_id)
                result.new_observations_count += 1

                thread_id = obs.metadata.get("gmail_thread_id") or full_msg.get("threadId")
                self._store.record_synced_message(
                    message_id=msg_id,
                    thread_id=thread_id,
                    history_id=str(rec_history_id) if rec_history_id else None,
                    status="synced",
                )
                self._store.update_sync_state(
                    last_history_id=str(max_history_id) if max_history_id > 0 else state.last_history_id,
                    last_sync_timestamp=datetime.now(UTC).isoformat(),
                    increment_synced_count=1,
                )

        updated_state = self._store.update_sync_state(
            last_history_id=str(max_history_id) if max_history_id > 0 else state.last_history_id,
            last_sync_timestamp=datetime.now(UTC).isoformat(),
            initial_sync_completed=True,
        )

        result.last_history_id = updated_state.last_history_id
        result.status = "completed"

        self._store.log_sync_run(
            sync_type="incremental",
            processed_count=result.processed_count,
            new_observations_count=result.new_observations_count,
            duplicate_count=result.duplicate_count,
            status="completed",
            started_at=started_at,
        )

        logger.info(
            "gmail_sync.incremental_complete",
            processed=result.processed_count,
            new=result.new_observations_count,
            duplicates=result.duplicate_count,
            history_id=result.last_history_id,
        )
        return result
