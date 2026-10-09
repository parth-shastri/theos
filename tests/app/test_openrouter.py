"""OpenRouter summaries, signed block replay, and provider-reported cost."""

from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion

from harness import UserMessage
from harness.events import GenerationComplete, ReasoningDelta
from harness.types import ModelRequest
from theos.runtime.openrouter import OpenRouterChatModel


async def test_openrouter_stream_preserves_reasoning_tools_and_cost(runtime):
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "reasoning": "Summary ",
                        "reasoning_details": [
                            {
                                "index": 0,
                                "type": "reasoning.text",
                                "text": "Summary ",
                                "signature": "signed",
                            }
                        ],
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "reasoning": "continued",
                        "reasoning_details": [{"index": 0, "text": "continued"}],
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_details": [
                            {"index": 1, "type": "reasoning.encrypted", "data": "opaque-block"}
                        ],
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "pref",
                                "function": {"name": "get_preferences", "arguments": "{}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cost": 0.00000342,
            }
        },
    ]

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def __aiter__(self):
            return self.events()

        async def events(self):
            for chunk in chunks:
                yield chunk

    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return Stream()

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    model = OpenRouterChatModel(client, "anthropic/claude-sonnet-5.5", api="chat_completions")
    events = [event async for event in model.stream(ModelRequest([UserMessage("Hello")]))]
    assert [event.text for event in events if isinstance(event, ReasoningDelta)] == [
        "Summary ",
        "continued",
    ]
    message = next(event.message for event in events if isinstance(event, GenerationComplete))
    assert message.reasoning == "Summary continued"
    assert "opaque-block" not in message.reasoning
    assert message.tool_calls[0].name == "get_preferences"
    assert message.usage["cost_nanousd"] == 3420
    assert calls[0]["stream"] is True
    replay = model.encode_request(ModelRequest([message]))["messages"][0]
    assert replay["reasoning_details"][0]["text"] == "Summary continued"
    assert replay["reasoning_details"][0]["signature"] == "signed"
    assert replay["reasoning_details"][1]["data"] == "opaque-block"
    other = OpenRouterChatModel(client, "openai/gpt-5.6-luna", api="chat_completions")
    assert "reasoning_details" not in other.encode_request(ModelRequest([message]))["messages"][0]
    runtime.settings.input_cost_per_million = 100
    runtime.settings.output_cost_per_million = 100
    session = runtime.db.create_session("alice", "sonnet-5.5", "default")
    runtime.record_usage(session, message.usage)
    assert runtime.db.one("SELECT cost FROM usage")["cost"] == pytest.approx(0.00000342)


@pytest.mark.parametrize(
    "cost, expected", [(0, 0), (0.12, 120000000), (-1, None), ("nan", None), (True, None)]
)
def test_openrouter_buffered_summaries_and_invalid_costs(cost, expected):
    model = OpenRouterChatModel(None, "deepseek/deepseek-v4.1-flash", api="chat_completions")
    response = ChatCompletion.model_validate(
        {
            "id": "chat-1",
            "created": 1,
            "model": model.model_id,
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "Answer",
                        "reasoning_content": "Summary",
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "cost": cost},
        }
    )
    message = model.decode_response(response)
    assert message.reasoning == "Summary"
    assert message.usage.get("cost_nanousd") == expected
    assert model.encode_request(ModelRequest([message]))["messages"][0]["reasoning"] == "Summary"
