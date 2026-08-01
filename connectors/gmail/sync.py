import asyncio
from datetime import datetime
from googleapiclient.discovery import build
from core.pipeline import EventBus
from core.models import PipelineEvent, EventType
from core.auth import authenticate

class GmailSync:
    def __init__(self, bus: EventBus):
        self.bus = bus
        self.service = None
        self._running = False

    async def authenticate(self):
        """Authenticate using core.auth and build the service."""
        try:
            creds = authenticate()
            self.service = build('gmail', 'v1', credentials=creds)
            print("[Gmail Sync] Authenticated with live Gmail API.")
        except Exception as e:
            print(f"[Gmail Sync] Authentication failed: {e}")
            raise

    async def _fetch_emails(self):
        """Fetch the latest emails from the primary inbox."""
        # Using loop.run_in_executor to not block the async event loop with synchronous API calls
        loop = asyncio.get_running_loop()
        
        def fetch():
            if not self.service:
                return []
            
            # Filter query: primary inbox only, exclude specified domains and keywords aggressively
            query = "in:inbox category:primary -linkedin -salesforce -careernet -medium"
            results = self.service.users().messages().list(userId='me', maxResults=100, q=query).execute()
            messages = results.get('messages', [])
            
            full_messages = []
            for msg in messages:
                # Fetch full payload for each message
                full_msg = self.service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                full_messages.append(full_msg)
            return full_messages

        # Run the synchronous fetch in a thread pool
        full_emails = await loop.run_in_executor(None, fetch)
        return full_emails

    async def run_sync_loop(self, interval_seconds: int = 60):
        self._running = True
        await self.authenticate()
        
        while self._running:
            print("[Gmail Sync] Polling for new emails...")
            try:
                emails = await self._fetch_emails()
                
                for email_data in emails:
                    event = PipelineEvent(
                        source="Gmail",
                        event_type=EventType.CREATED,
                        raw_data=email_data
                    )
                    await self.bus.publish("gmail_events", event)
                    
                    # Extract subject for logging safely
                    subject = next((h["value"] for h in email_data.get("payload", {}).get("headers", []) if h["name"] == "Subject"), "No Subject")
                    safe_subject = subject.encode('ascii', 'replace').decode('ascii')
                    print(f"[Gmail Sync] Pulled live email: {safe_subject}")
                
            except Exception as e:
                print(f"[Gmail Sync] Error during sync: {e}")
            
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self._running = False
