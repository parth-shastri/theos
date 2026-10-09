"""Tests for the OpenAI adapter: encode, decode, chunk accumulation, and generate.

Every wire shape is checked against the installed openai types. Fixture
payloads become real SDK objects with `Response.model_validate` and
`ChatCompletion.model_validate`, so a shape the SDK would reject fails here.
"""

from __future__ import annotations

from typing import Any

import pytest
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseTextDeltaEvent,
)

from harness.events import ReasoningDelta, TextDelta, ToolCallDelta
from harness.model import ChatModel
from harness.providers.openai import OpenAIChatModel, accumulate_chunks
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

MODEL_ID = "gpt-5"


def adapter(api: str = "responses", model_id: str = MODEL_ID, **kwargs) -> OpenAIChatModel:
    """Build an adapter over a client that never makes a call."""
    client = AsyncOpenAI(api_key="test-key")
    return OpenAIChatModel(client, model_id, api=api, **kwargs)


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
# Responses API fixtures
# --------------------------------------------------------------------------


def message_item(text: str, item_id: str = "msg_1") -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def refusal_item(reason: str, item_id: str = "msg_r") -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "refusal", "refusal": reason}],
    }


def function_call_item(
    call_id: str, name: str, arguments: str, item_id: str = "fc_1"
) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
        "status": "completed",
    }


def reasoning_item(
    summaries: list[str], encrypted: str = "enc-abc", item_id: str = "rs_1"
) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": text} for text in summaries],
        "encrypted_content": encrypted,
        "status": "completed",
    }


def responses_usage(
    input_tokens: int = 11, output_tokens: int = 7, cached: int = 4
) -> dict[str, Any]:
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 3},
        "total_tokens": input_tokens + output_tokens,
    }


def response(output: list[dict[str, Any]], **extra: Any) -> Response:
    payload: dict[str, Any] = {
        "id": "resp_1",
        "created_at": 1.0,
        "model": MODEL_ID,
        "object": "response",
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "status": "completed",
    }
    payload.update(extra)
    return Response.model_validate(payload)


# --------------------------------------------------------------------------
# Chat completions fixtures
# --------------------------------------------------------------------------


def completion(
    message: dict[str, Any],
    finish_reason: str = "stop",
    usage: dict[str, Any] | None = None,
    model: str = "gpt-4.1-mini",
) -> ChatCompletion:
    payload: dict[str, Any] = {
        "id": "chatcmpl_1",
        "created": 1,
        "model": model,
        "object": "chat.completion",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
    }
    if usage is not None:
        payload["usage"] = usage
    return ChatCompletion.model_validate(payload)


def chat_usage(prompt: int = 21, completion_tokens: int = 5, cached: int = 8) -> dict[str, Any]:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt + completion_tokens,
        "prompt_tokens_details": {"cached_tokens": cached},
    }


# --------------------------------------------------------------------------
# Stub clients for generate
# --------------------------------------------------------------------------


class StubStream:
    """An async iterable that yields prepared SDK stream events."""

    def __init__(self, events: list[Any]) -> None:
        self.events = events

    async def __aiter__(self):
        for event in self.events:
            yield event


class StubEndpoint:
    def __init__(self, result: Any, stream_events: list[Any] | None = None) -> None:
        self.result = result
        self.stream_events = stream_events or []
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return StubStream(self.stream_events)
        return self.result


class StubClient:
    """Enough of AsyncOpenAI for `generate` and nothing more."""

    def __init__(self, endpoint: StubEndpoint) -> None:
        self.responses = endpoint
        self.chat = type("Chat", (), {"completions": endpoint})()


# --------------------------------------------------------------------------
# Protocol and capabilities
# --------------------------------------------------------------------------


def test_adapter_satisfies_chat_model_without_inheriting():
    model = adapter()
    assert ChatModel not in type(model).__mro__
    assert isinstance(model, ChatModel)
    assert model.provider == "openai"
    assert model.model_id == MODEL_ID


def test_capabilities_report_tools_json_schema_and_vision():
    caps = adapter().capabilities
    assert caps.tools and caps.parallel_tool_calls and caps.forced_tool_choice
    assert caps.json_schema_output and caps.vision


async def test_estimate_tokens_uses_the_shared_heuristic():
    request = ModelRequest([UserMessage("Where is order 9127412?")], [spec()])
    assert await adapter().estimate_tokens(request) > 0


# --------------------------------------------------------------------------
# Responses API: encode
# --------------------------------------------------------------------------


def test_responses_encode_joins_system_messages_into_instructions():
    request = ModelRequest(
        [
            SystemMessage("You are helpful."),
            SystemMessage("Answer in one line."),
            UserMessage("Where is order 9127412?"),
        ]
    )
    payload = adapter().encode_request(request)
    assert payload["model"] == MODEL_ID
    assert payload["instructions"] == "You are helpful.\n\nAnswer in one line."
    assert payload["input"] == [{"role": "user", "content": "Where is order 9127412?"}]
    assert payload["store"] is False
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert payload["parallel_tool_calls"] is True
    assert "stream" not in payload
    assert "previous_response_id" not in payload


def test_responses_encode_omits_instructions_when_no_system_message():
    payload = adapter().encode_request(ModelRequest([UserMessage("hi")]))
    assert "instructions" not in payload


def test_responses_encode_tools_use_the_flat_function_shape():
    payload = adapter().encode_request(ModelRequest([UserMessage("hi")], [spec()]))
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "lookup_order",
            "description": "Look one order up",
            "parameters": spec().parameters,
            "strict": False,
        }
    ]


def test_responses_encode_omits_tools_when_there_are_none():
    assert "tools" not in adapter().encode_request(ModelRequest([UserMessage("hi")]))


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("auto", "auto"),
        ("none", "none"),
        ("any", "required"),
        ("lookup_order", {"type": "function", "name": "lookup_order"}),
    ],
)
def test_responses_encode_translates_tool_choice(given, expected):
    request = ModelRequest([UserMessage("hi")], [spec()], {"tool_choice": given})
    assert adapter().encode_request(request)["tool_choice"] == expected


def test_responses_encode_translates_json_schema():
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    request = ModelRequest([UserMessage("hi")], options={"json_schema": schema})
    payload = adapter().encode_request(request)
    assert payload["text"] == {
        "format": {
            "type": "json_schema",
            "name": "output",
            "schema": schema,
            "strict": False,
        }
    }
    assert "json_schema" not in payload


def test_responses_encode_passes_other_options_through():
    options = {"temperature": 0.2, "max_output_tokens": 64}
    request = ModelRequest([UserMessage("hi")], options=options)
    payload = adapter().encode_request(request)
    assert payload["temperature"] == 0.2
    assert payload["max_output_tokens"] == 64


def test_responses_encode_assistant_message_without_provider_data():
    history = [
        UserMessage("Where is order 9127412?"),
        AssistantMessage(
            text="Let me look.",
            tool_calls=[ToolCall("call_1", "lookup_order", {"order_id": "9127412"})],
        ),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["input"] == [
        {"role": "user", "content": "Where is order 9127412?"},
        {"role": "assistant", "content": "Let me look."},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup_order",
            "arguments": '{"order_id": "9127412"}',
        },
    ]


def test_responses_encode_skips_the_assistant_text_item_when_there_is_no_text():
    history = [
        UserMessage("hi"),
        AssistantMessage(tool_calls=[ToolCall("call_1", "lookup_order", {})]),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["input"][1]["type"] == "function_call"
    assert len(payload["input"]) == 2


def test_responses_encode_replays_raw_output_for_the_same_model():
    raw = [
        reasoning_item(["Checking the order"]),
        function_call_item("call_1", "lookup_order", "{}"),
    ]
    history = [
        UserMessage("hi"),
        AssistantMessage(
            text="ignored on replay",
            tool_calls=[ToolCall("call_1", "lookup_order", {})],
            provider_data={"openai": {"model": MODEL_ID, "output": raw}},
        ),
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["input"][1:] == raw
    assert payload["input"][1]["encrypted_content"] == "enc-abc"


def test_responses_encode_rebuilds_when_provider_data_is_from_another_model():
    raw = [reasoning_item(["Checking the order"])]
    history = [
        AssistantMessage(
            text="Hello",
            provider_data={"openai": {"model": "gpt-4.1-mini", "output": raw}},
        )
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["input"] == [{"role": "assistant", "content": "Hello"}]


def test_responses_encode_rebuilds_when_provider_data_is_from_another_provider():
    history = [
        AssistantMessage(
            text="Hello",
            provider_data={"anthropic": {"model": MODEL_ID, "content": [{"type": "thinking"}]}},
        )
    ]
    payload = adapter().encode_request(ModelRequest(history))
    assert payload["input"] == [{"role": "assistant", "content": "Hello"}]


def test_responses_encode_does_not_mutate_the_replayed_provider_data():
    raw = [function_call_item("call_1", "lookup_order", "{}")]
    message = AssistantMessage(provider_data={"openai": {"model": MODEL_ID, "output": raw}})
    payload = adapter().encode_request(ModelRequest([message]))
    payload["input"][0]["name"] = "mutated"
    assert message.provider_data["openai"]["output"][0]["name"] == "lookup_order"


def test_responses_encode_tool_result_as_function_call_output():
    result = ToolResultMessage(
        call_id="call_1", name="lookup_order", content='{"status": "shipped"}'
    )
    payload = adapter().encode_request(ModelRequest([result]))
    assert payload["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"status": "shipped"}',
        }
    ]


def test_responses_encode_ignores_the_view_and_status_on_a_tool_result():
    plain = ToolResultMessage(call_id="call_1", name="lookup_order", content="shipped")
    decorated = ToolResultMessage(
        call_id="call_1",
        name="lookup_order",
        content="shipped",
        status="failed",
        view=View("order_card", {"order_id": "9127412"}),
    )
    model = adapter()
    assert model.encode_request(ModelRequest([decorated])) == model.encode_request(
        ModelRequest([plain])
    )


# --------------------------------------------------------------------------
# Responses API: decode
# --------------------------------------------------------------------------


def test_responses_decode_text_and_stop_reason():
    message = adapter().decode_response(response([message_item("Order 9127412 shipped.")]))
    assert message.text == "Order 9127412 shipped."
    assert message.reasoning is None
    assert message.tool_calls == []
    assert message.stop_reason == "stop"
    assert message.provider_data["openai"]["model"] == MODEL_ID
    assert message.provider_data["openai"]["status"] == "completed"


def test_responses_decode_parallel_tool_calls():
    raw = response(
        [
            message_item("Working on it."),
            function_call_item("call_1", "lookup_order", '{"order_id": "1"}', item_id="fc_1"),
            function_call_item("call_2", "send_email", '{"to": "a@b.com"}', item_id="fc_2"),
        ]
    )
    message = adapter().decode_response(raw)
    assert message.stop_reason == "tool_calls"
    assert message.tool_calls == [
        ToolCall("call_1", "lookup_order", {"order_id": "1"}),
        ToolCall("call_2", "send_email", {"to": "a@b.com"}),
    ]
    assert message.text == "Working on it."


def test_responses_decode_invalid_argument_json():
    raw = response([function_call_item("call_1", "lookup_order", '{"order_id": ')])
    message = adapter().decode_response(raw)
    assert message.tool_calls == [ToolCall("call_1", "lookup_order", {})]
    assert message.provider_data["openai"]["invalid_arguments"] == {
        "call_1": '{"order_id": '
    }


def test_responses_decode_reasoning_summary_and_keeps_encrypted_content():
    raw = response(
        [
            reasoning_item(["Look the order up first.", "Then answer."]),
            message_item("Shipped."),
        ]
    )
    message = adapter().decode_response(raw)
    assert message.reasoning == "Look the order up first.\n\nThen answer."
    replayed = message.provider_data["openai"]["output"]
    assert replayed[0]["encrypted_content"] == "enc-abc"
    assert replayed[0]["type"] == "reasoning"


def test_responses_decode_leaves_reasoning_none_without_a_summary():
    raw = response([reasoning_item([]), message_item("Shipped.")])
    assert adapter().decode_response(raw).reasoning is None


def test_responses_decode_usage_with_cached_tokens():
    raw = response([message_item("ok")], usage=responses_usage())
    assert adapter().decode_response(raw).usage == {"input_tokens": 11, "output_tokens": 7, "cache_read_tokens": 4, "cache_write_tokens": 0, "total_tokens": 18}


def test_responses_decode_without_usage_returns_zero_counters():
    assert adapter().decode_response(response([message_item("ok")])).usage == {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "total_tokens": 0}


def test_responses_decode_maps_max_output_tokens_to_length():
    raw = response(
        [message_item("A long ans")],
        status="incomplete",
        incomplete_details={"reason": "max_output_tokens"},
    )
    assert adapter().decode_response(raw).stop_reason == "length"


def test_responses_decode_maps_a_refusal_part_to_refusal():
    raw = response([refusal_item("I cannot help with that.")])
    message = adapter().decode_response(raw)
    assert message.stop_reason == "refusal"
    assert message.text is None


def test_responses_decode_output_replays_through_encode_unchanged():
    raw = response(
        [reasoning_item(["Thinking"]), function_call_item("call_1", "lookup_order", "{}")]
    )
    model = adapter()
    message = model.decode_response(raw)
    payload = model.encode_request(ModelRequest([UserMessage("hi"), message]))
    assert payload["input"][1:] == [item.model_dump(exclude_none=True) for item in raw.output]


def test_responses_decode_keeps_the_requested_id_and_the_snapshot_separately():
    raw = response([message_item("ok")], model="gpt-5-2025-08-07")
    data = adapter().decode_response(raw).provider_data["openai"]
    assert data["model"] == MODEL_ID
    assert data["response_model"] == "gpt-5-2025-08-07"


def test_responses_decode_of_a_dated_snapshot_still_replays_through_encode():
    raw = response(
        [reasoning_item(["Thinking"]), function_call_item("call_1", "lookup_order", "{}")],
        model="gpt-5-2025-08-07",
    )
    model = adapter()
    message = model.decode_response(raw)
    payload = model.encode_request(ModelRequest([UserMessage("hi"), message]))
    assert payload["input"][1:] == [item.model_dump(exclude_none=True) for item in raw.output]


def test_responses_encode_rebuilds_what_another_requested_id_decoded():
    raw = response(
        [reasoning_item(["Thinking"]), function_call_item("call_1", "lookup_order", "{}")],
        model="gpt-5-2025-08-07",
    )
    message = adapter(model_id="gpt-4.1-mini").decode_response(raw)
    payload = adapter().encode_request(ModelRequest([message]))
    assert payload["input"] == [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup_order",
            "arguments": "{}",
        }
    ]


# --------------------------------------------------------------------------
# Chat completions: encode
# --------------------------------------------------------------------------


def test_chat_encode_messages_and_tools():
    request = ModelRequest(
        [SystemMessage("You are helpful."), UserMessage("Where is order 9127412?")],
        [spec()],
    )
    payload = adapter("chat_completions").encode_request(request)
    assert payload["model"] == MODEL_ID
    assert payload["messages"] == [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Where is order 9127412?"},
    ]
    assert payload["tools"] == [spec().to_openai()]
    assert "stream" not in payload
    assert "instructions" not in payload


def test_chat_encode_assistant_tool_calls():
    history = [
        AssistantMessage(
            text="Let me look.",
            tool_calls=[ToolCall("call_1", "lookup_order", {"order_id": "9127412"})],
        )
    ]
    payload = adapter("chat_completions").encode_request(ModelRequest(history))
    assert payload["messages"] == [
        {
            "role": "assistant",
            "content": "Let me look.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "lookup_order",
                        "arguments": '{"order_id": "9127412"}',
                    },
                }
            ],
        }
    ]


def test_chat_encode_uses_empty_content_when_an_assistant_message_has_no_text():
    history = [AssistantMessage(tool_calls=[ToolCall("call_1", "lookup_order", {})])]
    payload = adapter("chat_completions").encode_request(ModelRequest(history))
    assert payload["messages"][0]["content"] == ""


def test_chat_encode_tool_result_uses_the_tool_role():
    result = ToolResultMessage(call_id="call_1", name="lookup_order", content="shipped")
    payload = adapter("chat_completions").encode_request(ModelRequest([result]))
    assert payload["messages"] == [
        {"role": "tool", "tool_call_id": "call_1", "content": "shipped"}
    ]


def test_chat_encode_ignores_the_view_and_status_on_a_tool_result():
    plain = ToolResultMessage(call_id="call_1", name="lookup_order", content="shipped")
    decorated = ToolResultMessage(
        call_id="call_1",
        name="lookup_order",
        content="shipped",
        status="denied",
        view=View("order_card", {"order_id": "9127412"}),
    )
    model = adapter("chat_completions")
    assert model.encode_request(ModelRequest([decorated])) == model.encode_request(
        ModelRequest([plain])
    )


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("auto", "auto"),
        ("none", "none"),
        ("any", "required"),
        ("lookup_order", {"type": "function", "function": {"name": "lookup_order"}}),
    ],
)
def test_chat_encode_translates_tool_choice(given, expected):
    request = ModelRequest([UserMessage("hi")], [spec()], {"tool_choice": given})
    assert adapter("chat_completions").encode_request(request)["tool_choice"] == expected


def test_chat_encode_translates_json_schema():
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    request = ModelRequest([UserMessage("hi")], options={"json_schema": schema})
    payload = adapter("chat_completions").encode_request(request)
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "output", "schema": schema},
    }
    assert "json_schema" not in payload


def test_chat_encode_passes_other_options_through():
    request = ModelRequest([UserMessage("hi")], options={"temperature": 0.1})
    assert adapter("chat_completions").encode_request(request)["temperature"] == 0.1


def test_chat_encode_replays_nothing_from_provider_data():
    history = [
        AssistantMessage(
            text="Hello",
            provider_data={"openai": {"model": MODEL_ID, "output": [reasoning_item(["x"])]}},
        )
    ]
    payload = adapter("chat_completions").encode_request(ModelRequest(history))
    assert payload["messages"] == [{"role": "assistant", "content": "Hello"}]


# --------------------------------------------------------------------------
# Chat completions: decode
# --------------------------------------------------------------------------


def test_chat_decode_text_and_usage():
    raw = completion({"role": "assistant", "content": "Shipped."}, usage=chat_usage())
    message = adapter("chat_completions").decode_response(raw)
    assert message.text == "Shipped."
    assert message.stop_reason == "stop"
    assert message.usage == {"input_tokens": 21, "output_tokens": 5, "cache_read_tokens": 8, "cache_write_tokens": 0, "total_tokens": 26}
    assert message.provider_data["openai"]["finish_reason"] == "stop"
    assert message.provider_data["openai"]["model"] == MODEL_ID
    assert message.provider_data["openai"]["response_model"] == "gpt-4.1-mini"
    assert "output" not in message.provider_data["openai"]


def test_chat_decode_parallel_tool_calls():
    raw = completion(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup_order", "arguments": '{"order_id": "1"}'},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "send_email", "arguments": '{"to": "a@b.com"}'},
                },
            ],
        },
        finish_reason="tool_calls",
    )
    message = adapter("chat_completions").decode_response(raw)
    assert message.text is None
    assert message.stop_reason == "tool_calls"
    assert message.tool_calls == [
        ToolCall("call_1", "lookup_order", {"order_id": "1"}),
        ToolCall("call_2", "send_email", {"to": "a@b.com"}),
    ]


def test_chat_decode_invalid_argument_json():
    raw = completion(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup_order", "arguments": "not json"},
                }
            ],
        },
        finish_reason="tool_calls",
    )
    message = adapter("chat_completions").decode_response(raw)
    assert message.tool_calls == [ToolCall("call_1", "lookup_order", {})]
    assert message.provider_data["openai"]["invalid_arguments"] == {"call_1": "not json"}


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        ("stop", "stop"),
        ("tool_calls", "tool_calls"),
        ("length", "length"),
        ("content_filter", "refusal"),
    ],
)
def test_chat_decode_maps_finish_reason(finish_reason, expected):
    raw = completion({"role": "assistant", "content": "x"}, finish_reason=finish_reason)
    assert adapter("chat_completions").decode_response(raw).stop_reason == expected


def test_chat_decode_maps_a_refusal_message_to_refusal():
    raw = completion({"role": "assistant", "content": None, "refusal": "I cannot help."})
    assert adapter("chat_completions").decode_response(raw).stop_reason == "refusal"


def test_chat_decode_without_usage_returns_zero_counters():
    raw = completion({"role": "assistant", "content": "ok"})
    assert adapter("chat_completions").decode_response(raw).usage == {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "total_tokens": 0}


# --------------------------------------------------------------------------
# accumulate_chunks
# --------------------------------------------------------------------------


def chunk(
    delta: dict[str, Any] | None = None,
    finish_reason: str | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "chatcmpl_1",
        "created": 1,
        "model": "gpt-4.1-mini",
        "object": "chat.completion.chunk",
        "choices": [],
    }
    if delta is not None or finish_reason is not None:
        payload["choices"] = [
            {"index": 0, "delta": delta or {}, "finish_reason": finish_reason}
        ]
    if usage is not None:
        payload["usage"] = usage
    return payload


def test_accumulate_chunks_concatenates_content_and_takes_usage_from_the_last_chunk():
    chunks = [
        chunk({"role": "assistant", "content": "Order "}),
        chunk({"content": "shipped."}),
        chunk({}, finish_reason="stop"),
        chunk(usage=chat_usage()),
    ]
    merged = accumulate_chunks(chunks)
    assert merged["choices"][0]["message"]["content"] == "Order shipped."
    assert merged["choices"][0]["finish_reason"] == "stop"
    assert merged["usage"] == chat_usage()
    assert ChatCompletion.model_validate(merged).choices[0].message.content == "Order shipped."


def test_accumulate_chunks_merges_tool_calls_by_index():
    chunks = [
        chunk(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup_order", "arguments": '{"order'},
                    }
                ],
            }
        ),
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 1,
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "send_email", "arguments": "{}"},
                    }
                ]
            }
        ),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '_id": "1"}'}}]}),
        chunk({}, finish_reason="tool_calls"),
    ]
    merged = accumulate_chunks(chunks)
    decoded = adapter("chat_completions").decode_response(ChatCompletion.model_validate(merged))
    assert decoded.tool_calls == [
        ToolCall("call_1", "lookup_order", {"order_id": "1"}),
        ToolCall("call_2", "send_email", {}),
    ]
    assert decoded.stop_reason == "tool_calls"


def test_accumulate_chunks_keeps_content_none_when_only_tool_calls_stream():
    chunks = [
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup_order", "arguments": "{}"},
                    }
                ]
            }
        ),
        chunk({}, finish_reason="tool_calls"),
    ]
    merged = accumulate_chunks(chunks)
    assert merged["choices"][0]["message"]["content"] is None


def test_accumulate_chunks_accepts_sdk_chunk_objects():
    chunks = [
        ChatCompletionChunk.model_validate(chunk({"role": "assistant", "content": "hi"})),
        ChatCompletionChunk.model_validate(chunk({}, finish_reason="stop")),
    ]
    merged = accumulate_chunks([c.model_dump() for c in chunks])
    assert merged["choices"][0]["message"]["content"] == "hi"


# --------------------------------------------------------------------------
# streaming and buffered generation
# --------------------------------------------------------------------------


def text_delta_event(text: str, sequence: int) -> ResponseTextDeltaEvent:
    return ResponseTextDeltaEvent.model_validate(
        {
            "type": "response.output_text.delta",
            "logprobs": [],
            "content_index": 0,
            "delta": text,
            "item_id": "msg_1",
            "output_index": 0,
            "sequence_number": sequence,
        }
    )


def reasoning_delta_event(text: str, sequence: int) -> ResponseReasoningSummaryTextDeltaEvent:
    return ResponseReasoningSummaryTextDeltaEvent.model_validate(
        {
            "type": "response.reasoning_summary_text.delta",
            "delta": text,
            "item_id": "rs_1",
            "output_index": 0,
            "sequence_number": sequence,
            "summary_index": 0,
        }
    )


def function_call_added_event(name: str, sequence: int) -> ResponseOutputItemAddedEvent:
    return ResponseOutputItemAddedEvent.model_validate(
        {
            "type": "response.output_item.added",
            "item": function_call_item("call_1", name, "") | {"status": "in_progress"},
            "output_index": 1,
            "sequence_number": sequence,
        }
    )


def arguments_delta_event(text: str, sequence: int) -> ResponseFunctionCallArgumentsDeltaEvent:
    return ResponseFunctionCallArgumentsDeltaEvent.model_validate(
        {
            "type": "response.function_call_arguments.delta",
            "delta": text,
            "item_id": "fc_1",
            "output_index": 1,
            "sequence_number": sequence,
        }
    )


async def test_stream_yields_reasoning_and_tool_argument_deltas():
    completed = ResponseCompletedEvent.model_validate(
        {
            "type": "response.completed",
            "sequence_number": 5,
            "response": response(
                [function_call_item("call_1", "lookup_order", '{"order_id": "9127412"}')]
            ).model_dump(),
        }
    )
    endpoint = StubEndpoint(
        result=None,
        stream_events=[
            reasoning_delta_event("Check the order.", 1),
            function_call_added_event("lookup_order", 2),
            arguments_delta_event('{"order_id":', 3),
            arguments_delta_event(' "9127412"}', 4),
            completed,
        ],
    )
    model = OpenAIChatModel(StubClient(endpoint), MODEL_ID)
    events = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    assert events[:-1] == [
        ReasoningDelta("Check the order."),
        ToolCallDelta(1, name="lookup_order"),
        ToolCallDelta(1, '{"order_id":'),
        ToolCallDelta(1, ' "9127412"}'),
    ]
    assert not any(isinstance(event, TextDelta) for event in events)
    assert events[-1].message.tool_calls[0].arguments == {"order_id": "9127412"}


async def test_stream_yields_responses_deltas_and_decodes_the_completed_event():
    completed = ResponseCompletedEvent.model_validate(
        {
            "type": "response.completed",
            "sequence_number": 3,
            "response": response([message_item("Order shipped.")]).model_dump(),
        }
    )
    endpoint = StubEndpoint(
        result=None,
        stream_events=[text_delta_event("Order ", 1), text_delta_event("shipped.", 2), completed],
    )
    model = OpenAIChatModel(StubClient(endpoint), MODEL_ID)
    events = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    message = events[-1].message
    assert [event.text for event in events[:-1]] == ["Order ", "shipped."]
    assert message.text == "Order shipped."
    assert endpoint.calls[0]["stream"] is True


async def test_generate_without_streaming_calls_create_once():
    endpoint = StubEndpoint(result=response([message_item("ok")]))
    model = OpenAIChatModel(StubClient(endpoint), MODEL_ID, stream=False)
    message = await model.generate(ModelRequest([UserMessage("hi")]))
    assert message.text == "ok"
    assert len(endpoint.calls) == 1
    assert "stream" not in endpoint.calls[0]


async def test_generate_raises_when_the_responses_stream_never_completes():
    endpoint = StubEndpoint(result=None, stream_events=[text_delta_event("partial", 1)])
    model = OpenAIChatModel(StubClient(endpoint), MODEL_ID)
    with pytest.raises(RuntimeError):
        await model.generate(ModelRequest([UserMessage("hi")]))


async def test_generate_returns_an_incomplete_response_as_a_length_stop():
    incomplete = ResponseIncompleteEvent.model_validate(
        {
            "type": "response.incomplete",
            "sequence_number": 2,
            "response": response(
                [message_item("A long half ans")],
                status="incomplete",
                incomplete_details={"reason": "max_output_tokens"},
            ).model_dump(),
        }
    )
    endpoint = StubEndpoint(
        result=None, stream_events=[text_delta_event("A long half ans", 1), incomplete]
    )
    model = OpenAIChatModel(StubClient(endpoint), MODEL_ID)
    events = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    message = events[-1].message
    assert [event.text for event in events[:-1]] == ["A long half ans"]
    assert message.text == "A long half ans"
    assert message.stop_reason == "length"


async def test_generate_raises_with_the_error_when_the_response_fails():
    failed = ResponseFailedEvent.model_validate(
        {
            "type": "response.failed",
            "sequence_number": 2,
            "response": response(
                [],
                status="failed",
                error={"code": "server_error", "message": "upstream boom"},
            ).model_dump(),
        }
    )
    endpoint = StubEndpoint(result=None, stream_events=[failed])
    model = OpenAIChatModel(StubClient(endpoint), MODEL_ID)
    with pytest.raises(RuntimeError, match="server_error"):
        await model.generate(ModelRequest([UserMessage("hi")]))
    with pytest.raises(RuntimeError, match="upstream boom"):
        await model.generate(ModelRequest([UserMessage("hi")]))


async def test_stream_accumulates_a_chat_completions_stream():
    events = [
        ChatCompletionChunk.model_validate(chunk({"role": "assistant", "content": "Order "})),
        ChatCompletionChunk.model_validate(chunk({"content": "shipped."})),
        ChatCompletionChunk.model_validate(chunk({}, finish_reason="stop")),
        ChatCompletionChunk.model_validate(chunk(usage=chat_usage())),
    ]
    endpoint = StubEndpoint(result=None, stream_events=events)
    model = OpenAIChatModel(StubClient(endpoint), MODEL_ID, api="chat_completions")
    streamed = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    message = streamed[-1].message
    assert [event.text for event in streamed[:-1]] == ["Order ", "shipped."]
    assert message.text == "Order shipped."
    assert message.usage["input_tokens"] == 21
    assert endpoint.calls[0]["stream_options"] == {"include_usage": True}


async def test_chat_stream_yields_a_tool_call_delta_per_fragment():
    events = [
        ChatCompletionChunk.model_validate(
            chunk(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "lookup_order", "arguments": ""},
                        }
                    ],
                }
            )
        ),
        ChatCompletionChunk.model_validate(
            chunk(
                {
                    "tool_calls": [
                        {"index": 0, "function": {"arguments": '{"order_id": "9127412"}'}}
                    ]
                }
            )
        ),
        ChatCompletionChunk.model_validate(chunk({}, finish_reason="tool_calls")),
    ]
    endpoint = StubEndpoint(result=None, stream_events=events)
    model = OpenAIChatModel(StubClient(endpoint), MODEL_ID, api="chat_completions")
    streamed = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    assert streamed[:-1] == [
        ToolCallDelta(0, name="lookup_order"),
        ToolCallDelta(0, '{"order_id": "9127412"}'),
    ]
    assert streamed[-1].message.tool_calls[0].arguments == {"order_id": "9127412"}


async def test_generate_keeps_caller_stream_options():
    events = [ChatCompletionChunk.model_validate(chunk({}, finish_reason="stop"))]
    endpoint = StubEndpoint(result=None, stream_events=events)
    model = OpenAIChatModel(StubClient(endpoint), MODEL_ID, api="chat_completions")
    request = ModelRequest([UserMessage("hi")], options={"stream_options": {}})
    await model.generate(request)
    assert endpoint.calls[0]["stream_options"] == {}
