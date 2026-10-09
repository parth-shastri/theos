"""Tests for harness.loop: the reference turn loop."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from harness.context import RunContext, unanswered_calls
from harness.events import (
    GenerationComplete,
    ModelCalled,
    ModelResponded,
    ReasoningDelta,
    TextDelta,
    ToolCallDelta,
    ToolStarted,
)
from harness.hooks import Hooks, require_approval
from harness.inbox import Inbox
from harness.loop import TurnFinished, TurnResult, run_turn, run_turn_stream
from harness.tools import tool
from harness.types import (
    AssistantMessage,
    Budget,
    ModelRequest,
    PendingApproval,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

ran: list[str] = []


@pytest.fixture(autouse=True)
def clear_ran():
    ran.clear()


@tool(parallel_safe=True)
async def lookup(order_id: str) -> str:
    """Look one order up."""
    ran.append(order_id)
    return f"order {order_id} shipped"


@tool
async def slow_lookup(order_id: str) -> str:
    """Take longer than the test is willing to wait."""
    ran.append(order_id)
    await asyncio.sleep(10)
    return "never"


@tool
async def steering_lookup(order_id: str, ctx: RunContext) -> str:
    """Look one order up while the user types something else."""
    ran.append(order_id)
    ctx.inbox.steer(UserMessage("also check refunds"))
    return "shipped"


def call(name: str = "lookup", call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={"order_id": "9127412"})


def calls_message(name: str = "lookup") -> AssistantMessage:
    return AssistantMessage(tool_calls=[call(name)])


# --- completion, tools, and resume -----------------------------------------


async def test_a_text_response_completes_the_turn(fake_model):
    model = fake_model([AssistantMessage(text="Order 9127412 shipped.")])
    history = [UserMessage("Where is my order?")]
    result = await run_turn(model, [lookup], history)
    assert isinstance(result, TurnResult)
    assert result.status == "completed"
    assert result.message is history[-1]
    assert result.message.text == "Order 9127412 shipped."
    assert len(history) == 2


async def test_tool_calls_run_and_the_loop_continues(fake_model):
    model = fake_model([calls_message(), AssistantMessage(text="It shipped.")])
    history = [UserMessage("Where is my order?")]
    result = await run_turn(model, [lookup], history)
    assert ran == ["9127412"]
    assert result.status == "completed"
    assert [type(m).__name__ for m in history] == [
        "UserMessage",
        "AssistantMessage",
        "ToolResultMessage",
        "AssistantMessage",
    ]
    assert isinstance(model.requests[1].messages[-1], ToolResultMessage)
    assert model.requests[1].messages[-1].content == "order 9127412 shipped"


async def test_an_ask_pauses_the_turn_and_history_keeps_no_pending_approval(fake_model):
    model = fake_model([calls_message(), AssistantMessage(text="It shipped.")])
    history = [UserMessage("Where is my order?")]
    hooks = Hooks(before_tool=require_approval("lookup"))
    result = await run_turn(model, [lookup], history, hooks=hooks)
    assert result.status == "waiting_for_approval"
    assert [p.call.id for p in result.pending] == ["c1"]
    assert ran == []
    assert len(history) == 2
    assert not any(isinstance(m, PendingApproval) for m in history)

    history.append(ToolResultMessage("c1", "lookup", "order 9127412 shipped"))
    resumed = await run_turn(model, [lookup], history, hooks=hooks)
    assert resumed.status == "completed"
    assert resumed.message.text == "It shipped."


async def test_a_shared_budget_runs_out_across_a_pause(fake_model):
    model = fake_model([calls_message(), AssistantMessage(text="It shipped.")])
    history = [UserMessage("Where is my order?")]
    hooks = Hooks(before_tool=require_approval("lookup"))
    budget = Budget(max_model_calls=1)
    paused = await run_turn(model, [lookup], history, hooks=hooks, budget=budget)
    assert paused.status == "waiting_for_approval"
    assert budget.used == 1

    history.append(ToolResultMessage("c1", "lookup", "order 9127412 shipped"))
    exhausted = await run_turn(model, [lookup], history, hooks=hooks, budget=budget)
    assert exhausted.status == "budget_exhausted"
    assert exhausted.message is history[1]
    assert len(model.requests) == 1


async def test_the_default_budget_allows_ten_model_calls(fake_model):
    model = fake_model([calls_message() for _ in range(12)])
    history = [UserMessage("Where is my order?")]
    result = await run_turn(model, [lookup], history)
    assert result.status == "budget_exhausted"
    assert len(model.requests) == 10


# --- cancellation and a failing stream --------------------------------------


async def test_cancelling_during_a_slow_tool_records_unknown_and_prevents_a_retry(
    fake_model,
):
    model = fake_model([calls_message("slow_lookup"), AssistantMessage(text="It shipped.")])
    history = [UserMessage("Where is my order?")]
    task = asyncio.create_task(run_turn(model, [slow_lookup], history))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert isinstance(history[-1], ToolResultMessage)
    assert history[-1].status == "unknown"
    assert unanswered_calls(history) == []
    assert ran == ["9127412"]

    # Resuming sends the uncertain result to the model instead of repeating the tool.
    fast = replace(slow_lookup, execute=lookup.execute)
    result = await run_turn(model, [fast], history)
    assert ran == ["9127412"]
    assert result.status == "completed"
    assert isinstance(history[-2], ToolResultMessage)


async def test_a_stream_that_fails_mid_message_changes_nothing(fake_model):
    model = fake_model([RuntimeError("stream died")])
    history = [UserMessage("Where is my order?")]
    with pytest.raises(RuntimeError, match="stream died"):
        await run_turn(model, [lookup], history)
    assert history == [UserMessage("Where is my order?")]
    assert ran == []


# --- steering ---------------------------------------------------------------


async def test_steering_lands_after_tool_results_and_before_the_next_request(fake_model):
    model = fake_model([calls_message("steering_lookup"), AssistantMessage(text="Both done.")])
    history = [UserMessage("Where is my order?")]
    inbox = Inbox()
    result = await run_turn(model, [steering_lookup], history, inbox=inbox)
    assert result.status == "completed"
    assert [type(m).__name__ for m in history] == [
        "UserMessage",
        "AssistantMessage",
        "ToolResultMessage",
        "UserMessage",
        "AssistantMessage",
    ]
    second = model.requests[1].messages
    assert isinstance(second[-2], ToolResultMessage)
    assert second[-1] == UserMessage("also check refunds")


async def test_steering_after_a_text_response_triggers_one_more_model_call(fake_model):
    model = fake_model([AssistantMessage(text="First."), AssistantMessage(text="Second.")])
    inbox = Inbox()
    steered: list[int] = []

    async def steer_once(message: AssistantMessage, ctx: RunContext) -> AssistantMessage:
        if not steered:
            steered.append(1)
            inbox.steer(UserMessage("one more thing"))
        return message

    history = [UserMessage("Where is my order?")]
    result = await run_turn(
        model, [], history, hooks=Hooks(after_model=steer_once), inbox=inbox
    )
    assert len(model.requests) == 2
    assert model.requests[1].messages[-1] == UserMessage("one more thing")
    assert result.status == "completed"
    assert result.message.text == "Second."


# --- instructions -----------------------------------------------------------


async def test_instructions_reach_the_request_and_never_the_history(fake_model):
    model = fake_model([AssistantMessage(text="Sure.")])
    history = [UserMessage("Where is my order?")]
    await run_turn(model, [], history, instructions="You are a support agent.")
    assert model.requests[0].messages[0] == SystemMessage("You are a support agent.")
    assert not any(isinstance(m, SystemMessage) for m in history)


async def test_a_callable_instruction_reads_the_context_on_every_model_call(fake_model):
    model = fake_model([calls_message(), AssistantMessage(text="It shipped.")])
    seen: list[RunContext] = []

    def build(ctx: RunContext) -> str:
        seen.append(ctx)
        return f"Customer {ctx.deps}. Call {len(seen)}."

    history = [UserMessage("Where is my order?")]
    await run_turn(model, [lookup], history, deps="ada", instructions=build)
    assert [r.messages[0].content for r in model.requests] == [
        "Customer ada. Call 1.",
        "Customer ada. Call 2.",
    ]
    assert seen[0] is seen[1]
    assert seen[0].deps == "ada"
    assert seen[0].history is history


async def test_an_async_instruction_builder_is_awaited(fake_model):
    model = fake_model([AssistantMessage(text="Sure.")])

    async def build(ctx: RunContext) -> str:
        await asyncio.sleep(0)
        return f"Tier {ctx.deps}."

    history = [UserMessage("Where is my order?")]
    await run_turn(model, [], history, deps="gold", instructions=build)
    assert model.requests[0].messages[0] == SystemMessage("Tier gold.")


# --- hooks and events -------------------------------------------------------


async def test_before_model_sees_and_can_replace_the_request(fake_model):
    model = fake_model([AssistantMessage(text="Sure.")])
    seen: list[ModelRequest] = []

    async def add_policy(request: ModelRequest, ctx: RunContext) -> ModelRequest:
        seen.append(request)
        note = SystemMessage("Relevant policy: returns within 30 days.")
        return replace(request, messages=[note, *request.messages])

    history = [UserMessage("Where is my order?")]
    await run_turn(model, [], history, hooks=Hooks(before_model=add_policy))
    assert len(seen) == 1
    assert model.requests[0].messages[0] == SystemMessage(
        "Relevant policy: returns within 30 days."
    )
    assert model.requests[0] is not seen[0]


async def test_after_model_replaces_the_message_that_lands_in_history(fake_model):
    model = fake_model([AssistantMessage(text="Card 4111 1111 1111 1111.")])

    async def redact(message: AssistantMessage, ctx: RunContext) -> AssistantMessage:
        return replace(message, text="[redacted]")

    history = [UserMessage("What card is on file?")]
    result = await run_turn(model, [], history, hooks=Hooks(after_model=redact))
    assert history[-1].text == "[redacted]"
    assert result.message.text == "[redacted]"


async def test_model_events_are_emitted_once_per_call(fake_model):
    model = fake_model([calls_message(), AssistantMessage(text="It shipped.")])
    history = [UserMessage("Where is my order?")]
    events = [event async for event in run_turn_stream(model, [lookup], history)]
    called = [e for e in events if isinstance(e, ModelCalled)]
    responded = [e for e in events if isinstance(e, ModelResponded)]
    assert len(called) == 2
    assert len(responded) == 2
    assert called[0].request is model.requests[0]
    assert responded[1].message is history[-1]


async def test_every_model_delta_is_forwarded_and_the_final_message_is_not():
    class DeltaModel:
        provider = "fake"
        model_id = "fake-1"

        async def stream(self, request):
            yield ReasoningDelta("Check the order.")
            yield ToolCallDelta(0, name="lookup")
            yield ToolCallDelta(0, '{"order_id": "9127412"}')
            yield TextDelta("Looking.")
            yield GenerationComplete(AssistantMessage(text="Looking."))

    history = [UserMessage("Where is my order?")]
    events = [event async for event in run_turn_stream(DeltaModel(), [], history)]
    deltas = [e for e in events if isinstance(e, ReasoningDelta | ToolCallDelta | TextDelta)]
    assert deltas == [
        ReasoningDelta("Check the order."),
        ToolCallDelta(0, name="lookup"),
        ToolCallDelta(0, '{"order_id": "9127412"}'),
        TextDelta("Looking."),
    ]
    assert not any(isinstance(e, GenerationComplete) for e in events)


async def test_the_estimator_decides_what_context_trimming_keeps(fake_model):
    history = [UserMessage("first"), AssistantMessage(text="one"), UserMessage("second")]

    # The default estimate makes this history too big for the budget.
    trimmed = fake_model([AssistantMessage(text="ok")])
    await run_turn(trimmed, [], list(history), max_context_tokens=1)
    assert len(trimmed.requests[0].messages) < len(history)

    # An estimator that counts nothing keeps every message.
    kept = fake_model([AssistantMessage(text="ok")])
    await run_turn(kept, [], list(history), max_context_tokens=1, estimate_tokens=lambda m: 0)
    assert kept.requests[0].messages == history


async def test_run_turn_returns_the_same_result_as_the_stream(fake_model):
    script = [calls_message(), AssistantMessage(text="It shipped.")]
    streamed_history = [UserMessage("Where is my order?")]
    buffered_history = [UserMessage("Where is my order?")]

    events = [
        event
        async for event in run_turn_stream(
            fake_model(list(script)), [lookup], streamed_history
        )
    ]
    buffered = await run_turn(fake_model(list(script)), [lookup], buffered_history)

    assert events[-1] == TurnFinished(buffered)
    assert streamed_history == buffered_history


async def test_run_stream_yields_tool_started_before_the_tool_body(fake_model):
    body_started: list[bool] = []
    history = [UserMessage("Where is my order?")]

    @tool
    async def gated_lookup(order_id: str) -> str:
        body_started.append(True)
        return f"order {order_id} shipped"

    model = fake_model(
        [calls_message("gated_lookup"), AssistantMessage(text="It shipped.")]
    )
    events = run_turn_stream(model, [gated_lookup], history)

    async for event in events:
        if isinstance(event, ToolStarted):
            assert body_started == []
            break

    await events.aclose()
    assert isinstance(history[-1], ToolResultMessage)
    assert history[-1].status == "unknown"
