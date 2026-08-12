"""Continuous background synchronization service for Gmail, Google Calendar, Google Drive & Notes.

Runs as a standalone process. Fetches observations across all sources and processes them
through the unified extraction, evidence, entity resolution, and reconciliation pipeline into the world model.
Sync state is persisted in an SQLite database (data/gmail_sync_state.db).
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.api.world import get_evidence_service, get_world_model_service
from app.config.logging import get_logger, setup_logging
from app.config.settings import get_settings
from app.connectors.calendar import GoogleCalendarConnector
from app.connectors.drive import GoogleDriveConnector
from app.connectors.gmail import GmailConnector
from app.connectors.gmail_filter import GmailFilterService
from app.main import AppState, _app_state
from app.persistence.sqlite_sync_store import SQLiteSyncStore, SyncState
from app.services.entity_resolution import EntityResolver
from app.services.extraction import GPT41Extractor
from app.services.pipeline import GmailPipelineService

if TYPE_CHECKING:
    from app.config.settings import Settings

logger = get_logger(__name__)


async def _run_sync_cycle(
    connector: GmailConnector,
    pipeline: GmailPipelineService,
    wm: Any,
    store: SQLiteSyncStore,
    email_limit: int = 50,
) -> None:
    """Fetch and process Gmail emails immediately as they arrive from connector, updating SQLite after every email."""
    state = store.get_sync_state()
    is_initial_sync = not state.initial_sync_completed or state.last_history_id is None

    if is_initial_sync:
        logger.info("sync.initial_historical_deployment_started", limit=email_limit)
        since_param = None
    else:
        logger.info("sync.incremental_started", history_id=state.last_history_id, limit=email_limit)
        since_param = state.last_history_id

    success_count = 0
    error_count = 0
    duplicate_count = 0
    total_emails = 0
    max_history_id = (
        int(state.last_history_id) if (state.last_history_id and state.last_history_id.isdigit()) else 0
    )

    try:
        obs_iterator = connector.fetch_observations(since=since_param, limit=email_limit)
        async for obs in obs_iterator:
            total_emails += 1
            msg_id = obs.source_identifier

            # SQLite deduplication check
            if store.is_message_synced(msg_id):
                duplicate_count += 1
                continue

            h_id = obs.metadata.get("raw_metadata", {}).get("historyId")
            thread_id = obs.metadata.get("gmail_thread_id") or obs.metadata.get("raw_metadata", {}).get("threadId")
            if h_id and str(h_id).isdigit():
                max_history_id = max(max_history_id, int(h_id))

            try:
                # Fetch current state from DuckDB
                all_entities = await wm.get_all_entities()
                all_relationships = await wm.get_all_relationships()

                # Process through multi-source extraction & reconciliation pipeline
                report = await pipeline.process_observation(
                    raw_observation=obs,
                    existing_entities=all_entities,
                    existing_relationships=all_relationships,
                )
                success_count += 1
                logger.info(
                    "sync.email_processed",
                    observation_id=obs.id,
                    gmail_message_id=msg_id,
                    new_relationships=report.relationships_by_status.get("NEW", 0),
                    new_entities=report.entities_new,
                )

                # Persist message and updated cursor state to SQLite after EVERY email
                store.record_synced_message(
                    message_id=msg_id,
                    thread_id=thread_id,
                    history_id=str(h_id) if h_id else None,
                    status="synced",
                )
                store.update_sync_state(
                    last_history_id=str(max_history_id) if max_history_id > 0 else state.last_history_id,
                    last_sync_timestamp=datetime.now(UTC).isoformat(),
                    increment_synced_count=1,
                )

            except Exception as e:
                error_count += 1
                logger.warning(
                    "sync.email_processing_failed",
                    observation_id=obs.id,
                    gmail_message_id=msg_id,
                    error=str(e),
                )

    except Exception as e:
        logger.error("sync.fetch_failed", error=str(e))
        return

    # Mark initial deployment sync completed if this was the initial run
    if is_initial_sync:
        store.update_sync_state(
            last_history_id=str(max_history_id) if max_history_id > 0 else state.last_history_id,
            last_sync_timestamp=datetime.now(UTC).isoformat(),
            initial_sync_completed=True,
        )

    logger.info(
        "sync.cycle_complete",
        total_emails=total_emails,
        success=success_count,
        duplicates=duplicate_count,
        errors=error_count,
        cursor_history_id=max_history_id,
    )


async def _run_multi_source_sync_cycle(
    cal_connector: GoogleCalendarConnector,
    drive_connector: GoogleDriveConnector,
    pipeline: GmailPipelineService,
    wm: Any,
    store: SQLiteSyncStore,
) -> None:
    """Fetch and process Google Calendar & Google Drive/Notes observations into the evidence & reconciliation pipeline."""
    # 1. Sync Google Calendar events
    if cal_connector.is_authenticated():
        try:
            logger.info("sync.calendar_started")
            async for obs in cal_connector.fetch_observations(limit=20):
                if store.is_message_synced(obs.source_identifier):
                    continue
                all_entities = await wm.get_all_entities()
                all_relationships = await wm.get_all_relationships()
                await pipeline.process_observation(obs, existing_entities=all_entities, existing_relationships=all_relationships)
                store.record_synced_message(message_id=obs.source_identifier, status="synced")
        except Exception as e:
            logger.warning("sync.calendar_failed", error=str(e))

    # 2. Sync Google Drive & Local Notes
    if drive_connector.is_authenticated():
        try:
            logger.info("sync.drive_notes_started")
            async for obs in drive_connector.fetch_observations(limit=20):
                if store.is_message_synced(obs.source_identifier):
                    continue
                all_entities = await wm.get_all_entities()
                all_relationships = await wm.get_all_relationships()
                await pipeline.process_observation(obs, existing_entities=all_entities, existing_relationships=all_relationships)
                store.record_synced_message(message_id=obs.source_identifier, status="synced")
        except Exception as e:
            logger.warning("sync.drive_notes_failed", error=str(e))


async def main() -> None:
    """Main execution loop for continuous multi-source sync."""
    settings = get_settings()
    setup_logging(log_level=settings.log_level, environment=settings.environment)
    logger.info("sync.service_starting")

    # Ensure data directories exist
    settings.raw_data_dir.mkdir(parents=True, exist_ok=True)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)

    # Initialize AppState
    state = AppState(settings=settings)
    state.duckdb.init_schema()
    state.kuzu.init_schema()

    import app.main
    app.main._app_state = state

    # Initialize SQLite Sync Store
    store = SQLiteSyncStore()

    # Check Azure OpenAI configuration
    if not settings.azure_ai_api_key or not settings.azure_ai_endpoint:
        logger.critical(
            "sync.startup_failed",
            reason="No Azure OpenAI config. Set PI_AZURE_AI_API_KEY and PI_AZURE_AI_ENDPOINT in .env",
        )
        return

    # Check Connectors
    try:
        gmail_connector = GmailConnector()
        cal_connector = GoogleCalendarConnector()
        drive_connector = GoogleDriveConnector()
    except Exception as e:
        logger.critical("sync.startup_failed", reason=f"Connector error: {e}")
        return

    # Initialize pipeline services
    wm = get_world_model_service()
    ev = get_evidence_service()
    er = EntityResolver()
    extractor = GPT41Extractor(
        azure_endpoint=settings.azure_ai_endpoint,
        api_key=settings.azure_ai_api_key,
        deployment=settings.azure_openai_deployment,
        api_version=settings.azure_ai_api_version,
    )

    pipeline = GmailPipelineService(
        extractor=extractor,
        evidence_service=ev,
        entity_resolver=er,
        world_model_service=wm,
    )

    sync_interval_seconds = 60
    logger.info("sync.service_ready", interval=sync_interval_seconds)

    while True:
        try:
            filter_service = GmailFilterService()
            sync_state = store.get_sync_state()

            if not sync_state.initial_sync_completed:
                logger.info("sync.running_initial_deployment_full_sync", target_limit=sync_state.initial_sync_max_limit)
                batch_limit = sync_state.initial_sync_max_limit
            else:
                batch_limit = filter_service.config.max_emails_per_sync

            # Run Gmail sync cycle
            await _run_sync_cycle(gmail_connector, pipeline, wm, store, email_limit=batch_limit)

            # Run Calendar & Drive/Notes sync cycle
            await _run_multi_source_sync_cycle(cal_connector, drive_connector, pipeline, wm, store)

        except Exception as e:
            logger.exception("sync.unexpected_error_in_cycle", error=str(e))

        logger.info("sync.sleeping", seconds=sync_interval_seconds)
        await asyncio.sleep(sync_interval_seconds)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSync service stopped by user.")
