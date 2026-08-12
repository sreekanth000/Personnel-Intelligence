"""Health check endpoint.

Provides a single /health endpoint that reports the status
of the application and all its dependencies (DuckDB, Kuzu).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.main import get_app_state

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Structured health check response."""

    status: str
    version: str
    checks: dict[str, bool]


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Application health check",
)
async def health_check() -> dict[str, Any]:
    """Return the health status of all system components."""
    state = get_app_state()

    duckdb_ok = state.duckdb.is_healthy()
    kuzu_ok = state.kuzu.is_healthy()

    all_healthy = duckdb_ok and kuzu_ok
    overall_status = "healthy" if all_healthy else "degraded"

    return {
        "status": overall_status,
        "version": state.settings.app_version,
        "checks": {
            "duckdb": duckdb_ok,
            "kuzu": kuzu_ok,
        },
    }
