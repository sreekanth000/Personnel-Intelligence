import os
from core.pipeline import PipelineComponent, EventBus
from core.models import PipelineEvent, Entity, EntityType

class LocalFSParser(PipelineComponent):
    def __init__(self, bus: EventBus):
        super().__init__(bus)

    async def process(self, event: PipelineEvent) -> None:
        """
        Receives raw filesystem events, parses the file content,
        and publishes a normalized 'parsed_document' event.
        """
        if event.source != "Local_FS":
            return

        path = event.raw_data.get("path")
        if not path or not os.path.exists(path):
            return

        # Simple extraction logic - in a real app, use pypdf, python-docx, etc.
        extracted_text = ""
        try:
            # We'll only try to read it if it's a known text file for this demo
            ext = event.metadata.get("extension", "").lower()
            if ext in [".txt", ".md", ".csv", ".json", ".py"]:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    extracted_text = f.read(5000) # Read up to 5k chars for safety
        except Exception as e:
            print(f"[LocalFSParser] Failed to read {path}: {e}")

        # Create a basic Document entity representation
        doc_entity = Entity(
            type=EntityType.DOCUMENT,
            source="Local_FS",
            properties={
                "title": os.path.basename(path),
                "filepath": path,
                "extension": event.metadata.get("extension"),
                "size": event.metadata.get("size"),
                "content_preview": extracted_text[:1000] # Pass preview to AI
            }
        )

        # Publish to the AI extraction stage
        enriched_event = PipelineEvent(
            source="Local_FS_Parser",
            event_type=event.event_type,
            raw_data={"entity": doc_entity.model_dump(), "raw_text": extracted_text},
            metadata={"original_event_id": event.id}
        )
        
        await self.bus.publish("documents_to_extract", enriched_event)
        print(f"[LocalFSParser] Parsed {path} and queued for extraction.")
