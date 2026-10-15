"""Oversized call groups continue with bounded execution and exact outcomes."""

import asyncio

import pytest

from harness import (
    Agent,
    AssistantMessage,
    Budget,
    Hooks,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    tool,
)
from harness.context import RunContext
from harness.events import ToolStarted
from harness.limits import ExecutionLimits, HarnessError, validate_assistant_message
from harness.testing import FakeModel
from harness.tools import OutcomeUnknown, execute_tool, execute_tools


@pytest.mark.parametrize("batch_size", [1, 8, 16])
async def test_large_response_runs_every_call_once_with_bounded_parallelism_and_feedback(
    batch_size,
):
    attempts, checkpoints = [], []
    active, peak = 0, 0

    @tool(parallel_safe=True)
    async def read_receipt(index: int):
        nonlocal active, peak
        attempts.append(index)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return {"index": index}

    async def saved_result(result, ctx):
        checkpoints.append(
            (
                int(result.call_id.split("-")[-1]),
                len([m for m in ctx.history if isinstance(m, ToolResultMessage)]),
            )
        )
        return result

    calls = [ToolCall(f"receipt-{index}", "read_receipt", {"index": index}) for index in range(35)]
    model = FakeModel([AssistantMessage(tool_calls=calls), AssistantMessage("Complete.")])
    history = [UserMessage("Read all receipts.")]
    result = await Agent(
        model,
        [read_receipt],
        hooks=Hooks(after_tool=saved_result),
        limits=ExecutionLimits(tool_batch_size=batch_size),
    ).run(history, budget=Budget(2))
    assert result.status == "completed" and len(model.requests) == 2
    assert sorted(attempts) == list(range(35)) and peak <= batch_size
    results = [m for m in history if isinstance(m, ToolResultMessage)]
    assert [r.call_id for r in results] == [c.id for c in calls]
    assert all(r.status == "completed" for r in results)
    assert all(count >= (index // batch_size) * batch_size for index, count in checkpoints)
    instructions = "\n".join(
        m.content for m in model.requests[-1].messages if type(m).__name__ == "SystemMessage"
    )
    assert "last response requested 35 calls" in instructions
    assert (
        f"recommended {batch_size}" in instructions and "Do not resubmit this batch" in instructions
    )


async def test_direct_executor_also_bounds_parallel_calls():
    active, peak = 0, 0

    @tool(parallel_safe=True)
    async def read(index: int):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return index

    calls = [ToolCall(str(i), "read", {"index": i}) for i in range(40)]
    results = await execute_tools(calls, [read], ctx=RunContext(deps=None))
    assert len(results) == 40 and peak == 16
    assert [r.call_id for r in results] == [c.id for c in calls]


@pytest.mark.parametrize(
    "arguments,limits,code",
    [
        (
            {"payload": "x" * 100},
            ExecutionLimits(max_argument_bytes=32),
            "tool_arguments_too_large",
        ),
        (
            {"payload": {"a": {"b": 1}}},
            ExecutionLimits(max_nesting_depth=2),
            "tool_arguments_too_deep",
        ),
        ({"payload": [1, 2, 3]}, ExecutionLimits(max_batch_size=2), "batch_size_exceeded"),
        ({"payload": float("nan")}, ExecutionLimits(), "malformed_model_output"),
    ],
)
async def test_argument_limit_returns_not_started_before_approval_or_execution(
    arguments, limits, code
):
    attempts, approvals, events, saved = [], [], [], []

    @tool
    async def write(payload: object):
        attempts.append(payload)

    async def policy(selected, args, ctx):
        approvals.append(args)
        raise AssertionError("Invalid arguments reached approval")

    async def checkpoint(result, ctx):
        saved.append(result)
        return result

    result = await execute_tool(
        ToolCall("original-id", "write", arguments),
        [write],
        ctx=RunContext(deps=None, emit=events.append),
        hooks=Hooks(before_tool=policy, after_tool=checkpoint),
        limits=limits,
    )
    assert result.call_id == "original-id" and result.status == "not_started"
    assert code in result.content and "No tool executed" in result.content
    assert "new call with a new ID" in result.content
    assert not attempts and not approvals and not any(isinstance(e, ToolStarted) for e in events)
    assert saved == [result]


async def test_not_started_failed_and_unknown_results_are_distinct_and_model_can_correct():
    attempts = []

    @tool
    async def action(value: int):
        attempts.append(value)
        if value == 1:
            raise ValueError("Known failure")
        if value == 2:
            raise OutcomeUnknown("Check external state before repeating")
        return value

    calls = [
        ToolCall("invalid", "action", {"wrong": 1}),
        ToolCall("missing", "missing_tool", {}),
        ToolCall("failed", "action", {"value": 1}),
        ToolCall("unknown", "action", {"value": 2}),
        ToolCall("complete", "action", {"value": 3}),
    ]
    model = FakeModel(
        [
            AssistantMessage(tool_calls=calls),
            AssistantMessage(tool_calls=[ToolCall("corrected", "action", {"value": 4})]),
            AssistantMessage("Complete."),
        ]
    )
    history = [UserMessage("Perform the task.")]
    result = await Agent(model, [action]).run(history)
    assert result.status == "completed" and attempts == [1, 2, 3, 4]
    outcomes = [m for m in history if isinstance(m, ToolResultMessage)]
    assert [m.status for m in outcomes] == [
        "not_started",
        "not_started",
        "failed",
        "unknown",
        "completed",
        "completed",
    ]
    assert [m.call_id for m in outcomes] == [c.id for c in calls] + ["corrected"]
    assert any(
        isinstance(m, ToolResultMessage) and m.status == "not_started"
        for m in model.requests[1].messages
    )


async def test_duplicate_ids_still_stop_before_any_tool_can_execute():
    attempts = []

    @tool
    async def action():
        attempts.append(True)

    model = FakeModel(
        [
            AssistantMessage(
                tool_calls=[ToolCall("same", "action", {}), ToolCall("same", "action", {})]
            )
        ]
    )
    with pytest.raises(HarnessError) as error:
        await Agent(model, [action]).run([UserMessage("Do it.")])
    assert error.value.code == "duplicate_tool_call_id" and not attempts


def test_response_validation_accepts_more_than_sixteen_identifiable_calls():
    validate_assistant_message(
        AssistantMessage(tool_calls=[ToolCall(str(i), "read", {}) for i in range(40)])
    )
    with pytest.raises(ValueError, match="tool_batch_size"):
        ExecutionLimits(tool_batch_size=0)


async def test_cancellation_in_later_batch_keeps_prior_results_and_does_not_repeat_unknown():
    attempts = []
    entered = asyncio.Event()

    @tool
    async def read(index: int):
        attempts.append(index)
        if index == 16:
            entered.set()
            await asyncio.Future()
        return index

    calls = [ToolCall(str(i), "read", {"index": i}) for i in range(35)]
    history = [UserMessage("Read all receipts.")]
    agent = Agent(FakeModel([AssistantMessage(tool_calls=calls)]), [read])
    task = asyncio.create_task(agent.run(history))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    results = [m for m in history if isinstance(m, ToolResultMessage)]
    assert [m.call_id for m in results] == [str(i) for i in range(17)]
    assert [m.status for m in results] == ["completed"] * 16 + ["unknown"]
    assert attempts == list(range(17))
    resumed = Agent(FakeModel([AssistantMessage("Complete with uncertain receipt 16.")]), [read])
    result = await resumed.run(history)
    assert result.status == "completed" and attempts == list(range(35))
    assert len([m for m in history if isinstance(m, ToolResultMessage)]) == 35
