"""Tests for harness.hooks: decisions, defaults, and the approval helper."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from harness.context import RunContext
from harness.hooks import (
    ALLOW,
    ASK,
    Hooks,
    require_approval,
)


class Args(BaseModel):
    order_id: str


def fake_tool(name: str) -> SimpleNamespace:
    """Stand in for a Tool, which Task 2 defines. Only the name matters here."""
    return SimpleNamespace(name=name)


async def test_configured_hook_asks_for_named_tools_and_allows_the_rest():
    hooks = Hooks(before_tool=require_approval("refund", "cancel_order"))
    ctx = RunContext(deps=None)
    args = Args(order_id="A1")
    assert await hooks.before_tool(fake_tool("refund"), args, ctx) == ASK
    assert await hooks.before_tool(fake_tool("cancel_order"), args, ctx) == ASK
    assert await hooks.before_tool(fake_tool("get_order"), args, ctx) == ALLOW
