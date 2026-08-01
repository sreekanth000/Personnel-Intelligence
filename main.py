import asyncio
import os
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from core.pipeline import AsyncQueueEventBus, PipelineComponent, PipelineEvent
from core.db import DuckDBWorldModelStore, MockWorldModelStore, ChromaVectorStore
from core.models import Entity, Relationship, EntityType
from core.ai import AzureOpenAIExtractor
from dotenv import load_dotenv

load_dotenv()

# Connectors
from connectors.local_fs.watcher import LocalFSWatcher
from connectors.local_fs.parser import LocalFSParser
from connectors.gcal.sync import GoogleCalendarSync
from connectors.gcal.extractor import GCalExtractor
from connectors.gmail.sync import GmailSync
from connectors.gmail.parser import GmailParser
from connectors.gdrive.sync import GDriveSync
from connectors.gdrive.downloader import GDriveDownloader
from connectors.github.sync import GitHubSync
from connectors.github.parser import GitHubParser
from core.resolution import EntityResolutionEngine
from core.reasoning import ReasoningEngine
from agents.briefing import BriefingAgent
from core.proactive import AutonomousReadinessIntelligence

from core.builders import GraphEntityBuilder


async def main():
    print("Starting Personal Cognitive Brain - World Model Expansion Phase...")

    bus = AsyncQueueEventBus()

    duckdb_store = DuckDBWorldModelStore()
    chroma_db = ChromaVectorStore()

    db = duckdb_store

    local_fs_parser = LocalFSParser(bus)
    gcal_extractor = GCalExtractor(bus)
    gmail_parser = GmailParser(bus)
    gdrive_downloader = GDriveDownloader(bus)
    github_parser = GitHubParser(bus)

    semantic_extractor = AzureOpenAIExtractor(bus)
    resolution_engine = EntityResolutionEngine(db, chroma_db)
    reasoning_engine = ReasoningEngine(db)
    proactive_engine = AutonomousReadinessIntelligence(db, chroma_db)
    briefing_agent = BriefingAgent(db, chroma_db)

    if isinstance(db, DuckDBWorldModelStore):
        entity_builder = GraphEntityBuilder(bus, db, chroma_db)
    else:
        from core.pipeline import PipelineComponent

        class DummyBuilder(PipelineComponent):
            async def process(self, event):
                print(f"[DummyBuilder] Processed event from {event.source}")

        entity_builder = DummyBuilder(bus)

    await bus.subscribe("local_fs_events", local_fs_parser.process)
    await bus.subscribe("gcal_events", gcal_extractor.process)
    await bus.subscribe("gmail_events", gmail_parser.process)
    await bus.subscribe("gdrive_events", gdrive_downloader.process)
    await bus.subscribe("github_events", github_parser.process)

    await bus.subscribe("documents_to_extract", semantic_extractor.process)
    await bus.subscribe("events_to_extract", semantic_extractor.process)
    await bus.subscribe("emails_to_extract", semantic_extractor.process)
    await bus.subscribe("entities_to_build", entity_builder.process)
    await bus.subscribe("entity_built", proactive_engine.handle_new_entity)

    # 3. Initialize Connectors
    # Configure the folders that form part of the personal world model with a
    # platform-native path list, e.g. on Windows:
    # WATCH_DIRECTORIES=C:\\Work\\GreatLearning;C:\\Work\\SRM
    configured_watch_dirs = [
        path.strip()
        for path in os.environ.get("WATCH_DIRECTORIES", "").split(os.pathsep)
        if path.strip()
    ]
    watch_dirs = configured_watch_dirs or [os.path.join(os.getcwd(), "test_watch_dir")]
    for watch_dir in watch_dirs:
        os.makedirs(watch_dir, exist_ok=True)

    local_fs_watcher = LocalFSWatcher(bus, watch_dirs)
    gcal_sync = GoogleCalendarSync(bus)
    gmail_sync = GmailSync(bus)
    gdrive_sync = GDriveSync(bus)
    github_sync = GitHubSync(bus)

    # 4. Start Connectors
    local_fs_watcher.start()

    import json
    from fastapi.middleware.cors import CORSMiddleware

    # --- INTERNAL AND FRONTEND API ---
    internal_app = FastAPI(title="Cognitive Brain API")

    internal_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class PublishRequest(BaseModel):
        topic: str
        event: dict

    @internal_app.post("/publish")
    async def publish_event(req: PublishRequest):
        event = PipelineEvent(**req.event)
        await bus.publish(req.topic, event)
        return {"status": "published", "event_id": event.id}

    @internal_app.get("/api/graph")
    async def get_graph():
        try:
            with duckdb_store._get_connection() as conn:
                entities = (
                    conn.execute(
                        "SELECT id, type, properties, source, confidence FROM entities"
                    )
                    .df()
                    .to_dict(orient="records")
                )
                relationships = (
                    conn.execute(
                        "SELECT source_id, target_id, type, properties, confidence FROM relationships"
                    )
                    .df()
                    .to_dict(orient="records")
                )

                nodes = []
                for e in entities:
                    props = (
                        json.loads(e["properties"])
                        if isinstance(e["properties"], str)
                        else e["properties"]
                    )
                    nodes.append(
                        {
                            "id": e["id"],
                            "name": props.get("name")
                            or props.get("subject")
                            or props.get("title")
                            or e["id"],
                            "group": e["type"],
                            "val": 1.5 if e["type"] == "Email" else 1,
                            "properties": props,
                        }
                    )

                links = []
                for r in relationships:
                    links.append(
                        {
                            "source": r["source_id"],
                            "target": r["target_id"],
                            "label": r["type"],
                        }
                    )

                return {"nodes": nodes, "links": links}
        except Exception as e:
            print(f"Error querying DuckDB: {e}")
            return {"nodes": [], "links": []}

    @internal_app.get("/api/insights")
    async def get_insights():
        try:
            with duckdb_store._get_connection() as conn:
                insights = (
                    conn.execute(
                        "SELECT properties FROM entities WHERE type='Insight' AND (json_extract_string(properties, '$.state') IS NULL OR json_extract_string(properties, '$.state') != 'dismissed')"
                    )
                    .df()
                    .to_dict(orient="records")
                )
                results = []
                for idx, row in enumerate(insights):
                    props = (
                        json.loads(row["properties"])
                        if isinstance(row["properties"], str)
                        else row["properties"]
                    )
                    # Use fingerprint or generate unique id for React key
                    props["id"] = props.get("fingerprint", str(idx))
                    results.append(props)
                return results
        except Exception as e:
            print(f"Error querying insights: {e}")
            return []

    @internal_app.get("/api/stats")
    async def get_stats():
        try:
            with duckdb_store._get_connection() as conn:
                entities = (
                    conn.execute(
                        "SELECT type, COUNT(*) as count FROM entities GROUP BY type"
                    )
                    .df()
                    .to_dict(orient="records")
                )
                rels = (
                    conn.execute("SELECT COUNT(*) as count FROM relationships")
                    .df()
                    .to_dict(orient="records")
                )

                stats = {}
                for e in entities:
                    stats[e["type"]] = e["count"]

                total_rels = rels[0]["count"] if rels else 0
                stats["Relationships"] = total_rels

                return stats
        except Exception as e:
            return {}

    config = uvicorn.Config(
        internal_app, host="127.0.0.1", port=8000, log_level="warning"
    )
    server = uvicorn.Server(config)
    # ----------------------------------

    # Run sync loops
    sync_tasks = [
        asyncio.create_task(server.serve()),
        asyncio.create_task(gcal_sync.run_sync_loop(interval_seconds=30)),
        asyncio.create_task(gmail_sync.run_sync_loop(interval_seconds=30)),
        asyncio.create_task(gdrive_sync.run_sync_loop(interval_seconds=30)),
        asyncio.create_task(github_sync.run_sync_loop(interval_seconds=30)),
        asyncio.create_task(
            resolution_engine.run_resolution_loop(interval_seconds=120)
        ),
        asyncio.create_task(reasoning_engine.run_reasoning_loop(interval_seconds=60)),
        asyncio.create_task(proactive_engine.run_loop(interval_seconds=900)),
        asyncio.create_task(briefing_agent.run(interval_seconds=120)),
    ]

    print(f"\nPhase 3 Pipeline running. Press Ctrl+C to exit.\n")

    try:
        await asyncio.gather(*sync_tasks)
    except asyncio.CancelledError:
        pass
    finally:
        local_fs_watcher.stop()
        gcal_sync.stop()
        gmail_sync.stop()
        gdrive_sync.stop()
        github_sync.stop()
        resolution_engine.stop()
        reasoning_engine.stop()
        proactive_engine.stop()
        briefing_agent.stop()
        if isinstance(db, DuckDBWorldModelStore):
            await db.close()
        print("Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
