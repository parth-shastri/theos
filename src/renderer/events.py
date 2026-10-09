"""Small, framework-neutral event vocabulary understood by renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, kw_only=True)
class _ScopedEvent:
    """The tool whose execution produced this event, if any."""

    parent_call_id: str | None = None


@dataclass(frozen=True)
class RunStarted(_ScopedEvent):
    title: str = "Agent"
    prompt: str | None = None


@dataclass(frozen=True)
class ModelStarted(_ScopedEvent):
    label: str = "Thinking"
    model: str | None = None
    message_count: int | None = None
    tool_count: int | None = None


@dataclass(frozen=True)
class TextDelta(_ScopedEvent):
    text: str


@dataclass(frozen=True)
class ReasoningDelta(_ScopedEvent):
    """A chunk of model reasoning that arrived before the answer."""

    text: str


@dataclass(frozen=True)
class ToolCallDelta(_ScopedEvent):
    """A chunk of a tool call the model is still writing."""

    index: int
    text: str = ""
    name: str | None = None


@dataclass(frozen=True)
class ModelFinished(_ScopedEvent):
    text: str | None = None
    reasoning: str | None = None
    stop_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    requested_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolStarted(_ScopedEvent):
    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolProgress(_ScopedEvent):
    call_id: str
    message: str
    progress: float | None = None


@dataclass(frozen=True)
class ToolFinished(_ScopedEvent):
    call_id: str
    name: str
    output: str
    status: Literal["completed", "denied", "failed", "unknown"] = "completed"


@dataclass(frozen=True)
class ApprovalRequested(_ScopedEvent):
    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class QuestionRequested(_ScopedEvent):
    """A framework paused to ask the user for structured input."""

    request_id: str
    question: str
    choices: tuple[str, ...] = ()
    allow_free_text: bool = True


@dataclass(frozen=True)
class Notice(_ScopedEvent):
    message: str
    level: Literal["debug", "info", "warning", "error"] = "info"


@dataclass(frozen=True)
class RunFinished(_ScopedEvent):
    status: str = "completed"
    result: Any = None
    pending_count: int = 0


type RenderEvent = (
    RunStarted
    | ModelStarted
    | TextDelta
    | ReasoningDelta
    | ToolCallDelta
    | ModelFinished
    | ToolStarted
    | ToolProgress
    | ToolFinished
    | ApprovalRequested
    | QuestionRequested
    | Notice
    | RunFinished
)


def is_render_event(value: object) -> bool:
    """Return whether ``value`` already uses the renderer event protocol."""
    return isinstance(
        value,
        (
            RunStarted,
            ModelStarted,
            TextDelta,
            ReasoningDelta,
            ToolCallDelta,
            ModelFinished,
            ToolStarted,
            ToolProgress,
            ToolFinished,
            ApprovalRequested,
            QuestionRequested,
            Notice,
            RunFinished,
        ),
    )
