"""POST /api/v1/ask reasoning API endpoint.

Passes natural language questions through ContextEngine -> PrivacyFilter -> GPT-4.1 Reasoning Layer.
Returns AskResponse with answer, supporting_context, evidence, and uncertainties.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.domain.ask import AskRequest, AskResponse
from app.services.reasoning import GPT41ReasoningService

router = APIRouter(prefix="/api/v1", tags=["reasoning"])

_reasoning_service: GPT41ReasoningService | None = None


def get_reasoning_service() -> GPT41ReasoningService:
    """Dependency injector for GPT41ReasoningService."""
    global _reasoning_service
    if _reasoning_service is None:
        _reasoning_service = GPT41ReasoningService()
    return _reasoning_service


def set_reasoning_service(service: GPT41ReasoningService) -> None:
    """Set global GPT41ReasoningService instance for testing / app lifecycle."""
    global _reasoning_service
    _reasoning_service = service


@router.post(
    "/ask",
    response_model=AskResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask a question over Personal World Model",
)
async def ask_question(body: AskRequest) -> AskResponse:
    """Submit a natural language question about personal state to the GPT-4.1 reasoning layer.

    GPT-4.1 receives ONLY the filtered ContextPackage from PrivacyFilter.
    Does NOT allow GPT-4.1 to directly access Gmail, DuckDB, or Kuzu.
    """
    if not body.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question string cannot be empty.",
        )

    try:
        service = get_reasoning_service()
        return await service.answer_question(question=body.question, purpose=body.purpose)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(err),
        ) from err
