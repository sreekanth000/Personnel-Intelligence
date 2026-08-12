"""Unit tests for GmailFilterService and GmailFilterConfig."""

import pytest
from pathlib import Path
from app.connectors.gmail_filter import GmailFilterConfig, GmailFilterService


def test_gmail_filter_default_config() -> None:
    """Default filter config excludes promotions, social, spam, and noise senders."""
    cfg = GmailFilterConfig()
    assert "SPAM" in cfg.exclude_labels
    assert "CATEGORY_PROMOTIONS" in cfg.exclude_labels
    assert any("linkedin.com" in p for p in cfg.excluded_sender_patterns)
    assert any("bank" in p for p in cfg.excluded_sender_patterns)
    assert any("otp" in kw for kw in cfg.excluded_subject_keywords)


def test_gmail_filter_query_builder(tmp_path: Path) -> None:
    """build_gmail_query constructs proper search flags."""
    cfg_file = tmp_path / "filter.json"
    service = GmailFilterService(config_path=cfg_file)
    query = service.build_gmail_query("after:2026/01/01")

    assert "after:2026/01/01" in query
    assert "-label:SPAM" in query
    assert "category:primary" in query
    assert "-category:promotions" in query
    assert "-from:linkedin.com" in query


def test_should_process_message_filters_noise(tmp_path: Path) -> None:
    """Filters out bank notifications, LinkedIn emails, social media, and OTPs."""
    cfg_file = tmp_path / "filter.json"
    service = GmailFilterService(config_path=cfg_file)

    # Bank email -> Should be SKIPPED
    ok, reason = service.should_process_message(
        sender="alerts@hdfcbank.com",
        subject="Your monthly e-statement is ready",
        labels=["INBOX"],
    )
    assert not ok
    assert "Excluded sender pattern" in reason

    # LinkedIn notification -> Should be SKIPPED
    ok, reason = service.should_process_message(
        sender="notifications-noreply@linkedin.com",
        subject="Someone viewed your profile",
        labels=["INBOX"],
    )
    assert not ok
    assert "Excluded sender pattern" in reason

    # OTP Email -> Should be SKIPPED
    ok, reason = service.should_process_message(
        sender="auth@service.com",
        subject="Your OTP for login is 123456",
        labels=["INBOX"],
    )
    assert not ok
    assert "Excluded subject keyword" in reason

    # Bulk Unsubscribe Email -> Should be SKIPPED
    ok, reason = service.should_process_message(
        sender="deals@store.com",
        subject="Big summer sale",
        labels=["INBOX"],
        headers={"List-Unsubscribe": "<mailto:unsub@store.com>"},
    )
    assert not ok
    assert "Automated bulk/list email header" in reason


def test_should_process_message_accepts_legitimate_emails(tmp_path: Path) -> None:
    """Accepts legitimate project & work emails from colleagues and organizations."""
    cfg_file = tmp_path / "filter.json"
    service = GmailFilterService(config_path=cfg_file)

    ok, reason = service.should_process_message(
        sender="Alice Smith <alice@acme.com>",
        subject="Project Alpha architecture decisions and roadmap",
        labels=["INBOX", "IMPORTANT"],
    )
    assert ok
    assert reason == "Passed filter criteria"


def test_filter_config_persistence(tmp_path: Path) -> None:
    """Config saves and loads cleanly from JSON file."""
    cfg_file = tmp_path / "custom_filter.json"
    service = GmailFilterService(config_path=cfg_file)

    custom_cfg = GmailFilterConfig(
        exclude_labels=["SPAM", "TRASH"],
        excluded_sender_patterns=["customspam.com"],
        allowed_sender_domains=["acme.com"],
    )
    service.save_config(custom_cfg)

    # Load in new instance
    new_service = GmailFilterService(config_path=cfg_file)
    assert new_service.config.excluded_sender_patterns == ["customspam.com"]
    assert new_service.config.allowed_sender_domains == ["acme.com"]
