import asyncio
from googleapiclient.discovery import build
from core.pipeline import EventBus
from core.models import PipelineEvent, EventType
from core.auth import authenticate

class GDriveSync:
    def __init__(self, bus: EventBus):
        self.bus = bus
        self.service = None
        self._running = False

    async def authenticate(self):
        """Authenticate using core.auth and build the service."""
        try:
            creds = authenticate()
            self.service = build('drive', 'v3', credentials=creds)
            print("[GDrive Sync] Authenticated with live Drive API.")
        except Exception as e:
            print(f"[GDrive Sync] Authentication failed: {e}")
            raise

    async def _fetch_changes(self):
        """Fetch the latest modified files from Drive."""
        loop = asyncio.get_running_loop()
        
        def fetch():
            if not self.service:
                return []
            
            # We use files().list() here as a simpler polling mechanism for recently modified files
            # For a true push-based or incremental sync, changes().list with a pageToken is preferred
            results = self.service.files().list(
                pageSize=5, 
                fields="files(id, name, mimeType, modifiedTime)",
                orderBy="modifiedTime desc"
            ).execute()
            
            return results.get('files', [])

        files = await loop.run_in_executor(None, fetch)
        return files

    async def run_sync_loop(self, interval_seconds: int = 60):
        self._running = True
        await self.authenticate()
        
        while self._running:
            print("[GDrive Sync] Polling for recently modified files...")
            try:
                files = await self._fetch_changes()
                
                for file_data in files:
                    event = PipelineEvent(
                        source="Google_Drive",
                        event_type=EventType.MODIFIED, # Simplification for the demo
                        raw_data={"file": file_data} # Wrapped in 'file' to match parser expectation
                    )
                    await self.bus.publish("gdrive_events", event)
                    print(f"[GDrive Sync] Pulled live file modification: {file_data.get('name', 'Unknown')}")
                
            except Exception as e:
                print(f"[GDrive Sync] Error during sync: {e}")
            
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self._running = False
