"""Private Google Health connection, summary, and export tools."""

import time
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from harness import tool
from theos.services.result_files import for_model

HealthMetric = Literal[
    "steps",
    "distance_meters",
    "active_calories_kcal",
    "active_minutes",
    "active_zone_minutes",
    "resting_heart_rate_bpm",
    "weight_kg",
    "body_fat_percent",
    "heart_rate_zones",
    "heart_rate_zone_thresholds",
    "workouts",
    "sleep",
]
SUMMARY_METRICS = (
    "steps",
    "distance_meters",
    "active_calories_kcal",
    "active_minutes",
    "active_zone_minutes",
    "resting_heart_rate_bpm",
    "weight_kg",
    "body_fat_percent",
)


def _health_view(snapshot, start_date=None, end_date=None, metrics=None):
    days = []
    for day in snapshot.get("days", []):
        day_date = date.fromisoformat(day["date"])
        if (start_date and day_date < start_date) or (end_date and day_date > end_date):
            continue
        row = {"date": day["date"]}
        if metrics is None:
            row.update({key: day[key] for key in SUMMARY_METRICS if key in day})
            if day.get("sleep"):
                row["sleep_minutes"] = sum(item.get("minutes", 0) for item in day["sleep"])
            if day.get("workouts"):
                row["workout_count"] = len(day["workouts"])
                row["workout_minutes"] = sum(item.get("minutes", 0) for item in day["workouts"])
        else:
            row.update({key: day[key] for key in metrics if key in day})
        days.append(row)
    return {
        "from": start_date.isoformat() if start_date else snapshot.get("from"),
        "to": end_date.isoformat() if end_date else snapshot.get("to"),
        "days": days,
    }


def _covers(snapshot, start_date, end_date):
    available_from = datetime.fromisoformat(snapshot["from"]).date()
    available_to = datetime.fromisoformat(snapshot["to"]).date()
    return available_from <= start_date and end_date <= available_to


def health_tools(client, owner, *, result_stager=None):
    """Build private account, summary, and nutrition export tools."""

    # Health views are filtered before staging; raw provider payloads never reach it.

    @tool
    async def health_connect():
        """Create an authorization link for Google Health."""
        return {"url": client.oauth.start(owner, "health")}

    @tool
    async def health_disconnect():
        """Disconnect Google Health and stop pending imports and exports."""
        return await client.oauth.disconnect(owner, "health")

    @tool
    async def get_health_summary(
        start_date: date | None = None,
        end_date: date | None = None,
        metrics: Annotated[list[HealthMetric] | None, Field(max_length=12)] = None,
        refresh: bool = False,
    ):
        """Read compact daily metrics or selected details; provide both dates or neither, for up to 31 days."""
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
            if refresh or not cached or not _covers(cached, start_date, end_date):
                snapshot = await client.import_summary(owner, start_date, end_date, save=False)
            else:
                snapshot = cached
        else:
            snapshot = (
                await client.import_summary(owner)
                if refresh
                else client.db.record(owner, "health", "summary")
            )
        view = _health_view(snapshot, start_date, end_date, metrics)
        return await for_model(
            view,
            tool_name="get_health_summary",
            summary=f"{len(view['days'])} daily rows from {view['from']} through {view['to']}.",
            save_result=result_stager,
        )

    @tool
    async def get_meal_sync_status():
        """List recent nutrition export states, without meal contents."""
        rows = client.db.rows(
            "SELECT id,status,attempts,updated FROM jobs "
            "WHERE owner=? AND kind='nutrition' ORDER BY rowid DESC LIMIT 100",
            (owner,),
        )
        return await for_model(
            rows,
            tool_name="get_meal_sync_status",
            summary=f"{len(rows)} recent nutrition export status rows.",
            save_result=result_stager,
        )

    @tool
    async def retry_meal_sync():
        """Queue failed exports for reconciliation before any retry."""
        count = client.db.execute(
            "UPDATE jobs SET status='reconcile',attempts=0,due=? WHERE owner=? AND kind='nutrition' AND status='failed'",
            (time.time(), owner),
        ).rowcount
        return {"queued": count}

    @tool
    async def backfill_nutrition():
        """Queue historical meals that have no backfill marker."""
        client.oauth.read(owner, "health")
        return {"queued": client.backfill(owner)}

    return [
        health_connect,
        health_disconnect,
        get_health_summary,
        get_meal_sync_status,
        retry_meal_sync,
        backfill_nutrition,
    ]
