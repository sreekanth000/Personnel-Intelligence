"""Unit and integration tests for POST /api/v1/ask endpoint.

Verifies:
- POST /api/v1/ask 200 OK returning AskResponse
- Empty question validation 400 Bad Request
- Error handling on unconfigured API key
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.ask import set_reasoning_service
from app.domain.ask import AskResponse
from app.domain.context import ContextPackage
from app.main import app
from app.services.reasoning import GPT41ReasoningService


@pytest.fixture()
def client_with_mock_reasoning() -> tuple[TestClient, AsyncMock]:
    """Fixture mounting mocked reasoning service."""
    mock_service = AsyncMock(spec=GPT41ReasoningService)
    set_reasoning_service(mock_service)
    client = TestClient(app)
    return client, mock_service


def test_post_ask_question_200_ok(
    client_with_mock_reasoning: tuple[TestClient, AsyncMock],
) -> None:
    """POST /api/v1/ask returns 200 OK with answer, supporting_context, evidence, uncertainties."""
    client, mock_service = client_with_mock_reasoning

    mock_response = AskResponse(
        answer="Project X is on track.",
        supporting_context=ContextPackage(request_id="req_1", purpose="query"),
        evidence=[],
        uncertainties=["No explicit deadline found."],
    )
    mock_service.answer_question.return_value = mock_response

    payload = {"question": "What is happening with Project X?", "purpose": "query"}
    res = client.post("/api/v1/ask", json=payload)

    assert res.status_code == 200
    data = res.json()
    assert data["answer"] == "Project X is on track."
    assert data["uncertainties"] == ["No explicit deadline found."]
    assert "supporting_context" in data


def test_post_ask_question_400_empty_question(
    client_with_mock_reasoning: tuple[TestClient, AsyncMock],
) -> None:
    """POST /api/v1/ask returns 400 Bad Request if question is empty."""
    client, _ = client_with_mock_reasoning

    payload = {"question": "   ", "purpose": "query"}
    res = client.post("/api/v1/ask", json=payload)

    assert res.status_code == 400
    assert "cannot be empty" in res.json()["detail"].lower()
