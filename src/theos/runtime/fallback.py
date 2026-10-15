"""Run one alternate model after a safe, pre-output provider failure."""

import logging
from contextlib import aclosing

from harness.events import GenerationComplete
from harness.model import collect_model_stream

logger = logging.getLogger("theos")

_NON_FALLBACK_TYPES = {
    "authentication",
    "content_policy_violation",
    "context_length_exceeded",
    "invalid_prompt",
    "invalid_request",
    "refusal",
}
_NON_FALLBACK_CODES = {
    "content_filter",
    "context_length_exceeded",
    "context_window_exceeded",
    "insufficient_quota",
    "invalid_api_key",
    "invalid_prompt",
    "invalid_request",
}


def fallback_allowed(error):
    """Do not hide known request, context, policy, or account configuration errors."""
    from .errors import ProviderFailure

    if not isinstance(error, ProviderFailure):
        return False
    details = error.diagnostics
    if error.context_overflow:
        return False
    if details.get("provider_error_type") in _NON_FALLBACK_TYPES:
        return False
    if details.get("provider_code") in _NON_FALLBACK_CODES:
        return False
    if details.get("status_code") in {401, 402, 403}:
        return False
    return True


class FallbackModel:
    """Try the primary model once, then one configured model before any output."""

    def __init__(self, primary, fallback_factory, fallback_model, provider, tracing):
        self.primary = primary
        self.fallback_factory = fallback_factory
        self.fallback_model = fallback_model
        self.provider = provider
        self.tracing = tracing

    def __getattr__(self, name):
        return getattr(self.primary, name)

    async def generate(self, request):
        async with aclosing(self.stream(request)) as events:
            return await collect_model_stream(events)

    async def stream(self, request):
        emitted = False
        try:
            async with aclosing(self.primary.stream(request)) as events:
                async for event in events:
                    emitted = True
                    yield event
            return
        except Exception as error:
            if emitted or not fallback_allowed(error):
                raise
            primary_error = error

        details = primary_error.diagnostics
        attrs = {
            "theos.provider.fallback.used": True,
            "theos.provider.fallback.provider": self.provider,
            "theos.provider.fallback.primary_model": self.primary.model_id,
            "theos.provider.fallback.model": self.fallback_model,
        }
        for key in ("status_code", "provider_error_type", "provider_code", "provider_name"):
            value = details.get(key)
            if value is not None:
                attrs["theos.provider.fallback.primary_" + key] = value
        logger.warning(
            "provider_model_fallback",
            extra={
                "provider": self.provider,
                "primary_model": self.primary.model_id,
                "fallback_model": self.fallback_model,
                **details,
            },
        )
        with self.tracing.span("provider model fallback", attrs) as span:
            async with self.fallback_factory() as model:
                async with aclosing(model.stream(request)) as events:
                    async for event in events:
                        if isinstance(event, GenerationComplete):
                            event.message.provider_data.setdefault("theos", {})["model"] = (
                                self.fallback_model
                            )
                            if span is not None:
                                span.set_attribute("theos.provider.fallback.completed", True)
                        yield event
