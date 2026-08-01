import os
import json
import asyncio
from openai import AsyncAzureOpenAI
from core.pipeline import PipelineComponent, AsyncQueueEventBus, PipelineEvent


class AzureOpenAIExtractor(PipelineComponent):
    def __init__(self, bus: AsyncQueueEventBus):
        super().__init__(bus)

        self.api_key = os.environ.get("AZURE_AI_API_KEY")
        self.endpoint = os.environ.get("AZURE_AI_ENDPOINT")
        self.deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        self.api_version = os.environ.get("AZURE_AI_API_VERSION", "2024-12-01-preview")

        if not all([self.api_key, self.endpoint, self.deployment]):
            print(
                "[Warning] Azure OpenAI environment variables missing. Semantic extraction will fail if triggered."
            )
            self.client = None
        else:
            self.client = AsyncAzureOpenAI(
                azure_endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=self.api_version,
            )

    async def process(self, event: PipelineEvent) -> None:
        """Takes raw parsed events and extracts structured graph nodes/edges using Azure OpenAI."""
        payload = event.raw_data
        base_entity = payload.get("entity", {})
        raw_text = payload.get("raw_text", "")

        # FIX: Immediately forward the base entity so it is safely written to DuckDB
        # even if Azure API is missing or fails.
        await self.bus.publish(
            "entities_to_build",
            PipelineEvent(
                source="AzureOpenAIExtractor_Base",
                event_type="CREATED",
                raw_data={"base_entity": base_entity, "extraction": {}},
            ),
        )

        if not self.client:
            print(
                f"[AzureExtractor] Skipping LLM extraction for event {event.id} due to missing API configuration."
            )
            return

        if not raw_text:
            return

        prompt = f"""
        Extract the following from the raw text:
        1. A 1 sentence summary.
        2. A list of 2-3 keywords.
        3. A list of distinct sub-entities mentioned (e.g. People, Tasks, Events/Meetings, Commitments, Decisions, Projects/Goals).
        4. A list of relationships between the base item and the entities, or between the entities themselves.

        CRITICAL INSTRUCTION FOR SCHEDULES & TASKS:
        If the text contains any schedules, residency dates, timelines, or meeting information, you MUST extract these as distinct 'Event' or 'Task' entities.
        For every email, you MUST try to extract Events or Tasks if applicable.
        Instead of placing dates in the properties, you MUST extract the exact temporal fields: 'valid_from', 'valid_to', 'occurred_at', 'timezone', and 'recurrence' into the ROOT of the entity object (NOT in properties).
        Always pay special attention to the email Subject and explicitly create an entity for it if it implies a schedule.

        CRITICAL INSTRUCTION FOR RICH CONTEXT:
        Identify and extract:
        - Commitments: who promised what, to whom, due date, status
        - Decisions: decision, alternatives, rationale, owner, date
        - Tasks: assignee, priority, status, due date, blockers, dependencies
        - Meetings: attendees, organizer, agenda, decisions, action items, recurrence
        - Projects/Goals: owner, current health, milestones, deadlines, linked repos/docs
        - Bills: issuer, account_last4, bill_amount, currency, bill_date, due_date, status (unpaid/paid/uncertain)
        - FinancialTransactions: transaction_type (bill_payment/credit/debit/refund), amount, currency, occurred_at, account_last4, counterparty, reference_number
        - BankAccounts: bank_name, account_last4, balance, currency, last_updated
        - Preference/Context: working hours, key collaborators, recurring responsibilities (only when explicitly mentioned).
        Use the following relationship types: OWNS, ASSIGNED_TO, BLOCKED_BY, DEPENDS_ON, DECIDED, COMMITTED_TO, DISCUSSED_IN, SUPERSEDES, PAID_BY.

        Format as JSON matching this exact schema:
        {{
            "summary": "string",
            "topics": ["string"],
            "event_context": {{
                "organization": "string or null",
                "event_category": "lecture|workshop|session|presentation|client meeting|internal|other|null",
                "requires_preparation": "boolean",
                "preparation_requirements": "string or null"
            }},
            "entities": [
                {{
                    "entity_type": "Person|Task|Organization|Event|Commitment|Decision|Meeting|Project|Goal|Preference|Bill|FinancialTransaction|BankAccount",
                    "name": "string",
                    "valid_from": "ISO8601 string or null",
                    "valid_to": "ISO8601 string or null",
                    "occurred_at": "ISO8601 string or null",
                    "timezone": "string or null",
                    "recurrence": "string or null",
                    "supporting_text": "Exact string snippet from the raw text",
                    "identifiers": {{"email": "string", "github": "string", "calendar_id": "string", "drive_id": "string", "repository_url": "string", "file_path": "string"}},
                    "properties": {{
                        "description": "string", 
                        "metadata_tags": ["string"], 
                        "topics": ["string"],
                        "organization": "string",
                        "attendees": ["string"],
                        "location": "string",
                        "event_category": "lecture|workshop|review|client meeting|internal|other",
                        "duration": "string (e.g. 60m)",
                        "preparation_requirements": "string",
                        "linked_files": ["string"],
                        "issuer": "string",
                        "account_last4": "string",
                        "bill_amount": "number",
                        "amount": "number",
                        "balance": "number",
                        "currency": "string",
                        "bank_name": "string",
                        "bill_date": "ISO8601 string",
                        "due_date": "ISO8601 string",
                        "last_updated": "ISO8601 string",
                        "status": "unpaid|paid|uncertain",
                        "transaction_type": "bill_payment|credit|debit|refund",
                        "counterparty": "string",
                        "reference_number": "string",
                        "other_keys": "values"
                    }}
                }}
            ],
            "relationships": [
                {{
                    "source_entity_name": "string (can be the Base Item Name or an Entity Name)",
                    "target_entity_name": "string",
                    "relationship_type": "string (e.g. ASSIGNED_TO, MENTIONS)",
                    "valid_from": "ISO8601 string or null",
                    "valid_to": "ISO8601 string or null",
                    "supporting_text": "Exact string snippet from the raw text",
                    "properties": {{"key": "value"}}
                }}
            ]
        }}
        
        Base Item Name: {base_entity.get('properties', {}).get('name') or base_entity.get('properties', {}).get('subject') or base_entity.get('properties', {}).get('title') or 'Base_Document'}
        Base Item Type: {base_entity.get('type')}
        Base Item Source: {base_entity.get('source')}
        RAW TEXT: {raw_text[:5000]}
        """

        try:
            print(
                f"[AzureExtractor] Extracting semantics for {base_entity.get('type')} via Azure GPT-4..."
            )
            response = await self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise JSON semantic extractor.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                timeout=30.0,  # Force timeout if it hangs
            )

            extraction_json_str = response.choices[0].message.content
            extraction_data = json.loads(extraction_json_str)

            output_payload = {"base_entity": base_entity, "extraction": extraction_data}

            await self.bus.publish(
                "entities_to_build",
                PipelineEvent(
                    source="AzureOpenAIExtractor",
                    event_type="CREATED",
                    raw_data=output_payload,
                ),
            )
            print(
                f"[AzureExtractor] Extraction complete for {base_entity.get('type')}."
            )

        except Exception as e:
            print(f"[AzureExtractor] Error during Azure API call: {e}")
