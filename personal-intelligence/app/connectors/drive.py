"""Google Drive, Notes, and Local Document Files Connector.

Fetches raw document/note observations from Google Drive API or local notes directory
and normalizes them into standard Observation domain objects.

Feeds directly into the evidence recording and deterministic reconciliation pipeline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build

from app.config.logging import get_logger
from app.connectors.base import BaseConnector
from app.connectors.gmail_auth import GmailAuthService
from app.domain.enums import ObservationSource
from app.domain.observations import Observation

logger = get_logger(__name__)


def format_drive_file_as_text(
    filename: str,
    content: str,
    mime_type: str = "text/plain",
    author: str = "Unknown",
    modified_time: str | None = None,
) -> str:
    """Format Google Drive / note file into structured observation text."""
    mod_str = modified_time or datetime.now(UTC).isoformat()
    header = (
        f"Document Title: {filename}\n"
        f"Author / Owner: {author}\n"
        f"MIME Type: {mime_type}\n"
        f"Last Modified: {mod_str}\n"
        "--------------------------------------------------\n"
    )
    return header + content.strip()


class GoogleDriveConnector(BaseConnector):
    """Connector for fetching documents, notes, and files from Google Drive or local workspace notes."""

    def __init__(
        self,
        auth_service: GmailAuthService | None = None,
        service: Any | None = None,
        local_notes_dir: Path | str | None = None,
    ) -> None:
        self._auth_service = auth_service or GmailAuthService()
        self._service = service

        if local_notes_dir is None:
            local_notes_dir = Path(__file__).resolve().parent.parent.parent / "data" / "notes"
        self._local_notes_dir = Path(local_notes_dir)

    @property
    def name(self) -> str:
        """Return connector name."""
        return "google_drive"

    def is_authenticated(self) -> bool:
        """Return True if OAuth credentials exist and are valid or local notes directory exists."""
        if self._service is not None:
            return True
        creds = self._auth_service.load_credentials()
        if creds is not None and creds.valid:
            return True
        return self._local_notes_dir.exists()

    def get_service(self) -> Any:
        """Return authorized Google Drive API service instance."""
        if self._service is not None:
            return self._service

        creds = self._auth_service.load_credentials()
        if not creds or not creds.valid:
            msg = "Google Drive authentication is required. Run authentication setup first."
            raise RuntimeError(msg)

        self._service = build("drive", "v3", credentials=creds)
        return self._service

    def file_to_observation(
        self,
        file_id: str,
        filename: str,
        content: str,
        mime_type: str = "text/plain",
        author: str = "Unknown",
        modified_time: str | None = None,
    ) -> Observation:
        """Convert a document/note resource into an Observation."""
        body_text = format_drive_file_as_text(
            filename=filename,
            content=content,
            mime_type=mime_type,
            author=author,
            modified_time=modified_time,
        )
        mod_iso = modified_time or datetime.now(UTC).isoformat()

        return Observation(
            source=ObservationSource.GOOGLE_DRIVE if not file_id.startswith("local_") else ObservationSource.LOCAL_FILESYSTEM,
            source_identifier=f"drive:{file_id}",
            content=body_text,
            metadata={
                "drive_file_id": file_id,
                "filename": filename,
                "mime_type": mime_type,
                "author": author,
                "modified_time": mod_iso,
            },
            timestamp=mod_iso,
        )

    async def fetch_observations(
        self,
        since: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[Observation]:
        """Fetch files/notes from Google Drive or local data/notes directory."""
        fetched_count = 0

        # 1. Fetch from Google Drive if authenticated
        if self.is_authenticated() and self._auth_service.load_credentials():
            try:
                service = self.get_service()
                logger.info("drive_connector.fetching_google_drive", limit=limit)

                q = "(mimeType='text/plain' or mimeType='text/markdown' or mimeType='application/vnd.google-apps.document')"
                if since:
                    q += f" and modifiedTime > '{since}'"

                files_result = service.files().list(q=q, pageSize=limit, fields="files(id, name, mimeType, modifiedTime, owners)").execute()
                files = files_result.get("files", [])

                for f in files:
                    file_id = f.get("id", "")
                    name = f.get("name", "Untitled Note")
                    mime_type = f.get("mimeType", "text/plain")
                    mod_time = f.get("modifiedTime")
                    owners = f.get("owners", [])
                    owner_name = owners[0].get("displayName") or owners[0].get("emailAddress") if owners else "Unknown"

                    # Download text content
                    content = ""
                    try:
                        if mime_type == "application/vnd.google-apps.document":
                            content_bytes = service.files().export_media(fileId=file_id, mimeType="text/plain").execute()
                            content = content_bytes.decode("utf-8", errors="replace")
                        else:
                            content_bytes = service.files().get_media(fileId=file_id).execute()
                            content = content_bytes.decode("utf-8", errors="replace")
                    except Exception as e:
                        logger.warning("drive_connector.file_download_failed", file_id=file_id, error=str(e))
                        content = f"Note: Document content export for '{name}'."

                    obs = self.file_to_observation(
                        file_id=file_id,
                        filename=name,
                        content=content,
                        mime_type=mime_type,
                        author=owner_name,
                        modified_time=mod_time,
                    )
                    fetched_count += 1
                    yield obs

            except Exception as e:
                logger.warning("drive_connector.google_drive_fetch_warning", error=str(e))

        # 2. Fetch local notes/files from data/notes/ directory
        if self._local_notes_dir.exists():
            logger.info("drive_connector.fetching_local_notes", path=str(self._local_notes_dir))
            for note_path in self._local_notes_dir.glob("*"):
                if note_path.is_file() and note_path.suffix.lower() in (".txt", ".md", ".json"):
                    if fetched_count >= limit:
                        break
                    try:
                        content = note_path.read_text(encoding="utf-8", errors="replace")
                        stat = note_path.stat()
                        mod_iso = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
                        file_id = f"local_{note_path.name}"

                        obs = self.file_to_observation(
                            file_id=file_id,
                            filename=note_path.name,
                            content=content,
                            mime_type="text/markdown" if note_path.suffix == ".md" else "text/plain",
                            author="User",
                            modified_time=mod_iso,
                        )
                        fetched_count += 1
                        yield obs
                    except Exception as e:
                        logger.warning("drive_connector.local_note_read_failed", file=note_path.name, error=str(e))

        logger.info("drive_connector.fetch_complete", count=fetched_count)
