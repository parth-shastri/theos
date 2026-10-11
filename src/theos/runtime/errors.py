"""Identify model failures without exposing provider bodies or credentials."""

from contextlib import aclosing

import httpx


class ProviderFailure(RuntimeError):
    """A failure at the model boundary with a safe explanation for the user."""

    def __init__(self, provider, error):
        names = {
            "openai": "OpenAI",
            "openrouter": "OpenRouter",
            "anthropic": "Anthropic",
            "gemini": "Google Gemini",
            "llama": "the local model server",
            "fake": "the test model",
        }
        name = names.get(provider, "the model provider")
        status = getattr(error, "status_code", None)
        code = error.get("code") if isinstance(error, dict) else getattr(error, "code", None)
        if isinstance(code, str) and code.isascii() and code.isdecimal() and len(code) == 3:
            code = int(code)
        if status is None:
            status = (
                code
                if isinstance(code, int)
                else {
                    "rate_limit_exceeded": 429,
                    "insufficient_quota": 429,
                    "invalid_api_key": 401,
                    "model_not_found": 404,
                    "server_error": 500,
                }.get(code)
                if isinstance(code, str)
                else None
            )
        if status is None and isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
        kind = type(error).__name__
        next_step = "Please try again after the issue is resolved."
        if isinstance(error, (TimeoutError, httpx.TimeoutException)) or kind == "APITimeoutError":
            detail = "did not respond before the connection timed out"
        elif isinstance(error, httpx.NetworkError) or kind == "APIConnectionError":
            detail = "could not be reached over the network"
        elif status in {401, 403}:
            detail = "rejected my credentials or access permissions"
            next_step = "The deployment operator needs to check my provider access."
        elif status == 429:
            detail = "refused the request because its rate or quota limit was reached"
        elif status == 402:
            detail = "refused the request because the provider account has insufficient credit"
        elif status == 404:
            detail = "could not find an available model or route for this request"
        elif isinstance(status, int) and status >= 500:
            detail = "reported a provider-side server error"
        elif isinstance(status, int) and 400 <= status < 500:
            detail = "rejected the model request I sent"
            next_step = (
                "The deployment operator needs to check my request and provider configuration."
            )
        else:
            detail = "failed while generating the response"
        suffix = f" (HTTP {status})" if isinstance(status, int) else ""
        self.public_message = (
            f"I could not finish your request. {name} {detail}{suffix}. {next_step}"
        )
        super().__init__(self.public_message)


class CheckedModel:
    """Keep provider exceptions distinct from application limits and tool failures."""

    def __init__(self, model, provider):
        self.model = model
        self.provider = provider

    def __getattr__(self, name):
        return getattr(self.model, name)

    async def stream(self, request):
        from harness.events import GenerationComplete, TextDelta

        from .context import ResearchStopped

        pending = []
        try:
            async with aclosing(self.model.stream(request)) as events:
                async for event in events:
                    if isinstance(event, (TextDelta, GenerationComplete)):
                        pending.append(event)
                    else:
                        yield event
            if not any(isinstance(event, GenerationComplete) for event in pending):
                raise RuntimeError("The provider stream ended without a complete response.")
        except (ProviderFailure, ResearchStopped):
            raise
        except Exception as error:
            raise ProviderFailure(self.provider, error) from error
        for event in pending:
            yield event


def failure_message(reason, error=None):
    if isinstance(error, ProviderFailure):
        return error.public_message
    reasons = {
        "budget_limit": "I reached my model-call limit before I could finish the answer.",
        "timeout": "I reached my research time limit before I could finish the answer.",
        "context_limit": "The conversation and requested output exceed the model context available to me.",
        "output_limit": "The model provider stopped the answer at its output limit.",
        "delegate_partial": "I could not complete the delegated research needed for this answer.",
    }
    return (
        reasons.get(
            reason,
            "I could not finish your request because an internal Theos error interrupted the turn.",
        )
        + " Please try again."
    )
