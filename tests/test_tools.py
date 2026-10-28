"""Tests for harness.tools: the Tool record, the decorator, and the executor."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Annotated

import pytest
from fixtures.mocked_apis import http_GET_customer_order_history, http_GET_order_status
from pydantic import BaseModel, Field

from harness.context import RunContext
from harness.hooks import ALLOW, ASK, DENY, Decision, Hooks
from harness.tools import OutcomeUnknown, Tool, execute_tool, execute_tools, tool
from harness.types import (
    PendingApproval,
    ToolCall,
    ToolOutput,
    ToolResultMessage,
    ToolSpec,
    View,
)


async def _decide(decision: Decision) -> Decision:
    """Return a fixed decision, so a lambda can stand in for a before_tool hook."""
    return decision


@tool
async def get_order_status(order_id: str, ctx: RunContext) -> dict:
    """Return the shipping status of one order.

    The second paragraph never reaches the description.
    """
    return await asyncio.to_thread(http_GET_order_status, order_id)


@tool(name="order_history", parallel_safe=True)
async def get_order_history() -> list[dict]:
    """List every order this customer placed."""
    return await asyncio.to_thread(http_GET_customer_order_history)


def make_ctx(events: list | None = None) -> RunContext:
    """Build a run context whose emit appends to `events`."""
    return RunContext(deps=None, emit=None if events is None else events.append)


def call_of(name: str, arguments: dict, call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


# --- the decorator and the Tool record -------------------------------------


def test_tool_builds_a_tool_with_a_schema_from_the_signature():
    assert isinstance(get_order_status, Tool)
    assert get_order_status.name == "get_order_status"
    schema = get_order_status.input_model.model_json_schema()
    assert schema["properties"]["order_id"]["type"] == "string"
    assert schema["required"] == ["order_id"]
    assert get_order_status.description == "Return the shipping status of one order."
    assert get_order_history.name == "order_history" and get_order_history.parallel_safe
    assert not get_order_status.parallel_safe
    assert get_order_status.timeout_s is None and get_order_status.view is None
    spec = get_order_status.spec
    assert spec is get_order_status.spec
    assert isinstance(spec, ToolSpec)
    assert spec.name == get_order_status.name
    assert spec.description == get_order_status.description
    assert spec.parameters == schema


def test_tool_excludes_a_parameter_named_ctx_from_the_schema():
    schema = get_order_status.input_model.model_json_schema()
    assert "ctx" not in schema["properties"]


def test_tool_excludes_a_parameter_by_run_context_annotation():
    @tool
    async def annotated(order_id: str, context: RunContext[dict]) -> str:
        """Take the context under another name."""
        return order_id

    schema = annotated.input_model.model_json_schema()
    assert set(schema["properties"]) == {"order_id"}


def test_tool_keeps_annotated_field_descriptions_in_the_schema():
    @tool
    async def described(
        order_id: Annotated[str, Field(description="The order to look up.")],
        limit: int = 5,
    ) -> str:
        """Look one order up."""
        return order_id

    schema = described.input_model.model_json_schema()
    assert schema["properties"]["order_id"]["description"] == "The order to look up."
    assert schema["properties"]["limit"]["default"] == 5
    assert schema["required"] == ["order_id"]


def test_tool_input_model_forbids_extra_keys():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        get_order_status.input_model.model_validate({"order_id": "9127412", "hallucinated": 1})


async def test_tool_runs_a_plain_function_in_a_worker_thread():
    loop_thread = threading.get_ident()

    @tool
    def blocking(order_id: str) -> tuple[str, int]:
        """Run a blocking function away from the event loop."""
        return order_id, threading.get_ident()

    args = blocking.input_model.model_validate({"order_id": "9127412"})
    order_id, worker_thread = await blocking.execute(args, make_ctx())
    assert order_id == "9127412"
    assert worker_thread != loop_thread


async def test_plain_tool_receives_the_context():
    seen: list[RunContext] = []

    @tool
    def remember(ctx: RunContext) -> str:
        """Remember the run context."""
        seen.append(ctx)
        return "done"

    ctx = make_ctx()
    args = remember.input_model.model_validate({})
    assert await remember.execute(args, ctx) == "done"
    assert seen == [ctx]


async def test_cancelling_a_plain_tool_records_unknown_while_its_thread_finishes():
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    @tool
    def write() -> str:
        """Simulate a blocking write that cannot be stopped from asyncio."""
        started.set()
        release.wait(timeout=2)
        finished.set()
        return "written"

    ctx = make_ctx()
    task = asyncio.create_task(execute_tool(call_of("write", {}), [write], ctx=ctx))
    assert await asyncio.to_thread(started.wait, 2)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert isinstance(ctx.history[-1], ToolResultMessage)
    assert ctx.history[-1].status == "unknown"

    # Cancelling the await cannot terminate a function already running in a thread.
    release.set()
    assert await asyncio.to_thread(finished.wait, 2)


def test_tool_description_is_empty_without_a_docstring():
    @tool
    async def undocumented(order_id: str) -> str:
        return order_id

    assert undocumented.description == ""


def test_is_parallel_safe_reads_a_flag_or_calls_a_predicate():
    args = get_order_status.input_model.model_validate({"order_id": "9127412"})
    assert get_order_status.is_parallel_safe(args) is False
    assert get_order_history.is_parallel_safe(get_order_history.input_model.model_validate({}))

    seen: list[BaseModel] = []

    @tool(parallel_safe=lambda args: seen.append(args) or args.path != "/shared")
    async def write_file(path: str) -> str:
        """Write one file."""
        return path

    safe = write_file.input_model.model_validate({"path": "/tmp/a"})
    unsafe = write_file.input_model.model_validate({"path": "/shared"})
    assert write_file.is_parallel_safe(safe) is True
    assert write_file.is_parallel_safe(unsafe) is False
    assert [a.path for a in seen] == ["/tmp/a", "/shared"]


async def test_tool_execute_passes_validated_args_and_the_context():
    seen: list[object] = []

    @tool
    async def echo(order_id: str, ctx: RunContext) -> str:
        """Echo the order id."""
        seen.append(ctx)
        return order_id

    ctx = make_ctx()
    args = echo.input_model.model_validate({"order_id": "9127412"})
    assert await echo.execute(args, ctx) == "9127412"
    assert seen == [ctx]


async def test_tool_execute_omits_the_context_when_the_function_takes_none():
    args = get_order_history.input_model.model_validate({})
    history = await get_order_history.execute(args, make_ctx())
    assert [order["order_id"] for order in history] == ["9127412", "3451323"]


# --- execute_tool ----------------------------------------------------------


async def test_unknown_tool_name_fails_without_starting_anything():
    events: list = []
    result = await execute_tool(call_of("missing", {}), [get_order_status], ctx=make_ctx(events))
    assert isinstance(result, ToolResultMessage)
    assert result.status == "not_started"
    assert "unknown tool missing" in result.content and "No tool executed" in result.content
    assert result.call_id == "c1"
    assert result.name == "missing"
    assert result.view is None
    assert [type(e).__name__ for e in events] == ["ToolFinished"]


async def test_invalid_input_fails_with_the_pydantic_message():
    events: list = []
    result = await execute_tool(
        call_of("get_order_status", {"wrong": 1}), [get_order_status], ctx=make_ctx(events)
    )
    assert result.status == "not_started"
    assert "get_order_status_input" in result.content
    assert "wrong" in result.content
    assert result.view is None
    assert [type(e).__name__ for e in events] == ["ToolFinished"]


async def test_a_denied_call_carries_the_reason_and_never_starts():
    events: list = []
    hooks = Hooks(before_tool=lambda tool, args, ctx: _decide(DENY("Not your order")))
    result = await execute_tool(
        call_of("get_order_status", {"order_id": "9127412"}),
        [get_order_status],
        ctx=make_ctx(events),
        hooks=hooks,
    )
    assert result.status == "denied"
    assert result.content == "Not your order"
    assert [type(e).__name__ for e in events] == ["ToolFinished"]


async def test_a_denied_call_without_a_reason_says_denied_by_policy():
    hooks = Hooks(before_tool=lambda tool, args, ctx: _decide(Decision("deny")))
    result = await execute_tool(
        call_of("get_order_status", {"order_id": "9127412"}),
        [get_order_status],
        ctx=make_ctx(),
        hooks=hooks,
    )
    assert result.status == "denied"
    assert result.content == "Denied by policy"


async def test_ask_returns_a_pending_approval_and_runs_no_after_tool():
    events: list = []
    after_tool_calls: list = []

    async def after_tool(result, ctx):
        after_tool_calls.append(result)
        return result

    hooks = Hooks(
        before_tool=lambda tool, args, ctx: _decide(Decision("ask", "Needs a human")),
        after_tool=after_tool,
    )
    pending = await execute_tool(
        call_of("get_order_status", {"order_id": "9127412"}),
        [get_order_status],
        ctx=make_ctx(events),
        hooks=hooks,
    )
    assert isinstance(pending, PendingApproval)
    assert pending.reason == "Needs a human"
    assert pending.args.order_id == "9127412"
    assert pending.call.id == "c1"
    assert after_tool_calls == []
    assert [type(e).__name__ for e in events] == ["ToolFinished"]
    assert events[0].result is pending


async def test_an_allowed_call_completes_and_emits_start_then_finish():
    events: list = []
    result = await execute_tool(
        call_of("get_order_status", {"order_id": "9127412"}),
        [get_order_status],
        ctx=make_ctx(events),
    )
    assert result.status == "completed"
    payload = json.loads(result.content)
    assert payload["order_id"] == "9127412"
    assert payload["status"] in {"pending", "shipped", "delivered", "cancelled"}
    assert [type(e).__name__ for e in events] == ["ToolStarted", "ToolFinished"]
    assert events[0].call.name == "get_order_status"
    assert events[1].result is result


async def test_a_raised_error_inside_the_tool_becomes_a_failed_result():
    events: list = []
    result = await execute_tool(
        call_of("get_order_status", {"order_id": "0000"}),
        [get_order_status],
        ctx=make_ctx(events),
    )
    assert result.status == "failed"
    assert result.content == "ValueError: Order not found"
    assert [type(e).__name__ for e in events] == ["ToolStarted", "ToolFinished"]


async def test_a_timeout_becomes_an_unknown_outcome():
    @tool(timeout_s=0.01)
    async def slow_write() -> str:
        """Take too long."""
        await asyncio.sleep(1)
        return "written"

    result = await execute_tool(call_of("slow_write", {}), [slow_write], ctx=make_ctx())
    assert result.status == "unknown"
    assert result.content == "Outcome unknown: slow_write did not respond within 0.01s"


async def test_outcome_unknown_becomes_an_unknown_outcome():
    @tool
    async def charge() -> str:
        """Lose the response."""
        raise OutcomeUnknown("Payment sent, response lost")

    result = await execute_tool(call_of("charge", {}), [charge], ctx=make_ctx())
    assert result.status == "unknown"
    assert result.content == "Outcome unknown: Payment sent, response lost"


async def test_outcome_unknown_without_a_message_says_outcome_unknown():
    @tool
    async def charge() -> str:
        """Lose the response with no message."""
        raise OutcomeUnknown

    result = await execute_tool(call_of("charge", {}), [charge], ctx=make_ctx())
    assert result.status == "unknown"
    assert result.content == "Outcome unknown"


async def test_cancellation_propagates_after_recording_an_unknown_result():
    events: list = []
    entered = asyncio.Event()

    @tool
    async def slow() -> str:
        """Wait to be cancelled."""
        entered.set()
        await asyncio.sleep(10)
        return "done"

    ctx = make_ctx(events)
    task = asyncio.create_task(execute_tool(call_of("slow", {}), [slow], ctx=ctx))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [type(e).__name__ for e in events] == ["ToolStarted", "ToolFinished"]
    assert len(ctx.history) == 1
    result = ctx.history[0]
    assert isinstance(result, ToolResultMessage)
    assert result.status == "unknown"
    assert result.content == "Outcome unknown: slow was cancelled after it started"
    assert events[-1].result is result


async def test_before_tool_receives_the_tool_the_validated_args_and_the_context():
    seen: list = []

    async def before_tool(tool_arg, args, ctx):
        seen.append((tool_arg, args, ctx))
        return ALLOW

    ctx = make_ctx()
    await execute_tool(
        call_of("get_order_status", {"order_id": "9127412"}),
        [get_order_status],
        ctx=ctx,
        hooks=Hooks(before_tool=before_tool),
    )
    assert len(seen) == 1
    seen_tool, seen_args, seen_ctx = seen[0]
    assert seen_tool is get_order_status
    assert isinstance(seen_args, get_order_status.input_model)
    assert seen_args.order_id == "9127412"
    assert seen_ctx is ctx


async def test_after_tool_runs_on_denied_and_failed_results_and_replaces_them():
    seen: list = []

    async def after_tool(result, ctx):
        seen.append(result.status)
        return ToolResultMessage(
            call_id=result.call_id,
            name=result.name,
            content="redacted",
            status=result.status,
        )

    hooks_deny = Hooks(
        before_tool=lambda tool, args, ctx: _decide(DENY("no")), after_tool=after_tool
    )
    denied = await execute_tool(
        call_of("get_order_status", {"order_id": "9127412"}),
        [get_order_status],
        ctx=make_ctx(),
        hooks=hooks_deny,
    )
    failed = await execute_tool(
        call_of("get_order_status", {"order_id": "0000"}),
        [get_order_status],
        ctx=make_ctx(),
        hooks=Hooks(after_tool=after_tool),
    )
    unknown_name = await execute_tool(
        call_of("missing", {}),
        [get_order_status],
        ctx=make_ctx(),
        hooks=Hooks(after_tool=after_tool),
    )
    assert seen == ["denied", "failed", "not_started"]
    assert [r.content for r in (denied, failed, unknown_name)] == ["redacted"] * 3


async def test_tool_started_precedes_the_body_and_tool_finished_follows_after_tool():
    events: list = []

    @tool
    async def look(ctx: RunContext) -> str:
        """Report what the frontend has seen so far."""
        events.append("body")
        return "ok"

    async def after_tool(result, ctx):
        events.append("after_tool")
        return result

    await execute_tool(
        call_of("look", {}), [look], ctx=make_ctx(events), hooks=Hooks(after_tool=after_tool)
    )
    assert [e if isinstance(e, str) else type(e).__name__ for e in events] == [
        "ToolStarted",
        "body",
        "after_tool",
        "ToolFinished",
    ]


async def test_a_tool_output_return_splits_into_content_and_view():
    @tool(view="order-card")
    async def get_order(order_id: str) -> ToolOutput:
        """Return one order."""
        return ToolOutput(
            content={"order_id": order_id, "status": "shipped"},
            view=View("order-card", {"order": {"id": order_id}, "highlight": "status"}),
        )

    result = await execute_tool(
        call_of("get_order", {"order_id": "9127412"}), [get_order], ctx=make_ctx()
    )
    assert json.loads(result.content) == {"order_id": "9127412", "status": "shipped"}
    assert result.view == View("order-card", {"order": {"id": "9127412"}, "highlight": "status"})


async def test_a_plain_return_on_a_viewed_tool_gets_the_default_view():
    events: list = []

    @tool(view="order-card")
    async def get_order(order_id: str) -> str:
        """Return one order as text."""
        return "shipped"

    result = await execute_tool(
        call_of("get_order", {"order_id": "9127412"}), [get_order], ctx=make_ctx(events)
    )
    assert result.content == "shipped"
    assert result.view == View(
        "order-card", {"args": {"order_id": "9127412"}, "status": "completed"}
    )


async def test_a_denied_call_on_a_viewed_tool_gets_the_denied_default_view():
    @tool(view="order-card")
    async def get_order(order_id: str) -> str:
        """Return one order as text."""
        return "shipped"

    result = await execute_tool(
        call_of("get_order", {"order_id": "9127412"}),
        [get_order],
        ctx=make_ctx(),
        hooks=Hooks(before_tool=lambda tool, args, ctx: _decide(DENY("no"))),
    )
    assert result.view == View("order-card", {"args": {"order_id": "9127412"}, "status": "denied"})


async def test_tool_started_and_pending_approval_carry_the_tool_view_with_args():
    events: list = []

    @tool(view="order-card")
    async def get_order(order_id: str) -> str:
        """Return one order as text."""
        return "shipped"

    await execute_tool(
        call_of("get_order", {"order_id": "9127412"}), [get_order], ctx=make_ctx(events)
    )
    assert events[0].view == View("order-card", {"args": {"order_id": "9127412"}})

    pending = await execute_tool(
        call_of("get_order", {"order_id": "9127412"}),
        [get_order],
        ctx=make_ctx(),
        hooks=Hooks(before_tool=lambda tool, args, ctx: _decide(ASK)),
    )
    assert pending.view == View("order-card", {"args": {"order_id": "9127412"}})


async def test_a_tool_without_a_view_gets_no_view_anywhere():
    events: list = []
    result = await execute_tool(
        call_of("get_order_status", {"order_id": "9127412"}),
        [get_order_status],
        ctx=make_ctx(events),
    )
    assert result.view is None
    assert events[0].view is None


async def test_a_string_return_passes_through_and_anything_else_is_serialized():
    @tool
    async def as_text() -> str:
        """Return text."""
        return "  raw text  "

    @tool
    async def as_none() -> None:
        """Return nothing."""
        return None

    class Order(BaseModel):
        order_id: str

    @tool
    async def as_model() -> Order:
        """Return a pydantic model."""
        return Order(order_id="9127412")

    ctx = make_ctx()
    text = await execute_tool(call_of("as_text", {}), [as_text], ctx=ctx)
    nothing = await execute_tool(call_of("as_none", {}), [as_none], ctx=ctx)
    model = await execute_tool(call_of("as_model", {}), [as_model], ctx=ctx)
    assert text.content == "  raw text  "
    assert nothing.content == "null"
    assert json.loads(model.content) == {"order_id": "9127412"}


async def test_an_absent_emit_is_not_an_error():
    ctx = RunContext(deps=None)
    assert ctx.emit is None
    result = await execute_tool(
        call_of("get_order_status", {"order_id": "9127412"}), [get_order_status], ctx=ctx
    )
    assert result.status == "completed"


# --- execute_tools ---------------------------------------------------------


async def test_execute_tools_returns_results_in_call_order():
    calls = [
        call_of("order_history", {}, "a"),
        call_of("missing", {}, "b"),
        call_of("get_order_status", {"wrong": 1}, "c"),
        call_of("get_order_status", {"order_id": "9127412"}, "d"),
    ]
    results = await execute_tools(calls, [get_order_status, get_order_history], ctx=make_ctx())
    assert [r.call_id for r in results] == ["a", "b", "c", "d"]
    assert [r.status for r in results] == ["completed", "not_started", "not_started", "completed"]


async def test_a_batch_of_parallel_safe_calls_overlaps():
    order: list[str] = []

    @tool(parallel_safe=True)
    async def touch(path: str) -> str:
        """Touch one path."""
        order.append(f"start {path}")
        await asyncio.sleep(0.05)
        order.append(f"finish {path}")
        return path

    calls = [call_of("touch", {"path": "/a"}, "a"), call_of("touch", {"path": "/b"}, "b")]
    results = await execute_tools(calls, [touch], ctx=make_ctx())
    assert [r.call_id for r in results] == ["a", "b"]
    assert order == ["start /a", "start /b", "finish /a", "finish /b"]


async def test_an_unsafe_call_runs_alone_and_its_safe_neighbors_still_overlap():
    order: list[str] = []
    checked: list[str] = []

    def safe_unless_shared(args) -> bool:
        checked.append(args.path)
        return args.path != "/shared"

    @tool(parallel_safe=safe_unless_shared)
    async def touch(path: str) -> str:
        """Touch one path."""
        order.append(f"start {path}")
        await asyncio.sleep(0.05)
        order.append(f"finish {path}")
        return path

    calls = [
        call_of("touch", {"path": "/a"}, "a"),
        call_of("touch", {"path": "/shared"}, "b"),
        call_of("touch", {"path": "/c"}, "c"),
        call_of("touch", {"path": "/d"}, "d"),
    ]
    results = await execute_tools(calls, [touch], ctx=make_ctx())
    assert [r.call_id for r in results] == ["a", "b", "c", "d"]
    # The predicate runs once per call, in call order.
    assert checked == ["/a", "/shared", "/c", "/d"]
    # /a alone, then /shared alone, then /c and /d together.
    assert order == [
        "start /a",
        "finish /a",
        "start /shared",
        "finish /shared",
        "start /c",
        "start /d",
        "finish /c",
        "finish /d",
    ]


async def test_an_inline_failure_does_not_make_the_batch_sequential():
    order: list[str] = []

    @tool(parallel_safe=True)
    async def touch(path: str) -> str:
        """Touch one path."""
        order.append(f"start {path}")
        await asyncio.sleep(0.05)
        order.append(f"finish {path}")
        return path

    calls = [
        call_of("missing", {}, "a"),
        call_of("touch", {"path": "/a"}, "b"),
        call_of("touch", {"path": "/b"}, "c"),
    ]
    results = await execute_tools(calls, [touch], ctx=make_ctx())
    assert [r.call_id for r in results] == ["a", "b", "c"]
    assert results[0].status == "not_started"
    assert order == ["start /a", "start /b", "finish /a", "finish /b"]


async def test_execute_tools_on_an_empty_batch_returns_nothing():
    assert await execute_tools([], [get_order_status], ctx=make_ctx()) == []


async def test_an_unserializable_return_becomes_a_failed_result():
    events: list = []
    after_tool_calls: list = []

    async def after_tool(result, ctx):
        after_tool_calls.append(result.status)
        return result

    class Widget:
        """A type no serializer knows."""

    @tool
    async def build_widget() -> object:
        """Return something JSON cannot carry."""
        return Widget()

    result = await execute_tool(
        call_of("build_widget", {}),
        [build_widget],
        ctx=make_ctx(events),
        hooks=Hooks(after_tool=after_tool),
    )
    assert result.status == "failed"
    assert result.content.startswith("PydanticSerializationError")
    assert after_tool_calls == ["failed"]
    assert [type(e).__name__ for e in events] == ["ToolStarted", "ToolFinished"]


async def test_an_unserializable_view_content_becomes_a_failed_result():
    class Widget:
        """A type no serializer knows."""

    @tool(view="widget-card")
    async def build_widget() -> ToolOutput:
        """Return something JSON cannot carry inside a ToolOutput."""
        return ToolOutput(content=Widget(), view=View("widget-card", {}))

    result = await execute_tool(call_of("build_widget", {}), [build_widget], ctx=make_ctx())
    assert result.status == "failed"
    assert result.content.startswith("PydanticSerializationError")


async def test_parallel_safe_and_the_body_share_one_validated_args_object():
    checked: list = []
    executed: list = []

    class Args(BaseModel):
        path: str = "/default"

    async def execute(args: BaseModel, ctx: RunContext) -> str:
        executed.append(args)
        return args.path

    def predicate(args: BaseModel) -> bool:
        checked.append(args)
        return True

    probe = Tool(
        name="probe",
        description="Record the args object it runs on.",
        input_model=Args,
        execute=execute,
        parallel_safe=predicate,
    )
    results = await execute_tools([call_of("probe", {}, "a")], [probe], ctx=make_ctx())
    assert [r.content for r in results] == ["/default"]
    assert len(checked) == 1
    assert len(executed) == 1
    assert checked[0] is executed[0]
