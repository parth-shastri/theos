"""Tests for the optional terminal event-stream renderer."""

from __future__ import annotations

from io import StringIO

import harness
from harness import Agent, AssistantMessage, ModelRequest, ToolCall, UserMessage, tool
from harness.testing import FakeModel
from renderer import (
    RICH_AVAILABLE,
    HarnessAdapter,
    ModelFinished,
    ReasoningDelta,
    RunFinished,
    TerminalRenderer,
    ToolCallDelta,
    consume_model_stream,
    consume_run_stream,
)


@tool
def lookup_order(order_id: str) -> dict[str, str]:
    """Return a deterministic order for the renderer test."""
    return {"order_id": order_id, "status": "shipped"}


async def test_plain_consumer_renders_model_tool_and_turn_events() -> None:
    output = StringIO()
    renderer = TerminalRenderer(stream=output, use_rich=False, verbose=True)
    model = FakeModel(
        [
            AssistantMessage(
                tool_calls=[ToolCall("call-1", "lookup_order", {"order_id": "A-1"})],
                stop_reason="tool_calls",
            ),
            AssistantMessage("It has shipped.", stop_reason="stop"),
        ]
    )
    agent = Agent(model, [lookup_order])

    result = await consume_run_stream(
        agent.run_stream([UserMessage("Where is A-1?")]),
        title="Order lookup",
        prompt="Where is A-1?",
        renderer=renderer,
    )

    rendered = output.getvalue()
    assert result.status == "completed"
    assert result.message and result.message.text == "It has shipped."
    assert "Model call 1" in rendered
    assert 'lookup_order(order_id="A-1")' in rendered
    assert "lookup_order completed" in rendered
    assert "It has shipped." in rendered
    assert "Done" in rendered


def test_harness_adapter_maps_reasoning_and_tool_call_deltas() -> None:
    adapt = HarnessAdapter()
    assert adapt(harness.ReasoningDelta("Check.")) == ReasoningDelta("Check.")
    assert adapt(harness.ToolCallDelta(0, "{", "lookup")) == ToolCallDelta(0, "{", "lookup")


def test_plain_renderer_names_a_tool_call_while_the_model_writes_it() -> None:
    output = StringIO()
    renderer = TerminalRenderer(stream=output, use_rich=False)
    renderer.handle(ReasoningDelta("Check the order."))
    renderer.handle(ToolCallDelta(0, name="lookup_order"))
    renderer.handle(ToolCallDelta(0, '{"order_id": "A-1"}'))
    assert output.getvalue() == "… writing lookup_order\n"


async def test_model_consumer_writes_each_streamed_delta() -> None:
    output = StringIO()
    renderer = TerminalRenderer(stream=output, use_rich=False)
    request = ModelRequest([UserMessage("Hello")])
    model = FakeModel([AssistantMessage("Hello from the stream.", stop_reason="stop")])

    message = await consume_model_stream(
        model.stream(request),
        request=request,
        title="Streaming model",
        renderer=renderer,
    )

    assert message.text == "Hello from the stream."
    assert "Assistant\nHello from the stream." in output.getvalue()


def test_rich_request_falls_back_when_dependency_is_unavailable() -> None:
    renderer = TerminalRenderer(stream=StringIO(), use_rich=True)
    assert renderer.uses_rich is RICH_AVAILABLE


def test_summary_displays_cached_token_usage() -> None:
    output = StringIO()
    renderer = TerminalRenderer(stream=output, use_rich=False)

    renderer.handle(
        ModelFinished(
            usage={
                "input_tokens": 12_345,
                "output_tokens": 678,
                "cache_read_tokens": 10_000,
                "cache_write_tokens": 250,
            }
        )
    )
    renderer.handle(RunFinished())

    rendered = output.getvalue()
    assert "12,345 in" in rendered
    assert "678 out" in rendered
    assert "10,000 cached" in rendered
    assert "250 cache write" in rendered
