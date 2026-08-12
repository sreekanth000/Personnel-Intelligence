"""Gmail connector for fetching email observations via Gmail API v1.

Parses Gmail messages into immutable Observation domain instances.
Enforces privacy constraints:
- NO logging of email bodies
- NO printing of email contents
- Data remains local by default
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from googleapiclient.discovery import Resource, build

from app.config.logging import get_logger
from app.connectors.base import BaseConnector
from app.connectors.gmail_auth import GmailAuthService
from app.domain.enums import ObservationSource
from app.domain.observations import Observation

from app.connectors.gmail_filter import GmailFilterService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)


def parse_header(headers: list[dict[str, str]], name: str) -> str:
    """Case-insensitively extract a header value from a list of header dicts."""
    target = name.lower()
    for h in headers:
        if h.get("name", "").lower() == target:
            return h.get("value", "")
    return ""


def parse_recipients(headers: list[dict[str, str]]) -> list[str]:
    """Extract and combine To, Cc, and Bcc recipients from message headers."""
    recipients: list[str] = []
    for h_name in ("To", "Cc", "Bcc"):
        val = parse_header(headers, h_name)
        if val:
            for addr in val.split(","):
                cleaned = addr.strip()
                if cleaned:
                    recipients.append(cleaned)
    return recipients


def decode_body_data(data_str: str) -> str:
    """Decode a base64url-encoded body data string."""
    if not data_str:
        return ""
    try:
        # Standard base64url padding fix
        padded = data_str + "=" * (-len(data_str) % 4)
        raw_bytes = base64.urlsafe_b64decode(padded.encode("utf-8"))
        return raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_mime_bodies(payload: dict[str, Any]) -> tuple[str, str]:
    """Recursively traverse a MIME payload to extract plain text and HTML bodies.

    Returns:
        tuple[text_plain_body, text_html_body]
    """
    text_parts: list[str] = []
    html_parts: list[str] = []

    def _walk_parts(part: dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data", "")

        if data:
            decoded = decode_body_data(data)
            if mime_type == "text/plain":
                text_parts.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(decoded)

        # Recurse into sub-parts
        parts = part.get("parts", [])
        for sub_part in parts:
            _walk_parts(sub_part)

    _walk_parts(payload)

    plain_text = "\n".join(text_parts).strip()
    html_text = "\n".join(html_parts).strip()

    return plain_text, html_text


class GmailConnector(BaseConnector):
    """Connector for syncing email messages from the Gmail API."""

    def __init__(
        self,
        auth_service: GmailAuthService | None = None,
        service: Resource | None = None,
        filter_service: GmailFilterService | None = None,
    ) -> None:
        self._auth_service = auth_service or GmailAuthService()
        self._service: Resource | None = service
        self._filter_service = filter_service or GmailFilterService()

    @property
    def name(self) -> str:
        return "gmail"

    def is_authenticated(self) -> bool:
        """Return True if service resource or valid credentials are available."""
        if self._service is not None:
            return True
        creds = self._auth_service.load_credentials()
        return creds is not None and creds.valid

    def get_service(self) -> Resource:
        """Return initialized Gmail API resource."""
        if self._service is None:
            creds = self._auth_service.get_credentials()
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def fetch_observations(
        self,
        since: str | None = None,
        limit: int = 500,
    ) -> AsyncIterator[Observation]:
        """Async generator yielding Observations for matching Gmail messages.

        Args:
            since: Optional Gmail search query modifier (e.g. "after:2026/01/01" or history_id).
            limit: Maximum number of observations to fetch.
        """
        service = self.get_service()
        base_q = f"after:{since}" if since and not since.isdigit() else ""
        query = self._filter_service.build_gmail_query(base_q)

        logger.info("gmail_connector.fetch_started", query=query, limit=limit)
        messages_client = service.users().messages()

        async def _generator() -> AsyncIterator[Observation]:
            fetched_count = 0
            page_token: str | None = None

            while fetched_count < limit:
                batch_size = min(limit - fetched_count, 500)
                list_args: dict[str, Any] = {
                    "userId": "me",
                    "q": query,
                    "maxResults": batch_size,
                }
                if page_token:
                    list_args["pageToken"] = page_token

                list_resp = messages_client.list(**list_args).execute()
                messages = list_resp.get("messages", [])
                logger.info("gmail_connector.page_fetched", count=len(messages), total_so_far=fetched_count)

                if not messages:
                    break

                for msg_meta in messages:
                    if fetched_count >= limit:
                        break
                    msg_id = msg_meta.get("id")
                    if not msg_id:
                        continue

                    full_msg = messages_client.get(userId="me", id=msg_id, format="full").execute()

                    # Check filter rules
                    payload = full_msg.get("payload", {})
                    headers_list = payload.get("headers", [])
                    headers_dict = {h.get("name", ""): h.get("value", "") for h in headers_list if "name" in h}
                    sender = parse_header(headers_list, "From")
                    subject = parse_header(headers_list, "Subject")
                    label_ids = full_msg.get("labelIds", [])

                    should_proc, reason = self._filter_service.should_process_message(
                        sender=sender,
                        subject=subject,
                        labels=label_ids,
                        headers=headers_dict,
                    )

                    if not should_proc:
                        logger.info(
                            "gmail_connector.observation_skipped",
                            gmail_message_id=msg_id,
                            reason=reason,
                        )
                        continue

                    obs = self.message_to_observation(full_msg)
                    fetched_count += 1

                    # PRIVACY SAFEGUARD: Log ONLY message_id and observation_id, never bodies!
                    logger.info(
                        "gmail_connector.observation_produced",
                        observation_id=obs.id,
                        gmail_message_id=msg_id,
                        gmail_thread_id=obs.metadata.get("gmail_thread_id"),
                    )
                    yield obs

                page_token = list_resp.get("nextPageToken")
                if not page_token:
                    break

        return _generator()

    def fetch_thread(self, thread_id: str) -> list[Observation]:
        """Retrieve all messages in a Gmail thread as Observation objects."""
        service = self.get_service()
        logger.info("gmail_connector.fetch_thread", thread_id=thread_id)

        thread_resp = (
            service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        )
        thread_messages = thread_resp.get("messages", [])

        observations: list[Observation] = []
        for msg in thread_messages:
            obs = self.message_to_observation(msg)
            observations.append(obs)

        return observations

    def message_to_observation(self, msg: dict[str, Any]) -> Observation:
        """Convert a raw Gmail API message dict into an immutable Observation.

        Preserves:
        - observation_id
        - source = gmail
        - gmail_message_id
        - gmail_thread_id
        - sender
        - recipients
        - subject
        - timestamp
        - body (plain text + html)
        - labels
        - raw_metadata
        - content_hash
        """
        msg_id = msg.get("id", "")
        thread_id = msg.get("threadId", "")
        label_ids = msg.get("labelIds", [])
        history_id = msg.get("historyId", "")
        internal_date_ms = int(msg.get("internalDate", 0))

        if internal_date_ms > 0:
            msg_dt = datetime.fromtimestamp(internal_date_ms / 1000.0, tz=UTC)
        else:
            msg_dt = datetime.now(UTC)

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])

        sender = parse_header(headers, "From")
        recipients = parse_recipients(headers)
        subject = parse_header(headers, "Subject")

        plain_text, html_text = extract_mime_bodies(payload)

        # Primary content is plain text if available, falling back to html
        content = plain_text if plain_text else html_text

        # Compute SHA-256 content hash
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Build raw metadata dict
        raw_metadata: dict[str, Any] = {
            "snippet": msg.get("snippet", ""),
            "historyId": history_id,
            "internalDate": internal_date_ms,
            "sizeEstimate": msg.get("sizeEstimate", 0),
            "headers": {h.get("name", ""): h.get("value", "") for h in headers if "name" in h},
        }

        # Build comprehensive observation metadata
        metadata: dict[str, Any] = {
            "gmail_message_id": msg_id,
            "gmail_thread_id": thread_id,
            "sender": sender,
            "recipients": recipients,
            "subject": subject,
            "timestamp": msg_dt.isoformat(),
            "labels": label_ids,
            "plain_text_body": plain_text,
            "html_body": html_text,
            "raw_metadata": raw_metadata,
        }

        content_type = "text/plain" if plain_text else "text/html"

        return Observation(
            source=ObservationSource.GMAIL,
            source_identifier=msg_id,
            observed_at=msg_dt,
            content=content,
            content_type=content_type,
            content_hash=content_hash,
            metadata=metadata,
        )
