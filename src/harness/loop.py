"""A small model → tools → model loop. (the inner loop)"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import aclosing, suppress
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from harness.compaction import CompactionConfig, ContextMemory
from harness.context import (
    ContextLimitError,
    RunContext,
    default_estimate,
    select_context,
    unanswered_calls,
)
from harness.debug import log_detail, log_event
from harness.events import Event, GenerationComplete, ModelCalled, ModelResponded, _ScopedEvent
from harness.hooks import Hooks
from harness.inbox import Inbox
from harness.limits import DEFAULT_EXECUTION_LIMITS, ExecutionLimits, validate_assistant_message
from harness.model import ChatModel
from harness.output import DEFAULT_OUTPUT_RESERVATION, requested_output_tokens
from harness.tools import Tool, execute_tools
from harness.types import (
    AssistantMessage,
    Budget,
    Message,
    ModelRequest,
    PendingApproval,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
)

__all__ = [
    "EstimateTokens",
    "Instructions",
    "RunEvent",
    "TurnFinished",
    "TurnResult",
    "collect_run_stream",
    "run_turn",
    "run_turn_stream",
]

Instructions = str | Callable[[RunContext], str | Awaitable[str]]
"""Static instructions or a function that builds them for each model call.

Providers cache the request prefix, and the instructions sit at its front. Keep
the text identical between calls. One changed byte, such as a timestamp, makes
every later model call pay for the whole prefix again.
"""

EstimateTokens = Callable[[Sequence[Message]], int]
"""Count the tokens of a message list. The default counts four characters each."""


@dataclass
class TurnResult:
    """The final state of one turn."""

    status: Literal["completed", "waiting_for_approval", "budget_exhausted"]
    pending: list[PendingApproval] = field(default_factory=list)
    message: AssistantMessage | None = None  # last assistant message


@dataclass(frozen=True)
class TurnFinished(_ScopedEvent):
    """The final event from `run_turn_stream()`."""

    result: TurnResult


RunEvent = Event | TurnFinished


@dataclass(frozen=True)
class _ToolBatchFinished:
    results: list[ToolResultMessage | PendingApproval]


async def _resolve(instructions: Instructions, ctx: RunContext) -> str:
    """Build the instruction text for this model call."""
    if callable(instructions):
        built = instructions(ctx)
        if inspect.isawaitable(built):
            return await built
        return built
    return instructions


def _last_assistant(history: Sequence[Message]) -> AssistantMessage | None:
    """The most recent assistant message, or None when there is none."""
    return next(
        (m for m in reversed(history) if isinstance(m, AssistantMessage)),
        None,
    )


async def _stream_tools(
    calls: Sequence[ToolCall],
    tools: Sequence[Tool],
    ctx: RunContext,
    hooks: Hooks,
    limits: ExecutionLimits,
) -> AsyncIterator[Event | _ToolBatchFinished]:
    """Bridge the tool executor's events into an async iterator."""
    log_detail("tool stream start calls=%r tool_count=%d", calls, len(tools))
    done = object()
    queue: asyncio.Queue[Event | object] = asyncio.Queue()
    previous_emit = ctx.emit
    ctx.emit = queue.put_nowait

    async def execute() -> list[ToolResultMessage | PendingApproval]:
        try:
            return await execute_tools(calls, tools, ctx=ctx, hooks=hooks, limits=limits)
        finally:
            queue.put_nowait(done)

    task = asyncio.create_task(execute())
    try:
        while True:
            event = await queue.get()
            if event is done:
                break
            yield cast(Event, event)
        results = await task
        log_detail("tool stream complete results=%r", results)
        yield _ToolBatchFinished(results)
    finally:
        ctx.emit = previous_emit
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task


async def collect_run_stream(events: AsyncIterator[RunEvent]) -> TurnResult:
    """Consume a turn stream and return the exact result from its final event."""
    result: TurnResult | None = None
    async for event in events:
        if isinstance(event, TurnFinished):
            if result is not None:
                raise RuntimeError("turn stream produced more than one final result")
            result = event.result
    if result is None:
        raise RuntimeError("turn stream ended without a final result")
    return result


async def _build_request(
    model: ChatModel,
    *,
    prefix: Sequence[Message],
    history: Sequence[Message],
    tools: Sequence[Tool],
    ctx: RunContext,
    hooks: Hooks,
    max_context_tokens: int | None,
    estimate_tokens: EstimateTokens,
    context_window: int | None,
    reserved_output_tokens: int,
    compaction: CompactionConfig | None,
    compaction_budget: Budget | None,
) -> AsyncIterator[RunEvent | ModelRequest]:
    """Build a request that fits the model window, including tools and reply room."""

    def build(selected: Sequence[Message]) -> ModelRequest:
        return ModelRequest([*prefix, *selected], [tool.spec for tool in tools])

    async def prepare(selected: Sequence[Message]) -> ModelRequest:
        request = build(selected)
        return await hooks.before_model(request, ctx) if hooks.before_model else request

    if context_window is None:
        selected = select_context(
            history, max_tokens=max_context_tokens, estimate_tokens=estimate_tokens
        )
        if compaction is not None:
            raise ValueError("compaction requires context_window")
        yield await prepare(selected)
        return

    if context_window < 1 or reserved_output_tokens < 0:
        raise ValueError("context_window must be positive and output reservation non-negative")

    if compaction is not None:
        request = await prepare(ctx.memory.view(history))
        async for event in model.prepare(request):
            yield event
        return

    fixed = await model.estimate_tokens(build([]))
    # Read the output setting from the prepared request before reducing history.
    budget = context_window - fixed
    if max_context_tokens is not None:
        budget = min(budget, max_context_tokens)

    output_tokens = reserved_output_tokens
    for _ in range(6):
        if budget <= 0:
            break
        selected = select_context(history, max_tokens=budget, estimate_tokens=estimate_tokens)
        request = await prepare(selected)
        output_tokens = requested_output_tokens(request, reserved_output_tokens)
        over = await model.estimate_tokens(request) + output_tokens - context_window
        if over <= 0:
            yield request
            return
        if len(selected) <= 1:
            break
        selected_cost = estimate_tokens(selected)
        budget = min(selected_cost, budget) - over - 32

    raise ContextLimitError(
        f"request does not fit a {context_window}-token window with "
        f"{output_tokens} output tokens reserved"
    )


async def run_turn_stream(
    model: ChatModel,
    tools: Sequence[Tool],
    history: list[Message],
    *,
    deps: Any = None,
    hooks: Hooks | None = None,
    instructions: Instructions | None = None,
    inbox: Inbox | None = None,
    budget: Budget | None = None,
    compaction_budget: Budget | None = None,
    max_context_tokens: int | None = None,
    estimate_tokens: EstimateTokens = default_estimate,
    context_window: int | None = None,
    reserved_output_tokens: int = DEFAULT_OUTPUT_RESERVATION,
    limits: ExecutionLimits = DEFAULT_EXECUTION_LIMITS,
    compaction: CompactionConfig | None = None,
    memory: ContextMemory | None = None,
) -> AsyncIterator[RunEvent]:
    """Yield events until the model answers, pauses, or uses the budget."""
    budget = budget or Budget(max_model_calls=10)
    ctx = RunContext(
        deps=deps,
        history=history,
        budget=budget,
        inbox=inbox,
        memory=memory if memory is not None else ContextMemory(),
    )
    hooks = hooks or Hooks()
    if compaction is not None and context_window is not None:
        from harness.lean_context import LeanModel

        model = LeanModel(
            model,
            context_window,
            compaction,
            ctx.memory,
            history,
            compaction_budget if compaction_budget is not None else ctx.budget,
        )
    log_detail(
        "turn start run_id=%s model=%s/%s tools=%r history=%r deps=%r budget=%r "
        "instructions=%r max_context_tokens=%r",
        ctx.run_id,
        getattr(model, "provider", type(model).__name__),
        getattr(model, "model_id", None),
        [tool.name for tool in tools],
        history,
        deps,
        budget,
        instructions,
        max_context_tokens,
    )

    while True:
        # 1. Finish tool calls left by this run or by an earlier paused run.
        calls = unanswered_calls(history)
        log_detail(
            "turn cycle run_id=%s history_len=%d unanswered_calls=%r budget=%r inbox=%r",
            ctx.run_id,
            len(history),
            calls,
            budget,
            inbox,
        )
        if calls:
            results: list[ToolResultMessage | PendingApproval] = []
            for start in range(0, len(calls), limits.tool_batch_size):
                batch = calls[start : start + limits.tool_batch_size]
                # Closing the public stream also cancels its active execution batch.
                async with aclosing(_stream_tools(batch, tools, ctx, hooks, limits)) as events:
                    async for event in events:
                        if isinstance(event, _ToolBatchFinished):
                            results.extend(event.results)
                            history.extend(
                                r for r in event.results if isinstance(r, ToolResultMessage)
                            )
                        else:
                            yield event

            pending = [r for r in results if isinstance(r, PendingApproval)]
            if pending:
                finished = TurnFinished(TurnResult("waiting_for_approval", pending))
                log_event(finished, phase="turn-finished")
                yield finished
                return

        # 2. Add user steering only between tool execution and the next model call.
        if inbox:
            steering = inbox.drain()
            log_detail("inbox drain before model run_id=%s messages=%r", ctx.run_id, steering)
            history.extend(steering)

        # 3. Avoid building a request when the shared budget is already spent.
        if budget.used >= budget.max_model_calls:
            result = TurnResult("budget_exhausted", message=_last_assistant(history))
            finished = TurnFinished(result)
            log_event(finished, phase="turn-finished")
            yield finished
            return

        # 4. Build a fresh request. Instructions stay out of saved history.
        prefix = [SystemMessage(await _resolve(instructions, ctx))] if instructions else []
        if tools:
            guidance = (
                f"Request at most {limits.tool_batch_size} tool calls per response. "
                "Wait for their results before requesting the next group. "
                "A not_started result means no tool executed. Correct the stated problem "
                "before submitting a new call with a new ID. A failed result means the tool "
                "ran and failed. An unknown result means the action may have happened. "
                "Never repeat completed or unknown actions merely because a batch was split."
            )
            previous = _last_assistant(history)
            if previous and len(previous.tool_calls) > limits.tool_batch_size:
                guidance += (
                    f" Your last response requested {len(previous.tool_calls)} calls, above the "
                    f"recommended {limits.tool_batch_size}. They were processed in bounded batches "
                    "with their original IDs and approval checks. Read each result and keep future "
                    f"responses within {limits.tool_batch_size} calls. Do not resubmit this batch."
                )
            prefix.append(SystemMessage(guidance))
        request = None
        async with aclosing(
            _build_request(
                model,
                prefix=prefix,
                history=history,
                tools=tools,
                ctx=ctx,
                hooks=hooks,
                max_context_tokens=max_context_tokens,
                estimate_tokens=estimate_tokens,
                context_window=context_window,
                reserved_output_tokens=reserved_output_tokens,
                compaction=compaction,
                compaction_budget=compaction_budget,
            )
        ) as events:
            async for event in events:
                if isinstance(event, ModelRequest):
                    request = event
                else:
                    yield event
        assert request is not None

        log_detail(
            "model request built run_id=%s request=%r",
            ctx.run_id,
            request,
        )

        # Charge only after request sizing and hooks succeeded, immediately
        # before the provider call.
        if not budget.spend():
            result = TurnResult("budget_exhausted", message=_last_assistant(history))
            finished = TurnFinished(result)
            log_event(finished, phase="turn-finished")
            yield finished
            return
        log_detail("budget spent run_id=%s budget=%r", ctx.run_id, budget)

        # 5. Forward every delta (text, reasoning, tool arguments) and keep the
        #    one complete message.
        called = ModelCalled(request)
        log_event(called, phase="model-called")
        yield called
        msg: AssistantMessage | None = None
        async for event in model.stream(request):
            log_event(event, phase="model-stream")
            if not isinstance(event, GenerationComplete):
                yield event
                continue
            if msg is not None:
                raise RuntimeError("model stream produced more than one final message")
            msg = event.message
        if msg is None:
            raise RuntimeError("model stream ended without a final message")

        if hooks.after_model:
            log_detail("after_model hook start run_id=%s message=%r", ctx.run_id, msg)
            msg = await hooks.after_model(msg, ctx)
            log_detail("after_model hook complete run_id=%s message=%r", ctx.run_id, msg)
        # Keep identity errors fatal. Argument errors receive a result for the affected call.
        validate_assistant_message(msg, limits, validate_arguments=False)
        responded = ModelResponded(msg)
        log_event(responded, phase="model-responded")
        yield responded
        history.append(msg)
        log_detail("history updated run_id=%s history=%r", ctx.run_id, history)

        # 6. Tool calls continue the loop; plain text completes the turn.
        if msg.tool_calls:
            continue
        steering = inbox.drain() if inbox else []
        if steering:
            log_detail("inbox drain after model run_id=%s messages=%r", ctx.run_id, steering)
            history.extend(steering)
            continue
        finished = TurnFinished(TurnResult("completed", message=msg))
        log_event(finished, phase="turn-finished")
        yield finished
        return


async def run_turn(
    model: ChatModel,
    tools: Sequence[Tool],
    history: list[Message],
    *,
    deps: Any = None,
    hooks: Hooks | None = None,
    instructions: Instructions | None = None,
    inbox: Inbox | None = None,
    budget: Budget | None = None,
    compaction_budget: Budget | None = None,
    max_context_tokens: int | None = None,
    estimate_tokens: EstimateTokens = default_estimate,
    context_window: int | None = None,
    reserved_output_tokens: int = DEFAULT_OUTPUT_RESERVATION,
    limits: ExecutionLimits = DEFAULT_EXECUTION_LIMITS,
    compaction: CompactionConfig | None = None,
    memory: ContextMemory | None = None,
) -> TurnResult:
    """Run a turn and return the final result without streaming events."""
    events = run_turn_stream(
        model,
        tools,
        history,
        deps=deps,
        hooks=hooks,
        instructions=instructions,
        inbox=inbox,
        budget=budget,
        compaction_budget=compaction_budget,
        max_context_tokens=max_context_tokens,
        estimate_tokens=estimate_tokens,
        context_window=context_window,
        reserved_output_tokens=reserved_output_tokens,
        limits=limits,
        compaction=compaction,
        memory=memory,
    )
    return await collect_run_stream(events)
