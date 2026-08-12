"""Unit tests for GmailNormalizer.

Tests:
- normal email
- long email thread
- reply chain
- signature
- HTML email
- empty body
- attachment-only email
- raw & normalized storage separation
"""

from __future__ import annotations

import pytest

from app.connectors.gmail_normalizer import (
    GmailNormalizer,
    clean_html_to_text,
    normalize_whitespace,
    separate_quoted_reply,
    separate_signature,
)
from app.domain.enums import ObservationSource
from app.domain.observations import Observation


@pytest.fixture()
def normalizer() -> GmailNormalizer:
    return GmailNormalizer()


def test_normal_email(normalizer: GmailNormalizer) -> None:
    """Normal email without signatures or quoted replies."""
    raw_obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_normal_01",
        content="Hello Team,\n\nThe sprint review is scheduled for Thursday at 2 PM.",
        metadata={
            "sender": "pm@company.com",
            "recipients": ["team@company.com"],
            "subject": "Sprint Review Reminder",
            "gmail_message_id": "msg_normal_01",
            "gmail_thread_id": "thread_normal_01",
        },
    )

    norm = normalizer.normalize_observation(raw_obs)

    assert norm.raw_observation_id == raw_obs.id
    assert norm.sender == "pm@company.com"
    assert norm.subject == "Sprint Review Reminder"
    assert norm.body == "Hello Team,\n\nThe sprint review is scheduled for Thursday at 2 PM."
    assert norm.quoted_reply is None
    assert norm.signature is None


def test_long_email_thread(normalizer: GmailNormalizer) -> None:
    """Long email thread with multiple nested replies."""
    thread_content = (
        "Sounds good to me, let's proceed with Option B.\n\n"
        "On Tue, Aug 10, 2026 at 10:15 AM Alice <alice@example.com> wrote:\n"
        "> What about Option B?\n"
        ">\n"
        "> On Tue, Aug 10, 2026 at 9:30 AM Bob <bob@example.com> wrote:\n"
        ">> Here are the two options for the architecture migration.\n"
        ">> Option A: In-place update.\n"
        ">> Option B: Parallel deployment."
    )

    raw_obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_thread_01",
        content=thread_content,
        metadata={"subject": "Re: Architecture Migration"},
    )

    norm = normalizer.normalize_observation(raw_obs)

    assert norm.body == "Sounds good to me, let's proceed with Option B."
    assert norm.quoted_reply is not None
    assert "On Tue, Aug 10, 2026 at 10:15 AM Alice" in norm.quoted_reply
    assert "Option A: In-place update." in norm.quoted_reply


def test_reply_chain(normalizer: GmailNormalizer) -> None:
    """Single reply chain with On ... wrote: divider."""
    reply_text = (
        "I've updated the pull request based on your comments.\n\n"
        "On Mon, Aug 11, 2026 at 14:00, Lead Dev <lead@example.com> wrote:\n"
        "Please update unit test assertions before merging."
    )

    clean_body, quoted_reply = separate_quoted_reply(reply_text)

    assert clean_body == "I've updated the pull request based on your comments."
    assert quoted_reply is not None
    assert "On Mon, Aug 11, 2026 at 14:00" in quoted_reply


def test_signature_separation(normalizer: GmailNormalizer) -> None:
    """Signature separation for standard sign-offs and dashes."""
    text_with_sig = (
        "Please find the attached report for Q2 financial review.\n\n"
        "Best regards,\n"
        "John Doe\n"
        "Senior Analyst\n"
        "Acme Corp"
    )

    clean_body, sig = separate_signature(text_with_sig)

    assert clean_body == "Please find the attached report for Q2 financial review."
    assert sig is not None
    assert "Best regards," in sig
    assert "John Doe" in sig


def test_html_email_normalization(normalizer: GmailNormalizer) -> None:
    """HTML email converted to plain text with style/script tags stripped."""
    html_raw = (
        "<html><head><style>body { color: red; }</style></head>"
        "<body>"
        "<h1>Important Update</h1>"
        "<p>The deployment completed <b>successfully</b>.<br>All systems nominal.</p>"
        "<script>console.log('test');</script>"
        "</body></html>"
    )

    text = clean_html_to_text(html_raw)
    normalized = normalize_whitespace(text)

    assert "Important Update" in normalized
    assert "The deployment completed successfully." in normalized
    assert "All systems nominal." in normalized
    assert "console.log" not in normalized
    assert "color: red" not in normalized


def test_empty_body_email(normalizer: GmailNormalizer) -> None:
    """Empty body message handles normalization without errors."""
    raw_obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_empty_01",
        content="",
        metadata={"subject": "Empty body email"},
    )

    norm = normalizer.normalize_observation(raw_obs)

    assert norm.body == ""
    assert norm.quoted_reply is None
    assert norm.signature is None
    assert norm.content_hash is not None


def test_attachment_only_email(normalizer: GmailNormalizer) -> None:
    """Attachment-only email preserves attachment metadata."""
    msg_dict = {
        "id": "msg_attach_01",
        "threadId": "thread_attach_01",
        "internalDate": "1775000000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "scanner@office.com"},
                {"name": "To", "value": "user@company.com"},
                {"name": "Subject", "value": "Scanned Document.pdf"},
            ],
            "parts": [
                {
                    "filename": "Scanned_Invoice_2026.pdf",
                    "mimeType": "application/pdf",
                    "body": {"attachmentId": "attach_12345", "size": 204800},
                }
            ],
        },
    }

    norm = normalizer.normalize_message(msg_dict, raw_observation_id="raw_obs_attach_01")

    assert norm.raw_observation_id == "raw_obs_attach_01"
    assert norm.message_id == "msg_attach_01"
    assert len(norm.attachments_metadata) == 1

    attach = norm.attachments_metadata[0]
    assert attach["filename"] == "Scanned_Invoice_2026.pdf"
    assert attach["mime_type"] == "application/pdf"
    assert attach["size_bytes"] == 204800
    assert attach["attachment_id"] == "attach_12345"


def test_raw_and_normalized_storage_separation(normalizer: GmailNormalizer) -> None:
    """Raw observation and normalized observation remain distinct objects."""
    raw_content = (
        "Raw email message with full headers and quotes.\nOn Yesterday wrote:\nOld message"
    )
    raw_obs = Observation(
        source=ObservationSource.GMAIL,
        source_identifier="msg_sep_01",
        content=raw_content,
        metadata={"subject": "Storage Separation Test"},
    )

    norm_obs = normalizer.normalize_observation(raw_obs)

    # Verify raw observation content is NOT modified or deleted
    assert raw_obs.content == raw_content
    assert "On Yesterday wrote:" in raw_obs.content

    # Verify normalized observation has clean body and separated quoted reply
    assert norm_obs.raw_observation_id == raw_obs.id
    assert norm_obs.body == "Raw email message with full headers and quotes."
    assert norm_obs.quoted_reply is not None
    assert "On Yesterday wrote:" in norm_obs.quoted_reply
