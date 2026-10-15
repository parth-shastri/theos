"""Large batches retain approval snapshots, tool IDs, and restart guarantees."""

import json

from harness import AssistantMessage, ToolCall, ToolResultMessage, tool

from .conftest import collect


async def test_not_started_result_is_saved_and_the_model_can_correct_without_repeating_work(
    runtime, scripted_models
):
    attempts = []

    @tool
    async def read(index: int):
        attempts.append(index)
        return index

    async def registry(session):
        return [runtime.journal_tool(read, session)]

    runtime.tools = registry
    row = runtime.db.create_session("alice", "test-model", "none")
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall("invalid", "read", {"wrong": 1}),
                    ToolCall("valid", "read", {"index": 1}),
                ]
            ),
            AssistantMessage(tool_calls=[ToolCall("corrected", "read", {"index": 2})]),
            AssistantMessage("Complete."),
        ]
    )
    events = await collect(runtime.start("alice", row["id"], "Read the two records."))
    assert events[-1]["status"] == "completed" and attempts == [1, 2]
    assert not any(e["type"] == "error" for e in events)
    saved = runtime.db.load_history("alice", row["id"])
    results = [m for m in saved if isinstance(m, ToolResultMessage)]
    assert [m.status for m in results] == ["not_started", "completed", "completed"]
    assert [m.call_id for m in results] == ["invalid", "valid", "corrected"]
    assert (
        runtime.db.one("SELECT status FROM tool_runs WHERE call_id='invalid'")["status"]
        == "not_started"
    )
    assert events[-1]["stats"]["tool_outcomes"] == {"not_started": 1, "completed": 2}


async def test_large_batch_keeps_all_approvals_and_never_repeats_a_completed_write(
    runtime, scripted_models
):
    attempts = []

    @tool(name="zepto_confirm_cart")
    async def guarded_write(name: str):
        attempts.append(name)
        return {"name": name}

    async def registry(session):
        return [runtime.journal_tool(guarded_write, session)]

    runtime.tools = registry
    row = runtime.db.create_session("alice", "test-model", "none")
    calls = [
        ToolCall(f"write-{i}", "zepto_confirm_cart", {"name": f"notes_{i}"}) for i in range(17)
    ]
    scripted_models.responses.append([AssistantMessage(tool_calls=calls)])
    events = await collect(runtime.start("alice", row["id"], "Delete these test tables."))
    assert events[-1]["status"] == "waiting_for_approval" and not attempts
    pending = runtime.pending("alice", row["id"])
    assert len(pending) == 17 and {p["call_id"] for p in pending} == {c.id for c in calls}
    snapshots = {p["id"]: p["arguments"] for p in pending}
    last = next(p for p in pending if p["call_id"] == "write-16")
    events = await collect(runtime.start("alice", row["id"], approval=(last["id"], True)))
    assert events[-1]["status"] == "waiting_for_approval" and attempts == ["notes_16"]
    for item in runtime.pending("alice", row["id"]):
        events = await collect(runtime.start("alice", row["id"], approval=(item["id"], False)))
    assert events[-1]["status"] == "completed" and attempts == ["notes_16"]
    saved = runtime.db.load_history("alice", row["id"])
    results = [m for m in saved if isinstance(m, ToolResultMessage)]
    assert len(results) == 17 and {m.call_id for m in results} == {c.id for c in calls}
    assert sum(m.status == "completed" for m in results) == 1
    assert sum(m.status == "denied" for m in results) == 16
    for item in runtime.db.rows("SELECT * FROM approvals WHERE session=?", (row["id"],)):
        assert item["arguments"] == snapshots[item["id"]]
        assert json.loads(item["arguments"]) == json.loads(item["preview"])
