"""Personal organization, memory ownership, and scheduler acceptance tests."""

import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from theos.runtime.scheduler import Scheduler
from theos.services.custom_tables.tools import custom_tools
from theos.services.errors import ServiceError
from theos.services.memory.client import MemoryClient
from theos.services.memory.tools import memory_tools
from theos.services.personal import personal_tools
from theos.services.reminders.timezones import local_time
from theos.settings import MemorySettings

from .conftest import call_tool


def tools_for(db, owner="alice"):
    session = db.create_session(owner, "model", "default")
    return personal_tools(db, owner, session["id"], "Asia/Kolkata"), session


async def test_meal_edit_goal_timezone_and_isolation(db):
    tools, _ = tools_for(db)
    other, _ = tools_for(db, "bob")
    await call_tool(tools, "set_preference", name="calorie_goal", value="2200")
    meal = {"name": "Breakfast", "calories": 450, "protein": 20, "eaten_at": "2026-01-01T08:00:00"}
    saved = await call_tool(tools, "log_meal", meal=meal)
    assert saved["eaten_at"].endswith("+05:30")
    await call_tool(tools, "edit_meal", meal_id=saved["id"], meal={**meal, "calories": 500})
    result = await call_tool(tools, "get_calorie_summary", day="2026-01-01")
    assert result["totals"]["calories"] == 500
    assert result["goal"] == 2200
    with pytest.raises(LookupError):
        await call_tool(other, "delete_meal", meal_id=saved["id"])
    await call_tool(tools, "delete_meal", meal_id=saved["id"])
    assert (await call_tool(tools, "get_calorie_summary", day="2026-01-01"))["meals"] == []


async def test_training_cycle_history_metrics(db):
    tools, _ = tools_for(db)
    exercise = {"name": "Squat", "sets": 3, "repetitions": 5, "weight_kg": 60}
    await call_tool(tools, "set_training_program", name="Strength", days=[[exercise], []])
    assert (await call_tool(tools, "get_todays_training"))["exercises"][0]["name"] == "Squat"
    workout = await call_tool(
        tools, "log_training", exercises=[exercise], performed_at="2026-01-01T10:00:00+05:30"
    )
    await call_tool(tools, "advance_training_cycle")
    assert (await call_tool(tools, "get_todays_training"))["exercises"] == []
    await call_tool(
        tools,
        "update_training_metrics",
        name="weight",
        value=70,
        unit="kg",
        measured_at="2026-01-01T10:00:00Z",
    )
    assert len(await call_tool(tools, "get_training_metrics")) == 1
    assert len(await call_tool(tools, "get_training_history")) == 1
    await call_tool(tools, "delete_workout", workout_id=workout["id"])
    assert not await call_tool(tools, "get_training_history")


async def test_reminder_occurrence_is_durable_and_recurrence_skips_backlog(runtime):
    tools, session = tools_for(runtime.db)
    due = datetime.now(UTC) + timedelta(minutes=2)
    single = await call_tool(tools, "schedule_reminder", text="Drink water", due=due)
    recurring = await call_tool(
        tools,
        "schedule_reminder",
        text="Walk",
        due=due,
        recurrence="0 9 * * *",
        timezone="Asia/Kolkata",
    )
    scheduler = Scheduler(runtime)
    future = time.time() + 3 * 86400
    scheduler.reminders(future)
    scheduler.reminders(future)
    rows = runtime.db.rows("SELECT * FROM notifications")
    assert len(rows) == 2
    assert (
        runtime.db.one("SELECT status FROM reminders WHERE id=?", (single["id"],))["status"]
        == "completed"
    )
    assert (
        runtime.db.one("SELECT due FROM reminders WHERE id=?", (recurring["id"],))["due"] > future
    )
    await call_tool(tools, "cancel_reminder", reminder_id=recurring["id"])
    assert len(await call_tool(tools, "list_reminders")) == 2


@pytest.mark.parametrize("value", ["2026-11-01T01:30:00", "2026-03-08T02:30:00"])
def test_dst_requires_explicit_offset(value):
    with pytest.raises(ValueError, match="explicit UTC offset"):
        local_time(datetime.fromisoformat(value), "America/New_York")


async def test_custom_sql_isolated_and_parameterized(db, tmp_path):
    alice = custom_tools(db, "alice", tmp_path / "custom")
    bob = custom_tools(db, "bob", tmp_path / "custom")
    await call_tool(alice, "create_custom_table", name="notes", columns={"body": "TEXT"})
    await call_tool(
        alice, "create_query_template", name="add", sql="INSERT INTO notes(body) VALUES (:body)"
    )
    await call_tool(
        alice, "execute_query_template", name="add", parameters={"body": "'); DROP TABLE notes; --"}
    )
    await call_tool(alice, "create_query_template", name="read", sql="SELECT body FROM notes")
    rows = await call_tool(alice, "execute_query_template", name="read", parameters={})
    assert rows["rows"][0]["body"].startswith("'); DROP")
    assert not (await call_tool(bob, "list_custom_tables_and_templates"))["tables"]
    with pytest.raises(LookupError):
        await call_tool(bob, "execute_query_template", name="read", parameters={})
    with pytest.raises(ValueError):
        await call_tool(
            alice, "create_query_template", name="escape", sql="ATTACH '/tmp/other' AS other"
        )
    await call_tool(
        alice, "create_query_template", name="extension", sql="SELECT load_extension('something')"
    )
    with pytest.raises(sqlite3.DatabaseError):
        await call_tool(alice, "execute_query_template", name="extension", parameters={})


async def test_memory_crud_ownership_and_service_wire_format():
    seen = []

    def endpoint(request):
        seen.append(request)
        if request.url.path.endswith("/foreign"):
            return httpx.Response(
                200, json={"id": "foreign", "user_id": "bob", "memory": "private"}
            )
        if request.method == "GET" and request.url.path.endswith("/mine"):
            return httpx.Response(200, json={"id": "mine", "user_id": "alice", "memory": "tea"})
        if request.method == "GET" or request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "mine", "user_id": "alice"},
                        {"id": "foreign", "user_id": "bob"},
                        {"id": "unscoped"},
                    ]
                },
            )
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        client = MemoryClient(MemorySettings(enabled=True, endpoint="http://memory"), http)
        tools = memory_tools(client, "alice")
        await call_tool(tools, "save_memory", text="Tea")
        assert json.loads(seen[-1].content)["user_id"] == "alice"
        assert len(await client.search("alice", "tea")) == 1
        assert len(await client.list("alice")) == 1
        assert (await client.read("alice", "mine"))["memory"] == "tea"
        await client.update("alice", "mine", "Coffee")
        await client.delete("alice", "mine")
        writes = sum(r.method in {"DELETE", "PUT"} for r in seen)
        for action in (client.read, client.delete):
            with pytest.raises(LookupError):
                await action("alice", "foreign")
        with pytest.raises(LookupError):
            await client.update("alice", "foreign", "overwrite")
        assert sum(r.method in {"DELETE", "PUT"} for r in seen) == writes


async def test_memory_outage_does_not_report_success():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ) as http:
        client = MemoryClient(MemorySettings(enabled=True), http)
        with pytest.raises(ServiceError):
            await client.save("alice", "remember")


async def test_multimodal_training_prescriptions_and_instruction_override(db):
    tools, _ = tools_for(db)
    await call_tool(tools, "set_preference", name="instructions", value="Use metric units.")
    assert (await call_tool(tools, "get_preferences"))["instructions"] == "Use metric units."
    await call_tool(tools, "set_preference", name="instructions", value="")
    days = [
        {
            "session_type": "zone2",
            "prescription": "Cycle at a steady pace",
            "target_duration_minutes": 30,
            "target_zone": "2",
        },
        {
            "session_type": "resistance",
            "exercises": [{"name": "Squat", "set_details": [{"repetitions": 5, "weight_kg": 60}]}],
        },
    ]
    await call_tool(tools, "set_training_program", name="Mixed", days=days, current_week=5)
    today = await call_tool(tools, "get_todays_training")
    assert today["deload"] and today["target_duration_minutes"] == 30
    await call_tool(
        tools,
        "log_training",
        exercises=[],
        performed_at="2026-01-01T10:00:00Z",
        session_type="zone2",
        metrics={"duration_minutes": 32},
        advance_cycle=True,
    )
    assert (await call_tool(tools, "get_todays_training"))["session_type"] == "resistance"
    workout = await call_tool(
        tools,
        "log_training",
        exercises=days[1]["exercises"],
        performed_at="2026-01-02T10:00:00Z",
        completion_status="partial",
    )
    assert workout["exercises"][0]["set_details"][0]["weight_kg"] == 60
    assert len(await call_tool(tools, "get_training_history", exercise="squat")) == 1
    assert (await call_tool(tools, "get_todays_training"))["last_comparable_session"][
        "id"
    ] == workout["id"]
    await call_tool(tools, "set_training_program", name="New program", days=[[]])
    assert len(db.records("alice", "training_version")) == 2
