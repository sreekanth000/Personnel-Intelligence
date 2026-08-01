from core.pipeline import PipelineComponent, EventBus
from core.models import PipelineEvent, Entity, EntityType

class GDriveDownloader(PipelineComponent):
    def __init__(self, bus: EventBus):
        super().__init__(bus)

    async def process(self, event: PipelineEvent) -> None:
        """
        Receives raw GDrive events, downloads or exports the file content,
        and publishes a normalized 'Document' entity.
        """
        if event.source != "Google_Drive" or event.event_type == EventType.DELETED:
            return

        raw_change = event.raw_data
        file_info = raw_change.get("file", {})
        file_id = file_info.get("id")
        mime_type = file_info.get("mimeType", "")
        name = file_info.get("name", "Unknown Document")

        # Mock downloading or exporting
        extracted_text = ""
        if "google-apps.document" in mime_type:
            # Mock export to text
            extracted_text = f"[MOCK CONTENT] This is the exported text of Google Doc: {name}"
            print(f"[GDriveDownloader] Exported Google Doc: {name}")
        elif "google-apps.spreadsheet" in mime_type:
            extracted_text = f"[MOCK CONTENT] Row 1, Col 1 from Sheet: {name}"
            print(f"[GDriveDownloader] Exported Google Sheet: {name}")
        else:
            print(f"[GDriveDownloader] Downloaded raw file: {name}")

        # Build standard Entity
        doc_entity = Entity(
            type=EntityType.DOCUMENT,
            source="Google_Drive",
            properties={
                "gdrive_id": file_id,
                "title": name,
                "mime_type": mime_type,
                "modified_time": file_info.get("modifiedTime")
            }
        )

        # Prepare for semantic enrichment
        enriched_event = PipelineEvent(
            source="GDrive_Downloader",
            event_type=event.event_type,
            raw_data={"entity": doc_entity.model_dump(), "raw_text": extracted_text},
            metadata={"original_event_id": event.id}
        )
        
        await self.bus.publish("documents_to_extract", enriched_event)
