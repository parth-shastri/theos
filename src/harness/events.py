"""Observable events emitted while a turn runs."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field

from harness.types import (
    AssistantMessage,
    ModelRequest,
    PendingApproval,
    ToolCall,
    ToolResultMessage,
    View,
)

# Task-local ownership survives nested agent streams and parallel tool calls.
_tool_scope: ContextVar[str | None] = ContextVar("harness_tool_scope", default=None)


@dataclass(frozen=True, kw_only=True)
class _ScopedEvent:
    parent_call_id: str | None = field(default_factory=_tool_scope.get)


def _at() -> float:
    """The `at` field every event carries: the Unix time it was created.

    Telemetry reads the gap between two events, so no consumer keeps its own
    clock. The timestamp never takes part in equality, so tests can compare
    events by content alone.
    """
    return field(default_factory=time.time, compare=False)


@dataclass(frozen=True)
class TextDelta(_ScopedEvent):
    """One chunk of assistant text as it streams."""

    text: str
    at: float = _at()


@dataclass(frozen=True)
class ReasoningDelta(_ScopedEvent):
    """One chunk of the model's reasoning summary as it streams."""

    text: str
    at: float = _at()


@dataclass(frozen=True)
class ToolCallDelta(_ScopedEvent):
    """One chunk of the JSON arguments of a tool call as the model writes them.

    `index` tells the calls of one message apart. The first delta of a call
    carries its `name` and may carry no text yet.
    """

    index: int
    text: str = ""
    name: str | None = None
    at: float = _at()


@dataclass(frozen=True)
class GenerationComplete(_ScopedEvent):
    """The complete message at the end of a model stream."""

    message: AssistantMessage
    at: float = _at()


@dataclass(frozen=True)
class ModelCalled(_ScopedEvent):
    """The request the harness is about to send."""

    request: ModelRequest
    at: float = _at()


@dataclass(frozen=True)
class ModelResponded(_ScopedEvent):
    """The complete assistant message the provider returned."""

    message: AssistantMessage
    at: float = _at()


@dataclass(frozen=True)
class ToolStarted(_ScopedEvent):
    """A tool call that is about to run, with an optional progress view."""

    call: ToolCall
    view: View | None = None
    at: float = _at()


@dataclass(frozen=True)
class ToolFinished(_ScopedEvent):
    """One tool call that produced a result or paused for approval."""

    result: ToolResultMessage | PendingApproval
    at: float = _at()


ModelDelta = TextDelta | ReasoningDelta | ToolCallDelta
ModelEvent = ModelDelta | GenerationComplete


@dataclass(frozen=True)
class ContextCompaction(_ScopedEvent):
    """Progress metadata only. The private summary stays in conversation state."""

    status: str
    before_tokens: int
    after_tokens: int | None = None
    covered_messages: int | None = None
    reason: str | None = None
    model_calls: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    at: float = _at()
    compaction_id: str | None = None


Event = ContextCompaction | ModelDelta | ModelCalled | ModelResponded | ToolStarted | ToolFinished
Emit = Callable[[Event], None]
