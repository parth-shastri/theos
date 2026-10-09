"""Paginated Google Health reads and complete daily summaries."""

import time
from datetime import UTC, datetime, timedelta

from theos.services.errors import ServiceError
from theos.services.health.normalize import DATA_COMPONENTS, normalize_data_points

DATA_TYPES = tuple(DATA_COMPONENTS)


def range_filter(kind, start, end):
    """Select the provider time field for each health data type."""
    name = kind.replace("-", "_")
    if kind.startswith("daily-"):
        field = f"{name}.date"
        start, end = start[:10], end[:10]
    elif kind == "exercise":
        field = "exercise.interval.civil_start_time"
        start, end = start[:10], end[:10]
    elif kind in {"weight", "body-fat"}:
        field = f"{name}.sample_time.physical_time"
    elif kind == "sleep":
        field = "sleep.interval.end_time"
    else:
        field = f"{name}.interval.start_time"
    return f'{field} >= "{start}" AND {field} < "{end}"'


async def import_summary(client, owner):
    """Fetch seven days of data and save complete daily summaries."""
    end = datetime.now(UTC)
    start = (end - timedelta(days=7)).isoformat()
    snapshot = {"from": start, "to": end.isoformat(), "data": {}}
    # 1. Fetch a bounded set of pages for each data type before replacing the stored summary.
    for kind in DATA_TYPES:
        points, page = [], None
        for _ in range(100):
            params = {"pageSize": 1000, "filter": range_filter(kind, start, end.isoformat())}
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
    client.db.put_record(owner, "health", "summary", snapshot)
    client.db.put_record(owner, "health", "last_import", {"at": time.time()})
    return snapshot
