"""Tests for harness.hooks: decisions, defaults, and the approval helper."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from pydantic import BaseModel

from harness.context import RunContext
from harness.hooks import (
    ALLOW,
    ASK,
    DENY,
    Decision,
    Hooks,
    PendingApproval,
    allow_all,
    require_approval,
)
from harness.types import PendingApproval as TypesPendingApproval
from harness.types import ToolCall


class Args(BaseModel):
    order_id: str


def fake_tool(name: str) -> SimpleNamespace:
    """Stand in for a Tool, which Task 2 defines. Only the name matters here."""
    return SimpleNamespace(name=name)


def test_decision_is_a_frozen_record_with_an_empty_default_reason():
    decision = Decision(kind="allow")
    assert dataclasses.is_dataclass(decision)
    assert Decision.__dataclass_params__.frozen is True
    assert decision.reason == ""


def test_allow_and_ask_constants():
    assert ALLOW == Decision("allow")
    assert ASK == Decision("ask")


def test_deny_carries_its_reason():
    denied = DENY("refunds are disabled")
    assert denied.kind == "deny"
    assert denied.reason == "refunds are disabled"


async def test_allow_all_allows_every_tool():
    ctx = RunContext(deps=None)
    assert await allow_all(fake_tool("refund"), Args(order_id="A1"), ctx) is ALLOW


async def test_require_approval_asks_for_named_tools_and_allows_the_rest():
    before_tool = require_approval("refund", "cancel_order")
    ctx = RunContext(deps=None)
    args = Args(order_id="A1")
    assert await before_tool(fake_tool("refund"), args, ctx) == ASK
    assert await before_tool(fake_tool("cancel_order"), args, ctx) == ASK
    assert await before_tool(fake_tool("get_order"), args, ctx) == ALLOW


async def test_require_approval_with_no_names_allows_everything():
    before_tool = require_approval()
    assert await before_tool(fake_tool("refund"), Args(order_id="A1"), RunContext(deps=None)) == ALLOW


async def test_hooks_defaults_are_inert():
    hooks = Hooks()
    assert hooks.before_model is None
    assert hooks.after_model is None
    assert hooks.after_tool is None
    assert hooks.before_tool is allow_all
    assert await hooks.before_tool(fake_tool("refund"), Args(order_id="A1"), RunContext(deps=None)) is ALLOW


def test_hooks_is_a_frozen_dataclass():
    assert Hooks.__dataclass_params__.frozen is True


def test_hooks_accepts_a_replacement_before_tool():
    before_tool = require_approval("refund")
    hooks = Hooks(before_tool=before_tool)
    assert hooks.before_tool is before_tool


def test_pending_approval_is_re_exported_from_types():
    assert PendingApproval is TypesPendingApproval
    pending = PendingApproval(
        call=ToolCall(id="c1", name="refund", arguments={"order_id": "A1"}),
        args=Args(order_id="A1"),
        reason="refunds need approval",
    )
    assert pending.view is None
