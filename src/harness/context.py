"""Run-scoped dependencies and helpers for reading conversation history."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
from uuid import uuid4

from harness.debug import log_detail
from harness.compaction import ContextMemory
from harness.events import Emit
from harness.inbox import Inbox
from harness.types import (
    AssistantMessage,
    Budget,
    Message,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

Deps = TypeVar("Deps")


class ContextLimitError(ValueError):
    """The fixed request content leaves no room for a valid model reply."""


@dataclass
class RunContext(Generic[Deps]):
    """Values tools, hooks, and instruction builders need during a run."""

    deps: Deps
    history: list[Message] = field(default_factory=list)
    budget: Budget | None = None
    inbox: Inbox | None = None
    emit: Emit | None = None
    state: dict[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: uuid4().hex)
    memory: ContextMemory = field(default_factory=ContextMemory)


def _text_pieces(message: Message) -> list[str]:
    if isinstance(message, SystemMessage | UserMessage):
        return [message.content]
    if isinstance(message, ToolResultMessage):
        return [message.content]
    if isinstance(message, AssistantMessage):
        pieces = [message.text] if message.text else []
        pieces.extend(json.dumps(call.arguments) for call in message.tool_calls)
        return pieces
    return []


def default_estimate(messages: Sequence[Message]) -> int:
    """Estimate tokens at about four characters per token.

    Callers that need precision pass a tokenizer-backed estimator instead.
    """
    total = 0
    for message in messages:
        for piece in _text_pieces(message):
            total += max(1, len(piece) // 4)
        if isinstance(message, UserMessage):
            # Image token use depends on model, dimensions, and detail. Reserve
            # space without counting the Base64 payload as ordinary text.
            total += 1024 * len(message.images)
    return total


def _droppable_units(history: Sequence[Message], kept: set[int]) -> list[list[int]]:
    """Group tool calls with their results so trimming keeps them together."""
    owner_of_call: dict[str, int] = {}
    units: dict[int, list[int]] = {}
    for index, message in enumerate(history):
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                owner_of_call[call.id] = index
        if index in kept:
            continue
        anchor = index
        if isinstance(message, ToolResultMessage):
            owner = owner_of_call.get(message.call_id)
            if owner is not None and owner not in kept:
                anchor = owner
        units.setdefault(anchor, []).append(index)
    return [units[anchor] for anchor in sorted(units)]


def select_context(
    history: Sequence[Message],
    *,
    max_tokens: int | None = None,
    keep_tokens: int | None = None,
    estimate_tokens: Callable[[Sequence[Message]], int] = default_estimate,
) -> list[Message]:
    """Return a window of history that fits, cut at points that rarely move.

    Providers cache the request prefix, and a cut that moves on every call
    invalidates that cache every time. So the window does not simply hold the
    newest messages that fit. It grows until it passes `max_tokens`, then drops
    the oldest complete units until it is under `keep_tokens` (half of
    `max_tokens` by default). The cut then stays put while the window fills up
    again, so many calls in a row share one prefix.

    History is append-only, so replaying that rule over the whole history gives
    the same cuts a live run made. The function stays pure: same history, same
    window. System messages and the latest user message are always included,
    and a tool call never loses its results.
    """
    log_detail(
        "context selection start history_len=%d max_tokens=%r keep_tokens=%r history=%r",
        len(history),
        max_tokens,
        keep_tokens,
        history,
    )
    if max_tokens is None:
        selected = list(history)
        log_detail("context selection complete selected=%r", selected)
        return selected
    if keep_tokens is None:
        keep_tokens = max_tokens // 2
    if keep_tokens >= max_tokens:
        raise ValueError("keep_tokens must be below max_tokens")

    # 1. System messages are pinned. Everything else forms droppable units.
    pinned = {i for i, m in enumerate(history) if isinstance(m, SystemMessage)}
    units = _droppable_units(history, pinned)
    costs = [estimate_tokens([history[i] for i in unit]) for unit in units]
    fixed = estimate_tokens([history[i] for i in sorted(pinned)])

    # 2. Replay the run: add one unit at a time and move the cut only on overflow.
    cut = 0
    window = 0
    for newest, cost in enumerate(costs):
        window += cost
        if fixed + window > max_tokens:
            # The newest unit always stays, even when it is too big on its own.
            while cut < newest and fixed + window > keep_tokens:
                window -= costs[cut]
                cut += 1

    # 3. The latest question survives a cut that ran past it.
    selected = set(pinned)
    for unit in units[cut:]:
        selected.update(unit)
    last_user = next(
        (i for i in range(len(history) - 1, -1, -1) if isinstance(history[i], UserMessage)),
        None,
    )
    if last_user is not None:
        selected.add(last_user)
    chosen = [history[i] for i in sorted(selected)]
    log_detail(
        "context selection complete selected=%r estimated_tokens=%d cut=%d units=%d",
        chosen,
        estimate_tokens(chosen),
        cut,
        len(units),
    )
    return chosen


def unanswered_calls(history: Sequence[Message]) -> list[ToolCall]:
    """Tool calls in the trailing AssistantMessage with no ToolResultMessage yet."""
    last_assistant = next(
        (i for i in range(len(history) - 1, -1, -1) if isinstance(history[i], AssistantMessage)),
        None,
    )
    if last_assistant is None:
        log_detail("unanswered calls history_len=%d result=[]", len(history))
        return []
    assistant = history[last_assistant]
    answered = {
        m.call_id
        for m in history[last_assistant + 1 :]
        if isinstance(m, ToolResultMessage)
    }
    calls = [call for call in assistant.tool_calls if call.id not in answered]
    log_detail(
        "unanswered calls history_len=%d last_assistant_index=%d answered=%r calls=%r",
        len(history),
        last_assistant,
        answered,
        calls,
    )
    return calls
