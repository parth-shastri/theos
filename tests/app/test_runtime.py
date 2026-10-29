"""Acceptance tests for persistence, approvals, restart safety, and isolation."""

import asyncio
import json
import time
from contextlib import asynccontextmanager

import pytest

from harness import AssistantMessage, ToolCall, ToolResultMessage, UserMessage
from harness.events import GenerationComplete, TextDelta
from harness.testing import FakeModel
from theos.runtime import Runtime
from theos.storage.database import Database

from .conftest import collect


def new_session(runtime, owner="alice"):
    return runtime.db.create_session(owner, "test-model", "default")


async def test_stream_and_persist(runtime, scripted_models):
    session = new_session(runtime)
    scripted_models.responses.append(
        [AssistantMessage("Saved answer", usage={"input_tokens": 7, "output_tokens": 3})]
    )
    events = await collect(runtime.start("alice", session["id"], "Hello"))
    assert any(e["type"] == "text" for e in events)
    assert events[-1]["type"] == "done" and events[-1]["status"] == "completed"
    assert events[-1]["stats"]["tool_calls"] == 0
    assert events[-1]["stats"]["skills"] == []
    assert events[-1]["stats"]["elapsed_seconds"] >= 0
    history = runtime.db.load_history("alice", session["id"])
    assert history[-1].text == "Saved answer"
    assert runtime.db.one("SELECT input_tokens FROM usage")["input_tokens"] == 7
    assert "Hello" not in json.dumps(runtime.db.rows("SELECT * FROM traces"))


async def test_configured_summary_model_runs_only_for_compaction(runtime):
    session = new_session(runtime)
    runtime.settings.compaction_model = "summary-model"
    runtime.settings.compaction_trigger_ratio = 0.01
    runtime.settings.compaction_tail_ratio = 0.025
    runtime.settings.context_tokens = 16_000
    runtime.settings.max_output_tokens = 512
    runtime.db.save_history(
        "alice",
        session["id"],
        [UserMessage("Old request."), AssistantMessage("Old fact. " * 1500)],
    )
    main = FakeModel([AssistantMessage("Current answer.")])
    summary = FakeModel([AssistantMessage("Old fact summarized.")])
    opened = []

    @asynccontextmanager
    async def factory(_settings, model_id, _reasoning):
        opened.append(model_id)
        yield summary if model_id == "summary-model" else main

    runtime.models = factory
    events = await collect(runtime.start("alice", session["id"], "New question."))

    assert events[-1]["status"] == "completed"
    assert opened == ["test-model", "summary-model"]
    assert len(summary.requests) == 1 and not summary.requests[0].tools
    assert summary.requests[0].options["max_output_tokens"] == 400
    assert len(main.requests) == 1
    assert any(
        isinstance(message, UserMessage) and "Old fact summarized." in message.content
        for message in main.requests[0].messages
    )


async def test_approval_denial_and_owner_isolation(runtime, scripted_models, checkout_tool):
    session = new_session(runtime)
    runtime.db.put_record("alice", "query", "test", {"sql": "SELECT 1"})
    scripted_models.responses.append(
        [AssistantMessage(tool_calls=[ToolCall("delete", "zepto_confirm_cart", {"name": "notes"})])]
    )
    events = await collect(runtime.start("alice", session["id"], "Delete notes"))
    assert events[-1]["status"] == "waiting_for_approval"
    pending = runtime.pending("alice", session["id"])[0]
    with pytest.raises(LookupError):
        runtime.start("bob", session["id"], approval=(pending["id"], True))
    scripted_models.responses.append([AssistantMessage("I did not delete the table.")])
    await collect(runtime.start("alice", session["id"], approval=(pending["id"], False)))
    results = [
        m
        for m in runtime.db.load_history("alice", session["id"])
        if isinstance(m, ToolResultMessage)
    ]
    assert results[0].status == "denied"
    with pytest.raises(ValueError):
        runtime.start("alice", session["id"], approval=(pending["id"], True))


async def test_approval_survives_runtime_restart(runtime, scripted_models, checkout_tool):
    session = new_session(runtime)
    from theos.services.custom_tables.tools import custom_tools

    tools = custom_tools(runtime.db, "alice", runtime.settings.data_dir / "tables")
    from .conftest import call_tool

    await call_tool(tools, "create_custom_table", name="notes", columns={"text": "TEXT"})
    scripted_models.responses.append(
        [AssistantMessage(tool_calls=[ToolCall("delete", "zepto_confirm_cart", {"name": "notes"})])]
    )
    await collect(runtime.start("alice", session["id"], "Delete notes"))
    pending = runtime.pending("alice", session["id"])[0]
    restarted = Runtime(runtime.settings, runtime.db, models=scripted_models)
    scripted_models.responses.append([AssistantMessage("Deleted.")])
    await collect(restarted.start("alice", session["id"], approval=(pending["id"], True)))
    assert (
        runtime.db.one("SELECT status FROM tool_runs WHERE call_id='delete'")["status"]
        == "completed"
    )
    await restarted.close()


async def test_restart_does_not_repeat_uncertain_tool(runtime, scripted_models):
    session = new_session(runtime)
    history = [
        UserMessage("Delete a file"),
        AssistantMessage(tool_calls=[ToolCall("c", "delete_user_file", {"file_id": "missing"})]),
    ]
    runtime.db.save_history("alice", session["id"], history, status="running")
    runtime.db.execute(
        "INSERT INTO tool_runs VALUES (?,?,?,?,NULL)",
        (session["id"], "c", "delete_user_file", "running"),
    )
    runtime.db.recover()
    await collect(runtime.start("alice", session["id"]))
    result = runtime.db.load_history("alice", session["id"])[2]
    assert result.status == "unknown"
    assert runtime.db.one("SELECT status FROM tool_runs")["status"] == "unknown"


async def test_reset_retains_records_and_rejects_wrong_owner(runtime):
    session = new_session(runtime)
    runtime.db.put_record("alice", "meal", "meal1", {"name": "Lunch"})
    await collect(runtime.start("alice", session["id"], "Hello"))
    with pytest.raises(LookupError):
        await runtime.reset("bob", session["id"])
    await runtime.reset("alice", session["id"])
    assert runtime.db.load_history("alice", session["id"]) == []
    assert runtime.db.record("alice", "meal", "meal1")["name"] == "Lunch"


async def test_conversation_serialization_and_global_bound(runtime):
    gate = asyncio.Event()
    entered = 0
    maximum = 0

    class WaitingModel:
        async def stream(self, request):
            nonlocal entered, maximum
            entered += 1
            maximum = max(maximum, entered)
            await gate.wait()
            entered -= 1
            yield TextDelta("Done")
            yield GenerationComplete(AssistantMessage("Done"))

    @asynccontextmanager
    async def factory(*args):
        yield WaitingModel()

    runtime.models = factory
    runtime.semaphore = asyncio.Semaphore(1)
    first, second = new_session(runtime), new_session(runtime)
    a = runtime.start("alice", first["id"], "one")
    b = runtime.start("alice", second["id"], "two")
    with pytest.raises(ValueError, match="running turn"):
        runtime.start("alice", first["id"], "three")
    await asyncio.sleep(0.03)
    assert maximum == 1
    gate.set()
    await asyncio.gather(collect(a), collect(b))
    assert maximum == 1


def test_database_reopen_migrations_backup_and_single_worker(settings, tmp_path):
    db = Database(settings.data_dir)
    session = db.create_session("alice", "model", "default")
    db.save_history("alice", session["id"], [UserMessage("durable")])
    with pytest.raises(RuntimeError, match="one worker"):
        Database(settings.data_dir)
    backup = tmp_path / "backup.sqlite3"
    db.backup(backup)
    db.close()
    db = Database(settings.data_dir)
    assert db.load_history("alice", session["id"])[0].content == "durable"
    assert db.one("PRAGMA user_version")["user_version"] == 16
    tables = {row["name"] for row in db.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "research_scratchpad" in tables and "research_items" not in tables
    db.close()


async def test_group_and_terminal_have_no_sensitive_tools(runtime):
    runtime.settings.gmail.client_id = "configured"
    runtime.settings.health.client_id = "configured"
    for channel in ("terminal", "telegram-group"):
        session = runtime.db.create_session("alice", "model", "default", channel)
        names = [t.name for t in await runtime.tools(session)]
        assert not any(n.startswith(("gmail_", "health_", "zepto_")) for n in names)


async def test_expired_approval_cannot_execute(runtime, scripted_models, checkout_tool):
    session = new_session(runtime)
    scripted_models.responses.append(
        [AssistantMessage(tool_calls=[ToolCall("a", "zepto_confirm_cart", {"name": "notes"})])]
    )
    await collect(runtime.start("alice", session["id"], "delete"))
    approval = runtime.pending("alice", session["id"])[0]
    runtime.db.execute("UPDATE approvals SET expires=?", (time.time() - 1,))
    with pytest.raises(ValueError, match="expired"):
        runtime.start("alice", session["id"], approval=(approval["id"], True))


async def test_failed_tool_is_accurate_and_chat_continues(runtime, scripted_models):
    session = new_session(runtime)
    scripted_models.responses.append(
        [
            AssistantMessage(tool_calls=[ToolCall("missing", "get_todays_training", {})]),
            AssistantMessage("No training program is saved."),
        ]
    )
    await collect(runtime.start("alice", session["id"], "training"))
    history = runtime.db.load_history("alice", session["id"])
    assert history[2].status == "failed"
    assert history[-1].text == "No training program is saved."
