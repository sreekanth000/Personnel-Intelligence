"""
Exceptions for the Personal Intelligence Event subsystem.
"""


class EventError(Exception):
    """Base exception for all event-related errors."""
    pass


class EventValidationError(EventError):
    """Raised when an event fails validation."""
    pass


class DuplicateEventError(EventError):
    """Raised when attempting to insert an event with an already existing event_hash."""

    def __init__(self, event_hash: str, message: str = None) -> None:
        self.event_hash = event_hash
        msg = message or f"Event with hash '{event_hash}' already exists in event_log."
        super().__init__(msg)
