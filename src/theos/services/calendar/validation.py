"""Validate calendar paths, event versions, and local event times."""

import re
from datetime import UTC, date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from theos.services.reminders.timezones import local_time


def resource_id(value):
    if (
        not value
        or len(value) > 1024
        or value in {".", ".."}
        or any(char.isspace() or ord(char) < 32 or char in "/\\" for char in value)
    ):
        raise ValueError("Use a calendar or event ID returned by the Calendar tools.")
    return quote(value, safe="")


def timezone_name(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise ValueError("Use an IANA timezone such as Asia/Kolkata or UTC.") from error
    return value


def timed_range(start, end, timezone):
    timezone_name(timezone)
    try:
        # A date-only value must use all-day event semantics instead.
        if "T" not in start or "T" not in end:
            raise ValueError("Missing event time")
        first = local_time(datetime.fromisoformat(start), timezone)
        last = local_time(datetime.fromisoformat(end), timezone)
    except ValueError as error:
        raise ValueError(
            "Use ISO date-times. Ambiguous or missing local times need an explicit UTC offset."
        ) from error
    if last.astimezone(UTC) <= first.astimezone(UTC):
        raise ValueError("The end must be after the start.")
    return first.isoformat(), last.isoformat()


def event_times(start, end, timezone, all_day=False):
    if all_day:
        try:
            first, last = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError as error:
            raise ValueError(
                "All-day events need YYYY-MM-DD dates and an exclusive end date."
            ) from error
        if last <= first:
            raise ValueError("The exclusive end date must be after the start date.")
        return {"start": {"date": first.isoformat()}, "end": {"date": last.isoformat()}}
    first, last = timed_range(start, end, timezone)
    return {
        "start": {"dateTime": first, "timeZone": timezone},
        "end": {"dateTime": last, "timeZone": timezone},
    }


def event_version(value):
    if not re.fullmatch(r'"[A-Za-z0-9_+=/\-]{1,256}"', value):
        raise ValueError("Read the event first and supply its exact quoted etag.")
    return value


def editable_event(event, etag):
    if event.get("etag") != event_version(etag):
        raise ValueError("The event changed. Read it again before changing or deleting it.")
    if event.get("recurrence") or event.get("recurringEventId") or event.get("originalStartTime"):
        raise ValueError("Recurring-event changes are not supported yet.")
    if event.get("attendees") or event.get("attendeesOmitted"):
        raise ValueError("Changes to events with attendees are not supported yet.")
    if event.get("eventType", "default") != "default" or event.get("status") == "cancelled":
        raise ValueError("Only active, regular single events can be changed with these tools.")
