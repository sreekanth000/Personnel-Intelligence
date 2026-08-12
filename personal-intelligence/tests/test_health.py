"""Tests for the health check API endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Test suite for the /health endpoint."""

    def test_health_returns_200(self, client: TestClient) -> None:
        """Health endpoint should return 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_structure(self, client: TestClient) -> None:
        """Health response should have status, version, and checks."""
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "checks" in data
        assert "duckdb" in data["checks"]
        assert "kuzu" in data["checks"]

    def test_health_reports_healthy(self, client: TestClient) -> None:
        """When all databases are up, status should be 'healthy'."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert data["checks"]["duckdb"] is True
        assert data["checks"]["kuzu"] is True

    def test_health_reports_version(self, client: TestClient) -> None:
        """Version in health response should match app version."""
        response = client.get("/health")
        data = response.json()
        assert data["version"] == "0.1.0"
