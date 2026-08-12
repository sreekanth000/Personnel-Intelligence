"""Structured Extraction Service powered by GPT-4.1.

GPT-4.1 acts purely as an information extraction engine in this architecture.
It NEVER:
- updates the Personal World Model directly
- decides whether a claim is true
- resolves contradictions
- invents relationships
- infers unsupported personal attributes
- generates recommendations

It reads a NormalizedEmailObservation and returns a validated StructuredExtraction payload.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from openai import AsyncAzureOpenAI
from pydantic import BaseModel, Field, ValidationError

from app.config.logging import get_logger
from app.domain.claims import Claim
from app.domain.entities import (
    Constraint,
    Decision,
    Entity,
    Event,
    Goal,
    Preference,
    Project,
    Relationship,
)
from app.domain.values import TemporalReference
from app.services.prompts import PRODUCTION_EXTRACTION_SYSTEM_PROMPT

if TYPE_CHECKING:
    from app.domain.normalized_email import NormalizedEmailObservation
    from app.domain.observations import Observation

logger = get_logger(__name__)


class BaseExtractionService(ABC):
    """Abstract interface for LLM-based structured extraction."""

    @abstractmethod
    async def extract_from_observation(self, observation: Observation) -> StructuredExtraction:
        """Extract structured domain objects from a raw observation."""


EXTRACTION_SYSTEM_PROMPT = PRODUCTION_EXTRACTION_SYSTEM_PROMPT


class StructuredExtraction(BaseModel):
    """Payload containing all domain objects extracted by GPT-4.1 from a normalized email."""

    source_observation_id: str = Field(
        description="ID of the raw Observation that generated this extraction."
    )
    entities: list[Entity] = Field(
        default_factory=list, description="Extracted entities (people, orgs, tools, etc.)."
    )
    relationships: list[Relationship] = Field(
        default_factory=list, description="Extracted relationships connecting entities."
    )
    events: list[Event] = Field(
        default_factory=list, description="Extracted scheduled events/meetings."
    )
    claims: list[Claim] = Field(default_factory=list, description="Extracted claims/propositions.")
    goals: list[Goal] = Field(default_factory=list, description="Extracted user goals.")
    projects: list[Project] = Field(default_factory=list, description="Extracted active projects.")
    decisions: list[Decision] = Field(
        default_factory=list, description="Extracted structured decisions."
    )
    constraints: list[Constraint] = Field(
        default_factory=list, description="Extracted constraints."
    )
    preferences: list[Preference] = Field(
        default_factory=list, description="Extracted preferences."
    )
    temporal_references: list[TemporalReference] = Field(
        default_factory=list, description="Extracted temporal references/aspects."
    )


# Backward-compatible alias
from app.services.llm_provider import LLMProviderClient

ExtractionResult = StructuredExtraction


class GPT41Extractor(BaseExtractionService):
    """Extraction service supporting any LLM provider (Azure, OpenAI, Ollama, DeepSeek, Groq, OpenRouter, Custom)."""

    def __init__(
        self,
        azure_endpoint: str | None = None,
        api_key: str | None = None,
        deployment: str = "gpt-4.1",
        api_version: str = "2024-12-01-preview",
        max_retries: int = 3,
        client: Any | None = None,
        provider: str | None = None,
        api_base: str | None = None,
        llm_client: LLMProviderClient | None = None,
    ) -> None:
        self._max_retries = max_retries
        if llm_client is not None:
            self._llm_client = llm_client
        elif client is not None and isinstance(client, LLMProviderClient):
            self._llm_client = client
        else:
            self._llm_client = LLMProviderClient(
                provider=provider,
                model=deployment,
                api_key=api_key,
                api_base=api_base,
                api_version=api_version,
                azure_endpoint=azure_endpoint,
            )

    async def extract_from_observation(self, observation: Observation) -> StructuredExtraction:
        """Extract structured domain models from a raw Observation.

        Normalizes raw Observation first, then performs structured extraction.
        """
        from app.connectors.gmail_normalizer import GmailNormalizer

        normalizer = GmailNormalizer()
        norm_obs = normalizer.normalize_observation(observation)
        return await self.extract_from_normalized_email(norm_obs)

    def get_client(self) -> LLMProviderClient:
        """Return initialized LLMProviderClient."""
        if not self._llm_client.is_configured():
            msg = "LLM provider is not properly configured. Check API key and endpoint/base_url settings."
            logger.error("gpt41_extractor.missing_llm_config")
            raise RuntimeError(msg)
        return self._llm_client

    async def extract_from_normalized_email(
        self,
        norm_obs: NormalizedEmailObservation,
    ) -> StructuredExtraction:
        """Extract structured information from a NormalizedEmailObservation using configured LLM provider.

        Args:
            norm_obs: The noise-filtered NormalizedEmailObservation.

        Returns:
            Validated StructuredExtraction payload.
        """
        client = self.get_client()

        user_prompt = self._build_user_prompt(norm_obs)
        messages: list[Any] = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            logger.info(
                "gpt41_extractor.request_attempt",
                raw_observation_id=norm_obs.raw_observation_id,
                message_id=norm_obs.message_id,
                model=client.model,
                provider=client.provider,
                attempt=attempt,
            )

            try:
                response = await client.create_chat_completion(
                    messages=messages,
                    response_format=StructuredExtraction,
                    temperature=0.0,
                )

                if hasattr(response.choices[0].message, "parsed") and response.choices[0].message.parsed is not None:
                    parsed_result = response.choices[0].message.parsed
                    if isinstance(parsed_result, StructuredExtraction):
                        return parsed_result

                content = response.choices[0].message.content or "{}"
                extraction = self._parse_and_validate_response(content, norm_obs.raw_observation_id)

                logger.info(
                    "gpt41_extractor.extraction_success",
                    raw_observation_id=norm_obs.raw_observation_id,
                    entities_count=len(extraction.entities),
                    relationships_count=len(extraction.relationships),
                    claims_count=len(extraction.claims),
                    events_count=len(extraction.events),
                )
                return extraction

            except (ValidationError, ValueError, json.JSONDecodeError) as err:
                last_error = err
                logger.warning(
                    "gpt41_extractor.parse_validation_failed",
                    attempt=attempt,
                    error=str(err),
                )
                # Append error feedback for retry attempt
                messages.append(
                    {
                        "role": "user",
                        "content": f"The previous output failed validation with error: {err}. Please return valid JSON matching the schema.",
                    }
                )

            except Exception as err:
                last_error = err
                logger.exception("gpt41_extractor.api_call_failed", attempt=attempt)
                break

        msg = f"LLM extraction failed after {self._max_retries} attempts: {last_error}"
        logger.error(
            "gpt41_extractor.failed_all_retries", raw_observation_id=norm_obs.raw_observation_id
        )
        raise RuntimeError(msg) from last_error

    def _build_user_prompt(self, norm_obs: NormalizedEmailObservation) -> str:
        """Construct prompt containing normalized email content and metadata."""
        return (
            f"EMAIL METADATA:\n"
            f"Source Observation ID: {norm_obs.raw_observation_id}\n"
            f"Message ID: {norm_obs.message_id}\n"
            f"Sender: {norm_obs.sender}\n"
            f"Recipients: {', '.join(norm_obs.recipients)}\n"
            f"Subject: {norm_obs.subject}\n"
            f"Timestamp: {norm_obs.timestamp.isoformat()}\n\n"
            f"EMAIL CLEAN BODY:\n"
            f"{norm_obs.body}\n\n"
            f"ATTACHMENTS METADATA: {json.dumps(norm_obs.attachments_metadata)}\n\n"
            "Extract entities, relationships, events, claims, goals, projects, decisions, "
            "constraints, preferences, and temporal_references adhering strictly to all extraction rules."
        )

    def _parse_and_validate_response(
        self,
        response_content: str,
        raw_observation_id: str,
    ) -> StructuredExtraction:
        """Parse JSON response, normalize LLM output quirks, and validate using Pydantic."""
        data: dict[str, Any] = json.loads(response_content)
        data["source_observation_id"] = raw_observation_id

        # Normalize the entire response tree before Pydantic validation
        self._normalize_response_data(data, raw_observation_id)

        extraction = StructuredExtraction.model_validate(data)
        return extraction

    def _normalize_response_data(self, data: dict[str, Any], raw_observation_id: str) -> None:
        """Normalize GPT-4.1 output to match Pydantic schemas.

        Handles common LLM output variations:
        - Uppercase enum values (PERSON -> person)
        - Missing confidence.category (auto-derive from score)
        - evidence_span field naming (text -> text_snippet, start/end -> start_char/end_char)
        - Type coercions (bool -> str for claim values)
        """
        for key in (
            "relationships",
            "claims",
            "events",
            "entities",
            "goals",
            "projects",
            "decisions",
            "constraints",
            "preferences",
        ):
            items = data.get(key, [])
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    # Set source_observation_id
                    if "source_observation_id" not in item:
                        item["source_observation_id"] = raw_observation_id
                    else:
                        item["source_observation_id"] = raw_observation_id

                    # Map 'type' to 'entity_type' if present
                    if "type" in item and "entity_type" not in item:
                        item["entity_type"] = item.pop("type")

                    # Map relationship source/target/type aliases
                    if key == "relationships":
                        if "source" in item and "subject" not in item:
                            item["subject"] = item.pop("source")
                        if "target" in item and "object" not in item:
                            item["object"] = item.pop("target")
                        if "type" in item and "predicate" not in item:
                            item["predicate"] = item.pop("type")
                        if "relation" in item and "predicate" not in item:
                            item["predicate"] = item.pop("relation")
                        if "relationship_type" in item and "predicate" not in item:
                            item["predicate"] = item.pop("relationship_type")
                        if "predicate" not in item:
                            item["predicate"] = "related_to"
                        if "subject" not in item:
                            item["subject"] = "User"
                        if "object" not in item:
                            item["object"] = "Entity"

                    # Map constraint fields
                    if key == "constraints":
                        if "name" not in item:
                            item["name"] = item.get("description") or item.get("constraint_type") or "Constraint"
                        if "constraint_type" not in item:
                            item["constraint_type"] = "policy"
                        if "severity" not in item:
                            item["severity"] = "hard"

                    # Map preference fields
                    if key == "preferences":
                        if "name" not in item:
                            item["name"] = item.get("domain") or item.get("preference") or "Preference"
                        if "domain" not in item:
                            item["domain"] = item.get("name") or "general"
                        if "value" not in item:
                            item["value"] = str(item.get("preference") or item.get("description") or "default")

                    # Map entity name
                    if key == "entities" and "name" not in item:
                        item["name"] = item.get("id") or "Entity"

                    # Map goal name
                    if key == "goals" and "name" not in item:
                        item["name"] = item.get("description") or "Goal"

                    # Map project name
                    if key == "projects" and "name" not in item:
                        item["name"] = item.get("description") or "Project"

                    # Lowercase entity_type
                    if "entity_type" in item and isinstance(item["entity_type"], str):
                        item["entity_type"] = item["entity_type"].lower()

                    # Lowercase predicate
                    if "predicate" in item and isinstance(item["predicate"], str):
                        item["predicate"] = item["predicate"].lower()

                    # Flatten dict subject or object (e.g. {'name': 'Zoom'}) to string
                    for field in ("subject", "object"):
                        if field in item:
                            val = item[field]
                            if isinstance(val, dict):
                                item[field] = val.get("name") or val.get("id") or str(val)

                    # Coerce value to string (for claims with bool values)
                    if "value" in item and not isinstance(item["value"], str):
                        item["value"] = str(item["value"])

                    # Normalize claim status
                    if key == "claims" and "status" in item:
                        status_val = str(item["status"]).lower()
                        valid_statuses = ("proposed", "supported", "contested", "withdrawn", "confirmed")
                        item["status"] = status_val if status_val in valid_statuses else "proposed"

                    # Normalize event starts_at requirement
                    if key == "events" and "starts_at" not in item:
                        from app.domain.values import _utcnow
                        item["starts_at"] = _utcnow().isoformat()

                    # Normalize confidence objects
                    self._normalize_confidence(item)
                    if "confidence" not in item:
                        item["confidence"] = {"score": 0.9, "category": "very_high"}

                    # Normalize evidence_span (convert raw string quote to dict then normalize field names)
                    if "evidence_span" in item:
                        if isinstance(item["evidence_span"], str):
                            item["evidence_span"] = {"quote": item["evidence_span"]}
                        elif not isinstance(item["evidence_span"], dict):
                            item["evidence_span"] = {"quote": str(item["evidence_span"])}
                    else:
                        item["evidence_span"] = {"quote": ""}
                    # Always call the normalizer to map quote/text → text_snippet and add confidence
                    self._normalize_evidence_span(item["evidence_span"])

                    # Normalize evidence_spans (list, used in claims)
                    if "evidence_spans" in item and isinstance(item["evidence_spans"], list):
                        normalized_spans = []
                        for span in item["evidence_spans"]:
                            if isinstance(span, str):
                                span_dict = {"text_snippet": span, "confidence": {"score": 0.9, "category": "very_high"}}
                                normalized_spans.append(span_dict)
                            elif isinstance(span, dict):
                                self._normalize_evidence_span(span)
                                normalized_spans.append(span)
                        item["evidence_spans"] = normalized_spans

        # Normalize temporal_references
        temp_refs = data.get("temporal_references", [])
        if isinstance(temp_refs, list):
            valid_aspects = ("before", "after", "during", "since", "until", "current", "unknown")
            for tr in temp_refs:
                if isinstance(tr, dict) and "aspect" in tr:
                    aspect_val = str(tr["aspect"]).lower()
                    tr["aspect"] = aspect_val if aspect_val in valid_aspects else "unknown"

    def _normalize_confidence(self, item: dict[str, Any]) -> None:
        """Auto-derive category from score if missing in a confidence dict."""
        conf = item.get("confidence")
        if isinstance(conf, dict):
            score = conf.get("score", 0.5)
            if "category" not in conf:
                if score < 0.2:
                    conf["category"] = "very_low"
                elif score < 0.4:
                    conf["category"] = "low"
                elif score < 0.6:
                    conf["category"] = "medium"
                elif score < 0.8:
                    conf["category"] = "high"
                else:
                    conf["category"] = "very_high"
            elif isinstance(conf["category"], str):
                conf["category"] = conf["category"].lower()
        elif isinstance(conf, (int, float)):
            # Confidence given as bare number — wrap it
            score = float(conf)
            if score < 0.2:
                cat = "very_low"
            elif score < 0.4:
                cat = "low"
            elif score < 0.6:
                cat = "medium"
            elif score < 0.8:
                cat = "high"
            else:
                cat = "very_high"
            item["confidence"] = {"score": score, "category": cat}

    def _normalize_evidence_span(self, span: dict[str, Any]) -> None:
        """Normalize evidence_span field names from LLM output to match Pydantic schema."""
        # quote/text/content -> text_snippet
        if "quote" in span and "text_snippet" not in span:
            span["text_snippet"] = span.pop("quote")
        if "text" in span and "text_snippet" not in span:
            span["text_snippet"] = span.pop("text")
        if "content" in span and "text_snippet" not in span:
            span["text_snippet"] = span.pop("content")
        if "text_snippet" not in span or not span["text_snippet"]:
            span["text_snippet"] = "Source quote"

        # start -> start_char
        if "start" in span and "start_char" not in span:
            span["start_char"] = span.pop("start")
        # end -> end_char
        if "end" in span and "end_char" not in span:
            span["end_char"] = span.pop("end")
        # Ensure confidence sub-object
        self._normalize_confidence(span)
        # If no confidence at all, add a default
        if "confidence" not in span:
            span["confidence"] = {"score": 0.8, "category": "very_high"}

