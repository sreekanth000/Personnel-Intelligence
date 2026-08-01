from core.pipeline import PipelineComponent, EventBus
from core.models import PipelineEvent, Entity, EntityType

class GitHubParser(PipelineComponent):
    def __init__(self, bus: EventBus):
        super().__init__(bus)

    async def process(self, event: PipelineEvent) -> None:
        """
        Receives raw GitHub events (commits), formats them into a Knowledge/Event entity,
        and pushes to the AI extraction queue.
        """
        if event.source != "GitHub":
            return

        raw = event.raw_data
        repo = raw.get("repo")
        msg = raw.get("message", "")
        author = raw.get("author")
        
        # We classify a commit as an EVENT in our World Model
        commit_entity = Entity(
            type=EntityType.EVENT,
            source="GitHub",
            properties={
                "github_id": raw.get("commit_sha"),
                "repo": repo,
                "author": author,
                "title": f"Commit in {repo} by {author}",
                "date": raw.get("date"),
                "url": raw.get("url")
            }
        )

        # Build the text block for the AI to extract meaning from
        raw_text_for_ai = f"Code Commit in repository '{repo}' by '{author}'.\n\nCommit Message:\n{msg}"

        enriched_event = PipelineEvent(
            source="GitHub_Parser",
            event_type=event.event_type,
            raw_data={"entity": commit_entity.model_dump(), "raw_text": raw_text_for_ai},
            metadata={"original_event_id": event.id}
        )
        
        await self.bus.publish("events_to_extract", enriched_event)
        
        safe_msg = msg.split("\n")[0].encode('ascii', 'replace').decode('ascii')
        print(f"[GitHubParser] Parsed commit '{safe_msg[:50]}' and queued for AI extraction.")
