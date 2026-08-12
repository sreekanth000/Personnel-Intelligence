"""Gmail email normalization engine.

Normalizes raw Gmail messages and Observations into clean NormalizedEmailObservation models.
Strips noise (HTML markup, quoted reply chains, signatures, redundant whitespace)
to produce high-signal content for LLM extraction while preserving raw observation linkage.

DOES NOT delete or modify original raw email content.
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.config.logging import get_logger
from app.connectors.gmail import extract_mime_bodies, parse_header
from app.domain.normalized_email import NormalizedEmailObservation

if TYPE_CHECKING:
    from app.domain.observations import Observation

logger = get_logger(__name__)

# --- Regex Patterns for Noise Detection ---

# Quoted reply markers
QUOTED_REPLY_PATTERNS = [
    re.compile(r"(?im)^\s*On\s+.*?\s+wrote:\s*$", re.MULTILINE),
    re.compile(r"(?im)^\s*On\s+.*?\s+writes:\s*$", re.MULTILINE),
    re.compile(r"(?im)^\s*-----\s*Original Message\s*-----\s*$", re.MULTILINE),
    re.compile(r"(?im)^\s*-----\s*Forwarded Message\s*-----\s*$", re.MULTILINE),
    re.compile(r"(?im)^\s*From:\s+.*?\nSent:\s+.*?\n", re.MULTILINE),
    re.compile(r"(?im)^\s*_{5,}\s*$", re.MULTILINE),
    re.compile(r"(?im)^\s*-{5,}\s*$", re.MULTILINE),
]

# Signature markers
SIGNATURE_PATTERNS = [
    re.compile(r"(?m)^--\s*$", re.MULTILINE),
    re.compile(
        r"(?im)^\s*(?:Best regards|Regards|Best|Thanks|Thank you|Sincerely|Cheers|Warmly|Yours|Kind regards),\s*$",
        re.MULTILINE,
    ),
    re.compile(r"(?im)^\s*Sent from my (?:iPhone|iPad|Android|mobile|Outlook)\s*$", re.MULTILINE),
]


def clean_html_to_text(html_content: str) -> str:
    """Convert HTML string into clean, plain-text content."""
    if not html_content or not html_content.strip():
        return ""

    # Remove script and style blocks
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", "", html_content)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", "", cleaned)
    cleaned = re.sub(r"(?is)<head.*?>.*?</head>", "", cleaned)

    # Convert line break and block tags to newlines
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</(?:p|div|tr|li|h[1-6])>", "\n", cleaned)

    # Strip remaining HTML tags
    cleaned = re.sub(r"<[^>]+>", "", cleaned)

    # Decode HTML entities
    cleaned = html.unescape(cleaned)

    return cleaned


def normalize_whitespace(text: str) -> str:
    """Normalize line endings and collapse excessive blank lines."""
    if not text:
        return ""

    # Replace carriage returns
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # Strip trailing whitespace on each line
    lines = [line.rstrip() for line in normalized.split("\n")]
    joined = "\n".join(lines)

    # Collapse 3 or more newlines into double newline
    collapsed = re.sub(r"\n{3,}", "\n\n", joined)

    return collapsed.strip()


def separate_quoted_reply(body_text: str) -> tuple[str, str | None]:
    """Separate main body text from inline quoted reply chains.

    Returns:
        tuple[clean_body, quoted_reply]
    """
    if not body_text:
        return "", None

    earliest_split_idx: int | None = None

    # Check for header-style reply markers
    for pattern in QUOTED_REPLY_PATTERNS:
        match = pattern.search(body_text)
        if match:
            idx = match.start()
            if earliest_split_idx is None or idx < earliest_split_idx:
                earliest_split_idx = idx
                match.end()

    # Check for continuous leading '>' block quotes if no header marker was found
    if earliest_split_idx is None:
        lines = body_text.split("\n")
        quote_start_idx: int | None = None

        for i, line in enumerate(lines):
            if line.strip().startswith(">"):
                if quote_start_idx is None:
                    quote_start_idx = i
            else:
                if quote_start_idx is not None and (i - quote_start_idx) >= 2:
                    # Require at least 2 consecutive quote lines
                    break
                quote_start_idx = None

        if quote_start_idx is not None and quote_start_idx > 0:
            main_lines = lines[:quote_start_idx]
            reply_lines = lines[quote_start_idx:]
            return "\n".join(main_lines).strip(), "\n".join(reply_lines).strip()

    if earliest_split_idx is not None:
        main_part = body_text[:earliest_split_idx].strip()
        reply_part = body_text[earliest_split_idx:].strip()
        return main_part, reply_part if reply_part else None

    return body_text.strip(), None


def separate_signature(body_text: str) -> tuple[str, str | None]:
    """Separate main body text from sign-off or email signature.

    Returns:
        tuple[clean_body, signature]
    """
    if not body_text:
        return "", None

    earliest_sig_idx: int | None = None

    for pattern in SIGNATURE_PATTERNS:
        match = pattern.search(body_text)
        if match:
            idx = match.start()
            if (earliest_sig_idx is None or idx > earliest_sig_idx) and idx > (
                len(body_text) * 0.3
            ):
                earliest_sig_idx = idx

    if earliest_sig_idx is not None:
        main_part = body_text[:earliest_sig_idx].strip()
        sig_part = body_text[earliest_sig_idx:].strip()
        return main_part, sig_part if sig_part else None

    return body_text.strip(), None


def extract_attachments_metadata(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Traverse a Gmail MIME payload to extract attachment metadata."""
    attachments: list[dict[str, Any]] = []

    def _walk_parts(part: dict[str, Any]) -> None:
        filename = part.get("filename", "").strip()
        body = part.get("body", {})
        attachment_id = body.get("attachmentId", "")
        size = body.get("size", 0)
        mime_type = part.get("mimeType", "application/octet-stream")

        if filename or attachment_id:
            attachments.append(
                {
                    "filename": filename or "unnamed_attachment",
                    "mime_type": mime_type,
                    "size_bytes": size,
                    "attachment_id": attachment_id,
                }
            )

        for sub_part in part.get("parts", []):
            _walk_parts(sub_part)

    _walk_parts(payload)
    return attachments


def parse_recipient_list(header_val: str) -> list[str]:
    """Parse comma-separated header value into clean recipient addresses."""
    if not header_val:
        return []
    return [addr.strip() for addr in header_val.split(",") if addr.strip()]


class GmailNormalizer:
    """Email normalization engine for Gmail messages and Observations."""

    def normalize_message(
        self,
        msg: dict[str, Any],
        raw_observation_id: str,
    ) -> NormalizedEmailObservation:
        """Normalize a raw Gmail API message dict into NormalizedEmailObservation."""
        msg_id = msg.get("id", "")
        thread_id = msg.get("threadId", "")
        internal_date_ms = int(msg.get("internalDate", 0))

        if internal_date_ms > 0:
            msg_dt = datetime.fromtimestamp(internal_date_ms / 1000.0, tz=UTC)
        else:
            msg_dt = datetime.now(UTC)

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])

        sender = parse_header(headers, "From")
        recipients = parse_recipient_list(parse_header(headers, "To"))
        cc = parse_recipient_list(parse_header(headers, "Cc"))
        subject = parse_header(headers, "Subject")

        plain_text, html_text = extract_mime_bodies(payload)
        attachments = extract_attachments_metadata(payload)

        # Primary content extraction
        if plain_text and plain_text.strip():
            raw_text = plain_text
        elif html_text and html_text.strip():
            raw_text = clean_html_to_text(html_text)
        else:
            raw_text = ""

        # Step 1: Separate quoted reply
        body_without_reply, quoted_reply = separate_quoted_reply(raw_text)

        # Step 2: Separate signature
        clean_body, signature = separate_signature(body_without_reply)

        # Step 3: Whitespace normalization
        final_body = normalize_whitespace(clean_body)
        final_quoted_reply = normalize_whitespace(quoted_reply) if quoted_reply else None
        final_signature = normalize_whitespace(signature) if signature else None

        # Step 4: Content hash over clean body
        content_hash = hashlib.sha256(final_body.encode("utf-8")).hexdigest()

        logger.info(
            "gmail_normalizer.normalized",
            raw_observation_id=raw_observation_id,
            gmail_message_id=msg_id,
            has_quoted_reply=final_quoted_reply is not None,
            has_signature=final_signature is not None,
            attachments_count=len(attachments),
        )

        return NormalizedEmailObservation(
            raw_observation_id=raw_observation_id,
            message_id=msg_id,
            thread_id=thread_id,
            sender=sender,
            recipients=recipients,
            cc=cc,
            subject=subject,
            timestamp=msg_dt,
            body=final_body,
            quoted_reply=final_quoted_reply,
            signature=final_signature,
            attachments_metadata=attachments,
            content_hash=content_hash,
        )

    def normalize_observation(
        self,
        raw_obs: Observation,
    ) -> NormalizedEmailObservation:
        """Normalize an existing raw Observation model into NormalizedEmailObservation."""
        meta = raw_obs.metadata
        msg_id = meta.get("gmail_message_id", raw_obs.source_identifier)
        thread_id = meta.get("gmail_thread_id", "")
        sender = meta.get("sender", "")
        recipients = meta.get("recipients", [])
        subject = meta.get("subject", "")

        raw_text = raw_obs.content
        if raw_obs.content_type == "text/html":
            raw_text = clean_html_to_text(raw_obs.content)

        # Step 1: Separate quoted reply
        body_without_reply, quoted_reply = separate_quoted_reply(raw_text)

        # Step 2: Separate signature
        clean_body, signature = separate_signature(body_without_reply)

        # Step 3: Whitespace normalization
        final_body = normalize_whitespace(clean_body)
        final_quoted_reply = normalize_whitespace(quoted_reply) if quoted_reply else None
        final_signature = normalize_whitespace(signature) if signature else None

        content_hash = hashlib.sha256(final_body.encode("utf-8")).hexdigest()

        return NormalizedEmailObservation(
            raw_observation_id=raw_obs.id,
            message_id=msg_id,
            thread_id=thread_id,
            sender=sender,
            recipients=recipients if isinstance(recipients, list) else [str(recipients)],
            cc=[],
            subject=subject,
            timestamp=raw_obs.observed_at,
            body=final_body,
            quoted_reply=final_quoted_reply,
            signature=final_signature,
            attachments_metadata=[],
            content_hash=content_hash,
        )
