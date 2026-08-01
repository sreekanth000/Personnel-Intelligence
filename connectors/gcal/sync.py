import asyncio
from datetime import datetime
from googleapiclient.discovery import build
from core.pipeline import EventBus
from core.models import PipelineEvent, EventType
from core.auth import authenticate

class GoogleCalendarSync:
    def __init__(self, bus: EventBus):
        self.bus = bus
        self.service = None
        self._running = False

    async def authenticate(self):
        """Authenticate using core.auth and build the service."""
        try:
            creds = authenticate()
            self.service = build('calendar', 'v3', credentials=creds)
            print("[GCal Sync] Authenticated with live Calendar API.")
        except Exception as e:
            print(f"[GCal Sync] Authentication failed: {e}")
            raise

    async def _fetch_events(self):
        """Fetch the upcoming events from the primary calendar."""
        loop = asyncio.get_running_loop()
        
        def fetch():
            if not self.service:
                return []
            
            # Fetch events from now onwards
            now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
            events_result = self.service.events().list(
                calendarId='primary', 
                timeMin=now,
                maxResults=10, 
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            return events_result.get('items', [])

        events = await loop.run_in_executor(None, fetch)
        return events

    async def run_sync_loop(self, interval_seconds: int = 60):
        self._running = True
        await self.authenticate()
        
        while self._running:
            print("[GCal Sync] Polling for upcoming events...")
            try:
                events = await self._fetch_events()
                
                for event_data in events:
                    event = PipelineEvent(
                        source="Google_Calendar",
                        event_type=EventType.CREATED,
                        raw_data=event_data
                    )
                    await self.bus.publish("gcal_events", event)
                    print(f"[GCal Sync] Pulled live event: {event_data.get('summary', 'Untitled')}")
                
            except Exception as e:
                print(f"[GCal Sync] Error during sync: {e}")
            
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self._running = False
