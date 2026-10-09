"""Cross-provider replay: a history from one adapter encodes through the others.

The replay rule says an adapter replays its own raw output only when its key is
present and the model matches, and rebuilds from `text` and `tool_calls`
otherwise. These tests move a real decoded history across providers in both
directions and check that nothing provider-shaped leaks into the new request.
"""

from __future__ import annotations

import json
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message
from google import genai
from openai import AsyncOpenAI
from openai.types.responses import Response

from harness.providers.anthropic import AnthropicChatModel
from harness.providers.gemini import GeminiChatModel
from harness.providers.openai import OpenAIChatModel
from harness.types import (
    AssistantMessage,
    ModelRequest,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
)

CLAUDE_ID = "claude-opus-5"
GPT_ID = "gpt-5"
GEMINI_ID = "gemini-2.5-flash"

SPEC = ToolSpec(
    name="lookup_order",
    description="Look one order up",
    parameters={
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
        "required": ["order_id"],
    },
)


def anthropic_model() -> AnthropicChatModel:
    return AnthropicChatModel(AsyncAnthropic(api_key="test-key"), CLAUDE_ID)


def openai_model(api: str = "responses") -> OpenAIChatModel:
    return OpenAIChatModel(AsyncOpenAI(api_key="test-key"), GPT_ID, api=api)


def gemini_model() -> GeminiChatModel:
    return GeminiChatModel(genai.Client(api_key="test-key"), GEMINI_ID)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def anthropic_message() -> Message:
    """One Claude turn with a thinking block and a tool use block."""
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-20260401",
            "content": [
                {"type": "thinking", "thinking": "The order id is 9127412.", "signature": "sig-1"},
                {"type": "text", "text": "Looking that up."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "lookup_order",
                    "input": {"order_id": "9127412"},
                },
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }
    )


def openai_response() -> Response:
    """One Responses turn with a reasoning item and a function call."""
    return Response.model_validate(
        {
            "id": "resp_1",
            "created_at": 1.0,
            "model": "gpt-5-2025-08-07",
            "object": "response",
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "status": "completed",
            "output": [
                {
                    "id": "rs_1",
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "Look the order up."}],
                    "encrypted_content": "enc-abc",
                    "status": "completed",
                },
                {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "Looking that up.", "annotations": []}
                    ],
                },
                {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "lookup_order",
                    "arguments": '{"order_id": "9127412"}',
                    "status": "completed",
                },
            ],
        }
    )


def history(assistant: AssistantMessage, call_id: str) -> list[Any]:
    return [
        UserMessage("Where is order 9127412?"),
        assistant,
        ToolResultMessage(call_id=call_id, name="lookup_order", content='{"status": "shipped"}'),
    ]


# --------------------------------------------------------------------------
# Anthropic history replays through OpenAI and Gemini
# --------------------------------------------------------------------------


def test_an_anthropic_turn_decodes_into_the_common_fields():
    decoded = anthropic_model().decode_response(anthropic_message())
    assert decoded.text == "Looking that up."
    assert decoded.reasoning == "The order id is 9127412."
    assert [call.name for call in decoded.tool_calls] == ["lookup_order"]
    assert decoded.provider_data["anthropic"]["content"][0]["type"] == "thinking"


def test_an_anthropic_history_replays_through_the_responses_api():
    decoded = anthropic_model().decode_response(anthropic_message())
    request = ModelRequest(history(decoded, "toolu_1"), [SPEC])
    payload = openai_model().encode_request(request)
    assert payload["input"] == [
        {"role": "user", "content": "Where is order 9127412?"},
        {"role": "assistant", "content": "Looking that up."},
        {
            "type": "function_call",
            "call_id": "toolu_1",
            "name": "lookup_order",
            "arguments": '{"order_id": "9127412"}',
        },
        {
            "type": "function_call_output",
            "call_id": "toolu_1",
            "output": '{"status": "shipped"}',
        },
    ]
    assert "thinking" not in json.dumps(payload)


def test_an_anthropic_history_replays_through_chat_completions():
    decoded = anthropic_model().decode_response(anthropic_message())
    request = ModelRequest(history(decoded, "toolu_1"), [SPEC])
    payload = openai_model("chat_completions").encode_request(request)
    assistant = payload["messages"][1]
    assert assistant["content"] == "Looking that up."
    assert assistant["tool_calls"][0]["function"]["name"] == "lookup_order"
    assert payload["messages"][2]["role"] == "tool"
    assert "thinking" not in json.dumps(payload)


def test_an_anthropic_history_replays_through_gemini():
    decoded = anthropic_model().decode_response(anthropic_message())
    request = ModelRequest(history(decoded, "toolu_1"), [SPEC])
    payload = gemini_model().encode_request(request)
    contents = payload["contents"]
    assert [content.role for content in contents] == ["user", "model", "user"]
    assert contents[1].parts[0].text == "Looking that up."
    assert contents[1].parts[0].thought_signature is None
    assert contents[1].parts[1].function_call.name == "lookup_order"
    assert contents[1].parts[1].function_call.args == {"order_id": "9127412"}
    assert contents[2].parts[0].function_response.response == {"result": '{"status": "shipped"}'}
    assert "thinking" not in json.dumps(
        [content.model_dump(mode="json", exclude_none=True) for content in contents]
    )


# --------------------------------------------------------------------------
# OpenAI history replays through Anthropic and Gemini
# --------------------------------------------------------------------------


def test_an_openai_turn_decodes_into_the_common_fields():
    decoded = openai_model().decode_response(openai_response())
    assert decoded.text == "Looking that up."
    assert decoded.reasoning == "Look the order up."
    assert [call.id for call in decoded.tool_calls] == ["call_1"]
    assert decoded.provider_data["openai"]["output"][0]["type"] == "reasoning"


def test_an_openai_history_replays_through_anthropic():
    decoded = openai_model().decode_response(openai_response())
    request = ModelRequest(history(decoded, "call_1"), [SPEC])
    payload = anthropic_model().encode_request(request)
    assert payload["messages"] == [
        {"role": "user", "content": "Where is order 9127412?"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Looking that up."},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "lookup_order",
                    "input": {"order_id": "9127412"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_1",
                    "content": '{"status": "shipped"}',
                }
            ],
        },
    ]
    assert "encrypted_content" not in json.dumps(payload)


def test_an_openai_history_replays_through_gemini():
    decoded = openai_model().decode_response(openai_response())
    request = ModelRequest(history(decoded, "call_1"), [SPEC])
    payload = gemini_model().encode_request(request)
    contents = payload["contents"]
    assert [content.role for content in contents] == ["user", "model", "user"]
    assert contents[1].parts[0].text == "Looking that up."
    assert contents[1].parts[1].function_call.name == "lookup_order"
    assert contents[1].parts[1].function_call.id is None
    dumped = json.dumps(
        [content.model_dump(mode="json", exclude_none=True) for content in contents]
    )
    assert "encrypted_content" not in dumped
    assert "reasoning" not in dumped


def test_a_gemini_history_replays_through_the_other_two():
    """The third direction, so every pair in the table is covered."""
    from google.genai import types as genai_types

    raw = genai_types.GenerateContentResponse.model_validate(
        {
            "candidates": [
                {
                    "index": 0,
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "text": "Weighing it.",
                                "thought": True,
                                "thought_signature": b"\x00\x01\xffsig",
                            },
                            {"text": "Looking that up."},
                            {
                                "function_call": {
                                    "name": "lookup_order",
                                    "args": {"order_id": "9127412"},
                                }
                            },
                        ],
                    },
                    "finish_reason": "STOP",
                }
            ],
            "model_version": GEMINI_ID,
        }
    )
    decoded = gemini_model().decode_response(raw)
    call_id = decoded.tool_calls[0].id
    request = ModelRequest(history(decoded, call_id), [SPEC])

    anthropic_payload = anthropic_model().encode_request(request)
    assert anthropic_payload["messages"][1]["content"] == [
        {"type": "text", "text": "Looking that up."},
        {
            "type": "tool_use",
            "id": call_id,
            "name": "lookup_order",
            "input": {"order_id": "9127412"},
        },
    ]
    assert "thought_signature" not in json.dumps(anthropic_payload)

    openai_payload = openai_model().encode_request(request)
    assert openai_payload["input"][1] == {"role": "assistant", "content": "Looking that up."}
    assert "thought_signature" not in json.dumps(openai_payload)
