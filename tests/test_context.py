"""Tests for harness.context: RunContext, select_context, unanswered_calls."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from harness.context import (
    RunContext,
    default_estimate,
    select_context,
    unanswered_calls,
)
from harness.inbox import Inbox
from harness.types import (
    AssistantMessage,
    Budget,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


@dataclass
class Deps:
    account_id: str


def test_run_context_constructs_from_deps_alone():
    ctx = RunContext(deps=Deps(account_id="acct_1"))
    assert ctx.deps.account_id == "acct_1"
    assert ctx.history == []
    assert ctx.budget is None
    assert ctx.inbox is None
    assert ctx.emit is None
    assert ctx.state == {}
    assert len(ctx.run_id) == 32


def test_run_context_run_ids_differ_per_run():
    assert RunContext(deps=None).run_id != RunContext(deps=None).run_id


def test_run_context_accepts_the_optional_collaborators():
    inbox = Inbox()
    budget = Budget(max_model_calls=3)
    seen: list[object] = []
    ctx = RunContext(deps=None, budget=budget, inbox=inbox, emit=seen.append)
    assert ctx.budget is budget
    assert ctx.inbox is inbox
    ctx.emit("event")
    assert seen == ["event"]


def test_default_estimate_counts_about_four_characters_per_token():
    messages = [SystemMessage(content="a" * 40), UserMessage(content="b" * 8)]
    assert default_estimate(messages) == 12


def test_default_estimate_counts_tool_call_arguments_and_results():
    arguments = {"order_id": "A1"}
    messages = [
        AssistantMessage(
            text="looking",
            tool_calls=[ToolCall(id="c1", name="get_order", arguments=arguments)],
        ),
        ToolResultMessage(call_id="c1", name="get_order", content="shipped"),
    ]
    expected = (
        max(1, len("looking") // 4)
        + max(1, len(json.dumps(arguments)) // 4)
        + max(1, len("shipped") // 4)
    )
    assert default_estimate(messages) == expected


def test_default_estimate_of_empty_history_is_zero():
    assert default_estimate([]) == 0


def test_select_context_without_a_limit_returns_a_copy_of_history():
    history = [SystemMessage(content="be brief"), UserMessage(content="hi")]
    selected = select_context(history)
    assert selected == history
    assert selected is not history
    assert selected[0] is history[0]


def test_select_context_never_mutates_history():
    history = [
        SystemMessage(content="be brief"),
        UserMessage(content="a" * 400),
        AssistantMessage(text="b" * 400),
        UserMessage(content="c" * 400),
    ]
    before = list(history)
    select_context(history, max_tokens=1)
    assert history == before
    assert len(history) == 4


def test_select_context_keeps_system_messages_and_the_last_user_message():
    history = [
        SystemMessage(content="be brief"),
        UserMessage(content="a" * 400),
        AssistantMessage(text="b" * 400),
        SystemMessage(content="stay polite"),
        UserMessage(content="c" * 400),
    ]
    selected = select_context(history, max_tokens=1)
    assert selected == [
        SystemMessage(content="be brief"),
        SystemMessage(content="stay polite"),
        UserMessage(content="c" * 400),
    ]


def test_select_context_keeps_order():
    history = [
        SystemMessage(content="be brief"),
        UserMessage(content="a"),
        AssistantMessage(text="b"),
        UserMessage(content="c"),
    ]
    selected = select_context(history, max_tokens=1000)
    assert selected == history


def test_select_context_never_splits_a_tool_pair():
    call = ToolCall(id="c1", name="get_order", arguments={"order_id": "A1"})
    old_call = ToolCall(id="c0", name="get_order", arguments={"order_id": "A0"})
    history = [
        SystemMessage(content="be brief"),
        UserMessage(content="a" * 200),
        AssistantMessage(text="old", tool_calls=[old_call]),
        ToolResultMessage(call_id="c0", name="get_order", content="x" * 200),
        AssistantMessage(text="new", tool_calls=[call]),
        ToolResultMessage(call_id="c1", name="get_order", content="shipped"),
        UserMessage(content="and now"),
    ]
    budget = default_estimate(
        [history[0], history[4], history[5], history[6]]
    )
    selected = select_context(history, max_tokens=budget)
    assert selected == [history[0], history[4], history[5], history[6]]

    tight = select_context(history, max_tokens=1)
    assert tight == [history[0], history[6]]
    for message in tight:
        assert not isinstance(message, ToolResultMessage)


def assert_no_orphan_results(selected):
    """Every tool result in the selection answers a call that is still present."""
    offered: set[str] = set()
    for message in selected:
        if isinstance(message, AssistantMessage):
            offered.update(call.id for call in message.tool_calls)
        if isinstance(message, ToolResultMessage):
            assert message.call_id in offered


def test_select_context_keeps_a_tool_pair_together_across_an_interleaved_message():
    call = ToolCall(id="c1", name="refund", arguments={"order_id": "A1"})
    history = [
        AssistantMessage(text="x" * 400, tool_calls=[call]),
        UserMessage(content="approved"),
        ToolResultMessage(call_id="c1", name="refund", content="refunded"),
    ]
    selected = select_context(history, max_tokens=50)
    assert_no_orphan_results(selected)
    assert selected == [history[1]]


def test_select_context_keeps_interleaved_results_when_their_call_survives():
    call = ToolCall(id="c1", name="refund", arguments={"order_id": "A1"})
    history = [
        UserMessage(content="refund order A1"),
        AssistantMessage(text="asking", tool_calls=[call]),
        UserMessage(content="approved"),
        ToolResultMessage(call_id="c1", name="refund", content="refunded"),
    ]
    selected = select_context(history, max_tokens=1000)
    assert_no_orphan_results(selected)
    assert selected == history


def test_select_context_keeps_results_spread_across_other_messages_in_order():
    first = ToolCall(id="c1", name="get_order", arguments={"order_id": "A1"})
    second = ToolCall(id="c2", name="get_order", arguments={"order_id": "A2"})
    history = [
        UserMessage(content="old " * 100),
        AssistantMessage(text="working", tool_calls=[first, second]),
        ToolResultMessage(call_id="c1", name="get_order", content="shipped"),
        UserMessage(content="any news"),
        ToolResultMessage(call_id="c2", name="get_order", content="delayed"),
    ]
    selected = select_context(history, max_tokens=20)
    assert_no_orphan_results(selected)
    assert selected == [history[1], history[2], history[3], history[4]]


def test_select_context_drops_down_to_the_keep_mark_on_overflow():
    history = [
        UserMessage(content="a" * 40),
        AssistantMessage(text="b" * 40),
        UserMessage(content="c" * 40),
        AssistantMessage(text="d" * 40),
        UserMessage(content="e" * 40),
    ]
    # Ten tokens each. The fourth message passes 30, so the window drops to 15.
    selected = select_context(history, max_tokens=30)
    assert selected == history[3:]


def test_select_context_keeps_the_cut_point_while_history_grows():
    def turn(n: int) -> list:
        return [UserMessage(content=f"q{n}" * 20), AssistantMessage(text=f"a{n}" * 20)]

    history: list = []
    windows: list[list] = []
    for n in range(12):
        history.extend(turn(n))
        windows.append(select_context(history, max_tokens=100, keep_tokens=50))

    # Every window is a prefix of the next one, until a cut moves. Counting the
    # moves shows the cut stayed put for several turns each time.
    moves = sum(1 for a, b in zip(windows, windows[1:]) if b[: len(a)] != a)
    assert 1 <= moves <= 3
    assert windows[-1][-1] is history[-1]


def test_select_context_the_same_history_always_gives_the_same_window():
    history = [UserMessage(content=str(n) * 40) for n in range(9)]
    assert select_context(history, max_tokens=50) == select_context(history, max_tokens=50)


def test_select_context_rejects_a_keep_mark_at_or_above_the_limit():
    with pytest.raises(ValueError):
        select_context([UserMessage(content="hi")], max_tokens=10, keep_tokens=10)


def test_select_context_keeps_the_latest_question_when_a_cut_runs_past_it():
    call = ToolCall(id="c1", name="get_order", arguments={"order_id": "A1"})
    history = [
        UserMessage(content="where is A1"),
        AssistantMessage(text="x" * 400, tool_calls=[call]),
        ToolResultMessage(call_id="c1", name="get_order", content="y" * 400),
    ]
    selected = select_context(history, max_tokens=50)
    assert selected[0] is history[0]
    assert_no_orphan_results(selected)


def test_select_context_accepts_a_custom_estimator():
    history = [UserMessage(content="a"), AssistantMessage(text="b"), UserMessage(content="c")]
    selected = select_context(
        history, max_tokens=2, estimate_tokens=lambda messages: 10 * len(messages)
    )
    assert selected == [history[2]]


def test_unanswered_calls_of_empty_history_is_empty():
    assert unanswered_calls([]) == []


def test_unanswered_calls_returns_the_trailing_assistant_calls_in_order():
    calls = [
        ToolCall(id="c1", name="get_order", arguments={}),
        ToolCall(id="c2", name="refund", arguments={}),
    ]
    history = [UserMessage(content="hi"), AssistantMessage(text="working", tool_calls=calls)]
    assert unanswered_calls(history) == calls


def test_unanswered_calls_skips_answered_calls():
    calls = [
        ToolCall(id="c1", name="get_order", arguments={}),
        ToolCall(id="c2", name="refund", arguments={}),
    ]
    history = [
        UserMessage(content="hi"),
        AssistantMessage(text="working", tool_calls=calls),
        ToolResultMessage(call_id="c1", name="get_order", content="shipped"),
    ]
    assert unanswered_calls(history) == [calls[1]]


def test_unanswered_calls_reads_the_trailing_assistant_only():
    old_call = ToolCall(id="c0", name="get_order", arguments={})
    new_call = ToolCall(id="c1", name="refund", arguments={})
    history = [
        AssistantMessage(text="old", tool_calls=[old_call]),
        ToolResultMessage(call_id="c0", name="get_order", content="shipped"),
        AssistantMessage(text="new", tool_calls=[new_call]),
    ]
    assert unanswered_calls(history) == [new_call]


def test_unanswered_calls_ignores_results_recorded_before_the_trailing_assistant():
    call = ToolCall(id="c1", name="refund", arguments={})
    history = [
        ToolResultMessage(call_id="c1", name="refund", content="stale"),
        AssistantMessage(text="new", tool_calls=[call]),
    ]
    assert unanswered_calls(history) == [call]


def test_unanswered_calls_is_empty_without_an_assistant_message():
    assert unanswered_calls([UserMessage(content="hi")]) == []


def test_unanswered_calls_is_empty_when_the_assistant_made_no_calls():
    assert unanswered_calls([AssistantMessage(text="done")]) == []
