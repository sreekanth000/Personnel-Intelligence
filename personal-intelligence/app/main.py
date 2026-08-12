"""Application startup, lifecycle management, and FastAPI app factory.

This is the single entry point for the Personal Intelligence system.
It initializes configuration, logging, databases, and mounts API routers.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.api import ask, extraction, ui, world
from app.config.logging import get_logger, setup_logging
from app.config.settings import Settings, get_settings
from app.persistence.duckdb_store import DuckDBStore
from app.persistence.kuzu_store import KuzuStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Application state — holds all initialized resources
# ---------------------------------------------------------------------------


@dataclass
class AppState:
    """Container for application-wide shared resources.

    Stored on the FastAPI app instance so that routers can access
    databases and settings without global mutable state.
    """

    settings: Settings = field(default_factory=get_settings)
    duckdb: DuckDBStore = field(init=False)
    kuzu: KuzuStore = field(init=False)

    def __post_init__(self) -> None:
        self.duckdb = DuckDBStore(self.settings.duckdb_path)
        self.kuzu = KuzuStore(self.settings.kuzu_path)


# Module-level reference so the health router can reach it.
# Set during app creation in create_app().
_app_state: AppState | None = None


def get_app_state() -> AppState:
    """Return the current application state. Raises if app not initialized."""
    if _app_state is None:
        msg = "Application state not initialized. Was create_app() called?"
        raise RuntimeError(msg)
    return _app_state


# ---------------------------------------------------------------------------
# Lifespan — startup and shutdown hooks
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown."""
    global _app_state

    settings = get_settings()
    setup_logging(log_level=settings.log_level, environment=settings.environment)

    logger.info(
        "app.starting",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )

    # Ensure data directories exist
    settings.raw_data_dir.mkdir(parents=True, exist_ok=True)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)

    # Initialize databases
    state = AppState(settings=settings)
    state.duckdb.init_schema()
    state.kuzu.init_schema()

    _app_state = state

    logger.info("app.started")

    yield

    # --- Shutdown ---
    logger.info("app.shutting_down")
    _app_state = None
    logger.info("app.stopped")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from app.api.health import router as health_router

    app = FastAPI(
        title="Personal Intelligence",
        description="Local-first Personal Intelligence system — a user-owned cognitive layer.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(ask.router)
    app.include_router(world.router)
    app.include_router(ui.router)
    app.include_router(extraction.router, prefix="/api/v1")

    return app


# Module-level app instance for uvicorn
app = create_app()
