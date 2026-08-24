"""
Local Voice Notes & Meeting Summaries Adapter.

Provides ingestion, structured parsing, action item extraction, and vectorization
for local voice recordings, audio transcripts, and meeting summaries.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.events.models import format_iso8601, ensure_timezone_aware

logger = logging.getLogger(__name__)


@dataclass
class VoiceNoteItem:
    """Structured representation of a local voice note or meeting summary."""
    id: str = field(default_factory=lambda: f"vn-{uuid.uuid4().hex[:8]}")
    title: str = "Voice Note"
    transcript: str = ""
    summary: str = ""
    action_items: List[str] = field(default_factory=list)
    attendees: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: format_iso8601(datetime.now(timezone.utc)))
    duration_seconds: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    provenance: str = "local_voice_recording"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "transcript": self.transcript,
            "summary": self.summary,
            "action_items": self.action_items,
            "attendees": self.attendees,
            "created_at": self.created_at,
            "duration_seconds": self.duration_seconds,
            "tags": self.tags,
            "provenance": self.provenance,
        }


class VoiceNotesAdapter:
    """
    Manages ingestion of voice recordings, meeting transcripts, and offline spoken memos.
    """

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self.storage_dir = storage_dir or (Path.home() / ".personal_intelligence" / "voice_notes")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def parse_note_content(self, text: str, title: Optional[str] = None) -> VoiceNoteItem:
        """
        Parses raw text or transcript into structured summary and action items.
        """
        clean_text = text.strip()
        lines = [l.strip() for l in clean_text.splitlines() if l.strip()]

        # Extract title
        note_title = title
        if not note_title and lines:
            first_line = lines[0].lstrip("#").strip()
            note_title = first_line[:50] if len(first_line) > 5 else "Voice Note"
        if not note_title:
            note_title = "Voice Memo"

        # Extract Action Items using bullet or keyword matching
        action_items = []
        for line in lines:
            if any(line.lower().startswith(p) for p in ("- [ ]", "* [ ]", "todo:", "action:", "action item:", "follow up:", "deliverable:")):
                cleaned = re.sub(r"^[-*]\s*(\[[ xX]\])?\s*(todo:|action:|action item:|follow up:)?\s*", "", line, flags=re.IGNORECASE)
                if cleaned:
                    action_items.append(cleaned.strip())
            elif "need to " in line.lower() or "will deliver " in line.lower() or "promised to " in line.lower():
                action_items.append(line.strip())

        # Generate summary
        summary = lines[0] if lines else "Recorded spoken memo."
        if len(lines) > 1:
            summary = f"{lines[0]} ({len(lines)} key discussion points recorded)."

        # Extract participants if mentioned
        attendees = []
        for line in lines:
            if "attendees:" in line.lower() or "participants:" in line.lower():
                names = re.split(r"[,;]", line.split(":", 1)[1])
                attendees.extend([n.strip() for n in names if n.strip()])

        note_id = f"vn-{uuid.uuid4().hex[:8]}"
        return VoiceNoteItem(
            id=note_id,
            title=note_title,
            transcript=clean_text,
            summary=summary,
            action_items=action_items[:10],
            attendees=attendees,
            provenance=f"voice_note:{note_id}",
        )

    def save_note_file(self, item: VoiceNoteItem) -> Path:
        """Persists voice note JSON to local disk."""
        target = self.storage_dir / f"{item.id}.json"
        with open(target, "w", encoding="utf-8") as f:
            json.dump(item.to_dict(), f, indent=2, ensure_ascii=False)
        return target
