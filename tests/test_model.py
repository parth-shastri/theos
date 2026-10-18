"""Tests for harness.model: the protocols, Capabilities, and the estimator."""

from __future__ import annotations

from harness.events import GenerationComplete, TextDelta
from harness.model import default_estimate_tokens
from harness.types import (
    AssistantMessage,
    ModelRequest,
    ToolSpec,
    UserMessage,
)


def test_default_estimate_tokens_counts_tool_parameters():
    messages = [UserMessage("hi")]
    spec = ToolSpec("lookup", "Look one thing up", {"type": "object", "properties": {}})
    assert default_estimate_tokens(ModelRequest(messages, [spec])) > default_estimate_tokens(
        ModelRequest(messages)
    )


async def test_fake_model_streams_text_and_a_complete_message(fake_model):
    fake = fake_model([AssistantMessage(text="hi there")])
    request = ModelRequest([UserMessage("hello")])
    events = [event async for event in fake.stream(request)]
    message = events[-1].message
    assert message.text == "hi there"
    assert fake.requests == [request]
    assert events[:-1] == [TextDelta("hi there")]
    assert isinstance(events[-1], GenerationComplete)
    assert await fake.estimate_tokens(request) == default_estimate_tokens(request)
    buffered = fake_model([message])
    assert await buffered.generate(request) == message
