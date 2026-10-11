"""OpenRouter summaries, signed block replay, and provider-reported cost."""

import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError, AsyncOpenAI, BadRequestError, NotFoundError
from openai.types.chat import ChatCompletion

from harness import AssistantMessage, ToolCall, ToolResultMessage, UserMessage
from harness.events import GenerationComplete, ReasoningDelta, TextDelta
from harness.types import ModelRequest, ToolSpec
from theos.runtime.openrouter import OpenRouterChatModel


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("custom_options", [False, True])
async def test_openrouter_sends_zdr_without_changing_request_options(streaming, custom_options):
    options = {}
    if custom_options:
        options = {
            "max_tokens": 512,
            "extra_body": {
                "reasoning": {"effort": "low"},
                "top_k": 25,
                "provider": {"zdr": False, "only": ["azure"], "allow_fallbacks": False},
            },
        }
    original = copy.deepcopy(options)
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        response = {
            "id": "chat-zdr",
            "created": 1,
            "model": body["model"],
            "object": "chat.completion.chunk" if streaming else "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "delta" if streaming else "message": {"role": "assistant", "content": "OK"},
                }
            ],
        }
        if streaming:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="data: " + json.dumps(response) + "\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, json=response)

    async with AsyncOpenAI(
        api_key="test",
        base_url="https://openrouter.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        model = OpenRouterChatModel(
            client, "openai/gpt-6-luna", api="chat_completions", stream=streaming
        )
        reply = await model.generate(ModelRequest([UserMessage("Reply OK")], options=options))
    assert reply.text == "OK"
    assert len(calls) == 1
    assert calls[0]["provider"]["zdr"] is True
    if custom_options:
        assert calls[0]["provider"] == {
            "zdr": True,
            "only": ["azure"],
            "allow_fallbacks": False,
        }
        assert calls[0]["reasoning"] == {"effort": "low"}
        assert calls[0]["top_k"] == 25
        assert calls[0]["max_tokens"] == 512
    assert options == original


async def test_openrouter_unavailable_zdr_route_does_not_retry_without_policy():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(404, json={"error": {"message": "No eligible ZDR endpoint"}})

    async with AsyncOpenAI(
        api_key="test",
        base_url="https://openrouter.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        model = OpenRouterChatModel(client, "openai/gpt-6-luna", api="chat_completions")
        with pytest.raises(APIStatusError):
            await model.generate(ModelRequest([UserMessage("Reply OK")]))
    assert len(calls) == 1
    assert calls[0]["provider"] == {"zdr": True}


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("retry_fails", [False, True])
@pytest.mark.parametrize("status", [400, 404])
async def test_openrouter_rejected_encrypted_replay_keeps_history_tools_and_zdr(
    streaming, retry_fails, status
):
    calls = []
    failure = {
        "error": {
            "message": "No endpoints found matching your data policy (Zero data retention)."
            if status == 404
            else "Your request contains encrypted reasoning or compaction content from multiple providers."
        }
    }

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1 or retry_fails:
            return httpx.Response(status, json=failure)
        reply = {
            "id": "chat-recovered",
            "created": 1,
            "model": body["model"],
            "object": "chat.completion.chunk" if streaming else "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "delta" if streaming else "message": {"role": "assistant", "content": "OK"},
                }
            ],
        }
        if streaming:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="data: " + json.dumps(reply) + "\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, json=reply)

    previous = AssistantMessage(
        "Saved answer",
        reasoning="Saved summary",
        provider_data={
            "openrouter": {
                "model": "openai/gpt-6-luna",
                "reasoning_details": [
                    {
                        "type": "reasoning.summary",
                        "summary": "Saved summary",
                        "format": "openai-responses-v1",
                    },
                    {
                        "type": "reasoning.encrypted",
                        "data": "opaque",
                        "format": "openai-responses-v1",
                    },
                ],
            }
        },
    )
    original = copy.deepcopy(previous)
    async with AsyncOpenAI(
        api_key="test",
        base_url="https://openrouter.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        model = OpenRouterChatModel(
            client, "openai/gpt-6-luna", api="chat_completions", stream=streaming
        )
        request = ModelRequest(
            [previous, UserMessage("Reply OK")],
            tools=[
                ToolSpec(
                    "get_preferences", "Read preferences", {"type": "object", "properties": {}}
                )
            ],
            options={"max_tokens": 100, "extra_body": {"provider": {"only": ["azure"]}}},
        )
        if retry_fails:
            with pytest.raises(APIStatusError):
                await model.generate(request)
        else:
            assert (await model.generate(request)).text == "OK"
    assert len(calls) == 2
    expected = copy.deepcopy(calls[0])
    expected["messages"][0].pop("reasoning_details")
    assert calls[1] == expected
    assert all(call["provider"] == {"zdr": True, "only": ["azure"]} for call in calls)
    assert previous == original


async def test_openrouter_consecutive_turns_select_latest_provider_state():
    calls = []
    formats = ["azure-openai-responses-v1", "bedrock-openai-responses-v1", "openai-responses-v1"]

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "id": "chat-provider-change",
                "created": 1,
                "model": body["model"],
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "Done",
                            "reasoning_details": [
                                {
                                    "type": "reasoning.encrypted",
                                    "data": "opaque-new",
                                    "format": formats[len(calls) - 1],
                                }
                            ],
                        },
                    }
                ],
            },
        )

    previous = AssistantMessage(
        tool_calls=[ToolCall("read-1", "get_preferences", {})],
        provider_data={
            "openrouter": {
                "model": "openai/gpt-6-luna",
                "reasoning_details": [
                    {
                        "type": "reasoning.encrypted",
                        "data": "opaque-old",
                        "format": "openai-responses-v1",
                    }
                ],
            }
        },
    )
    history = [
        UserMessage("Read my preferences"),
        previous,
        ToolResultMessage("read-1", "get_preferences", '{"timezone":"UTC"}'),
    ]
    original = copy.deepcopy(history)
    async with AsyncOpenAI(
        api_key="test",
        base_url="https://openrouter.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        model = OpenRouterChatModel(
            client, "openai/gpt-6-luna", api="chat_completions", stream=False
        )
        for _ in range(3):
            history.append(UserMessage("Continue"))
            saved = copy.deepcopy(history)
            expected = model.encode_request(ModelRequest(history))
            response = await model.generate(ModelRequest(history))
            assert history == saved
            history.append(response)
            wire = calls[-1]["messages"]
            replay = [b["format"] for m in wire for b in m.get("reasoning_details", [])]
            assert set(replay) == {
                "openai-responses-v1" if len(calls) == 1 else formats[len(calls) - 2]
            }
            assert wire == expected["messages"]
            assert calls[-1]["provider"] == {"zdr": True}
            assert wire[1]["tool_calls"][0]["function"]["name"] == "get_preferences"
            assert wire[2]["content"] == '{"timezone":"UTC"}'
    assert history[:3] == original


def test_openrouter_omits_entire_internally_mixed_reasoning_sequence():
    details = [
        {"type": "reasoning.encrypted", "data": "opaque", "format": f}
        for f in ("openai-responses-v1", "azure-openai-responses-v1")
    ]
    previous = AssistantMessage(
        "Saved answer",
        provider_data={
            "openrouter": {
                "model": "openai/gpt-6-luna",
                "reasoning_details": details,
            }
        },
    )
    model = OpenRouterChatModel(SimpleNamespace(), "openai/gpt-6-luna", api="chat_completions")
    wire = model.encode_request(ModelRequest([previous]))["messages"][0]
    assert wire["content"] == "Saved answer"
    assert "reasoning_details" not in wire
    assert previous.provider_data["openrouter"]["reasoning_details"] == details


@pytest.mark.parametrize(
    "model_id,block_format,error_message,status",
    [
        (
            "anthropic/claude-sonnet-5.5",
            "anthropic-claude-v1",
            "No endpoints found matching your data policy (Zero data retention).",
            404,
        ),
        ("openai/gpt-6-luna", "openai-responses-v1", "Unknown model", 404),
        ("openai/gpt-6-luna", "openai-responses-v1", "Invalid tool schema", 400),
    ],
)
async def test_openrouter_does_not_discard_claude_state_or_retry_unrelated_404(
    model_id, block_format, error_message, status
):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(status, json={"error": {"message": error_message}})

    previous = AssistantMessage(
        "Saved",
        provider_data={
            "openrouter": {
                "model": model_id,
                "reasoning_details": [
                    {"type": "reasoning.encrypted", "data": "opaque", "format": block_format}
                ],
            }
        },
    )
    async with AsyncOpenAI(
        api_key="test",
        base_url="https://openrouter.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        model = OpenRouterChatModel(client, model_id, api="chat_completions")
        with pytest.raises(APIStatusError):
            await model.generate(ModelRequest([previous, UserMessage("Reply OK")]))
    assert len(calls) == 1
    assert calls[0]["messages"][0]["reasoning_details"][0]["data"] == "opaque"


@pytest.mark.parametrize("status", [400, 404])
async def test_openrouter_does_not_restart_a_stream_after_output(status):
    calls = []
    model = OpenRouterChatModel(SimpleNamespace(), "openai/gpt-6-luna", api="chat_completions")

    async def partial(payload):
        calls.append(payload)
        yield TextDelta("Already delivered")
        error_class = NotFoundError if status == 404 else BadRequestError
        raise error_class(
            "Routing failed",
            response=httpx.Response(
                status, request=httpx.Request("POST", "https://openrouter.test/v1")
            ),
            body={
                "message": "No endpoints found matching your data policy (Zero data retention)."
                if status == 404
                else "encrypted reasoning or compaction content from multiple providers"
            },
        )

    model._stream_chat_once = partial
    previous = AssistantMessage(
        "Saved",
        provider_data={
            "openrouter": {
                "model": model.model_id,
                "reasoning_details": [
                    {
                        "type": "reasoning.encrypted",
                        "data": "opaque",
                        "format": "openai-responses-v1",
                    }
                ],
            }
        },
    )
    events = []
    with pytest.raises(NotFoundError if status == 404 else BadRequestError):
        async for event in model.stream(ModelRequest([previous, UserMessage("Continue")])):
            events.append(event)
    assert [event.text for event in events] == ["Already delivered"]
    assert len(calls) == 1


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


@pytest.mark.parametrize("with_error_body", [False, True])
async def test_openrouter_stream_error_does_not_complete_partial_text(with_error_body):
    from theos.runtime.errors import CheckedModel, ProviderFailure

    calls = []

    def respond(request):
        calls.append(request)
        chunks = [
            {
                "id": "failed",
                "created": 1,
                "model": "openai/gpt-6-luna",
                "object": "chat.completion.chunk",
                "choices": [
                    {"index": 0, "delta": {"content": "Unfinished response"}, "finish_reason": None}
                ],
            },
            {
                "id": "failed",
                "created": 1,
                "model": "openai/gpt-6-luna",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
            },
        ]
        if with_error_body:
            chunks[-1]["error"] = {"code": 502, "message": "private upstream response"}
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n",
        )

    async with AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        model = CheckedModel(
            OpenRouterChatModel(client, "openai/gpt-6-luna", api="chat_completions"), "openrouter"
        )
        events = []
        with pytest.raises(ProviderFailure) as failure:
            async for event in model.stream(ModelRequest([UserMessage("Answer")])):
                events.append(event)
    assert not any(isinstance(e, (TextDelta, GenerationComplete)) for e in events)
    assert "OpenRouter" in str(failure.value)
    assert "private" not in str(failure.value)
    if with_error_body:
        assert "502" in str(failure.value)
    assert len(calls) == 1
