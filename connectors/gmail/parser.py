import base64
from core.pipeline import PipelineComponent, EventBus
from core.models import PipelineEvent, Entity, EntityType

class GmailParser(PipelineComponent):
    def __init__(self, bus: EventBus):
        super().__init__(bus)

    async def process(self, event: PipelineEvent) -> None:
        """
        Receives raw Gmail API message events, decodes headers and body,
        and publishes a normalized 'Email' entity.
        """
        if event.source != "Gmail":
            return

        raw_email = event.raw_data
        payload = raw_email.get("payload", {})
        headers = payload.get("headers", [])
        
        # Extract headers
        def get_header(name: str) -> str:
            return next((h["value"] for h in headers if h["name"].lower() == name.lower()), "")

        sender = get_header("From")
        recipient = get_header("To")
        subject = get_header("Subject")
        date = get_header("Date")

        # Decode body (simplified, assumes single part plain text for now)
        body_data = payload.get("body", {}).get("data", "")
        body_text = ""
        if body_data:
            try:
                # Gmail API uses base64url encoding
                body_text = base64.urlsafe_b64decode(body_data).decode("utf-8")
            except Exception as e:
                print(f"[GmailParser] Failed to decode body for {raw_email.get('id')}: {e}")

        # Build standard Entity
        email_entity = Entity(
            type=EntityType.EMAIL,
            source="Gmail",
            properties={
                "gmail_id": raw_email.get("id"),
                "thread_id": raw_email.get("threadId"),
                "sender": sender,
                "recipient": recipient,
                "subject": subject,
                "date": date
            }
        )

        # Prepare for semantic enrichment
        enriched_event = PipelineEvent(
            source="Gmail_Parser",
            event_type=event.event_type,
            raw_data={"entity": email_entity.model_dump(), "raw_text": f"Subject: {subject}\n\n{body_text}"},
            metadata={"original_event_id": event.id}
        )
        
        await self.bus.publish("emails_to_extract", enriched_event)
        safe_subject = subject.encode('ascii', 'replace').decode('ascii')
        print(f"[GmailParser] Parsed email '{safe_subject}' and queued for AI extraction.")
