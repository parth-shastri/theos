"""Construct harness models and close the SDK clients that own connections."""

import json
from contextlib import asynccontextmanager

import httpx

from harness import AssistantMessage
from harness.testing import FakeModel

from .model_catalog import generation_options, wire_model


def session_options(settings, session):
    """Combine generation and reasoning without replacing OpenRouter's extra body."""
    options = model_options(settings.provider, session["reasoning"])
    generation = generation_options(
        settings.provider, session["model"], json.loads(session.get("generation", "{}"))
    )
    extra = {**options.pop("extra_body", {}), **generation.pop("extra_body", {})}
    options.update(generation)
    if extra:
        options["extra_body"] = extra
    return options


@asynccontextmanager
async def model_client(settings, model_id, reasoning):
    """Use the configured provider with explicit timeouts and bounded retries."""
    model_id = wire_model(settings.provider, model_id)
    if settings.provider == "fake":
        yield FakeModel(
            [AssistantMessage(f"{settings.name} is ready. This is a local test response.")]
        )
        return
    key = settings.api_key.get_secret_value()
    if not key and settings.provider != "llama":
        raise ValueError("Set AGENT_API_KEY for the configured model provider.")
    if settings.provider == "gemini":
        from google import genai

        from harness.providers.gemini import GeminiChatModel

        async def idle_timeout(request):
            # The SDK passes timeout=None. Set phase timeouts without a server deadline header.
            request.extensions["timeout"] = httpx.Timeout(60, connect=10).as_dict()

        # Force httpx so Gemini's optional aiohttp transport cannot impose a total deadline.
        transport = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=10), event_hooks={"request": [idle_timeout]}
        )
        client = genai.Client(api_key=key, http_options={"httpx_async_client": transport})
        thinking = None
        if reasoning != "default":
            if model_id.startswith("gemini-3"):
                thinking = {"thinking_level": {"none": "minimal"}.get(reasoning, reasoning)}
            else:
                thinking = {
                    "thinking_budget": {"none": 0, "low": 1024, "medium": 4096, "high": 8192}[
                        reasoning
                    ]
                }
        try:
            yield GeminiChatModel(client, model_id, thinking_config=thinking)
        finally:
            await client.aio.aclose()
            client.close()
            await transport.aclose()
    elif settings.provider == "anthropic":
        from anthropic import AsyncAnthropic

        from harness.providers.anthropic import AnthropicChatModel

        async with AsyncAnthropic(
            api_key=key, timeout=httpx.Timeout(60, connect=10), max_retries=2
        ) as client:
            yield AnthropicChatModel(
                client,
                model_id,
                max_tokens=None,
                thinking=None if reasoning == "none" else {"type": "adaptive"},
            )
    else:
        from openai import AsyncOpenAI

        from harness.providers.openai import OpenAIChatModel
        from theos.operations.provider_diagnostics import request_hook, response_hook

        base_url = settings.model_base_url or {
            "openrouter": "https://openrouter.ai/api/v1",
            "llama": "http://127.0.0.1:8081/v1",
        }.get(settings.provider)
        async with AsyncOpenAI(
            api_key=key or "local",
            base_url=base_url,
            timeout=httpx.Timeout(60, connect=10),
            max_retries=2,
            http_client=httpx.AsyncClient(
                timeout=httpx.Timeout(60, connect=10),
                event_hooks={"request": [request_hook], "response": [response_hook]},
            ),
        ) as client:
            if settings.provider == "llama":
                from harness.providers.llama import LlamaServerModel

                yield LlamaServerModel(client, model_id)
            else:
                model_class = OpenAIChatModel
                if settings.provider == "openrouter":
                    from .openrouter import OpenRouterChatModel

                    model_class = OpenRouterChatModel
                yield model_class(
                    client,
                    model_id,
                    api="chat_completions" if settings.provider == "openrouter" else "responses",
                    **(
                        {"provider_preferences": settings.openrouter.preferences()}
                        if settings.provider == "openrouter"
                        else {}
                    ),
                )


def model_options(provider, reasoning):
    """Use each provider's reasoning field without changing the harness API."""
    if provider == "openai":
        options = {} if reasoning == "default" else {"effort": reasoning}
        if reasoning != "none":
            options["summary"] = "auto"
        return {"reasoning": options}
    if reasoning == "default":
        return {}
    if provider == "openrouter":
        return {"extra_body": {"reasoning": {"effort": reasoning}}}
    if provider == "anthropic" and reasoning != "none":
        return {"output_config": {"effort": reasoning}}
    return {}
