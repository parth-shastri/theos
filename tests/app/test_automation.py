"""Scheduled agent execution and consented memory automation contracts."""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from harness import AssistantMessage, OutcomeUnknown, ToolCall, tool
from harness.events import GenerationComplete
from theos.runtime.scheduler import Scheduler
from theos.services.errors import ServiceError
from theos.services.schedules.tools import task_tools

from .conftest import call_tool, collect


def session_for(runtime, owner="alice", channel="browser", address=""):
    return runtime.db.create_session(owner, "test-model", "default", channel, address)


async def schedule(runtime, session, **overrides):
    tools = task_tools(runtime.db, session["owner"], session["id"], runtime.settings)
    value = await call_tool(
        tools,
        "schedule_task",
        **{
            "name": "Morning brief",
            "prompt": "Find the latest news and summarize it.",
            "due": datetime.now(UTC) + timedelta(minutes=2),
            **overrides,
        },
    )
    runtime.db.execute(
        "UPDATE scheduled_tasks SET due=? WHERE id=?", (time.time() - 1, value["id"])
    )
    return value, tools


async def drain(scheduler):
    await asyncio.gather(*list(scheduler.scheduled.workers))


async def test_scheduled_turn_runs_once_and_notifies_browser(runtime, scripted_models):
    session = session_for(runtime)
    task, _ = await schedule(runtime, session)
    scripted_models.responses.append([AssistantMessage("Your morning brief.")])
    scheduler = Scheduler(runtime)
    scheduler.scheduled.tick(time.time())
    scheduler.scheduled.tick(time.time())
    await drain(scheduler)
    scheduler.scheduled.tick(time.time())
    assert runtime.db.one("SELECT COUNT(*) n FROM scheduled_runs")["n"] == 1
    run = runtime.db.one("SELECT * FROM scheduled_runs")
    assert run["status"] == "completed" and run["delivery"] == "delivered"
    assert runtime.db.one("SELECT text FROM notifications")["text"] == "Your morning brief."
    history = runtime.db.load_history("alice", session["id"])
    assert history[0].content.startswith("Scheduled task: Morning brief")
    assert (
        runtime.db.one("SELECT status FROM scheduled_tasks WHERE id=?", (task["id"],))["status"]
        == "completed"
    )
    await scheduler.close()


async def test_recurring_task_skips_downtime_and_defers_busy_session(runtime):
    session = session_for(runtime)
    task, _ = await schedule(runtime, session, recurrence="0 9 * * *", timezone="Asia/Kolkata")
    scheduler = Scheduler(runtime)
    runtime.active[session["id"]] = object()
    scheduler.scheduled.tick(time.time())
    assert not runtime.db.rows("SELECT * FROM scheduled_runs")
    runtime.active.pop(session["id"])
    future = time.time() + 86400 * 5
    scheduler.scheduled.tick(future)
    await drain(scheduler)
    scheduler.scheduled.tick(future)
    row = runtime.db.one("SELECT * FROM scheduled_tasks WHERE id=?", (task["id"],))
    assert row["due"] > future and row["status"] == "pending"
    assert len(runtime.db.rows("SELECT * FROM scheduled_runs")) == 1
    await scheduler.close()


async def test_task_controls_validation_and_owner_isolation(runtime):
    alice, bob = session_for(runtime), session_for(runtime, "bob")
    task, tools = await schedule(runtime, alice)
    other = task_tools(runtime.db, "bob", bob["id"], runtime.settings)
    for name in ("cancel_scheduled_task", "pause_scheduled_task", "list_scheduled_runs"):
        with pytest.raises(LookupError):
            await call_tool(other, name, task_id=task["id"])
    with pytest.raises(ValueError):
        await schedule(runtime, alice, recurrence="* * * * * *")
    with pytest.raises(ValueError):
        await schedule(runtime, alice, due=datetime.now(UTC) - timedelta(days=1))
    await call_tool(tools, "pause_scheduled_task", task_id=task["id"])
    due = datetime.now(UTC) + timedelta(hours=1)
    await call_tool(tools, "resume_scheduled_task", task_id=task["id"], due=due)
    assert runtime.db.one("SELECT due FROM scheduled_tasks")["due"] == due.timestamp()
    await call_tool(tools, "cancel_scheduled_task", task_id=task["id"])
    scheduler = Scheduler(runtime)
    scheduler.scheduled.tick(time.time() + 86400)
    assert not runtime.db.rows("SELECT * FROM scheduled_runs")
    await scheduler.close()


async def test_scheduled_tool_requires_normal_approval_and_resumes(runtime, scripted_models):
    session = session_for(runtime)
    _, _ = await schedule(runtime, session)
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[ToolCall("delete", "delete_user_file", {"file_id": "missing"})]
            )
        ]
    )
    scheduler = Scheduler(runtime)
    scheduler.scheduled.tick(time.time())
    await drain(scheduler)
    assert runtime.db.one("SELECT status FROM scheduled_runs")["status"] == "waiting_for_approval"
    assert not runtime.db.rows("SELECT * FROM tool_runs")
    decision = runtime.pending("alice", session["id"])[0]
    scripted_models.responses.append([AssistantMessage("Cancelled the deletion.")])
    await collect(runtime.start("alice", session["id"], approval=(decision["id"], False)))
    assert runtime.db.one("SELECT status FROM scheduled_runs")["status"] == "completed"
    await scheduler.close()


async def test_scheduled_delivery_failure_does_not_rerun_model(runtime, scripted_models):
    runtime.settings.telegram_users = {123}
    session = session_for(runtime, "telegram:123", "telegram-private", "123:0")
    await schedule(runtime, session)
    scripted_models.responses.append([AssistantMessage("Generated once.")])

    class BrokenTelegram:
        async def render(self, *args):
            raise ServiceError("Offline")

    scheduler = Scheduler(runtime, BrokenTelegram())
    scheduler.scheduled.tick(time.time())
    await drain(scheduler)
    scheduler.scheduled.tick(time.time())
    row = runtime.db.one("SELECT * FROM scheduled_runs")
    assert row["status"] == "completed" and row["delivery"] == "uncertain"
    assert len(runtime.db.load_history(session["owner"], session["id"])) == 2
    await scheduler.close()


async def test_revoked_owner_does_not_run_scheduled_task(runtime):
    session = session_for(runtime)
    await schedule(runtime, session)
    del runtime.settings.users["alice"]
    scheduler = Scheduler(runtime)
    scheduler.scheduled.tick(time.time())
    assert runtime.db.one("SELECT status FROM scheduled_tasks")["status"] == "paused"
    assert not runtime.db.rows("SELECT * FROM scheduled_runs")
    await scheduler.close()


async def test_restart_pauses_interrupted_occurrence_without_replay(runtime):
    session = session_for(runtime)
    task, _ = await schedule(runtime, session)
    runtime.db.execute(
        "INSERT INTO scheduled_runs(id,task_id,session,due,status,started,delivery) VALUES (?,?,?,?,?,?,?)",
        ("run", task["id"], session["id"], time.time() - 1, "running", time.time(), "sending"),
    )
    runtime.db.recover()
    scheduler = Scheduler(runtime)
    scheduler.scheduled.tick(time.time())
    assert runtime.db.one("SELECT status FROM scheduled_tasks")["status"] == "paused"
    run = runtime.db.one("SELECT * FROM scheduled_runs")
    assert run["status"] == "interrupted" and run["delivery"] == "uncertain"
    assert not scheduler.scheduled.workers
    await scheduler.close()


async def test_memory_retrieval_scoped_bounded_ephemeral_and_in_model_context(runtime):
    runtime.settings.memory.enabled = True
    runtime.settings.memory.retrieval_chars = 256
    seen = []

    async def search(owner, query):
        seen.append((owner, query))
        return [
            {"user_id": "bob", "memory": "OTHER OWNER SECRET"},
            {"user_id": "alice", "memory": "Prefer tea. " * 100},
        ]

    runtime.memory.search = search

    class InspectModel:
        async def stream(self, request):
            prompt = request.messages[0].content
            assert "untrusted reference data" in prompt
            assert "Prefer tea." in prompt and "OTHER OWNER SECRET" not in prompt
            assert prompt.count("Prefer tea.") < 30
            yield GenerationComplete(AssistantMessage("Tea suits your preference."))

    @asynccontextmanager
    async def models(*args):
        yield InspectModel()

    runtime.models = models
    session = session_for(runtime)
    await collect(runtime.start("alice", session["id"], "Suggest a drink"))
    assert seen == [("alice", "Suggest a drink")]
    assert "Retrieved personal memory" not in runtime.db.session("alice", session["id"])["history"]


async def test_memory_outage_timeout_and_groups_do_not_block_chat(runtime):
    runtime.settings.memory.enabled = True
    runtime.settings.memory.retrieval_timeout = 0.01
    calls = []

    async def slow(owner, query):
        calls.append(owner)
        await asyncio.sleep(1)

    runtime.memory.search = slow
    session = session_for(runtime)
    assert (await collect(runtime.start("alice", session["id"], "hello")))[-1][
        "status"
    ] == "completed"
    group = session_for(runtime, "group", "telegram-group")
    await collect(runtime.start("group", group["id"], "group message"))
    assert calls == ["alice"]


async def test_consolidation_consent_batching_wire_format_and_no_replay(runtime):
    runtime.settings.memory.enabled = True
    runtime.settings.memory.consolidation_turns = 2
    auto = runtime.memory_automation
    session = session_for(runtime)
    auto.enqueue(session, "Before consent")
    assert not runtime.db.rows("SELECT * FROM memory_batches")
    await call_tool(
        auto.tools("alice"), "configure_memory_automation", retrieval=True, consolidation=True
    )
    sent = []

    def endpoint(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        runtime.memory.http = http
        auto.enqueue(session, "I prefer tea.")
        await auto.consolidate()
        assert not sent
        auto.enqueue(session, "I now prefer coffee.")
        await auto.consolidate()
        await auto.consolidate()
    assert len(sent) == 1
    assert sent[0]["user_id"] == "alice"
    assert sent[0]["messages"] == [
        {"role": "user", "content": "I prefer tea."},
        {"role": "user", "content": "I now prefer coffee."},
    ]
    assert len(sent[0]["metadata"]["source_ids"]) == 2
    assert all(
        r["status"] == "completed" and r["content"] == ""
        for r in runtime.db.rows("SELECT * FROM memory_batches")
    )


async def test_consolidation_excludes_secrets_groups_scheduled_and_assistant_text(runtime):
    runtime.settings.memory.enabled = True
    auto = runtime.memory_automation
    for owner in ("alice", "group"):
        await call_tool(
            auto.tools(owner), "configure_memory_automation", retrieval=False, consolidation=True
        )
    session = session_for(runtime)
    auto.enqueue(session, "api_key=sk-a-secret-value")
    group = session_for(runtime, "group", "telegram-group")
    auto.enqueue(group, "Group facts")
    await collect(runtime.start("alice", session["id"], "Scheduled prompt", scheduled=True))
    assert not runtime.db.rows("SELECT * FROM memory_batches")
    await collect(runtime.start("alice", session["id"], "I live in Pune."))
    rows = runtime.db.rows("SELECT * FROM memory_batches")
    assert len(rows) == 1 and rows[0]["content"] == "I live in Pune."


async def test_consolidation_failure_is_unknown_and_disable_discards_pending(runtime):
    runtime.settings.memory.enabled = True
    runtime.settings.memory.consolidation_turns = 1
    auto = runtime.memory_automation
    session = session_for(runtime)
    await call_tool(
        auto.tools("alice"), "configure_memory_automation", retrieval=False, consolidation=True
    )
    calls = []

    async def fail(owner, rows):
        calls.append(owner)
        raise ServiceError("Uncertain connection")

    runtime.memory.consolidate = fail
    auto.enqueue(session, "I like tea.")
    await auto.consolidate()
    await auto.consolidate()
    assert calls == ["alice"]
    assert runtime.db.one("SELECT status FROM memory_batches")["status"] == "unknown"
    auto.enqueue(session, "Queued next")
    await call_tool(
        auto.tools("alice"), "configure_memory_automation", retrieval=False, consolidation=False
    )
    assert not runtime.db.rows("SELECT * FROM memory_batches WHERE status='pending'")
    assert not any(r["content"] for r in runtime.db.rows("SELECT * FROM memory_batches"))


async def test_memory_automation_consent_requires_approval(runtime, scripted_models):
    runtime.settings.memory.enabled = True
    session = session_for(runtime)
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall(
                        "consent",
                        "configure_memory_automation",
                        {"retrieval": True, "consolidation": True},
                    )
                ]
            )
        ]
    )
    events = await collect(runtime.start("alice", session["id"], "Enable automatic memory"))
    assert events[-1]["status"] == "waiting_for_approval"
    assert not runtime.memory_automation.policy("alice")["consolidation"]
    approval = runtime.pending("alice", session["id"])[0]
    await collect(runtime.start("alice", session["id"], approval=(approval["id"], True)))
    assert runtime.memory_automation.policy("alice")["consolidation"]


async def test_memory_consolidation_interval_and_restart_recovery(runtime):
    runtime.settings.memory.enabled = True
    auto = runtime.memory_automation
    session = session_for(runtime)
    await call_tool(
        auto.tools("alice"), "configure_memory_automation", retrieval=False, consolidation=True
    )
    auto.enqueue(session, "Old pending fact")
    runtime.db.execute("UPDATE memory_batches SET created=?", (time.time() - 10000,))
    calls = []

    async def save(owner, rows):
        calls.append(owner)

    runtime.memory.consolidate = save
    await auto.consolidate()
    assert calls == ["alice"]
    auto.enqueue(session, "Uncertain write")
    runtime.db.execute("UPDATE memory_batches SET status='running' WHERE status='pending'")
    runtime.db.recover()
    await auto.consolidate()
    assert calls == ["alice"]
    assert (
        runtime.db.one("SELECT content FROM memory_batches WHERE status='unknown'")["content"] == ""
    )


@pytest.mark.parametrize("unknown", [False, True])
async def test_scheduled_budget_or_uncertain_action_pauses_schedule(
    runtime, scripted_models, unknown
):
    session = session_for(runtime)
    await schedule(runtime, session, recurrence="0 9 * * *")

    @tool
    async def attempt():
        """Attempt the test action."""
        if unknown:
            raise OutcomeUnknown("The action may have completed.")
        return "Done"

    async def tools_for(current):
        return [runtime.journal_tool(attempt, current)]

    runtime.tools = tools_for
    if not unknown:
        runtime.settings.max_model_calls = 1
    scripted_models.responses.append(
        [
            AssistantMessage(tool_calls=[ToolCall("attempt-1", "attempt", {})]),
            AssistantMessage("Done"),
        ]
    )
    scheduler = Scheduler(runtime)
    scheduler.scheduled.tick(time.time())
    await drain(scheduler)
    expected = "uncertain" if unknown else "budget_exhausted"
    assert runtime.db.one("SELECT status FROM scheduled_runs")["status"] == expected
    assert runtime.db.one("SELECT status FROM scheduled_tasks")["status"] == "paused"
    scheduler.scheduled.tick(time.time() + 86400)
    assert runtime.db.one("SELECT COUNT(*) n FROM scheduled_runs")["n"] == 1
    await scheduler.close()


async def test_scheduled_group_requires_current_enrollment_and_chat_access(runtime):
    runtime.settings.telegram_users = {123}
    runtime.settings.telegram_chats = {-456}
    private = session_for(runtime, "telegram:123", "telegram-private", "123:0")
    runtime.db.execute(
        "INSERT INTO telegram_enrollments VALUES (?,?,?,?)",
        (123, private["owner"], "timezone", time.time()),
    )
    group = session_for(runtime, "telegram-group:-456:0:123", "telegram-group", "-456:0")
    scheduler = Scheduler(runtime)
    assert not scheduler.scheduled.allowed(group)
    runtime.db.execute("UPDATE telegram_enrollments SET state='ready'")
    assert scheduler.scheduled.allowed(group)
    runtime.settings.telegram_chats = set()
    assert not scheduler.scheduled.allowed(group)
    await scheduler.close()


async def test_scheduler_shutdown_cancels_active_agent_and_consolidation(runtime):
    runtime.settings.memory.enabled = True
    runtime.settings.memory.consolidation_turns = 1
    auto = runtime.memory_automation
    session = session_for(runtime)
    await call_tool(
        auto.tools("alice"), "configure_memory_automation", retrieval=False, consolidation=True
    )
    auto.enqueue(session, "I prefer tea.")
    await schedule(runtime, session)
    model_started, memory_started = asyncio.Event(), asyncio.Event()

    class SlowModel:
        async def stream(self, request):
            model_started.set()
            await asyncio.Event().wait()
            yield GenerationComplete(AssistantMessage("Never reached"))

    @asynccontextmanager
    async def models(*args):
        yield SlowModel()

    async def consolidate(*args):
        memory_started.set()
        await asyncio.Event().wait()

    runtime.models = models
    runtime.memory.consolidate = consolidate
    scheduler = Scheduler(runtime)
    await scheduler.tick()
    await asyncio.wait_for(model_started.wait(), 1)
    await asyncio.wait_for(memory_started.wait(), 1)
    await asyncio.wait_for(scheduler.close(), 1)
    assert not runtime.active
    assert runtime.db.one("SELECT status FROM scheduled_runs")["status"] == "interrupted"
    assert runtime.db.one("SELECT status FROM scheduled_tasks")["status"] == "paused"
    assert runtime.db.one("SELECT status FROM memory_batches")["status"] == "unknown"


async def test_memory_batches_never_mix_owners_and_retrieval_skips_credentials(runtime):
    runtime.settings.memory.enabled = True
    runtime.settings.memory.consolidation_turns = 1
    auto = runtime.memory_automation
    sent = []

    async def consolidate(owner, rows):
        assert all(row["owner"] == owner for row in rows)
        sent.append((owner, [row["content"] for row in rows]))

    async def search(*args):
        pytest.fail("Credential message must not reach memory search")

    runtime.memory.consolidate = consolidate
    runtime.memory.search = search
    for owner in ("alice", "bob"):
        session = session_for(runtime, owner)
        await call_tool(
            auto.tools(owner), "configure_memory_automation", retrieval=True, consolidation=True
        )
        auto.enqueue(session, f"My name is {owner}.")
        assert await auto.retrieve(session, "password=example-secret") == ""
    await auto.consolidate()
    await auto.consolidate()
    assert sent == [("alice", ["My name is alice."]), ("bob", ["My name is bob."])]
