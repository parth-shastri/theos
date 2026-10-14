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


def test_performance_routing_keeps_zdr_and_saved_signed_state():
    from theos.settings import OpenRouterSettings

    preferences = OpenRouterSettings().preferences()
    saved = AssistantMessage(
        tool_calls=[ToolCall("saved-call", "read", {})],
        provider_data={
            "openrouter": {
                "model": "openai/gpt-6-luna",
                "reasoning_details": [
                    {
                        "type": "reasoning.encrypted",
                        "format": "azure-openai-responses-v1",
                        "data": "unchanged-signed-state",
                    }
                ],
            }
        },
    )
    request = ModelRequest(
        [saved, ToolResultMessage("saved-call", "read", "already completed")],
        options={
            "max_tokens": 8192,
            "extra_body": {"reasoning": {"effort": "medium"}, "provider": {"zdr": False}},
        },
    )
    original = copy.deepcopy(request)
    model = OpenRouterChatModel(
        SimpleNamespace(),
        "openai/gpt-6-luna",
        api="chat_completions",
        provider_preferences=preferences,
    )
    wire = model.encode_request(request)
    provider = wire["extra_body"]["provider"]
    assert provider == {**preferences, "zdr": True}
    assert wire["extra_body"]["reasoning"] == {"effort": "medium"}
    assert wire["max_tokens"] == 8192
    assert wire["messages"][0]["reasoning_details"][0]["data"] == "unchanged-signed-state"
    assert wire["messages"][1]["tool_call_id"] == "saved-call"
    assert wire["messages"][1]["content"] == "already completed"
    assert request == original
    assert preferences == OpenRouterSettings().preferences()
    request.options["extra_body"]["provider"] = {"only": ["azure/us"], "allow_fallbacks": False}
    explicit = model.encode_request(request)["extra_body"]["provider"]
    assert explicit["only"] == ["azure/us"]
    assert explicit["allow_fallbacks"] is False
    assert "order" not in explicit
    assert explicit["zdr"] is True


def test_reasoning_usage_is_a_subset_of_total_output():
    raw = ChatCompletion.model_validate(
        {
            "id": "chat-usage",
            "created": 1,
            "model": "openai/gpt-6-luna",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "OK",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 40952,
                "completion_tokens": 940,
                "total_tokens": 41892,
                "completion_tokens_details": {"reasoning_tokens": 808},
            },
        }
    )
    model = OpenRouterChatModel(SimpleNamespace(), "openai/gpt-6-luna", api="chat_completions")
    usage = model.decode_response(raw).usage
    assert usage["reasoning_tokens"] == 808
    assert usage["output_tokens"] == 940
    assert usage["total_tokens"] == 41892


@pytest.mark.parametrize(
    "choice",
    [
        "gpt-6-luna",
        "gpt-5.6-luna",
        "sonnet-5.5",
        "deepseek-flash-v4.1",
        "gemini-3.8-flash",
        "glm-5.3-flash",
        "qwen-3.8-27b",
    ],
)
async def test_runtime_client_uses_automatic_routing_for_every_model(settings, choice):
    from pydantic import SecretStr

    from theos.runtime.models import model_client
    from theos.settings import OpenRouterSettings

    settings.provider = "openrouter"
    settings.api_key = SecretStr("test")
    settings.openrouter = OpenRouterSettings()
    async with model_client(settings, choice, "default") as model:
        wire = model.encode_request(ModelRequest([UserMessage("Private prompt")]))
        assert wire["extra_body"]["provider"] == {
            **settings.openrouter.preferences(),
            "zdr": True,
        }
        assert "order" not in wire["extra_body"]["provider"]
    assert "order" not in OpenRouterSettings.model_fields
    assert "model_orders" not in OpenRouterSettings.model_fields


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


@pytest.mark.parametrize("recover", [True, False])
async def test_transient_stream_retry_is_bounded_and_keeps_request(recover, monkeypatch):
    import asyncio

    from theos.runtime.errors import ProviderFailure

    async def no_delay(seconds):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_delay)
    calls = []
    gid = "gen-1791970172-H2H3UnsPNxCqHKMmHtkD"

    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) < 3 or not recover:
            data = {
                "error": {
                    "code": 502,
                    "message": "PRIVATE BODY sk-SECRET123456789",
                    "metadata": {
                        "provider_name": "Azure",
                        "error_type": "provider_unavailable",
                        "raw": "PRIVATE PROVIDER RESPONSE",
                    },
                }
            }
        else:
            data = {
                "id": gid,
                "created": 1,
                "model": "openai/gpt-6-luna",
                "object": "chat.completion.chunk",
                "choices": [
                    {"index": 0, "delta": {"content": "Completed"}, "finish_reason": "stop"}
                ],
            }
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "x-generation-id": gid},
            text="data: " + json.dumps(data) + "\n\ndata: [DONE]\n\n",
        )

    async with AsyncOpenAI(
        api_key="test",
        base_url="https://openrouter.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        model = OpenRouterChatModel(client, "openai/gpt-6-luna", api="chat_completions")
        request = ModelRequest(
            [UserMessage("Continue after saved results.")], options={"max_tokens": 8192}
        )
        if recover:
            assert (await model.generate(request)).text == "Completed"
        else:
            with pytest.raises(ProviderFailure) as problem:
                await model.generate(request)
            assert problem.value.diagnostics == {
                "status_code": 502,
                "http_status": 200,
                "generation_id": gid,
                "provider_name": "Azure",
                "provider_error_type": "provider_unavailable",
                "provider_stage": "stream",
            }
            assert "PRIVATE" not in str(problem.value)
    assert len(calls) == 3
    assert calls[0] == calls[1] == calls[2]
    assert calls[0]["provider"]["zdr"] is True


async def test_retry_after_completed_tool_never_repeats_that_tool(runtime, monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager

    from harness import tool

    from .conftest import collect

    async def no_delay(seconds):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_delay)
    performed = []
    requests = []
    gid = "gen-1791970172-H2H3UnsPNxCqHKMmHtkD"

    @tool
    async def save_once(value: int):
        performed.append(value)
        return {"saved": value}

    async def registry(session):
        return [runtime.journal_tool(save_once, session)]

    runtime.tools = registry
    runtime.settings.provider = "openrouter"

    def respond(request):
        requests.append(json.loads(request.content))
        data = {
            "id": gid,
            "created": 1,
            "model": "openai/gpt-6-luna",
            "object": "chat.completion.chunk",
        }
        if len(requests) == 1:
            data["choices"] = [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-once",
                                "type": "function",
                                "function": {"name": "save_once", "arguments": '{"value":42}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        elif len(requests) < 4:
            data["error"] = {"code": 502, "metadata": {"error_type": "provider_unavailable"}}
        else:
            data["choices"] = [
                {"index": 0, "delta": {"content": "Saved once."}, "finish_reason": "stop"}
            ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "x-generation-id": gid},
            text="data: " + json.dumps(data) + "\n\ndata: [DONE]\n\n",
        )

    @asynccontextmanager
    async def factory(*args):
        async with AsyncOpenAI(
            api_key="test",
            base_url="https://openrouter.test/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            yield runtime.tracing.model(
                OpenRouterChatModel(client, "openai/gpt-6-luna", api="chat_completions")
            )

    runtime.models = factory
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    events = await collect(runtime.start("alice", row["id"], "Save the value."))
    assert events[-1]["status"] == "completed"
    assert performed == [42]
    assert len(requests) == 4
    assert requests[1] == requests[2] == requests[3]
    assert (
        runtime.db.one(
            "SELECT status FROM tool_runs WHERE session=? AND call_id=?", (row["id"], "call-once")
        )["status"]
        == "completed"
    )


async def test_long_failed_stream_does_not_start_more_provider_waits(monkeypatch):
    from theos.runtime import openrouter
    from theos.runtime.errors import ProviderFailure

    clock = iter([0, 31])
    monkeypatch.setattr(openrouter, "monotonic", lambda: next(clock))
    attempts = []
    model = OpenRouterChatModel(SimpleNamespace(), "openai/gpt-6-luna", api="chat_completions")

    async def stalled(payload):
        attempts.append(payload)
        error = ProviderFailure("openrouter", {"code": 502})
        error.diagnostics["http_status"] = 200
        raise error
        yield

    model._stream_chat_once = stalled
    with pytest.raises(ProviderFailure):
        await model.generate(ModelRequest([UserMessage("Answer")]))
    assert len(attempts) == 1
