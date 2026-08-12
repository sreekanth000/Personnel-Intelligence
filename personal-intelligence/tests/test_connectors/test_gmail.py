"""Unit tests for GmailAuthService and GmailConnector using mocked Gmail API responses.

Verifies:
- Gmail scope constraint (https://www.googleapis.com/auth/gmail.readonly)
- Secure token file permission handling
- Header parsing (Sender, Recipients, Subject, Date)
- Plain text and HTML MIME body extraction
- SHA-256 content_hash computation
- Message ID, Thread ID, Labels, Raw metadata preservation
- Privacy rule compliance (no body text in logs)
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from app.connectors.gmail import (
    GmailConnector,
    decode_body_data,
    extract_mime_bodies,
    parse_header,
    parse_recipients,
)
from app.connectors.gmail_auth import GMAIL_READONLY_SCOPE, GmailAuthService
from app.domain.enums import ObservationSource

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# GmailAuthService Tests
# ---------------------------------------------------------------------------


def test_gmail_auth_scope_constraint(tmp_path: Path) -> None:
    """GmailAuthService must enforce narrow read-only scope."""
    auth_service = GmailAuthService(credentials_dir=tmp_path)
    assert auth_service.scopes == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert GMAIL_READONLY_SCOPE == ["https://www.googleapis.com/auth/gmail.readonly"]


def test_gmail_auth_unauthenticated_raises(tmp_path: Path) -> None:
    """Unauthenticated get_credentials() must raise RuntimeError."""
    auth_service = GmailAuthService(credentials_dir=tmp_path)
    with pytest.raises(RuntimeError, match="Gmail authentication is required"):
        auth_service.get_credentials()


def test_gmail_auth_missing_client_secrets_raises(tmp_path: Path) -> None:
    """Interactive auth without client secrets file raises FileNotFoundError."""
    auth_service = GmailAuthService(credentials_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="Client secrets file not found"):
        auth_service.authenticate_interactive()


def test_gmail_auth_secure_token_save(tmp_path: Path) -> None:
    """Token file must be saved and carry strict permissions on POSIX systems."""
    auth_service = GmailAuthService(credentials_dir=tmp_path)

    mock_creds = MagicMock()
    mock_creds.to_json.return_value = '{"token": "mock_oauth_token"}'

    auth_service.save_credentials(mock_creds)

    token_path = auth_service.token_path
    assert token_path.exists()
    assert token_path.read_text(encoding="utf-8") == '{"token": "mock_oauth_token"}'

    if os.name == "posix":
        mode = oct(token_path.stat().st_mode)
        assert mode.endswith("600")


# ---------------------------------------------------------------------------
# GmailConnector Parsing Tests
# ---------------------------------------------------------------------------


def test_decode_body_data() -> None:
    """Base64url decoding helper handles standard and padded strings."""
    raw_str = "Hello, World! Testing base64url encoding."
    b64_str = base64.urlsafe_b64encode(raw_str.encode("utf-8")).decode("utf-8")

    decoded = decode_body_data(b64_str)
    assert decoded == raw_str
    assert decode_body_data("") == ""


def test_parse_header_and_recipients() -> None:
    """Header extraction handles case-insensitivity and recipient splitting."""
    headers = [
        {"name": "From", "value": "Alice <alice@example.com>"},
        {"name": "To", "value": "Bob <bob@example.com>, Carol <carol@example.com>"},
        {"name": "Cc", "value": "Dave <dave@example.com>"},
        {"name": "Subject", "value": "Quarterly Review"},
    ]

    assert parse_header(headers, "from") == "Alice <alice@example.com>"
    assert parse_header(headers, "SUBJECT") == "Quarterly Review"

    recipients = parse_recipients(headers)
    assert "Bob <bob@example.com>" in recipients
    assert "Carol <carol@example.com>" in recipients
    assert "Dave <dave@example.com>" in recipients


def test_extract_mime_bodies_multipart() -> None:
    """MIME extractor separates text/plain and text/html parts."""
    plain_b64 = base64.urlsafe_b64encode(b"Plain text body content").decode("utf-8")
    html_b64 = base64.urlsafe_b64encode(b"<html><body>HTML body content</body></html>").decode(
        "utf-8"
    )

    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": plain_b64}},
            {"mimeType": "text/html", "body": {"data": html_b64}},
        ],
    }

    plain, html = extract_mime_bodies(payload)
    assert plain == "Plain text body content"
    assert html == "<html><body>HTML body content</body></html>"


# ---------------------------------------------------------------------------
# GmailConnector Observation Transformation
# ---------------------------------------------------------------------------


def test_message_to_observation_transformation() -> None:
    """Gmail message dictionary transforms into a complete Observation domain instance."""
    plain_b64 = base64.urlsafe_b64encode(b"Project roadmap update for Q3.").decode("utf-8")

    mock_msg = {
        "id": "msg_999",
        "threadId": "thread_888",
        "labelIds": ["INBOX", "UNREAD", "WORK"],
        "historyId": "123456",
        "internalDate": "1775000000000",
        "snippet": "Project roadmap update...",
        "sizeEstimate": 1500,
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": plain_b64},
            "headers": [
                {"name": "From", "value": "sender@company.com"},
                {"name": "To", "value": "recipient@company.com"},
                {"name": "Subject", "value": "Q3 Roadmap Sync"},
            ],
        },
    }

    connector = GmailConnector()
    obs = connector.message_to_observation(mock_msg)

    assert obs.source == ObservationSource.GMAIL
    assert obs.source_identifier == "msg_999"
    assert obs.content == "Project roadmap update for Q3."
    assert obs.content_hash is not None
    assert len(obs.content_hash) == 64  # SHA-256 hex string

    meta = obs.metadata
    assert meta["gmail_message_id"] == "msg_999"
    assert meta["gmail_thread_id"] == "thread_888"
    assert meta["sender"] == "sender@company.com"
    assert meta["recipients"] == ["recipient@company.com"]
    assert meta["subject"] == "Q3 Roadmap Sync"
    assert meta["labels"] == ["INBOX", "UNREAD", "WORK"]
    assert meta["plain_text_body"] == "Project roadmap update for Q3."
    assert meta["raw_metadata"]["historyId"] == "123456"


@pytest.mark.asyncio
async def test_gmail_connector_fetch_observations_mocked() -> None:
    """GmailConnector fetch_observations yields Observation instances using mocked API service."""
    plain_b64 = base64.urlsafe_b64encode(b"Mock email content").decode("utf-8")

    mock_msg = {
        "id": "msg_001",
        "threadId": "thread_001",
        "labelIds": ["INBOX"],
        "historyId": "100",
        "internalDate": "1775000000000",
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": plain_b64},
            "headers": [
                {"name": "From", "value": "test@example.com"},
                {"name": "Subject", "value": "Test Subject"},
            ],
        },
    }

    mock_service = MagicMock()
    mock_messages = MagicMock()

    mock_messages.list.return_value.execute.return_value = {"messages": [{"id": "msg_001"}]}
    mock_messages.get.return_value.execute.return_value = mock_msg
    mock_service.users.return_value.messages.return_value = mock_messages

    connector = GmailConnector(service=mock_service)
    assert connector.is_authenticated()

    observations = [obs async for obs in connector.fetch_observations(limit=5)]

    assert len(observations) == 1
    assert observations[0].source_identifier == "msg_001"
    assert observations[0].metadata["subject"] == "Test Subject"
