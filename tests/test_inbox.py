"""Tests for harness.events and harness.inbox."""

from __future__ import annotations

import dataclasses

from pydantic import BaseModel

from harness.events import (
    GenerationComplete,
    ModelCalled,
    ModelResponded,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from harness.inbox import Inbox
from harness.types import (
    AssistantMessage,
    ModelRequest,
    PendingApproval,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    View,
)


class Args(BaseModel):
    order_id: str


def test_events_are_frozen_records():
    delta = TextDelta(text="hi")
    assert dataclasses.is_dataclass(delta)
    assert delta.text == "hi"
    for event in (
        delta,
        GenerationComplete(message=AssistantMessage(text="hi")),
        ModelCalled(request=ModelRequest(messages=[])),
        ModelResponded(message=AssistantMessage(text="hi")),
        ToolStarted(call=ToolCall(id="c", name="t", arguments={})),
        ToolFinished(result=ToolResultMessage(call_id="c", name="t", content="x")),
    ):
        assert type(event).__dataclass_params__.frozen is True


def test_tool_started_carries_an_optional_view():
    call = ToolCall(id="c", name="get_order", arguments={"order_id": "A1"})
    assert ToolStarted(call=call).view is None
    started = ToolStarted(call=call, view=View("order-card", {"order_id": "A1"}))
    assert started.view == View("order-card", {"order_id": "A1"})


def test_tool_finished_carries_a_result_or_a_pending_approval():
    result = ToolResultMessage(call_id="c", name="t", content="x")
    assert ToolFinished(result=result).result is result
    pending = PendingApproval(
        call=ToolCall(id="c", name="t", arguments={"order_id": "A1"}),
        args=Args(order_id="A1"),
        reason="refund needs approval",
    )
    assert ToolFinished(result=pending).result is pending


def test_emit_accepts_any_event_callable():
    seen: list[object] = []
    emit = seen.append
    emit(TextDelta(text="a"))
    emit(ModelResponded(message=AssistantMessage(text="a")))
    assert len(seen) == 2


def test_inbox_starts_empty():
    assert Inbox().drain() == []


def test_inbox_drain_returns_steered_messages_in_order_and_empties():
    inbox = Inbox()
    inbox.steer(UserMessage(content="first"))
    inbox.steer(UserMessage(content="second"))
    drained = inbox.drain()
    assert [m.content for m in drained] == ["first", "second"]
    assert inbox.drain() == []


def test_inbox_drain_returns_a_new_list_each_time():
    inbox = Inbox()
    inbox.steer(UserMessage(content="first"))
    drained = inbox.drain()
    inbox.steer(UserMessage(content="second"))
    assert [m.content for m in drained] == ["first"]
