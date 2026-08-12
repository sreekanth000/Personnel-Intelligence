"""Configurable Gmail filtering service.

Allows users to configure:
1. Included / excluded Gmail labels/folders (e.g. INBOX, excluding PROMOTIONS, SOCIAL, SPAM)
2. Excluded sender domains & patterns (banks, LinkedIn, social media, newsletters, no-reply)
3. Excluded subject keywords (OTP, statements, transaction alerts, notifications)
4. Allowed sender domains / personal email filters
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config.logging import get_logger

logger = get_logger(__name__)


class GmailFilterConfig(BaseModel):
    """Configurable filter settings for Gmail synchronization."""

    include_labels: list[str] = Field(
        default_factory=lambda: ["INBOX", "Primary"],
        description="Gmail labels/folders or categories to include (e.g. INBOX, Primary, or sub-folders like Work/ProjectAlpha).",
    )
    exclude_labels: list[str] = Field(
        default_factory=lambda: [
            "SPAM",
            "TRASH",
            "Social",
            "Promotions",
            "Updates",
            "Forums",
            "CATEGORY_PROMOTIONS",
            "CATEGORY_SOCIAL",
            "CATEGORY_UPDATES",
            "CATEGORY_FORUMS",
        ],
        description="Gmail labels, sub-folders, or category tabs to exclude.",
    )
    excluded_sender_patterns: list[str] = Field(
        default_factory=lambda: [
            "linkedin.com",
            "facebookmail.com",
            "twitter.com",
            "x.com",
            "instagram.com",
            "pinterest.com",
            "tiktok.com",
            "no-reply",
            "noreply",
            "donotreply",
            "notifications@",
            "alerts@",
            "newsletters@",
            "marketing@",
            "bank",
            "paypal.com",
            "stripe.com",
            "hdfc",
            "icici",
            "chase.com",
            "wellsfargo.com",
            "citibank.com",
        ],
        description="Substrings or regex patterns in sender email/name to ignore.",
    )
    excluded_subject_keywords: list[str] = Field(
        default_factory=lambda: [
            "otp",
            "verification code",
            "security code",
            "account statement",
            "bank statement",
            "e-statement",
            "transaction alert",
            "payment received",
            "unsubscribe",
            "newsletter",
            "promotional",
            "digest",
        ],
        description="Keywords in email subjects to ignore.",
    )
    allowed_sender_domains: list[str] = Field(
        default_factory=list,
        description="If non-empty, only emails from these sender domains will be processed.",
    )
    ignore_bulk_emails: bool = Field(
        default=True,
        description="Ignore emails with List-Unsubscribe or Precedence: bulk headers.",
    )
    max_emails_per_sync: int = Field(
        default=50,
        description="Maximum number of emails to fetch and process per sync cycle (e.g. 50, 100, 500).",
    )


class GmailFilterService:
    """Evaluates Gmail messages against configurable filter rules."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or (Path("data") / "gmail_filter_config.json")
        self.config = self.load_config()

    def load_config(self) -> GmailFilterConfig:
        """Load configuration from JSON file or return defaults if not present."""
        if self._config_path.exists():
            try:
                with open(self._config_path, encoding="utf-8") as f:
                    data = json.load(f)
                    return GmailFilterConfig.model_validate(data)
            except Exception as err:
                logger.warning("gmail_filter.load_failed_using_defaults", error=str(err))
        
        default_cfg = GmailFilterConfig()
        self.save_config(default_cfg)
        return default_cfg

    def save_config(self, config: GmailFilterConfig) -> None:
        """Persist current filter config to JSON file for easy editing."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                f.write(config.model_dump_json(indent=2))
            self.config = config
            logger.info("gmail_filter.config_saved", path=str(self._config_path))
        except Exception as err:
            logger.error("gmail_filter.save_failed", error=str(err))

    def build_gmail_query(self, base_query: str = "") -> str:
        """Construct a Gmail API search query string based on folder & label rules."""
        query_parts: list[str] = []
        if base_query:
            query_parts.append(base_query)

        # Included labels / category tabs
        for label in self.config.include_labels:
            lbl_upper = label.upper()
            if lbl_upper in ("PRIMARY", "PERSONAL", "CATEGORY_PERSONAL"):
                query_parts.append("category:primary")
            elif label.startswith("category:") or label.startswith("label:"):
                query_parts.append(label)
            elif lbl_upper.startswith("CATEGORY_"):
                query_parts.append(f"label:{label}")
            else:
                query_parts.append(f"label:{label}")

        # Excluded labels / category tabs
        for label in self.config.exclude_labels:
            lbl_upper = label.upper()
            if lbl_upper in ("SOCIAL", "CATEGORY_SOCIAL"):
                query_parts.append("-category:social")
            elif lbl_upper in ("PROMOTIONS", "PROMOTION", "CATEGORY_PROMOTIONS"):
                query_parts.append("-category:promotions")
            elif lbl_upper in ("UPDATES", "UPDATE", "CATEGORY_UPDATES"):
                query_parts.append("-category:updates")
            elif lbl_upper in ("FORUMS", "FORUM", "CATEGORY_FORUMS"):
                query_parts.append("-category:forums")
            elif label.startswith("category:") or label.startswith("label:"):
                query_parts.append(f"-{label}")
            else:
                query_parts.append(f"-label:{label}")

        # Excluded sender domains in search query
        for pattern in self.config.excluded_sender_patterns:
            if "." in pattern and not pattern.startswith("@"):
                query_parts.append(f"-from:{pattern}")

        return " ".join(query_parts).strip()

    def should_process_message(
        self,
        sender: str,
        subject: str,
        labels: list[str],
        headers: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Evaluate whether an email should be processed or skipped.

        Returns:
            (should_process: bool, reason: str)
        """
        # 1. Label / category tab exclusion check
        excluded_upper = [l.upper() for l in self.config.exclude_labels]
        for label in labels:
            lbl_u = label.upper()
            if (
                lbl_u in excluded_upper
                or (lbl_u == "CATEGORY_SOCIAL" and any(x in excluded_upper for x in ("SOCIAL", "CATEGORY_SOCIAL")))
                or (lbl_u == "CATEGORY_PROMOTIONS" and any(x in excluded_upper for x in ("PROMOTIONS", "PROMOTION", "CATEGORY_PROMOTIONS")))
                or (lbl_u == "CATEGORY_UPDATES" and any(x in excluded_upper for x in ("UPDATES", "UPDATE", "CATEGORY_UPDATES")))
                or (lbl_u == "CATEGORY_FORUMS" and any(x in excluded_upper for x in ("FORUMS", "FORUM", "CATEGORY_FORUMS")))
            ):
                return False, f"Excluded label/category: {label}"

        # 2. Excluded sender pattern check
        sender_lower = sender.lower()
        for pattern in self.config.excluded_sender_patterns:
            if pattern.lower() in sender_lower:
                return False, f"Excluded sender pattern: {pattern}"

        # 3. Allowed domains check (if specified)
        if self.config.allowed_sender_domains:
            allowed = any(dom.lower() in sender_lower for dom in self.config.allowed_sender_domains)
            if not allowed:
                return False, "Sender domain not in allowed_sender_domains"

        # 4. Excluded subject keyword check
        subj_lower = subject.lower()
        for kw in self.config.excluded_subject_keywords:
            if kw.lower() in subj_lower:
                return False, f"Excluded subject keyword: {kw}"

        # 5. Ignore bulk/list headers check
        if self.config.ignore_bulk_emails and headers:
            headers_lower = {str(k).lower(): str(v).lower() for k, v in headers.items()}
            if "list-unsubscribe" in headers_lower or headers_lower.get("precedence") == "bulk":
                return False, "Automated bulk/list email header detected"

        return True, "Passed filter criteria"
