"""Optional hooks around model calls and tool calls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from harness.context import RunContext
from harness.types import (
    AssistantMessage,
    ModelRequest,
    PendingApproval,
    ToolResultMessage,
)

if TYPE_CHECKING:  # Avoid a runtime import cycle with harness.tools.
    from harness.tools import Tool

__all__ = [
    "ALLOW",
    "ASK",
    "DENY",
    "AfterModel",
    "AfterTool",
    "BeforeModel",
    "BeforeTool",
    "Decision",
    "Hooks",
    "PendingApproval",
    "allow_all",
    "require_approval",
]


@dataclass(frozen=True)
class Decision:
    """Allow, deny, or pause one tool call for approval."""

    kind: Literal["allow", "deny", "ask"]
    reason: str = ""


ALLOW = Decision("allow")
ASK = Decision("ask")


def DENY(reason: str) -> Decision:
    """Refuse a call and tell the model why."""
    return Decision("deny", reason)


BeforeModel = Callable[[ModelRequest, RunContext], Awaitable[ModelRequest]]
"""Replace the request before it is sent. Add per-call content at the end.

A SystemMessage goes to the front of the prompt on every provider, so one that
changes per call invalidates the cached prefix. A trailing UserMessage does not.
"""
AfterModel = Callable[[AssistantMessage, RunContext], Awaitable[AssistantMessage]]
BeforeTool = Callable[["Tool", BaseModel, RunContext], Awaitable[Decision]]
AfterTool = Callable[[ToolResultMessage, RunContext], Awaitable[ToolResultMessage]]


async def allow_all(tool: Tool, args: BaseModel, ctx: RunContext) -> Decision:
    """Allow every call. The default policy."""
    return ALLOW


def require_approval(*tool_names: str) -> BeforeTool:
    """Return a `before_tool` hook that asks before the named tools run."""
    names = frozenset(tool_names)

    async def before_tool(tool: Tool, args: BaseModel, ctx: RunContext) -> Decision:
        return ASK if tool.name in names else ALLOW

    return before_tool


@dataclass(frozen=True)
class Hooks:
    """The hook set of one agent. Defaults are inert."""

    before_model: BeforeModel | None = None
    after_model: AfterModel | None = None
    before_tool: BeforeTool = allow_all
    after_tool: AfterTool | None = None
