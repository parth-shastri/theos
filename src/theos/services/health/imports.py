"""Paginated Google Health reads and complete daily summaries."""

import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_start

from theos.services.errors import ServiceError
from theos.services.health.normalize import (
    DATA_COMPONENTS,
    SAMPLE_DATA_TYPES,
    normalize_data_points,
)

DATA_TYPES = tuple(DATA_COMPONENTS)
SUMMARY_VERSION = 2


async def read_summary(client, owner, start_date=None, end_date=None, *, refresh=False):
    """Read a current cached summary or import the requested range before returning."""
    if (start_date is None) != (end_date is None):
        raise ValueError("Provide both start_date and end_date.")
    if start_date and end_date:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date.")
        if (end_date - start_date).days > 30:
            raise ValueError("Read no more than 31 days at a time.")
    try:
        cached = client.db.record(owner, "health", "summary")
    except LookupError:
        cached = None
    current = bool(cached and cached.get("schema_version") == SUMMARY_VERSION)
    if start_date and end_date:
        covers = (
            current
            and datetime.fromisoformat(cached["from"]).date() <= start_date
            and end_date <= datetime.fromisoformat(cached["to"]).date()
        )
        if refresh or not covers:
            return await client.import_summary(owner, start_date, end_date, save=False)
    elif refresh or not current:
        return await client.import_summary(owner)
    return cached


def range_filter(kind, start, end, *, calendar_dates=False):
    """Select the provider time field for each health data type."""
    name = kind.replace("-", "_")
    if kind.startswith("daily-"):
        field = f"{name}.date"
        start, end = start[:10], end[:10]
    elif kind == "exercise":
        field = "exercise.interval.civil_start_time"
        start, end = start[:10], end[:10]
    elif kind in SAMPLE_DATA_TYPES:
        if calendar_dates:
            field = f"{name}.sample_time.civil_time"
            start, end = start[:10], end[:10]
        else:
            field = f"{name}.sample_time.physical_time"
    elif kind == "sleep":
        field = "sleep.interval.end_time"
    else:
        field = f"{name}.interval.start_time"
    return f'{field} >= "{start}" AND {field} < "{end}"'


async def import_summary(client, owner, start_date=None, end_date=None, *, save=True):
    """Fetch at most 31 days and optionally save the default seven-day summary."""
    if (start_date is None) != (end_date is None):
        raise ValueError("Provide both start_date and end_date.")
    if start_date is None:
        end = datetime.now(UTC)
        start = end - timedelta(days=7)
    else:
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise ValueError("Health date filters must use calendar dates.")
        if end_date < start_date or (end_date - start_date).days > 30:
            raise ValueError("Read a date range of 1 to 31 days.")
        start = datetime.combine(start_date, day_start.min, UTC)
        end = datetime.combine(end_date + timedelta(days=1), day_start.min, UTC)
    snapshot = {
        "schema_version": SUMMARY_VERSION,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "data": {},
    }
    # 1. Fetch a bounded set of pages for each data type before replacing the stored summary.
    for kind in DATA_TYPES:
        points, page = [], None
        for _ in range(100):
            params = {
                "pageSize": 1000,
                "filter": range_filter(
                    kind, start.isoformat(), end.isoformat(), calendar_dates=start_date is not None
                ),
            }
            if page:
                params["pageToken"] = page
            payload = await client.request(
                owner, "GET", f"users/me/dataTypes/{kind}/dataPoints", params=params
            )
            points.extend(payload.get("dataPoints", []))
            page = payload.get("nextPageToken")
            if not page:
                break
        else:
            raise ServiceError(
                "The health import exceeded its page limit. Reduce the import range."
            )
        snapshot["data"][kind] = points
    # 2. Normalize complete input so partial imports cannot overwrite the last usable summary.
    snapshot["days"] = [day.to_dict() for day in normalize_data_points(snapshot.pop("data"))]
    if save:
        client.db.put_record(owner, "health", "summary", snapshot)
        client.db.put_record(owner, "health", "last_import", {"at": time.time()})
    return snapshot
