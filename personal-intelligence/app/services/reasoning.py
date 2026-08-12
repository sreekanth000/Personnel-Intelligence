"""GPT-4.1 Reasoning Layer for Personal World Model queries.

Architecture Isolation:
- GPT-4.1 MUST NOT directly access Gmail.
- GPT-4.1 MUST NOT access DuckDB.
- GPT-4.1 MUST NOT access Kuzu.
- GPT-4.1 receives ONLY the filtered ContextPackage from PrivacyFilter.

System Reasoning Prompt Requirements:
- "The supplied context is a representation of personal state."
- "Do not assume information not present in the context."
- "Distinguish facts, user-confirmed state, inferred state and uncertainty."
- "Do not fabricate missing details."
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncAzureOpenAI
from pydantic import BaseModel, Field

from app.config.logging import get_logger
from app.config.settings import Settings, get_settings
from app.domain.ask import AskResponse
from app.domain.context import ContextRequest
from app.services.context import ContextEngine
from app.services.privacy_filter import PrivacyFilter

from app.services.llm_provider import LLMProviderClient

logger = get_logger(__name__)

REASONING_SYSTEM_PROMPT = """You are the reasoning layer for a Personal Intelligence system.

The supplied context is a representation of personal state.
Do not assume information not present in the context.
Distinguish facts, user-confirmed state, inferred state and uncertainty.
Do not fabricate missing details.

Given the user's question and the provided filtered ContextPackage:
1. Answer the question accurately using ONLY the supplied context.
2. List any uncertainties, missing details, or ambiguous aspects explicitly.
"""


class StructuredReasoningOutput(BaseModel):
    """Structured response schema enforced from LLM reasoning call."""

    answer: str = Field(
        description="Clear, fact-grounded answer based strictly on supplied context."
    )
    uncertainties: list[str] = Field(
        default_factory=list,
        description="Explicit list of uncertainties, gaps, or ambiguities.",
    )


class GPT41ReasoningService:
    """Reasoning engine leveraging configurable LLM provider over isolated ContextPackage data."""

    def __init__(
        self,
        settings: Settings | None = None,
        context_engine: ContextEngine | None = None,
        privacy_filter: PrivacyFilter | None = None,
        client: Any | None = None,
        llm_client: LLMProviderClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._context_engine = context_engine or ContextEngine()
        self._privacy_filter = privacy_filter or PrivacyFilter()
        if llm_client is not None:
            self._llm_client = llm_client
        elif client is not None and isinstance(client, LLMProviderClient):
            self._llm_client = client
        else:
            self._llm_client = LLMProviderClient(
                provider=self._settings.llm_provider,
                model=self._settings.llm_model,
                api_key=self._settings.llm_api_key or self._settings.azure_ai_api_key,
                api_base=self._settings.llm_api_base,
                api_version=self._settings.llm_api_version or self._settings.azure_ai_api_version,
                azure_endpoint=self._settings.azure_ai_endpoint,
            )

    def _get_client(self) -> LLMProviderClient:
        if not self._llm_client.is_configured():
            msg = "LLM provider is not properly configured for reasoning. Check API key and endpoint settings."
            raise ValueError(msg)
        return self._llm_client

    async def answer_question(
        self,
        question: str,
        purpose: str = "user_query",
    ) -> AskResponse:
        """Process user question through ContextEngine -> PrivacyFilter -> LLM Reasoning.

        Args:
            question: Natural language question from user.
            purpose: Declared purpose for context retrieval.

        Returns:
            AskResponse containing answer, supporting_context, evidence, and uncertainties.
        """
        logger.info("reasoning.question_received", question=question, purpose=purpose)

        # 1. Retrieve structured context package from ContextEngine (No LLM)
        request = ContextRequest(
            task_intent="reasoning_query",
            query=question,
            purpose=purpose,
        )
        raw_package = await self._context_engine.assemble_context(request)

        # 2. Pass through Privacy Filter / Context Firewall
        filtered_package = self._privacy_filter.filter_package(raw_package)

        # 3. Serialize ContextPackage for LLM input
        package_serialized = json.dumps(filtered_package.model_dump(mode="json"), indent=2)

        prompt_user = f"User Question: {question}\n\nFiltered ContextPackage:\n{package_serialized}"

        # 4. Call LLM reasoning layer
        client = self._get_client()
        logger.info("reasoning.calling_llm", provider=client.provider, model=client.model)

        response = await client.create_chat_completion(
            messages=[
                {"role": "system", "content": REASONING_SYSTEM_PROMPT},
                {"role": "user", "content": prompt_user},
            ],
            response_format=StructuredReasoningOutput,
            temperature=0.0,
        )

        parsed: StructuredReasoningOutput | None = None
        if hasattr(response.choices[0].message, "parsed") and response.choices[0].message.parsed is not None:
            parsed = response.choices[0].message.parsed
        else:
            raw_content = response.choices[0].message.content or "{}"
            data = json.loads(raw_content)
            parsed = StructuredReasoningOutput.model_validate(data)

        # 5. Extract evidence items and build clear provenance lineage mapping
        evidence_items: list[Any] = list(filtered_package.evidence)
        provenance_lineage: list[dict[str, Any]] = []

        for ev in evidence_items:
            source_obs_id = getattr(ev, "source_observation_id", "") or getattr(ev, "observation_id", "")
            source_msg_id = getattr(ev, "source_message_id", "") or getattr(ev, "target_id", "")
            snippet = ""
            if hasattr(ev, "evidence_span") and ev.evidence_span:
                snippet = ev.evidence_span.text_snippet
            elif hasattr(ev, "content") and ev.content:
                snippet = ev.content

            conf = ev.confidence.score if hasattr(ev, "confidence") and hasattr(ev.confidence, "score") else 1.0

            provenance_lineage.append(
                {
                    "evidence_id": getattr(ev, "id", ""),
                    "target_id": getattr(ev, "target_id", ""),
                    "target_type": getattr(ev, "target_type", "evidence"),
                    "source_observation_id": source_obs_id,
                    "source_message_id": source_msg_id,
                    "text_snippet": snippet,
                    "confidence": conf,
                }
            )

        logger.info(
            "reasoning.answer_generated",
            answer_length=len(parsed.answer),
            provenance_count=len(provenance_lineage),
            uncertainties_count=len(parsed.uncertainties),
        )

        return AskResponse(
            answer=parsed.answer,
            supporting_context=filtered_package,
            evidence=evidence_items,
            provenance_lineage=provenance_lineage,
            uncertainties=parsed.uncertainties,
        )
