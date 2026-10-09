"""Tests for harness.events: the timestamp every event carries."""

from __future__ import annotations

import time

from harness.events import ModelCalled, TextDelta, ToolCallDelta
from harness.types import ModelRequest


def test_every_event_records_when_it_was_created():
    before = time.time()
    event = ModelCalled(ModelRequest([]))
    assert before <= event.at <= time.time()


def test_timestamps_do_not_take_part_in_equality():
    assert TextDelta("a") == TextDelta("a", at=0.0)
    assert TextDelta("a") != TextDelta("b")


def test_a_tool_call_delta_can_carry_only_a_name():
    first = ToolCallDelta(0, name="lookup")
    assert first.text == ""
    assert ToolCallDelta(0, "{}").name is None
