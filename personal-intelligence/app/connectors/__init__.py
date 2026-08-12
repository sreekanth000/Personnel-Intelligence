"""Connectors package — external data source connectors."""

from app.connectors.base import BaseConnector
from app.connectors.calendar import GoogleCalendarConnector, format_calendar_event_as_text
from app.connectors.drive import GoogleDriveConnector, format_drive_file_as_text
from app.connectors.gmail import GmailConnector
from app.connectors.gmail_auth import GMAIL_READONLY_SCOPE, GmailAuthService
from app.connectors.gmail_normalizer import GmailNormalizer

__all__ = [
    "GMAIL_READONLY_SCOPE",
    "BaseConnector",
    "GmailAuthService",
    "GmailConnector",
    "GmailNormalizer",
    "GoogleCalendarConnector",
    "GoogleDriveConnector",
    "format_calendar_event_as_text",
    "format_drive_file_as_text",
]
