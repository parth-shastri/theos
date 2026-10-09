"""Tests for harness.model: the protocols, Capabilities, and the estimator."""

from __future__ import annotations

import pytest

from harness.events import GenerationComplete, TextDelta
from harness.model import Capabilities, ChatModel, Model, default_estimate_tokens
from harness.testing import FakeModel
from harness.types import (
    AssistantMessage,
    ModelRequest,
    SystemMessage,
    ToolSpec,
    UserMessage,
)


def test_fake_model_satisfies_chat_model_without_inheriting(fake_model):
    fake = fake_model([AssistantMessage(text="hello")])
    assert ChatModel not in type(fake).__mro__
    assert isinstance(fake, ChatModel)
    assert isinstance(fake, Model)


def test_an_object_without_generate_is_not_a_chat_model():
    class Incomplete:
        provider = "fake"
        model_id = "fake-1"
        capabilities = Capabilities()

        async def stream(self, request: ModelRequest):
            if False:
                yield

        async def estimate_tokens(self, request: ModelRequest) -> int:
            return 1

    assert not isinstance(Incomplete(), ChatModel)
    assert isinstance(Incomplete(), Model)


def test_default_estimate_tokens_returns_a_positive_count():
    request = ModelRequest(
        [SystemMessage("You are helpful."), UserMessage("Where is order 9127412?")]
    )
    assert default_estimate_tokens(request) > 0


def test_default_estimate_tokens_counts_tool_parameters():
    messages = [UserMessage("hi")]
    spec = ToolSpec("lookup", "Look one thing up", {"type": "object", "properties": {}})
    assert default_estimate_tokens(ModelRequest(messages, [spec])) > default_estimate_tokens(
        ModelRequest(messages)
    )


def test_capabilities_is_a_frozen_record_with_five_fields():
    caps = Capabilities()
    assert (caps.tools, caps.parallel_tool_calls, caps.forced_tool_choice) == (True, True, True)
    assert (caps.json_schema_output, caps.vision) == (False, False)
    with pytest.raises(Exception):
        caps.tools = False


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


async def test_fake_model_raises_a_scripted_exception_after_a_partial_delta(fake_model):
    events: list = []
    fake = fake_model([RuntimeError("stream died")])
    with pytest.raises(RuntimeError, match="stream died"):
        async for event in fake.stream(ModelRequest([UserMessage("hello")])):
            events.append(event)
    assert [e.text for e in events] == ['{"tool_call": "partial"}']


async def test_generate_returns_the_same_message_as_stream(fake_model):
    expected = AssistantMessage(text="same answer")
    streamed = fake_model([expected])
    buffered = fake_model([expected])
    request = ModelRequest([UserMessage("hello")])

    events = [event async for event in streamed.stream(request)]
    generated = await buffered.generate(request)

    assert events[-1] == GenerationComplete(generated)


async def test_fake_model_raises_when_the_script_runs_out(fake_model):
    fake = fake_model([])
    with pytest.raises(RuntimeError, match="FakeModel script exhausted"):
        await fake.generate(ModelRequest([UserMessage("hello")]))


def test_fake_model_carries_its_identity(fake_model):
    fake = fake_model(
        [], provider="anthropic", model_id="claude-x", capabilities=Capabilities(vision=True)
    )
    assert (fake.provider, fake.model_id) == ("anthropic", "claude-x")
    assert fake.capabilities.vision is True
    assert FakeModel is type(fake)
