"""Tests for the Anthropic adapter: encode, decode, and a thin generate.

Every wire shape is checked against the installed anthropic types. Fixture
payloads become real SDK objects with `Message.model_validate`, so a shape the
SDK would reject fails here.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from anthropic import AsyncAnthropic
from anthropic.lib.streaming import TextEvent
from anthropic.lib.streaming._types import ThinkingEvent
from anthropic.resources.beta.messages.messages import AsyncMessages as AsyncBetaMessages
from anthropic.resources.messages.messages import AsyncMessages
from anthropic.types import (
    InputJSONDelta,
    Message,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    ToolUseBlock,
)

from harness.events import ReasoningDelta, TextDelta, ToolCallDelta
from harness.model import ChatModel, default_estimate_tokens
from harness.providers.anthropic import AnthropicChatModel
from harness.types import (
    AssistantMessage,
    ModelRequest,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    View,
)

MODEL_ID = "claude-opus-5"
SNAPSHOT_ID = "claude-opus-5-20260401"


def adapter(model_id: str = MODEL_ID, **kwargs: Any) -> AnthropicChatModel:
    """Build an adapter over a client that never makes a call."""
    client = AsyncAnthropic(api_key="test-key")
    return AnthropicChatModel(client, model_id, **kwargs)


def spec(name: str = "lookup_order") -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Look one order up",
        parameters={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    )


# --------------------------------------------------------------------------
# Message fixtures
# --------------------------------------------------------------------------


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def thinking_block(thinking: str, signature: str = "sig-abc") -> dict[str, Any]:
    return {"type": "thinking", "thinking": thinking, "signature": signature}


def tool_use_block(
    block_id: str, name: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"type": "tool_use", "id": block_id, "name": name, "input": payload or {}}


def usage(
    input_tokens: int = 11,
    output_tokens: int = 7,
    cache_read: int | None = None,
    cache_write: int | None = None,
) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if cache_read is not None:
        counts["cache_read_input_tokens"] = cache_read
    if cache_write is not None:
        counts["cache_creation_input_tokens"] = cache_write
    return counts


def message(
    content: list[dict[str, Any]],
    stop_reason: str = "end_turn",
    model: str = MODEL_ID,
    **extra: Any,
) -> Message:
    payload: dict[str, Any] = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage(),
    }
    payload.update(extra)
    return Message.model_validate(payload)


# --------------------------------------------------------------------------
# Stub client for generate
# --------------------------------------------------------------------------


class StubStream:
    """An async iterable of prepared stream events with a final message."""

    def __init__(self, events: list[Any], final: Message | None) -> None:
        self.events = events
        self.final = final

    async def __aiter__(self):
        for event in self.events:
            yield event

    async def get_final_message(self) -> Message | None:
        return self.final


class StubStreamManager:
    def __init__(self, stream: StubStream) -> None:
        self.stream = stream

    async def __aenter__(self) -> StubStream:
        return self.stream

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class StubMessages:
    """Enough of `client.messages` for `generate` and nothing more."""

    def __init__(
        self,
        result: Message | None = None,
        events: list[Any] | None = None,
        final: Message | None = None,
    ) -> None:
        self.result = result
        self.events = events or []
        self.final = final
        self.calls: list[dict[str, Any]] = []
        self.streams: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Message | None:
        self.calls.append(kwargs)
        return self.result

    def stream(self, **kwargs: Any) -> StubStreamManager:
        self.streams.append(kwargs)
        return StubStreamManager(StubStream(self.events, self.final))


class StubBeta:
    def __init__(self, messages: StubMessages) -> None:
        self.messages = messages


class StubClient:
    def __init__(self, messages: StubMessages, beta: StubMessages | None = None) -> None:
        self.messages = messages
        self.beta = StubBeta(beta if beta is not None else messages)


def text_event(text: str) -> TextEvent:
    return TextEvent(type="text", text=text, snapshot=text)


def thinking_event(text: str) -> ThinkingEvent:
    return ThinkingEvent(type="thinking", thinking=text, snapshot=text)


def tool_use_start(index: int, name: str) -> RawContentBlockStartEvent:
    return RawContentBlockStartEvent(
        type="content_block_start",
        index=index,
        content_block=ToolUseBlock(type="tool_use", id="toolu_1", name=name, input={}),
    )


def input_json_event(index: int, partial: str) -> RawContentBlockDeltaEvent:
    return RawContentBlockDeltaEvent(
        type="content_block_delta",
        index=index,
        delta=InputJSONDelta(type="input_json_delta", partial_json=partial),
    )


# --------------------------------------------------------------------------
# Protocol and capabilities
# --------------------------------------------------------------------------


async def test_adapter_contract_and_estimator_forwarding():
    model = adapter()
    assert ChatModel not in type(model).__mro__
    assert isinstance(model, ChatModel)
    assert model.provider == "anthropic"
    assert model.model_id == MODEL_ID
    caps = model.capabilities
    assert caps.tools and caps.parallel_tool_calls and caps.forced_tool_choice
    assert caps.json_schema_output and caps.vision
    request = ModelRequest([UserMessage("Evidence. " * 100)], [spec()])
    assert await model.estimate_tokens(request) == default_estimate_tokens(request)


@pytest.mark.parametrize(
    ("model_id", "forced"),
    [
        ("claude-opus-5", True),
        ("claude-sonnet-5", True),
        ("claude-fable-5", True),
        ("claude-fable-5-1", False),
        ("claude-mythos-5-1", False),
    ],
)
def test_capabilities_drop_forced_tool_choice_where_the_model_rejects_it(model_id, forced):
    assert adapter(model_id).capabilities.forced_tool_choice is forced
    assert AnthropicChatModel.capabilities.forced_tool_choice is True


# --------------------------------------------------------------------------
# Encode
# --------------------------------------------------------------------------


def test_encode_complete_request_contract():
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    request = ModelRequest(
        [
            SystemMessage("You are helpful."),
            SystemMessage("Answer in one line."),
            UserMessage("Where is order 9127412?"),
        ],
        [spec()],
        {"json_schema": schema, "stop_sequences": ["END"], "metadata": {"user_id": "u1"}},
    )
    payload = adapter(max_tokens=64000).encode_request(request)
    assert payload == {
        "model": MODEL_ID,
        "system": "You are helpful.\n\nAnswer in one line.",
        "messages": [{"role": "user", "content": "Where is order 9127412?"}],
        "max_tokens": 64000,
        "thinking": {"type": "adaptive"},
        "cache_control": {"type": "ephemeral"},
        "tools": [
            {
                "name": "lookup_order",
                "description": "Look one order up",
                "input_schema": spec().parameters,
            }
        ],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
        "stop_sequences": ["END"],
        "metadata": {"user_id": "u1"},
    }
    assert set(payload) <= set(inspect.signature(AsyncMessages.create).parameters)


def test_encode_minimal_request_and_disabled_features():
    payload = adapter(cache=False, thinking=None).encode_request(ModelRequest([UserMessage("hi")]))
    assert payload == {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 16000,
    }


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("auto", {"type": "auto"}),
        ("none", {"type": "none"}),
        ("any", {"type": "any"}),
        ("lookup_order", {"type": "tool", "name": "lookup_order"}),
    ],
)
def test_encode_translates_tool_choice(given, expected):
    request = ModelRequest([UserMessage("hi")], [spec()], {"tool_choice": given})
    assert adapter().encode_request(request)["tool_choice"] == expected


def test_encode_merges_json_schema_into_a_caller_output_config():
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    request = ModelRequest(
        [UserMessage("hi")],
        options={"json_schema": schema, "output_config": {"effort": "high"}},
    )
    payload = adapter().encode_request(request)
    assert payload["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": schema},
    }


def test_encode_sends_a_fallback_list_with_the_array_form_beta():
    model = adapter(fallbacks=[{"model": "claude-opus-4-8"}])
    payload = model.encode_request(ModelRequest([UserMessage("hi")]))
    assert payload["fallbacks"] == [{"model": "claude-opus-4-8"}]
    assert payload["betas"] == ["server-side-fallback-2026-06-01"]


def test_encode_sends_the_default_fallback_with_the_scalar_form_beta():
    model = adapter(fallbacks="default")
    payload = model.encode_request(ModelRequest([UserMessage("hi")]))
    assert payload["fallbacks"] == "default"
    assert payload["betas"] == ["server-side-fallback-2026-07-01"]


def test_encode_assistant_message_without_provider_data():
    history = [
        UserMessage("Where is order 9127412?"),
        AssistantMessage(
            text="Let me look.",
            tool_calls=[ToolCall("toolu_1", "lookup_order", {"order_id": "9127412"})],
        ),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"] == [
        {"role": "user", "content": "Where is order 9127412?"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me look."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "lookup_order",
                    "input": {"order_id": "9127412"},
                },
            ],
        },
    ]


def test_encode_skips_the_text_block_when_an_assistant_message_has_no_text():
    history = [AssistantMessage(tool_calls=[ToolCall("toolu_1", "lookup_order", {})])]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"][0]["content"] == [
        {"type": "tool_use", "id": "toolu_1", "name": "lookup_order", "input": {}}
    ]


def test_encode_drops_an_assistant_turn_that_has_nothing_to_say():
    """A refusal before any output decodes to empty content, which the wire rejects."""
    history = [
        UserMessage("hi"),
        AssistantMessage(
            stop_reason="refusal",
            provider_data={"anthropic": {"model": MODEL_ID, "content": []}},
        ),
        UserMessage("try again"),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hi"},
                {"type": "text", "text": "try again"},
            ],
        }
    ]


def test_encode_merges_tool_results_that_an_empty_assistant_turn_separates():
    history = [
        ToolResultMessage(call_id="toolu_1", name="lookup_order", content="shipped"),
        AssistantMessage(provider_data={"anthropic": {"model": MODEL_ID, "content": []}}),
        ToolResultMessage(call_id="toolu_2", name="send_email", content="sent"),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "shipped"},
                {"type": "tool_result", "tool_use_id": "toolu_2", "content": "sent"},
            ],
        }
    ]


def test_encode_merges_a_steering_message_into_the_tool_result_turn():
    history = [
        ToolResultMessage(call_id="toolu_1", name="lookup_order", content="shipped"),
        UserMessage("also check the address"),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "shipped"},
                {"type": "text", "text": "also check the address"},
            ],
        }
    ]


def test_encode_leaves_an_alternating_conversation_alone():
    history = [
        SystemMessage("You are helpful."),
        UserMessage("hi"),
        AssistantMessage(text="Hello."),
        UserMessage("where is order 9127412?"),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "Hello."}]},
        {"role": "user", "content": "where is order 9127412?"},
    ]


def test_encode_replays_raw_content_for_the_same_model():
    raw = [thinking_block("Check the order first"), tool_use_block("toolu_1", "lookup_order")]
    history = [
        UserMessage("hi"),
        AssistantMessage(
            text="ignored on replay",
            tool_calls=[ToolCall("toolu_1", "lookup_order", {})],
            provider_data={"anthropic": {"model": MODEL_ID, "content": raw}},
        ),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"][1] == {"role": "assistant", "content": raw}
    assert payload["messages"][1]["content"][0]["signature"] == "sig-abc"


def test_encode_rebuilds_when_provider_data_is_from_another_model():
    history = [
        AssistantMessage(
            text="Hello",
            provider_data={
                "anthropic": {"model": "claude-sonnet-5", "content": [thinking_block("x")]}
            },
        )
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"] == [
        {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}
    ]


def test_encode_rebuilds_when_provider_data_is_from_another_provider():
    history = [
        AssistantMessage(
            text="Hello",
            provider_data={"openai": {"model": MODEL_ID, "output": [{"type": "reasoning"}]}},
        )
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"] == [
        {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}
    ]


def test_encode_does_not_mutate_the_replayed_provider_data():
    raw = [tool_use_block("toolu_1", "lookup_order")]
    history = [AssistantMessage(provider_data={"anthropic": {"model": MODEL_ID, "content": raw}})]
    payload = adapter().encode_request(ModelRequest(history))
    payload["messages"][0]["content"][0]["name"] = "mutated"
    assert raw[0]["name"] == "lookup_order"


def test_encode_folds_consecutive_tool_results_into_one_user_message():
    history = [
        UserMessage("hi"),
        AssistantMessage(
            tool_calls=[
                ToolCall("toolu_1", "lookup_order", {}),
                ToolCall("toolu_2", "send_email", {}),
            ]
        ),
        ToolResultMessage(call_id="toolu_1", name="lookup_order", content="shipped"),
        ToolResultMessage(call_id="toolu_2", name="send_email", content="sent"),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"][2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "shipped"},
            {"type": "tool_result", "tool_use_id": "toolu_2", "content": "sent"},
        ],
    }
    assert len(payload["messages"]) == 3


def test_encode_keeps_the_order_of_mixed_user_content():
    history = [
        ToolResultMessage(call_id="toolu_1", name="lookup_order", content="shipped"),
        UserMessage("thanks"),
        ToolResultMessage(call_id="toolu_2", name="send_email", content="sent"),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "shipped"},
                {"type": "text", "text": "thanks"},
                {"type": "tool_result", "tool_use_id": "toolu_2", "content": "sent"},
            ],
        }
    ]


@pytest.mark.parametrize("status", ["denied", "failed", "unknown"])
def test_encode_marks_a_tool_result_that_did_not_complete_as_an_error(status):
    result = ToolResultMessage(
        call_id="toolu_1", name="lookup_order", content="boom", status=status
    )
    payload = adapter().encode_request(ModelRequest([result]))
    assert payload["messages"][0]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": "boom",
            "is_error": True,
        }
    ]


def test_encode_omits_is_error_for_a_completed_tool_result():
    result = ToolResultMessage(call_id="toolu_1", name="lookup_order", content="shipped")
    block = adapter().encode_request(ModelRequest([result]))["messages"][0]["content"][0]
    assert "is_error" not in block


@pytest.mark.parametrize("content", ["", "   ", "\n\t "])
def test_encode_replaces_empty_tool_result_content_with_a_placeholder(content):
    """The Messages API rejects an empty content block, so a tool that returns nothing says so."""
    result = ToolResultMessage(call_id="toolu_1", name="lookup_order", content=content)
    payload = adapter().encode_request(ModelRequest([result]))
    assert payload["messages"][0]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "(empty result)"}
    ]


def test_encode_leaves_tool_result_content_that_is_not_empty_untouched():
    result = ToolResultMessage(call_id="toolu_1", name="lookup_order", content=" shipped ")
    block = adapter().encode_request(ModelRequest([result]))["messages"][0]["content"][0]
    assert block["content"] == " shipped "


def test_encode_marks_an_empty_failed_tool_result_as_an_error():
    result = ToolResultMessage(call_id="toolu_1", name="lookup_order", content="", status="failed")
    block = adapter().encode_request(ModelRequest([result]))["messages"][0]["content"][0]
    assert block == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "(empty result)",
        "is_error": True,
    }


def test_encode_ignores_the_view_on_a_tool_result():
    plain = ToolResultMessage(call_id="toolu_1", name="lookup_order", content="shipped")
    decorated = ToolResultMessage(
        call_id="toolu_1",
        name="lookup_order",
        content="shipped",
        view=View("order_card", {"order_id": "9127412"}),
    )
    model = adapter()
    assert model.encode_request(ModelRequest([decorated])) == model.encode_request(
        ModelRequest([plain])
    )


def test_every_encoded_key_is_a_beta_messages_create_parameter_with_fallbacks():
    model = adapter(fallbacks="default")
    payload = model.encode_request(ModelRequest([UserMessage("hi")], [spec()]))
    accepted = set(inspect.signature(AsyncBetaMessages.create).parameters)
    assert set(payload) <= accepted
    assert "fallbacks" not in set(inspect.signature(AsyncMessages.create).parameters)


def test_encode_rejects_an_unknown_message():
    with pytest.raises(ValueError):
        adapter().encode_request(ModelRequest([object()]))  # type: ignore[list-item]


# --------------------------------------------------------------------------
# Decode
# --------------------------------------------------------------------------


def test_decode_text_and_stop_reason():
    decoded = adapter().decode_response(message([text_block("Order 9127412 shipped.")]))
    assert decoded.text == "Order 9127412 shipped."
    assert decoded.reasoning is None
    assert decoded.tool_calls == []
    assert decoded.stop_reason == "stop"
    data = decoded.provider_data["anthropic"]
    assert data["model"] == MODEL_ID
    assert data["response_model"] == MODEL_ID
    assert data["stop_reason"] == "end_turn"
    assert data["content"] == [{"type": "text", "text": "Order 9127412 shipped."}]
    assert "stop_details" not in data
    assert decoded.usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 18,
    }


def test_decode_preserves_thinking_text_parallel_calls_and_cached_usage():
    raw = message(
        [
            thinking_block("Look the order up."),
            thinking_block("Then answer."),
            text_block("Working on it."),
            tool_use_block("toolu_1", "lookup_order", {"order_id": "1"}),
            tool_use_block("toolu_2", "send_email", {"to": "a@b.com"}),
        ],
        stop_reason="tool_use",
        usage=usage(cache_read=4, cache_write=9),
    )
    decoded = adapter().decode_response(raw)
    assert decoded.text == "Working on it."
    assert decoded.reasoning == "Look the order up.\n\nThen answer."
    assert decoded.stop_reason == "tool_calls"
    assert decoded.tool_calls == [
        ToolCall("toolu_1", "lookup_order", {"order_id": "1"}),
        ToolCall("toolu_2", "send_email", {"to": "a@b.com"}),
    ]
    assert decoded.usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "cache_read_tokens": 4,
        "cache_write_tokens": 9,
        "total_tokens": 18,
    }


def test_decoded_arguments_are_independent_of_the_raw_message():
    raw = message(
        [tool_use_block("toolu_1", "lookup_order", {"order_id": "1"})], stop_reason="tool_use"
    )
    decoded = adapter().decode_response(raw)
    decoded.tool_calls[0].arguments["order_id"] = "mutated"
    assert raw.content[0].input == {"order_id": "1"}


@pytest.mark.parametrize(
    ("raw_reason", "expected"),
    [
        ("end_turn", "stop"),
        ("stop_sequence", "stop"),
        ("tool_use", "tool_calls"),
        ("max_tokens", "length"),
        ("refusal", "refusal"),
        ("pause_turn", "pause_turn"),
        ("model_context_window_exceeded", "model_context_window_exceeded"),
    ],
)
def test_decode_maps_stop_reason(raw_reason, expected):
    decoded = adapter().decode_response(message([text_block("x")], stop_reason=raw_reason))
    assert decoded.stop_reason == expected
    assert decoded.provider_data["anthropic"]["stop_reason"] == raw_reason


def test_decode_keeps_stop_details_for_a_refusal():
    raw = message(
        [text_block("I cannot help with that.")],
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": "policy"},
    )
    decoded = adapter().decode_response(raw)
    assert decoded.stop_reason == "refusal"
    assert decoded.provider_data["anthropic"]["stop_details"] == {
        "type": "refusal",
        "category": "cyber",
        "explanation": "policy",
    }


def test_decode_of_a_dated_snapshot_still_replays_through_encode():
    raw = message(
        [thinking_block("Thinking"), tool_use_block("toolu_1", "lookup_order")],
        stop_reason="tool_use",
        model=SNAPSHOT_ID,
    )
    model = adapter()
    decoded = model.decode_response(raw)
    payload = model.encode_request(ModelRequest([UserMessage("hi"), decoded]))
    assert payload["messages"][1]["content"] == [
        block.model_dump(exclude_none=True) for block in raw.content
    ]
    assert decoded.provider_data["anthropic"]["model"] == MODEL_ID
    assert decoded.provider_data["anthropic"]["response_model"] == SNAPSHOT_ID


def test_encode_rebuilds_what_another_requested_id_decoded():
    raw = message(
        [thinking_block("Thinking"), tool_use_block("toolu_1", "lookup_order")],
        stop_reason="tool_use",
        model=SNAPSHOT_ID,
    )
    decoded = adapter("claude-sonnet-5").decode_response(raw)
    payload = adapter().encode_request(ModelRequest([decoded]))
    assert payload["messages"][0]["content"] == [
        {"type": "tool_use", "id": "toolu_1", "name": "lookup_order", "input": {}}
    ]


# --------------------------------------------------------------------------
# streaming and buffered generation
# --------------------------------------------------------------------------


async def test_stream_yields_text_deltas_and_decodes_the_final_message():
    final = message([text_block("Order shipped.")])
    endpoint = StubMessages(events=[text_event("Order "), text_event("shipped.")], final=final)
    model = AnthropicChatModel(StubClient(endpoint), MODEL_ID)
    events = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    decoded = events[-1].message
    assert [event.text for event in events[:-1]] == ["Order ", "shipped."]
    assert decoded.text == "Order shipped."
    assert "stream" not in endpoint.streams[0]
    assert endpoint.calls == []


async def test_stream_yields_reasoning_and_tool_argument_deltas():
    final = message([tool_use_block("toolu_1", "lookup_order")], stop_reason="tool_use")
    endpoint = StubMessages(
        events=[
            thinking_event("Check the order."),
            thinking_event(""),  # display "omitted" streams empty thinking text
            tool_use_start(1, "lookup_order"),
            input_json_event(1, '{"order_id":'),
            input_json_event(1, ' "9127412"}'),
        ],
        final=final,
    )
    model = AnthropicChatModel(StubClient(endpoint), MODEL_ID)
    events = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    assert events[:-1] == [
        ReasoningDelta("Check the order."),
        ToolCallDelta(1, name="lookup_order"),
        ToolCallDelta(1, '{"order_id":'),
        ToolCallDelta(1, ' "9127412"}'),
    ]
    assert not any(isinstance(event, TextDelta) for event in events)
    assert events[-1].message.tool_calls[0].name == "lookup_order"


async def test_generate_without_streaming_calls_create_once():
    endpoint = StubMessages(result=message([text_block("ok")]))
    model = AnthropicChatModel(StubClient(endpoint), MODEL_ID, stream=False)
    decoded = await model.generate(ModelRequest([UserMessage("hi")]))
    assert decoded.text == "ok"
    assert len(endpoint.calls) == 1
    assert "stream" not in endpoint.calls[0]
    assert endpoint.streams == []


async def test_generate_ignores_events_that_are_not_text():
    final = message([text_block("ok")])
    endpoint = StubMessages(events=[object(), text_event("ok")], final=final)
    model = AnthropicChatModel(StubClient(endpoint), MODEL_ID)
    events = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    assert [event.text for event in events[:-1]] == ["ok"]


async def test_generate_raises_when_the_stream_ends_without_a_final_message():
    endpoint = StubMessages(events=[text_event("partial")], final=None)
    model = AnthropicChatModel(StubClient(endpoint), MODEL_ID)
    with pytest.raises(RuntimeError):
        await model.generate(ModelRequest([UserMessage("hi")]))


async def test_generate_uses_the_beta_endpoint_when_fallbacks_are_set():
    plain = StubMessages()
    beta = StubMessages(result=message([text_block("ok")]))
    model = AnthropicChatModel(
        StubClient(plain, beta),
        MODEL_ID,
        stream=False,
        fallbacks=[{"model": "claude-opus-4-8"}],
    )
    decoded = await model.generate(ModelRequest([UserMessage("hi")]))
    assert decoded.text == "ok"
    assert plain.calls == []
    assert beta.calls[0]["betas"] == ["server-side-fallback-2026-06-01"]
