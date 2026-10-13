"""Full-request fit guarantees, progress-based overflow recovery, and preserved journals."""

import json
from contextlib import asynccontextmanager
from math import inf

import pytest

from harness import (
    Agent,
    AssistantMessage,
    Budget,
    CompactionConfig,
    ContextMemory,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    tool,
)
from harness.context_fit import cut_request, smaller_request
from harness.context_size import ContextOverflowError, request_size
from harness.lean_context import LeanModel
from harness.testing import FakeModel
from harness.types import ModelRequest, ToolSpec, message_to_dict
from tests.test_bounded_context import transcript


@pytest.mark.parametrize(
    "summary",
    [
        AssistantMessage("## Goal\n" + "detail " * 40000),
        AssistantMessage("Partial summary", stop_reason="length"),
        RuntimeError("Summary unavailable"),
    ],
)
async def test_oversized_or_failed_summary_is_cut_until_the_entire_request_fits(summary):
    history = transcript()
    original = [message_to_dict(m) for m in history]
    auxiliary = FakeModel([summary])

    @asynccontextmanager
    async def summaries():
        yield auxiliary

    memory = ContextMemory()
    policy = CompactionConfig("", summary_model=summaries, summary_window=100000)
    main = FakeModel([])
    model = LeanModel(main, 40000, policy, memory, history, Budget(inf))
    spec = ToolSpec("history_read", "Read original history.", {"type": "object"})
    request = ModelRequest(
        [SystemMessage("Required policy. " * 1000), *history], [spec], {"max_output_tokens": 8192}
    )
    events = [event async for event in model.prepare(request)]
    selected = events[-1]
    assert isinstance(selected, ModelRequest)
    assert request_size(selected) + 8192 <= 40000
    assert selected.messages[0] == request.messages[0] and history[-1] in selected.messages
    assert selected.options == request.options
    assert [message_to_dict(m) for m in history] == original
    assert "Partial summary" not in memory.summary
    assert not main.requests
    assert events[0].status == "started" and events[-2].status == "completed"


async def test_more_than_two_provider_overflows_can_recover_without_repeating_a_tool():
    count = 0

    @tool
    async def read_once():
        """Read a saved value."""
        nonlocal count
        count += 1
        return "Saved value 42."

    history = [
        m
        for i in range(30)
        for m in (
            UserMessage(f"Earlier question {i}"),
            AssistantMessage("Earlier evidence. " * 1000),
        )
    ] + [UserMessage("Use the saved value once.")]
    auxiliary = FakeModel([AssistantMessage("## Goal\nUse the saved value.")] * 20)

    @asynccontextmanager
    async def summaries():
        yield auxiliary

    main = FakeModel(
        [
            AssistantMessage(tool_calls=[ToolCall("read-one", "read_once", {})]),
            *[ContextOverflowError() for _ in range(4)],
            AssistantMessage("The value is 42."),
        ]
    )
    result = await Agent(
        main,
        [read_once],
        context_window=100000,
        compaction=CompactionConfig("", summary_model=summaries),
    ).run(history, budget=Budget(inf))
    assert result.message.text == "The value is 42." and count == 1
    retries = [request_size(r) for r in main.requests[1:]]
    assert len(retries) == 5 and all(a > b for a, b in zip(retries, retries[1:], strict=False))


async def test_irreducible_input_stops_before_provider_and_keeps_active_memory():
    history = [UserMessage("Current task " * 20000)]
    memory = ContextMemory(state={"references": {"record_ids": ["Ssaved"]}})
    main = FakeModel([])
    with pytest.raises(ContextOverflowError, match="No safe context reduction"):
        await Agent(
            main,
            instructions="Required policy.",
            context_window=16000,
            compaction=CompactionConfig(""),
        ).run(history, memory=memory, budget=Budget(inf))
    assert not main.requests and memory.working_messages is None
    assert memory.state["references"]["record_ids"] == ["Ssaved"]


def test_cuts_preserve_parallel_pairing_pending_arguments_and_user_steering():
    history = [
        UserMessage("Earlier"),
        AssistantMessage("Earlier answer. " * 2000),
        UserMessage("Current task"),
        AssistantMessage(
            tool_calls=[ToolCall("a", "read", {"id": "one"}), ToolCall("b", "read", {"id": "two"})]
        ),
        ToolResultMessage("a", "read", "Evidence " * 5000),
        UserMessage("Correction: preserve exact dates."),
        ToolResultMessage("b", "read", "Evidence " * 5000),
        AssistantMessage(tool_calls=[ToolCall("pending", "write", {"amount": 42})]),
    ]
    original = [message_to_dict(m) for m in history]
    request = ModelRequest(history)
    for _ in range(30):
        reduced = cut_request(request, history)
        if reduced is None:
            break
        selected, _ = reduced
        assert request_size(selected) < request_size(request)
        request = selected
    assert history[2] in request.messages and history[5] in request.messages
    calls = [
        call for m in request.messages if isinstance(m, AssistantMessage) for call in m.tool_calls
    ]
    assert calls == [*history[3].tool_calls, *history[-1].tool_calls]
    assert {m.call_id for m in request.messages if isinstance(m, ToolResultMessage)} == {"a", "b"}
    assert [message_to_dict(m) for m in history] == original


def test_optional_tool_documentation_can_be_removed_without_changing_schema_contracts():
    schema = {
        "type": "object",
        "description": "Documentation " * 5000,
        "properties": {
            "description": {"type": "string", "description": "Help " * 2000},
            "examples": {"type": "integer", "minimum": 0},
        },
        "required": ["description", "examples"],
        "additionalProperties": False,
        "default": {"description": "value", "examples": 3},
    }
    original = json.dumps(schema)
    request = ModelRequest([UserMessage("Task")], [ToolSpec("action", "Help " * 5000, schema)])
    selected, reason = cut_request(request, request.messages)
    assert reason == "tool_documentation_cut"
    after = selected.tools[0].parameters
    assert after["properties"]["description"]["type"] == "string"
    assert after["properties"]["examples"]["minimum"] == 0
    assert after["required"] == schema["required"] and after["default"] == schema["default"]
    assert after["additionalProperties"] is False and json.dumps(schema) == original


async def test_opaque_replay_can_be_cut_when_the_token_estimate_is_unchanged():
    history = [
        AssistantMessage(provider_data={"replay": "opaque" * 5000}),
        UserMessage("Current task"),
    ]
    request = ModelRequest(history)
    selected, reason = cut_request(request, history)
    assert reason == "reasoning_cut" and request_size(selected) == request_size(request)
    assert smaller_request(selected, request) and history[0].provider_data
    model = LeanModel(
        FakeModel([]), 40000, CompactionConfig(""), ContextMemory(), history, Budget(inf)
    )
    events = [event async for event in model.prepare(request, force=True)]
    assert smaller_request(events[-1], request)


async def test_full_compression_preserves_all_active_user_steering():
    history = [
        *transcript(),
        AssistantMessage(tool_calls=[ToolCall("read", "history_read", {})]),
        ToolResultMessage("read", "history_read", "Evidence " * 50000),
        UserMessage("Correction: do not send email."),
        AssistantMessage(tool_calls=[ToolCall("pending", "write", {"id": "exact"})]),
    ]
    auxiliary = FakeModel([AssistantMessage("## Goal\nMake the report.")])

    @asynccontextmanager
    async def summaries():
        yield auxiliary

    model = LeanModel(
        FakeModel([]),
        40000,
        CompactionConfig("", summary_model=summaries),
        ContextMemory(),
        history,
        Budget(inf),
    )
    events = [event async for event in model.prepare(ModelRequest(history))]
    selected = events[-1]
    assert history[-5] in selected.messages and history[-2] in selected.messages
    assert history[-1] in selected.messages
    assert request_size(selected) <= 40000
