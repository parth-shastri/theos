"""Tests for the Gemini adapter: encode, decode, chunk accumulation, and generate.

Every wire shape is checked against the installed google-genai types. Fixture
payloads become real SDK objects with `GenerateContentResponse.model_validate`,
so a shape the SDK would reject fails here.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
from google import genai
from google.genai import types as genai_types
from google.genai.models import AsyncModels

from harness.events import ReasoningDelta, TextDelta, ToolCallDelta
from harness.model import ChatModel, default_estimate_tokens
from harness.providers.gemini import GeminiChatModel, accumulate_chunks
from harness.types import (
    AssistantMessage,
    ModelRequest,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    View,
    message_from_dict,
    message_to_dict,
)

MODEL_ID = "gemini-2.5-flash"
SNAPSHOT_ID = "gemini-2.5-flash-001"
SIGNATURE = b"\x00\x01\xffsig"


def adapter(model_id: str = MODEL_ID, **kwargs: Any) -> GeminiChatModel:
    """Build an adapter over a client that never makes a call."""
    client = genai.Client(api_key="test-key")
    return GeminiChatModel(client, model_id, **kwargs)


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
# Response fixtures
# --------------------------------------------------------------------------


def text_part(text: str) -> dict[str, Any]:
    return {"text": text}


def thought_part(text: str, signature: bytes | None = None) -> dict[str, Any]:
    part: dict[str, Any] = {"text": text, "thought": True}
    if signature is not None:
        part["thought_signature"] = signature
    return part


def call_part(name: str, args: dict[str, Any], call_id: str | None = None) -> dict[str, Any]:
    function_call: dict[str, Any] = {"name": name, "args": args}
    if call_id is not None:
        function_call["id"] = call_id
    return {"function_call": function_call}


def usage(prompt: int = 11, candidates: int = 7, cached: int | None = None) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "prompt_token_count": prompt,
        "candidates_token_count": candidates,
        "total_token_count": prompt + candidates,
    }
    if cached is not None:
        counts["cached_content_token_count"] = cached
    return counts


def response(
    parts: list[dict[str, Any]],
    finish_reason: str = "STOP",
    model_version: str = MODEL_ID,
    usage_metadata: dict[str, Any] | None = None,
) -> genai_types.GenerateContentResponse:
    payload: dict[str, Any] = {
        "candidates": [
            {
                "index": 0,
                "content": {"role": "model", "parts": parts},
                "finish_reason": finish_reason,
            }
        ],
        "model_version": model_version,
        "response_id": "resp_1",
        "usage_metadata": usage() if usage_metadata is None else usage_metadata,
    }
    return genai_types.GenerateContentResponse.model_validate(payload)


def chunk(
    parts: list[dict[str, Any]] | None = None,
    finish_reason: str | None = None,
    usage_metadata: dict[str, Any] | None = None,
    model_version: str = MODEL_ID,
) -> dict[str, Any]:
    """One streamed chunk as the dict `generate` collects."""
    candidate: dict[str, Any] = {"index": 0}
    if parts is not None:
        candidate["content"] = {"role": "model", "parts": parts}
    if finish_reason is not None:
        candidate["finish_reason"] = finish_reason
    payload: dict[str, Any] = {"candidates": [candidate], "model_version": model_version}
    if usage_metadata is not None:
        payload["usage_metadata"] = usage_metadata
    return payload


def two_candidate_chunk(
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    """One streamed chunk carrying two candidates, as `candidate_count` produces."""
    candidates = []
    for index, parts in enumerate((first, second)):
        candidate: dict[str, Any] = {
            "index": index,
            "content": {"role": "model", "parts": parts},
        }
        if finish_reason is not None:
            candidate["finish_reason"] = finish_reason
        candidates.append(candidate)
    return {"candidates": candidates, "model_version": MODEL_ID}


# --------------------------------------------------------------------------
# Stub client for generate
# --------------------------------------------------------------------------


class StubModels:
    """Enough of `client.aio.models` for `generate` and nothing more."""

    def __init__(
        self,
        result: genai_types.GenerateContentResponse | None = None,
        chunks: list[genai_types.GenerateContentResponse] | None = None,
    ) -> None:
        self.result = result
        self.chunks = chunks or []
        self.calls: list[dict[str, Any]] = []
        self.streams: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.result

    async def generate_content_stream(self, **kwargs: Any) -> Any:
        self.streams.append(kwargs)

        async def iterator():
            for item in self.chunks:
                yield item

        return iterator()


class StubAio:
    def __init__(self, models: StubModels) -> None:
        self.models = models


class StubClient:
    def __init__(self, models: StubModels) -> None:
        self.aio = StubAio(models)


def stream_chunk(
    parts: list[dict[str, Any]] | None = None,
    finish_reason: str | None = None,
    usage_metadata: dict[str, Any] | None = None,
) -> genai_types.GenerateContentResponse:
    return genai_types.GenerateContentResponse.model_validate(
        chunk(parts, finish_reason, usage_metadata)
    )


# --------------------------------------------------------------------------
# Protocol and capabilities
# --------------------------------------------------------------------------


async def test_adapter_contract_and_estimator_forwarding():
    model = adapter()
    assert ChatModel not in type(model).__mro__
    assert isinstance(model, ChatModel)
    assert model.provider == "gemini"
    assert model.model_id == MODEL_ID
    caps = model.capabilities
    assert caps.tools and caps.parallel_tool_calls and caps.forced_tool_choice
    assert caps.json_schema_output and caps.vision
    request = ModelRequest([UserMessage("Evidence. " * 100)], [spec()])
    assert await model.estimate_tokens(request) == default_estimate_tokens(request)


# --------------------------------------------------------------------------
# Encode: the config
# --------------------------------------------------------------------------


def test_encode_complete_request_contract():
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}
    request = ModelRequest(
        [
            SystemMessage("You are helpful."),
            SystemMessage("Answer in one line."),
            UserMessage("Where is order 9127412?"),
        ],
        [spec(), spec("cancel_order")],
        {"json_schema": schema, "temperature": 0.25, "max_output_tokens": 64},
    )
    payload = adapter(
        thinking_config={"include_thoughts": True, "thinking_budget": 512}
    ).encode_request(request)
    assert set(payload) == {"model", "contents", "config"}
    assert payload["model"] == MODEL_ID
    assert [
        (content.role, [part.text for part in content.parts]) for content in payload["contents"]
    ] == [("user", ["Where is order 9127412?"])]
    config = payload["config"]
    assert isinstance(config, genai_types.GenerateContentConfig)
    assert config.system_instruction == "You are helpful.\n\nAnswer in one line."
    assert config.automatic_function_calling == genai_types.AutomaticFunctionCallingConfig(
        disable=True
    )
    assert len(config.tools) == 1
    declarations = config.tools[0].function_declarations
    assert [declaration.name for declaration in declarations] == ["lookup_order", "cancel_order"]
    assert declarations[0].description == "Look one order up"
    assert declarations[0].parameters.model_dump(mode="json", exclude_none=True) == {
        "type": "OBJECT",
        "properties": {"order_id": {"type": "STRING"}},
        "required": ["order_id"],
    }
    assert config.thinking_config == genai_types.ThinkingConfig(
        include_thoughts=True, thinking_budget=512
    )
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == schema
    assert config.temperature == 0.25 and config.max_output_tokens == 64
    assert set(payload) <= set(inspect.signature(AsyncModels.generate_content).parameters)
    assert set(payload) <= set(inspect.signature(AsyncModels.generate_content_stream).parameters)


def test_encode_minimal_request_omits_optional_config():
    payload = adapter().encode_request(ModelRequest([UserMessage("hi")]))
    config = payload["config"]
    assert config.system_instruction is None
    assert config.tools is None
    assert config.thinking_config is None
    assert config.response_mime_type is None
    assert config.automatic_function_calling.disable is True


def test_encode_strips_schema_keys_the_sdk_rejects():
    """`$schema`, `$defs` and `additionalProperties` have no `Schema` field."""
    parameters = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "title": "Args",
        "additionalProperties": False,
        "properties": {"order_id": {"type": "string", "const": "x"}},
        "required": ["order_id"],
    }
    request = ModelRequest([UserMessage("hi")], [ToolSpec("t", "d", parameters)])
    config = adapter().encode_request(request)["config"]
    declaration = config.tools[0].function_declarations[0]
    assert declaration.parameters.model_dump(mode="json", exclude_none=True) == {
        "type": "OBJECT",
        "title": "Args",
        "properties": {"order_id": {"type": "STRING"}},
        "required": ["order_id"],
    }


def test_encode_inlines_a_ref_into_the_schema_it_points_at():
    parameters = {
        "type": "object",
        "$defs": {
            "Address": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            }
        },
        "properties": {"to": {"$ref": "#/$defs/Address"}},
        "required": ["to"],
    }
    request = ModelRequest([UserMessage("hi")], [ToolSpec("ship", "Ship it", parameters)])
    config = adapter().encode_request(request)["config"]
    declaration = config.tools[0].function_declarations[0]
    assert declaration.parameters.model_dump(mode="json", exclude_none=True) == {
        "type": "OBJECT",
        "properties": {
            "to": {
                "type": "OBJECT",
                "properties": {"city": {"type": "STRING"}},
                "required": ["city"],
            }
        },
        "required": ["to"],
    }


def test_encode_carries_a_pydantic_tool_schema_the_sdk_accepts():
    from pydantic import BaseModel

    class Address(BaseModel):
        city: str

    class Args(BaseModel):
        order_id: str
        limit: int = 3
        ship_to: Address | None = None

    request = ModelRequest(
        [UserMessage("hi")], [ToolSpec.from_model("lookup_order", "Look it up", Args)]
    )
    config = adapter().encode_request(request)["config"]
    schema = config.tools[0].function_declarations[0].parameters
    assert set(schema.properties) == {"order_id", "limit", "ship_to"}
    assert schema.required == ["order_id"]
    # An optional nested model arrives as `anyOf` around a `$ref`, and the
    # inliner has to reach through both.
    nested = schema.properties["ship_to"].any_of[0]
    assert set(nested.properties) == {"city"}


@pytest.mark.parametrize(
    ("given", "mode"),
    [("auto", "AUTO"), ("none", "NONE"), ("any", "ANY")],
)
def test_encode_translates_the_three_tool_choice_words(given, mode):
    request = ModelRequest([UserMessage("hi")], [spec()], {"tool_choice": given})
    config = adapter().encode_request(request)["config"]
    assert config.tool_config == genai_types.ToolConfig(
        function_calling_config=genai_types.FunctionCallingConfig(mode=mode)
    )


def test_encode_translates_a_named_tool_choice_into_an_allowed_name():
    request = ModelRequest([UserMessage("hi")], [spec()], {"tool_choice": "lookup_order"})
    config = adapter().encode_request(request)["config"]
    assert config.tool_config == genai_types.ToolConfig(
        function_calling_config=genai_types.FunctionCallingConfig(
            mode="ANY", allowed_function_names=["lookup_order"]
        )
    )


# --------------------------------------------------------------------------
# Encode: contents
# --------------------------------------------------------------------------


def test_encode_assistant_message_without_provider_data():
    assistant = AssistantMessage(
        text="Looking it up.",
        tool_calls=[ToolCall(id="call_1", name="lookup_order", arguments={"order_id": "9127412"})],
    )
    contents = adapter().encode_request(ModelRequest([UserMessage("hi"), assistant]))["contents"]
    assert contents[1] == genai_types.Content(
        role="model",
        parts=[
            genai_types.Part(text="Looking it up."),
            genai_types.Part(
                function_call=genai_types.FunctionCall(
                    name="lookup_order", args={"order_id": "9127412"}
                )
            ),
        ],
    )


def test_encode_skips_the_text_part_when_an_assistant_message_has_no_text():
    assistant = AssistantMessage(
        tool_calls=[ToolCall(id="call_1", name="lookup_order", arguments={})]
    )
    contents = adapter().encode_request(ModelRequest([UserMessage("hi"), assistant]))["contents"]
    assert len(contents[1].parts) == 1
    assert contents[1].parts[0].function_call is not None


def test_encode_drops_an_assistant_turn_that_has_nothing_to_say():
    """Gemini rejects a content with no parts, so an empty turn never goes back."""
    request = ModelRequest(
        [UserMessage("hi"), AssistantMessage(stop_reason="refusal"), UserMessage("again")]
    )
    contents = adapter().encode_request(request)["contents"]
    assert [content.role for content in contents] == ["user", "user"]
    assert [content.parts[0].text for content in contents] == ["hi", "again"]


# --------------------------------------------------------------------------
# Encode: raw part replay
# --------------------------------------------------------------------------


def test_encode_replays_raw_parts_for_the_same_model():
    decoded = adapter().decode_response(
        response([thought_part("weighing", SIGNATURE), text_part("Order shipped.")])
    )
    contents = adapter().encode_request(ModelRequest([UserMessage("hi"), decoded]))["contents"]
    assert contents[1].parts[0].thought is True
    assert contents[1].parts[0].thought_signature == SIGNATURE
    assert contents[1].parts[1].text == "Order shipped."


def test_encode_replays_thought_signature_bytes_after_a_json_round_trip():
    """`message_to_dict` has to stay JSON-ready, so the bytes travel base64."""
    decoded = adapter().decode_response(
        response([thought_part("weighing", SIGNATURE), text_part("Order shipped.")])
    )
    stored = json.dumps(message_to_dict(decoded))
    restored = message_from_dict(json.loads(stored))
    contents = adapter().encode_request(ModelRequest([UserMessage("hi"), restored]))["contents"]
    assert contents[1].parts[0].thought_signature == SIGNATURE


def test_encode_rebuilds_when_provider_data_is_from_another_model():
    decoded = adapter().decode_response(
        response([thought_part("weighing", SIGNATURE), text_part("Order shipped.")])
    )
    contents = adapter("gemini-2.5-pro").encode_request(ModelRequest([UserMessage("hi"), decoded]))[
        "contents"
    ]
    assert contents[1].parts == [genai_types.Part(text="Order shipped.")]


def test_encode_rebuilds_when_provider_data_is_from_another_provider():
    assistant = AssistantMessage(
        text="Order shipped.",
        provider_data={"anthropic": {"model": MODEL_ID, "content": [{"type": "text"}]}},
    )
    contents = adapter().encode_request(ModelRequest([UserMessage("hi"), assistant]))["contents"]
    assert contents[1].parts == [genai_types.Part(text="Order shipped.")]


def test_encode_does_not_mutate_the_replayed_provider_data():
    decoded = adapter().decode_response(response([text_part("Order shipped.")]))
    before = json.dumps(decoded.provider_data, sort_keys=True)
    adapter().encode_request(ModelRequest([UserMessage("hi"), decoded]))
    assert json.dumps(decoded.provider_data, sort_keys=True) == before


def test_decode_of_a_dated_snapshot_still_replays_through_encode():
    """The requested id drives replay, so a snapshot answer keeps its thoughts."""
    decoded = adapter().decode_response(
        response([thought_part("weighing", SIGNATURE)], model_version=SNAPSHOT_ID)
    )
    data = decoded.provider_data["gemini"]
    assert data["model"] == MODEL_ID
    assert data["response_model"] == SNAPSHOT_ID
    contents = adapter().encode_request(ModelRequest([UserMessage("hi"), decoded]))["contents"]
    assert contents[1].parts[0].thought_signature == SIGNATURE


def test_encode_rebuilds_what_another_requested_id_decoded():
    decoded = adapter("gemini-2.5-pro").decode_response(
        response([thought_part("weighing", SIGNATURE), text_part("Order shipped.")])
    )
    contents = adapter().encode_request(ModelRequest([UserMessage("hi"), decoded]))["contents"]
    assert contents[1].parts == [genai_types.Part(text="Order shipped.")]


# --------------------------------------------------------------------------
# Encode: function responses
# --------------------------------------------------------------------------


def test_encode_tool_result_becomes_a_function_response_part():
    result = ToolResultMessage(call_id="call_1", name="lookup_order", content="shipped")
    contents = adapter().encode_request(ModelRequest([result]))["contents"]
    assert contents == [
        genai_types.Content(
            role="user",
            parts=[
                genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name="lookup_order", response={"result": "shipped"}
                    )
                )
            ],
        )
    ]


@pytest.mark.parametrize("status", ["denied", "failed", "unknown"])
def test_encode_reports_a_result_that_did_not_complete_as_an_error(status):
    result = ToolResultMessage(
        call_id="call_1", name="lookup_order", content="no such order", status=status
    )
    contents = adapter().encode_request(ModelRequest([result]))["contents"]
    assert contents[0].parts[0].function_response.response == {"error": "no such order"}


def test_encode_reports_a_completed_result_under_result():
    result = ToolResultMessage(call_id="call_1", name="lookup_order", content="shipped")
    contents = adapter().encode_request(ModelRequest([result]))["contents"]
    assert contents[0].parts[0].function_response.response == {"result": "shipped"}


def test_encode_folds_consecutive_tool_results_into_one_user_content():
    results = [
        ToolResultMessage(call_id="call_1", name="lookup_order", content="shipped"),
        ToolResultMessage(call_id="call_2", name="lookup_order", content="delayed"),
    ]
    contents = adapter().encode_request(ModelRequest(results))["contents"]
    assert len(contents) == 1
    assert [p.function_response.response for p in contents[0].parts] == [
        {"result": "shipped"},
        {"result": "delayed"},
    ]


def test_encode_keeps_a_user_message_out_of_the_tool_result_turn():
    messages = [
        ToolResultMessage(call_id="call_1", name="lookup_order", content="shipped"),
        UserMessage("thanks"),
        ToolResultMessage(call_id="call_2", name="lookup_order", content="delayed"),
    ]
    contents = adapter().encode_request(ModelRequest(messages))["contents"]
    assert len(contents) == 3
    assert contents[1].parts[0].text == "thanks"


def test_encode_ignores_the_view_on_a_tool_result():
    plain = ToolResultMessage(call_id="call_1", name="lookup_order", content="shipped")
    decorated = ToolResultMessage(
        call_id="call_1",
        name="lookup_order",
        content="shipped",
        view=View("order_card", {"order_id": "9127412"}),
    )
    model = adapter()
    assert model.encode_request(ModelRequest([decorated])) == model.encode_request(
        ModelRequest([plain])
    )


def test_encode_rejects_an_unknown_message():
    with pytest.raises(ValueError):
        adapter().encode_request(ModelRequest([object()]))  # type: ignore[list-item]


# --------------------------------------------------------------------------
# Decode
# --------------------------------------------------------------------------


def test_decode_text_and_stop_reason():
    decoded = adapter().decode_response(response([text_part("Order 9127412 shipped.")]))
    assert decoded.text == "Order 9127412 shipped."
    assert decoded.reasoning is None
    assert decoded.tool_calls == []
    assert decoded.stop_reason == "stop"
    data = decoded.provider_data["gemini"]
    assert data["model"] == MODEL_ID
    assert data["response_model"] == MODEL_ID
    assert data["finish_reason"] == "STOP"
    assert data["call_ids"] == {}
    assert decoded.usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 18,
    }


def test_decode_preserves_thought_text_and_cached_usage():
    decoded = adapter().decode_response(
        response(
            [thought_part("first"), thought_part("second"), text_part("done")],
            usage_metadata=usage(11, 7, cached=4),
        )
    )
    assert decoded.reasoning == "first\n\nsecond"
    assert decoded.text == "done"
    assert decoded.usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "cache_read_tokens": 4,
        "cache_write_tokens": 0,
        "total_tokens": 18,
    }


def test_provider_call_id_survives_decode_and_rebuild_with_its_result():
    decoded = adapter().decode_response(
        response([call_part("lookup_order", {"order_id": "9127412"}, "fc-9")], "STOP")
    )
    assert decoded.tool_calls == [ToolCall("fc-9", "lookup_order", {"order_id": "9127412"})]
    assert decoded.provider_data["gemini"]["call_ids"] == {"fc-9": "fc-9"}
    assert decoded.stop_reason == "tool_calls"
    result = ToolResultMessage("fc-9", "lookup_order", "shipped")
    rebuilt = adapter(model_id="another-model").encode_request(ModelRequest([decoded, result]))[
        "contents"
    ]
    assert rebuilt[0].parts[0].function_call.id == "fc-9"
    assert rebuilt[1].parts[0].function_response.id == "fc-9"


def test_missing_provider_ids_get_distinct_local_ids_without_leaking_to_wire():
    decoded = adapter().decode_response(
        response(
            [
                call_part("lookup_order", {"order_id": "1"}),
                call_part("lookup_order", {"order_id": "2"}),
            ]
        )
    )
    ids = [call.id for call in decoded.tool_calls]
    assert len(set(ids)) == 2
    assert all(call_id.startswith("call_") and len(call_id) > 10 for call_id in ids)
    assert decoded.provider_data["gemini"]["call_ids"] == dict.fromkeys(ids)
    results = [ToolResultMessage(call_id, "lookup_order", "shipped") for call_id in ids]
    rebuilt = adapter(model_id="another-model").encode_request(ModelRequest([decoded, *results]))[
        "contents"
    ]
    assert all(part.function_call.id is None for part in rebuilt[0].parts)
    assert all(part.function_response.id is None for part in rebuilt[1].parts)


def test_decoded_arguments_are_independent_of_the_raw_response():
    raw = response([call_part("lookup_order", {"order_id": "9127412"}, "fc-9")])
    decoded = adapter().decode_response(raw)
    decoded.tool_calls[0].arguments["order_id"] = "changed"
    assert raw.candidates[0].content.parts[0].function_call.args == {"order_id": "9127412"}


@pytest.mark.parametrize(
    ("raw_reason", "expected"),
    [
        ("STOP", "stop"),
        ("MAX_TOKENS", "length"),
        ("SAFETY", "refusal"),
        ("PROHIBITED_CONTENT", "refusal"),
        ("BLOCKLIST", "refusal"),
        ("RECITATION", "refusal"),
        ("MALFORMED_FUNCTION_CALL", "MALFORMED_FUNCTION_CALL"),
        ("OTHER", "OTHER"),
    ],
)
def test_decode_maps_the_finish_reason(raw_reason, expected):
    decoded = adapter().decode_response(response([text_part("x")], raw_reason))
    assert decoded.stop_reason == expected
    assert decoded.provider_data["gemini"]["finish_reason"] == raw_reason


def test_decode_without_usage_metadata():
    raw = genai_types.GenerateContentResponse.model_validate(
        {"candidates": [{"index": 0, "content": {"role": "model", "parts": [text_part("x")]}}]}
    )
    assert adapter().decode_response(raw).usage == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
    }


def test_decode_of_a_response_with_no_candidate():
    raw = genai_types.GenerateContentResponse.model_validate({"candidates": []})
    decoded = adapter().decode_response(raw)
    assert decoded.text is None
    assert decoded.tool_calls == []
    assert decoded.provider_data["gemini"]["parts"] == []


# --------------------------------------------------------------------------
# accumulate_chunks
# --------------------------------------------------------------------------


def test_accumulate_preserves_thoughts_text_late_signature_and_final_metadata():
    merged = accumulate_chunks(
        [
            chunk([thought_part("weigh")], usage_metadata=usage(1, 1)),
            chunk([thought_part("ing")]),
            chunk([thought_part("", SIGNATURE)]),
            chunk([text_part("Order ")]),
            chunk([text_part("shipped.")]),
            chunk(None, finish_reason="STOP", usage_metadata=usage(11, 7)),
        ]
    )
    parsed = genai_types.GenerateContentResponse.model_validate(merged)
    parts = parsed.candidates[0].content.parts
    assert [(part.text, part.thought) for part in parts] == [
        ("weighing", True),
        ("Order shipped.", None),
    ]
    assert parts[0].thought_signature == SIGNATURE
    assert parsed.usage_metadata.prompt_token_count == 11
    assert parsed.usage_metadata.candidates_token_count == 7
    assert parsed.candidates[0].finish_reason.name == "STOP"
    assert parsed.model_version == MODEL_ID


def test_accumulate_collects_function_call_parts():
    merged = accumulate_chunks(
        [
            chunk([text_part("Looking.")]),
            chunk([call_part("lookup_order", {"order_id": "9127412"}, "fc-9")]),
        ]
    )
    parsed = genai_types.GenerateContentResponse.model_validate(merged)
    parts = parsed.candidates[0].content.parts
    assert parts[0].text == "Looking."
    assert parts[1].function_call.name == "lookup_order"


def test_accumulate_of_no_chunks_is_an_empty_model_turn():
    parsed = genai_types.GenerateContentResponse.model_validate(accumulate_chunks([]))
    assert parsed.candidates[0].content.parts == []


def test_accumulate_reads_only_the_first_candidate():
    """`candidate_count` asks for several answers, and only the first is decoded."""
    merged = accumulate_chunks(
        [
            two_candidate_chunk([text_part("first ")], [text_part("second ")]),
            two_candidate_chunk(
                [text_part("answer."), call_part("lookup_order", {"order_id": "1"})],
                [text_part("other."), call_part("lookup_order", {"order_id": "2"})],
                finish_reason="STOP",
            ),
        ]
    )
    parsed = genai_types.GenerateContentResponse.model_validate(merged)
    assert len(parsed.candidates) == 1
    parts = parsed.candidates[0].content.parts
    assert [p.text for p in parts if p.text] == ["first answer."]
    assert [p.function_call.args for p in parts if p.function_call] == [{"order_id": "1"}]
    assert parsed.candidates[0].finish_reason.name == "STOP"


def test_accumulate_treats_a_candidate_without_an_index_as_the_first():
    merged = accumulate_chunks([{"candidates": [{"content": {"parts": [text_part("a")]}}]}])
    parsed = genai_types.GenerateContentResponse.model_validate(merged)
    assert [p.text for p in parsed.candidates[0].content.parts] == ["a"]


# --------------------------------------------------------------------------
# streaming and buffered generation
# --------------------------------------------------------------------------


async def test_stream_yields_text_deltas_and_decodes_the_merged_response():
    endpoint = StubModels(
        chunks=[
            stream_chunk([text_part("Order ")]),
            stream_chunk([text_part("shipped.")], finish_reason="STOP", usage_metadata=usage()),
        ]
    )
    model = GeminiChatModel(StubClient(endpoint), MODEL_ID)
    events = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    decoded = events[-1].message
    assert [event.text for event in events[:-1]] == ["Order ", "shipped."]
    assert decoded.text == "Order shipped."
    assert decoded.stop_reason == "stop"
    assert set(endpoint.streams[0]) == {"model", "contents", "config"}
    assert endpoint.calls == []


async def test_stream_yields_thought_text_as_reasoning_not_as_text():
    endpoint = StubModels(
        chunks=[
            stream_chunk([thought_part("weighing")]),
            stream_chunk([text_part("done")], finish_reason="STOP"),
        ]
    )
    model = GeminiChatModel(StubClient(endpoint), MODEL_ID)
    events = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    decoded = events[-1].message
    assert events[:-1] == [ReasoningDelta("weighing"), TextDelta("done")]
    assert decoded.reasoning == "weighing"


async def test_stream_yields_one_complete_delta_per_function_call():
    endpoint = StubModels(
        chunks=[
            stream_chunk(
                [
                    call_part("lookup_order", {"order_id": "1"}),
                    call_part("lookup_order", {"order_id": "2"}),
                ],
                finish_reason="STOP",
            )
        ]
    )
    model = GeminiChatModel(StubClient(endpoint), MODEL_ID)
    events = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    assert events[:-1] == [
        ToolCallDelta(0, '{"order_id": "1"}', "lookup_order"),
        ToolCallDelta(1, '{"order_id": "2"}', "lookup_order"),
    ]
    assert len(events[-1].message.tool_calls) == 2


async def test_stream_yields_only_the_first_candidate_text():
    endpoint = StubModels(
        chunks=[
            genai_types.GenerateContentResponse.model_validate(
                two_candidate_chunk([text_part("first ")], [text_part("second ")])
            ),
            genai_types.GenerateContentResponse.model_validate(
                two_candidate_chunk(
                    [text_part("answer.")], [text_part("other.")], finish_reason="STOP"
                )
            ),
        ]
    )
    model = GeminiChatModel(StubClient(endpoint), MODEL_ID)
    events = [event async for event in model.stream(ModelRequest([UserMessage("hi")]))]
    decoded = events[-1].message
    assert [event.text for event in events[:-1]] == ["first ", "answer."]
    assert decoded.text == "first answer."


async def test_generate_without_streaming_calls_generate_content_once():
    endpoint = StubModels(result=response([text_part("ok")]))
    model = GeminiChatModel(StubClient(endpoint), MODEL_ID, stream=False)
    decoded = await model.generate(ModelRequest([UserMessage("hi")]))
    assert decoded.text == "ok"
    assert len(endpoint.calls) == 1
    assert endpoint.streams == []
