"""Resolve user times without guessing during daylight-saving changes."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def local_time(value: datetime, timezone: str) -> datetime:
    """Reject ambiguous wall times. Explicit offsets resolve daylight-saving changes."""
    zone = ZoneInfo(timezone)
    if value.tzinfo is not None:
        return value.astimezone(zone)
    # Compare both folds. A naive wall time cannot identify a repeated or missing clock hour.
    first = value.replace(tzinfo=zone, fold=0)
    second = value.replace(tzinfo=zone, fold=1)
    if (
        first.utcoffset() != second.utcoffset()
        or first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != value
    ):
        raise ValueError("This local time is ambiguous or absent. Supply an explicit UTC offset.")
    return first
