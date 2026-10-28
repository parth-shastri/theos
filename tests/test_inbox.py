"""Tests for harness.events and harness.inbox."""

from __future__ import annotations

from pydantic import BaseModel

from harness.inbox import Inbox
from harness.types import (
    UserMessage,
)


class Args(BaseModel):
    order_id: str


def test_inbox_drain_returns_steered_messages_in_order_and_empties():
    inbox = Inbox()
    inbox.steer(UserMessage(content="first"))
    inbox.steer(UserMessage(content="second"))
    drained = inbox.drain()
    assert [m.content for m in drained] == ["first", "second"]
    assert inbox.drain() == []
    inbox.steer(UserMessage(content="third"))
    assert [m.content for m in drained] == ["first", "second"]
    assert [m.content for m in inbox.drain()] == ["third"]
