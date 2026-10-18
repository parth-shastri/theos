"""Turn Python functions into model-callable tools and safely run their calls.

This module validates generic tool schemas and runs hooks. Theos supplies the functions,
permissions, and persistence behavior through its runtime layer.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Annotated, Any, Literal, get_origin, get_type_hints

import pydantic_core
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from harness.context import RunContext
from harness.debug import log_detail, log_event
from harness.events import ToolFinished, ToolStarted, _tool_scope
from harness.hooks import ALLOW, DENY, Hooks
from harness.limits import (
    DEFAULT_EXECUTION_LIMITS,
    ExecutionLimits,
    HarnessError,
    validate_tool_arguments,
)
from harness.types import (
    AssistantMessage,
    PendingApproval,
    SystemMessage,
    ToolCall,
    ToolOutput,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    View,
)

Status = Literal["completed", "denied", "not_started", "failed", "unknown"]
_DEFAULT_HOOKS = Hooks()

__all__ = [
    "OutcomeUnknown",
    "Tool",
    "execute_tool",
    "execute_tools",
    "history_tools",
    "tool",
]


class OutcomeUnknown(Exception):
    """The tool may have succeeded, but its final result is unknown."""


def _history_text(message):
    """Render only saved, user-visible message content for exact read and search."""
    if isinstance(message, (SystemMessage, UserMessage, ToolResultMessage)):
        return message.content
    if isinstance(message, AssistantMessage):
        parts = [message.text] if message.text else []
        parts.extend(
            json.dumps(
                {"call_id": call.id, "tool": call.name, "arguments": call.arguments},
                ensure_ascii=False,
            )
            for call in message.tool_calls
            if call.name not in {"history_read", "history_search"}
        )
        return "\n".join(parts)
    return ""


def _history_match(text, query):
    """Find case-insensitively and map folded text back to original character offsets."""
    folded = []
    original_offsets = []
    for index, char in enumerate(text):
        value = char.casefold()
        folded.append(value)
        original_offsets.extend([index] * len(value))
    position = "".join(folded).find(query.casefold())
    return original_offsets[position] if position >= 0 else -1


def history_tools():
    """Return tools that page and search the original, append-only transcript."""

    @tool
    async def history_read(
        ctx: RunContext,
        message_index: Annotated[int | None, Field(ge=0)] = None,
        call_id: str | None = None,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=12000)] = 4000,
    ):
        """Read exact saved message text by index or tool call ID. Continue with next_offset until null."""
        index = message_index
        if call_id is not None:
            index = next(
                (
                    number
                    for number, message in enumerate(ctx.history)
                    if isinstance(message, ToolResultMessage) and message.call_id == call_id
                ),
                None,
            )
        if index is None or index >= len(ctx.history):
            raise ValueError("No matching message exists in this agent's history.")

        message = ctx.history[index]
        text = _history_text(message)
        page = text[offset : offset + limit]
        return {
            "message_index": index,
            "role": (
                "tool"
                if isinstance(message, ToolResultMessage)
                else "assistant"
                if isinstance(message, AssistantMessage)
                else "user"
                if isinstance(message, UserMessage)
                else "system"
            ),
            "tool": message.name if isinstance(message, ToolResultMessage) else None,
            "offset": offset,
            "total_chars": len(text),
            "content": page,
            "next_offset": offset + len(page) if offset + len(page) < len(text) else None,
        }

    @tool
    async def history_search(
        query: Annotated[str, Field(min_length=0, max_length=200)],
        ctx: RunContext,
        start_index: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=20)] = 10,
    ):
        """Find exact text in saved history and return message indexes for history_read. An empty query lists saved tool results."""
        matches = []
        for index in range(start_index, len(ctx.history)):
            message = ctx.history[index]
            if isinstance(message, ToolResultMessage) and message.name in {
                "history_read",
                "history_search",
            }:
                continue
            if not query and not isinstance(message, ToolResultMessage):
                continue

            text = _history_text(message)
            found = _history_match(text, query) if query else 0
            if found < 0:
                continue
            start = max(0, found - 120)
            matches.append(
                {
                    "message_index": index,
                    "snippet": text[start : start + 600],
                    "tool": message.name if isinstance(message, ToolResultMessage) else None,
                    "total_chars": len(text),
                }
            )
            if len(matches) >= limit:
                return {"matches": matches, "next_index": index + 1}
        return {"matches": matches, "next_index": None}

    return [history_read, history_search]


@dataclass
class Tool:
    """A callable the model can invoke."""

    name: str
    description: str
    input_model: type[BaseModel]
    execute: Callable[[BaseModel, RunContext], Awaitable[Any]]
    parallel_safe: bool | Callable[[BaseModel], bool] = False
    timeout_s: float | None = None
    view: str | None = None

    @cached_property
    def spec(self) -> ToolSpec:
        """The wire description of this tool, built once per tool."""
        return ToolSpec.from_model(self.name, self.description, self.input_model)

    def is_parallel_safe(self, args: BaseModel) -> bool:
        """Return whether this invocation can overlap other tool calls."""
        if callable(self.parallel_safe):
            return bool(self.parallel_safe(args))
        return bool(self.parallel_safe)


def _first_paragraph(fn: Callable[..., Any]) -> str:
    """Return the docstring text up to the first blank line."""
    doc = inspect.getdoc(fn) or ""
    return doc.split("\n\n", 1)[0].strip()


def _is_context_annotation(annotation: Any) -> bool:
    """True for `RunContext` and for `RunContext[...]`."""
    return annotation is RunContext or get_origin(annotation) is RunContext


def _resolve_hints(fn: Callable[..., Any]) -> dict[str, Any]:
    """Resolve parameter annotations while preserving `Annotated` metadata."""
    annotations = {
        key: value for key, value in getattr(fn, "__annotations__", {}).items() if key != "return"
    }
    shim = type("_ToolAnnotations", (), {"__annotations__": annotations})
    return get_type_hints(
        shim,
        globalns=getattr(fn, "__globals__", {}),
        localns={"RunContext": RunContext},
        include_extras=True,
    )


def _build_input_model(fn: Callable[..., Any], name: str) -> tuple[type[BaseModel], str | None]:
    """Build the input model and report which parameter takes the run context."""
    hints = _resolve_hints(fn)
    fields: dict[str, tuple[Any, Any]] = {}
    context_param: str | None = None
    for parameter in inspect.signature(fn).parameters.values():
        annotation = hints.get(parameter.name, Any)
        if parameter.name == "ctx" or _is_context_annotation(annotation):
            context_param = parameter.name
            continue
        default = ... if parameter.default is inspect.Parameter.empty else parameter.default
        fields[parameter.name] = (annotation, default)
    model = create_model(
        f"{name}_input",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
    return model, context_param


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    parallel_safe: bool | Callable[[BaseModel], bool] = False,
    timeout_s: float | None = None,
    view: str | None = None,
) -> Tool | Callable[..., Tool]:
    """Turn a function into a tool with a generated input schema."""

    def build(target: Callable[..., Any]) -> Tool:
        # The model sees a JSON schema derived from Python annotations and the first
        # docstring paragraph. Application-only RunContext is injected during execution.
        tool_name = name or target.__name__
        input_model, context_param = _build_input_model(target, tool_name)
        is_async = inspect.iscoroutinefunction(target)

        async def execute(args: BaseModel, ctx: RunContext) -> Any:
            arguments = dict(args.model_dump())
            if context_param is not None:
                arguments[context_param] = ctx

            # Async tools already cooperate with the event loop.
            if is_async:
                return await target(**arguments)

            # Plain functions may block, so run them in a worker thread.
            return await asyncio.to_thread(target, **arguments)

        return Tool(
            name=tool_name,
            description=_first_paragraph(target),
            input_model=input_model,
            execute=execute,
            parallel_safe=parallel_safe,
            timeout_s=timeout_s,
            view=view,
        )

    if fn is None:
        return build
    return build(fn)


def _emit(ctx: RunContext, event: Any) -> None:
    """Send one event when the context carries an emit."""
    log_event(event, phase="tool-emit")
    if ctx.emit is not None:
        ctx.emit(event)


def _serialize(value: Any) -> str:
    """A string is the content. Anything else becomes JSON the model can read."""
    if isinstance(value, str):
        return value
    return json.dumps(value, default=pydantic_core.to_jsonable_python)


def _call_view(tool_obj: Tool, args: BaseModel) -> View | None:
    """The view a frontend shows for a call before any result exists."""
    if tool_obj.view is None:
        return None
    return View(tool_obj.view, {"args": args.model_dump()})


def _with_default_view(
    result: ToolResultMessage, tool_obj: Tool, args: BaseModel
) -> ToolResultMessage:
    """Attach the tool's own view when the tool returned none."""
    if result.view is None and tool_obj.view is not None:
        result.view = View(tool_obj.view, {"args": args.model_dump(), "status": result.status})
    return result


async def _finish(result: ToolResultMessage, ctx: RunContext, hooks: Hooks) -> ToolResultMessage:
    """Run `after_tool` on every result, then announce the finished call."""
    if hooks.after_tool is not None:
        result = await hooks.after_tool(result, ctx)
    _emit(ctx, ToolFinished(result))
    return result


def _find(name: str, tools: Sequence[Tool]) -> Tool | None:
    return next((t for t in tools if t.name == name), None)


def _resolve(
    call: ToolCall, tools: Sequence[Tool], limits: ExecutionLimits
) -> tuple[Tool, BaseModel] | ToolResultMessage:
    """Find the tool and validate the arguments once, or answer the call inline.

    Both entry points go through here, so the arguments a `parallel_safe`
    predicate sees are the same object the tool body runs on.
    """
    log_detail("resolve tool call=%r available_tools=%r", call, [t.name for t in tools])
    try:
        validate_tool_arguments(call, limits)
    except HarnessError as error:
        return ToolResultMessage(
            call.id,
            call.name,
            f"Not started ({error.code.value}): {error}. No tool executed. "
            "Correct the arguments and submit a new call with a new ID.",
            "not_started",
        )
    tool_obj = _find(call.name, tools)
    if tool_obj is None:
        log_detail("tool resolution failed unknown_tool=%s call=%r", call.name, call)
        return ToolResultMessage(
            call_id=call.id,
            name=call.name,
            content=f"Not started: unknown tool {call.name}. No tool executed. "
            "Choose an available tool and submit a new call with a new ID.",
            status="not_started",
        )
    try:
        args = tool_obj.input_model.model_validate(call.arguments)
    except ValidationError as exc:
        log_detail(
            "tool argument validation failed tool=%s call=%r error=%r",
            tool_obj.name,
            call,
            exc,
        )
        return ToolResultMessage(
            call_id=call.id,
            name=tool_obj.name,
            content=f"Not started: invalid arguments. No tool executed.\n{exc}\n"
            "Correct the arguments and submit a new call with a new ID.",
            status="not_started",
        )
    log_detail("tool resolved tool=%s args=%r", tool_obj.name, args.model_dump())
    return tool_obj, args


async def execute_tool(
    call: ToolCall,
    tools: Sequence[Tool],
    *,
    ctx: RunContext,
    hooks: Hooks = _DEFAULT_HOOKS,
    limits: ExecutionLimits = DEFAULT_EXECUTION_LIMITS,
) -> ToolResultMessage | PendingApproval:
    """Validate, authorize, and run one tool call."""
    log_detail("execute_tool start call=%r", call)
    # 1. Find the registered tool and validate the model's arguments. Invalid calls return
    # a not_started result so the model can correct them without an external side effect.
    resolved = _resolve(call, tools, limits)
    if isinstance(resolved, ToolResultMessage):
        return await _finish(resolved, ctx, hooks)

    # 2. The remaining pipeline works only with validated arguments.
    tool_obj, args = resolved
    return await _run(call, tool_obj, args, ctx=ctx, hooks=hooks)


async def _run(
    call: ToolCall,
    tool_obj: Tool,
    args: BaseModel,
    *,
    ctx: RunContext,
    hooks: Hooks,
) -> ToolResultMessage | PendingApproval:
    """Authorize one validated call, run it, and finish it."""
    # 1. Policy can allow, deny, or pause the call for approval.
    log_detail(
        "before_tool hook start tool=%s call=%r args=%r",
        tool_obj.name,
        call,
        args.model_dump(),
    )
    # A user's saved approval response takes precedence over a new approval prompt.
    approval = ctx.inbox.take_approval(call.id) if ctx.inbox is not None else None
    if approval is not None:
        decision = ALLOW if approval.approved else DENY(approval.reason or "Denied by user")
        log_detail(
            "tool approval response tool=%s call=%r response=%r", tool_obj.name, call, approval
        )
    else:
        decision = await hooks.before_tool(tool_obj, args, ctx)
        log_detail("before_tool hook decision tool=%s decision=%r", tool_obj.name, decision)
    # Only ALLOW reaches the function body. ASK returns a pending record for the transport;
    # DENY returns a result that explains why no action ran.
    if decision.kind == "deny":
        denied = ToolResultMessage(
            call_id=call.id,
            name=tool_obj.name,
            content=decision.reason or "Denied by policy",
            status="denied",
        )
        return await _finish(_with_default_view(denied, tool_obj, args), ctx, hooks)
    if decision.kind == "ask":
        pending = PendingApproval(
            call=call, args=args, reason=decision.reason, view=_call_view(tool_obj, args)
        )
        _emit(ctx, ToolFinished(pending))
        return pending

    # 2. Only allowed calls reach the tool body. Emit the start event first so a live
    # transport can show progress while a slow service request is running.
    _emit(ctx, ToolStarted(call, _call_view(tool_obj, args)))
    log_detail(
        "tool execution started tool=%s call=%r args=%r", tool_obj.name, call, args.model_dump()
    )
    result: ToolResultMessage | None = None
    try:
        # Let a streaming consumer render the start event before the tool does work.
        await asyncio.sleep(0)
        scope = _tool_scope.set(call.id)
        try:
            result = await _invoke(call, tool_obj, args, ctx)
        finally:
            _tool_scope.reset(scope)
        log_detail("tool invocation returned tool=%s result=%r", tool_obj.name, result)

        # 3. Run the after-tool hook before announcing completion. The application can
        # persist the result here, before the loop starts another model request.
        return await _finish(_with_default_view(result, tool_obj, args), ctx, hooks)
    except asyncio.CancelledError:
        # ToolStarted is now part of history's story. Preserve a known result if
        # the body returned; otherwise record that its outcome is uncertain.
        # Cancellation after a tool started may have interrupted an external write. Record
        # unknown unless the body already returned a known result; never blindly repeat it.
        if result is None:
            result = ToolResultMessage(
                call_id=call.id,
                name=tool_obj.name,
                content=f"Outcome unknown: {tool_obj.name} was cancelled after it started",
                status="unknown",
            )
        result = _with_default_view(result, tool_obj, args)
        log_detail("tool execution cancelled tool=%s result=%r", tool_obj.name, result)
        if not any(
            isinstance(message, ToolResultMessage) and message.call_id == call.id
            for message in ctx.history
        ):
            ctx.history.append(result)
            _emit(ctx, ToolFinished(result))
        raise


async def _invoke(
    call: ToolCall, tool_obj: Tool, args: BaseModel, ctx: RunContext
) -> ToolResultMessage:
    """Run the tool once and convert its outcome to a result message."""

    def answer(content: str, status: Status, view: View | None = None) -> ToolResultMessage:
        return ToolResultMessage(
            call_id=call.id, name=tool_obj.name, content=content, status=status, view=view
        )

    try:
        # A tool's returned Python value must also serialize successfully before it counts
        # as completed. Otherwise the model would not receive a usable result.
        # Keep execution and serialization together: either one can fail the call.
        log_detail(
            "tool body start tool=%s call_id=%s timeout_s=%r args=%r",
            tool_obj.name,
            call.id,
            tool_obj.timeout_s,
            args.model_dump(),
        )
        async with asyncio.timeout(tool_obj.timeout_s):
            returned = await tool_obj.execute(args, ctx)
        log_detail("tool body raw return tool=%s returned=%r", tool_obj.name, returned)
        if isinstance(returned, ToolOutput):
            result = answer(_serialize(returned.content), "completed", returned.view)
        else:
            result = answer(_serialize(returned), "completed")
        log_detail("tool body serialized result tool=%s result=%r", tool_obj.name, result)
        return result
    # Cancellation is intentionally not caught: CancelledError is a BaseException.
    except TimeoutError:
        # A timeout does not prove that a remote service stopped its work, so mark the
        # outcome unknown rather than failed or safe to retry.
        result = answer(
            f"Outcome unknown: {tool_obj.name} did not respond within {tool_obj.timeout_s}s",
            "unknown",
        )
        log_detail("tool body timed out tool=%s result=%r", tool_obj.name, result)
        return result
    except OutcomeUnknown as exc:
        detail = str(exc)
        content = f"Outcome unknown: {detail}" if detail else "Outcome unknown"
        result = answer(content, "unknown")
        log_detail(
            "tool body outcome unknown tool=%s error=%r result=%r", tool_obj.name, exc, result
        )
        return result
    except Exception as exc:
        result = answer(f"{type(exc).__name__}: {exc}", "failed")
        log_detail("tool body failed tool=%s error=%r result=%r", tool_obj.name, exc, result)
        return result


def _groups(
    scheduled: Sequence[tuple[int, ToolCall, Tool, BaseModel]],
    batch_size: int,
) -> list[list[tuple[int, ToolCall, Tool, BaseModel]]]:
    """Split a batch into runs that may overlap, keeping the call order.

    Neighboring parallel-safe calls form bounded groups and run together.
    An unsafe call is a group of its own and never overlaps another call.
    """
    groups: list[list[tuple[int, ToolCall, Tool, BaseModel]]] = []
    open_group = False  # whether the last group still accepts safe calls
    for item in scheduled:
        _, _, tool_obj, args = item
        safe = tool_obj.is_parallel_safe(args)  # asked once, like the body runs once
        if safe and open_group and len(groups[-1]) < batch_size:
            groups[-1].append(item)
        else:
            groups.append([item])
        open_group = safe
    log_detail(
        "tool scheduling groups=%r",
        [
            [(call.id, tool_obj.name, args.model_dump()) for _, call, tool_obj, args in group]
            for group in groups
        ],
    )
    return groups


async def execute_tools(
    calls: Sequence[ToolCall],
    tools: Sequence[Tool],
    *,
    ctx: RunContext,
    hooks: Hooks = _DEFAULT_HOOKS,
    limits: ExecutionLimits = DEFAULT_EXECUTION_LIMITS,
) -> list[ToolResultMessage | PendingApproval]:
    """Run a batch in call order. Neighboring parallel-safe calls overlap."""
    log_detail("execute_tools start calls=%r tool_count=%d", calls, len(tools))
    # 1. Resolve every call once. Validation errors are answered inline; valid calls are
    # kept with their original index so the final result order matches the model's calls.
    results: list[ToolResultMessage | PendingApproval | None] = [None] * len(calls)
    scheduled: list[tuple[int, ToolCall, Tool, BaseModel]] = []
    for index, call in enumerate(calls):
        resolved = _resolve(call, tools, limits)
        if isinstance(resolved, ToolResultMessage):
            results[index] = await _finish(resolved, ctx, hooks)
            continue
        scheduled.append((index, call) + resolved)

    # 2. Run one group at a time. _groups places only declared parallel-safe calls together;
    # gather() waits for each group before starting the next one.
    for group in _groups(scheduled, limits.tool_batch_size):
        gathered = await asyncio.gather(
            *(_run(call, tool_obj, args, ctx=ctx, hooks=hooks) for _, call, tool_obj, args in group)
        )
        for (index, _, _, _), result in zip(group, gathered, strict=True):
            results[index] = result

    # 3. Merge validation responses, approvals, and executed results in original call order.
    final_results = [result for result in results if result is not None]
    log_detail("execute_tools complete results=%r", final_results)
    return final_results
