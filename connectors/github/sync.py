import asyncio
import os
import requests
from datetime import datetime, timedelta
from core.pipeline import EventBus
from core.models import PipelineEvent, EventType

class GitHubSync:
    def __init__(self, bus: EventBus):
        self.bus = bus
        self.token = os.environ.get("GITHUB_TOKEN")
        self._running = False
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {self.token}" if self.token else None
        }

    async def _fetch_recent_commits(self):
        """Fetches recent commits from the user's repositories."""
        if not self.token:
            print("[GitHub Sync] Warning: GITHUB_TOKEN not set. Skipping sync.")
            return []
            
        import asyncio
        loop = asyncio.get_running_loop()
        
        def fetch():
            try:
                # Get authenticated user's repos
                repos_resp = requests.get("https://api.github.com/user/repos?sort=updated&per_page=3", headers=self.headers)
                repos_resp.raise_for_status()
                repos = repos_resp.json()
                
                recent_events = []
                for repo in repos:
                    repo_name = repo["full_name"]
                    # Get commits for the repo
                    commits_resp = requests.get(f"https://api.github.com/repos/{repo_name}/commits?per_page=2", headers=self.headers)
                    if commits_resp.status_code == 200:
                        for commit in commits_resp.json():
                            recent_events.append({
                                "repo": repo_name,
                                "commit_sha": commit["sha"],
                                "message": commit["commit"]["message"],
                                "author": commit["commit"]["author"]["name"],
                                "date": commit["commit"]["author"]["date"],
                                "url": commit["html_url"]
                            })
                return recent_events
            except Exception as e:
                print(f"[GitHub Sync] API Error: {e}")
                return []

        return await loop.run_in_executor(None, fetch)

    async def run_sync_loop(self, interval_seconds: int = 120):
        self._running = True
        print("[GitHub Sync] Initialized.")
        
        while self._running:
            print("[GitHub Sync] Polling for recent commits...")
            commits = await self._fetch_recent_commits()
            
            for commit in commits:
                event = PipelineEvent(
                    source="GitHub",
                    event_type=EventType.CREATED,
                    raw_data=commit
                )
                await self.bus.publish("github_events", event)
                
                msg = commit.get("message", "").split("\n")[0]
                print(f"[GitHub Sync] Pulled commit: {msg[:50]}...")
                
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self._running = False
