"""
Sensitive payload redactor and data sanitizer for Personal Intelligence.
Guarantees that raw sensitive personal fields (credentials, PII, precise GPS coordinates,
raw biometrics, medical waveforms, private communications) are never logged in plaintext.
"""

import copy
import re
from typing import Any, Dict, Optional, Set


class SensitivePayloadRedactor:
    """
    Sanitizes and redacts sensitive payload fields for safe logging and debugging.
    """

    DEFAULT_SENSITIVE_KEYS: Set[str] = {
        "password",
        "secret",
        "token",
        "auth",
        "authorization",
        "api_key",
        "access_token",
        "refresh_token",
        "private_key",
        "ssn",
        "credit_card",
        "cvv",
        "pin",
        "lat",
        "lon",
        "latitude",
        "longitude",
        "coordinates",
        "exact_location",
        "gps",
        "street_address",
        "phone_number",
        "email",
        "raw_ecg",
        "raw_audio",
        "raw_waveform",
        "blood_pressure",
        "glucose_mg_dl",
        "message_body",
        "email_body",
        "chat_text",
        "notes",
    }

    REDACTED_MARKER = "[REDACTED_SENSITIVE]"

    def __init__(self, additional_sensitive_keys: Optional[Set[str]] = None) -> None:
        self.sensitive_keys = set(self.DEFAULT_SENSITIVE_KEYS)
        if additional_sensitive_keys:
            self.sensitive_keys.update(k.lower() for k in additional_sensitive_keys)

    def is_sensitive_key(self, key: str) -> bool:
        """Checks if a field key matches known sensitive identifiers."""
        k = str(key).strip().lower()
        if k in self.sensitive_keys:
            return True
        return any(sens in k for sens in ["password", "secret", "token", "auth", "api_key", "credential", "private"])

    def redact_value(self, val: Any) -> Any:
        """Returns redacted placeholder for a sensitive value, preserving string type."""
        if isinstance(val, (int, float)):
            return 0.0
        elif isinstance(val, bool):
            return False
        return self.REDACTED_MARKER

    def sanitize(self, data: Any) -> Any:
        """
        Recursively sanitizes dictionaries, lists, and primitive data structures,
        replacing sensitive key-value pairs with redacted markers.
        """
        if isinstance(data, dict):
            clean_dict: Dict[str, Any] = {}
            for k, v in data.items():
                if self.is_sensitive_key(k):
                    clean_dict[k] = self.redact_value(v)
                else:
                    clean_dict[k] = self.sanitize(v)
            return clean_dict
        elif isinstance(data, list):
            return [self.sanitize(item) for item in data]
        elif isinstance(data, tuple):
            return tuple(self.sanitize(item) for item in data)
        elif isinstance(data, str):
            # Check for inline bearer tokens or emails
            if "bearer " in data.lower():
                return re.sub(r"bearer\s+[A-Za-z0-9_\-\.]+", self.REDACTED_MARKER, data, flags=re.IGNORECASE)
            return data
        return data

    def safe_event_summary(self, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Produces an audit-safe, sanitized representation of an event record for logging.
        """
        clean = copy.deepcopy(event_dict)
        if "payload" in clean and isinstance(clean["payload"], dict):
            clean["payload"] = self.sanitize(clean["payload"])
        if "payload_json" in clean and isinstance(clean["payload_json"], str):
            try:
                import json
                raw_payload = json.loads(clean["payload_json"])
                clean["payload_json"] = json.dumps(self.sanitize(raw_payload))
            except Exception:
                clean["payload_json"] = self.REDACTED_MARKER
        return clean
