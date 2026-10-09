"""Create tools from functions and execute model tool calls."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Literal, get_origin, get_type_hints

import pydantic_core
from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from harness.context import RunContext
from harness.debug import log_detail, log_event
from harness.events import ToolFinished, ToolStarted, _tool_scope
from harness.hooks import ALLOW, DENY, Hooks
from harness.types import (
    PendingApproval,
    ToolCall,
    ToolOutput,
    ToolResultMessage,
    ToolSpec,
    View,
)

Status = Literal["completed", "denied", "failed", "unknown"]

__all__ = [
    "OutcomeUnknown",
    "Tool",
    "execute_tool",
    "execute_tools",
    "tool",
]


class OutcomeUnknown(Exception):
    """The tool may have succeeded, but its final result is unknown."""


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
        key: value
        for key, value in getattr(fn, "__annotations__", {}).items()
        if key != "return"
    }
    shim = type("_ToolAnnotations", (), {"__annotations__": annotations})
    return get_type_hints(
        shim,
        globalns=getattr(fn, "__globals__", {}),
        localns={"RunContext": RunContext},
        include_extras=True,
    )


def _build_input_model(
    fn: Callable[..., Any], name: str
) -> tuple[type[BaseModel], str | None]:
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
        result.view = View(
            tool_obj.view, {"args": args.model_dump(), "status": result.status}
        )
    return result


async def _finish(
    result: ToolResultMessage, ctx: RunContext, hooks: Hooks
) -> ToolResultMessage:
    """Run `after_tool` on every result, then announce the finished call."""
    if hooks.after_tool is not None:
        result = await hooks.after_tool(result, ctx)
    _emit(ctx, ToolFinished(result))
    return result


def _find(name: str, tools: Sequence[Tool]) -> Tool | None:
    return next((t for t in tools if t.name == name), None)


def _resolve(
    call: ToolCall, tools: Sequence[Tool]
) -> tuple[Tool, BaseModel] | ToolResultMessage:
    """Find the tool and validate the arguments once, or answer the call inline.

    Both entry points go through here, so the arguments a `parallel_safe`
    predicate sees are the same object the tool body runs on.
    """
    log_detail("resolve tool call=%r available_tools=%r", call, [t.name for t in tools])
    tool_obj = _find(call.name, tools)
    if tool_obj is None:
        log_detail("tool resolution failed unknown_tool=%s call=%r", call.name, call)
        return ToolResultMessage(
            call_id=call.id,
            name=call.name,
            content=f"Unknown tool: {call.name}",
            status="failed",
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
            call_id=call.id, name=tool_obj.name, content=str(exc), status="failed"
        )
    log_detail("tool resolved tool=%s args=%r", tool_obj.name, args.model_dump())
    return tool_obj, args


async def execute_tool(
    call: ToolCall,
    tools: Sequence[Tool],
    *,
    ctx: RunContext,
    hooks: Hooks = Hooks(),
) -> ToolResultMessage | PendingApproval:
    """Validate, authorize, and run one tool call."""
    log_detail("execute_tool start call=%r", call)
    # 1. Find the tool and validate the model's arguments.
    resolved = _resolve(call, tools)
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
    approval = ctx.inbox.take_approval(call.id) if ctx.inbox is not None else None
    if approval is not None:
        decision = ALLOW if approval.approved else DENY(approval.reason or "Denied by user")
        log_detail("tool approval response tool=%s call=%r response=%r", tool_obj.name, call, approval)
    else:
        decision = await hooks.before_tool(tool_obj, args, ctx)
        log_detail("before_tool hook decision tool=%s decision=%r", tool_obj.name, decision)
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

    # 2. Only allowed calls reach the tool body.
    _emit(ctx, ToolStarted(call, _call_view(tool_obj, args)))
    log_detail("tool execution started tool=%s call=%r args=%r", tool_obj.name, call, args.model_dump())
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

        # 3. Add a default view, run the final hook, and emit ToolFinished.
        return await _finish(_with_default_view(result, tool_obj, args), ctx, hooks)
    except asyncio.CancelledError:
        # ToolStarted is now part of history's story. Preserve a known result if
        # the body returned; otherwise record that its outcome is uncertain.
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
        log_detail("tool body outcome unknown tool=%s error=%r result=%r", tool_obj.name, exc, result)
        return result
    except Exception as exc:
        result = answer(f"{type(exc).__name__}: {exc}", "failed")
        log_detail("tool body failed tool=%s error=%r result=%r", tool_obj.name, exc, result)
        return result


def _groups(
    scheduled: Sequence[tuple[int, ToolCall, Tool, BaseModel]],
) -> list[list[tuple[int, ToolCall, Tool, BaseModel]]]:
    """Split a batch into runs that may overlap, keeping the call order.

    Neighboring parallel-safe calls form one group and run together. An unsafe
    call is a group of its own, so it never overlaps any other call.
    """
    groups: list[list[tuple[int, ToolCall, Tool, BaseModel]]] = []
    open_group = False  # whether the last group still accepts safe calls
    for item in scheduled:
        _, _, tool_obj, args = item
        safe = tool_obj.is_parallel_safe(args)  # asked once, like the body runs once
        if safe and open_group:
            groups[-1].append(item)
        else:
            groups.append([item])
        open_group = safe
    log_detail(
        "tool scheduling groups=%r",
        [[(call.id, tool_obj.name, args.model_dump()) for _, call, tool_obj, args in group] for group in groups],
    )
    return groups


async def execute_tools(
    calls: Sequence[ToolCall],
    tools: Sequence[Tool],
    *,
    ctx: RunContext,
    hooks: Hooks = Hooks(),
) -> list[ToolResultMessage | PendingApproval]:
    """Run a batch in call order. Neighboring parallel-safe calls overlap."""
    log_detail("execute_tools start calls=%r tool_count=%d", calls, len(tools))
    # 1. Resolve every call once. Validation errors are answered inline.
    results: list[ToolResultMessage | PendingApproval | None] = [None] * len(calls)
    scheduled: list[tuple[int, ToolCall, Tool, BaseModel]] = []
    for index, call in enumerate(calls):
        resolved = _resolve(call, tools)
        if isinstance(resolved, ToolResultMessage):
            results[index] = await _finish(resolved, ctx, hooks)
            continue
        scheduled.append((index, call) + resolved)

    # 2. Run one group at a time. gather() keeps the order within a group.
    for group in _groups(scheduled):
        gathered = await asyncio.gather(
            *(
                _run(call, tool_obj, args, ctx=ctx, hooks=hooks)
                for _, call, tool_obj, args in group
            )
        )
        for (index, _, _, _), result in zip(group, gathered, strict=True):
            results[index] = result

    # 3. Merge inline validation errors and executed calls into call order.
    final_results = [result for result in results if result is not None]
    log_detail("execute_tools complete results=%r", final_results)
    return final_results
