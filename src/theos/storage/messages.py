"""Application display metadata, separate from provider and harness state."""

import time

from harness.types import message_from_dict, message_to_dict


def display_metadata(message):
    """Read the timestamp and duration attached by the application."""
    return dict(getattr(message, "_theos_display", {}))


def update_display_metadata(message, values):
    """Merge application display values without changing the model message."""
    display = display_metadata(message)
    display.update(values)
    message._theos_display = display
    return message


def stamp_message(message, *, created_at=None, duration_ms=None):
    """Attach display values without sending them to a model provider."""
    display = {"created_at": time.time() if created_at is None else created_at}
    if duration_ms is not None:
        display["duration_ms"] = max(0, round(duration_ms))
    message._theos_display = display
    return message


def serialize_message(message):
    """Keep display values in the application's existing history JSON."""
    value = message_to_dict(message)
    display = display_metadata(message)
    if display:
        value["display"] = display
    return value


def restore_message(value):
    """Restore saved values without inventing timestamps for older messages."""
    message = message_from_dict(value)
    if isinstance(value.get("display"), dict):
        message._theos_display = dict(value["display"])
    return message
