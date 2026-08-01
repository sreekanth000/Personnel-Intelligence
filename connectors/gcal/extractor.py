from core.pipeline import PipelineComponent, EventBus
from core.models import PipelineEvent, Entity, EntityType

class GCalExtractor(PipelineComponent):
    def __init__(self, bus: EventBus):
        super().__init__(bus)

    async def process(self, event: PipelineEvent) -> None:
        """
        Receives raw Google Calendar events, extracts core metadata,
        and publishes a normalized entity to be semantically enriched.
        """
        if event.source != "Google_Calendar":
            return

        raw_event = event.raw_data
        
        from datetime import datetime
        start_str = raw_event.get("start", {}).get("dateTime")
        end_str = raw_event.get("end", {}).get("dateTime")
        
        valid_from = None
        if start_str:
            try: valid_from = datetime.fromisoformat(start_str)
            except: pass
            
        valid_to = None
        if end_str:
            try: valid_to = datetime.fromisoformat(end_str)
            except: pass

        gcal_id = raw_event.get("id")
        
        # Build the standard Entity representation
        meeting_entity = Entity(
            id=f"gcal_{gcal_id}" if gcal_id else None,
            type=EntityType.MEETING,
            source="Google_Calendar",
            valid_from=valid_from,
            valid_to=valid_to,
            properties={
                "title": raw_event.get("summary", "Untitled Event"),
                "description": raw_event.get("description", ""),
                "start_time": start_str,
                "end_time": end_str,
                "attendees": [a.get("email") for a in raw_event.get("attendees", [])],
                "gcal_event_id": gcal_id
            }
        )

        # Prepare for semantic enrichment (extracting inferred goals, projects, etc.)
        enriched_event = PipelineEvent(
            source="GCal_Extractor",
            event_type=event.event_type,
            # Calendar titles often contain the organisation and session topics.
            # Include them in the extraction context instead of relying on the
            # description field being populated.
            raw_data={
                "entity": meeting_entity.model_dump(),
                "raw_text": "\n".join(filter(None, [
                    f"Title: {meeting_entity.properties['title']}",
                    f"Description: {meeting_entity.properties['description']}",
                    f"Attendees: {', '.join(meeting_entity.properties['attendees'])}",
                ])),
            },
            metadata={"original_event_id": event.id}
        )
        
        await self.bus.publish("events_to_extract", enriched_event)
        print(f"[GCalExtractor] Processed meeting '{meeting_entity.properties['title']}' and queued for AI extraction.")
