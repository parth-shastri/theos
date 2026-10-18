"""Provider capacities and shared context rules for research and final answers.

    runtime -- model, limits, options --> generic harness
    harness -- each summary response --> usage accounting
    harness -- complete checkpoint ---> session or research persistence

The harness owns summary prompts, message ordering, and fit checks.
This module binds those rules to application configuration and storage.
"""

import logging
import time
from dataclasses import dataclass
from urllib.parse import quote

from harness import CompactionConfig
from theos.prompts import compaction_overrides

from .model_catalog import catalog_entry, wire_model
from .models import session_options

logger = logging.getLogger("theos")
# OpenAI's model API does not report context limits. Keep the direct Responses
# provider at its conservative 272K catalog window; other hosts may allow more.
OPENAI_CONTEXT_WINDOWS = {
    "gpt-6-luna": 272_000,
    "gpt-5.6-luna": 272_000,
}
UNKNOWN_CONTEXT_WINDOW = 24_000
CAPACITY_CACHE_SECONDS = 3600


class ResearchStopped(TimeoutError):
    """The research deadline forbids new work but does not cancel a running reply."""


@dataclass(frozen=True)
class ModelCapacity:
    context: int
    output: int | None
    source: str


def _positive_int(value):
    """Provider metadata is optional; accept only usable token limits."""
    return value if type(value) is int and value > 0 else None


def _openai_context_window(model):
    """Resolve the conservative OpenAI cap for either configured model alias."""
    if model in OPENAI_CONTEXT_WINDOWS:
        return OPENAI_CONTEXT_WINDOWS[model]
    entry = catalog_entry(model)
    return next(
        (
            window
            for name, window in OPENAI_CONTEXT_WINDOWS.items()
            if entry is not None and catalog_entry(name) == entry
        ),
        None,
    )


def _fallback_capacity(provider, model):
    """Keep direct OpenAI conservative; unknown providers get a safe small window."""
    entry = catalog_entry(model)
    context = _openai_context_window(model) if provider == "openai" else None
    if context is None:
        return ModelCapacity(UNKNOWN_CONTEXT_WINDOW, entry[2] if entry else None, "fallback")
    return ModelCapacity(context, entry[2] if entry else None, "openai_conservative")


async def _provider_capacity(runtime, model):
    """Read limits from providers that publish model metadata."""
    provider = runtime.settings.provider
    entry = catalog_entry(model)
    output_fallback = entry[2] if entry else None

    if provider == "openrouter":
        response = await runtime.http.get("https://openrouter.ai/api/v1/models", timeout=10)
        response.raise_for_status()
        row = next(
            row for row in response.json()["data"] if row["id"] == wire_model(provider, model)
        )
        top = row.get("top_provider") or {}
        context = _positive_int(top.get("context_length")) or _positive_int(
            row.get("context_length")
        )
        output = _positive_int(top.get("max_completion_tokens")) or output_fallback
        return ModelCapacity(context, output, "provider") if context else None

    api_key = runtime.settings.api_key.get_secret_value()
    if not api_key:
        return None

    if provider == "gemini":
        model_id = model.removeprefix("models/")
        response = await runtime.http.get(
            f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model_id, safe='-_.')}",
            headers={"x-goog-api-key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        metadata = response.json()
        context = _positive_int(metadata.get("inputTokenLimit"))
        output = _positive_int(metadata.get("outputTokenLimit")) or output_fallback
        return ModelCapacity(context, output, "provider") if context else None

    if provider == "anthropic":
        response = await runtime.http.get(
            f"https://api.anthropic.com/v1/models/{quote(model, safe='-_.')}",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=10,
        )
        response.raise_for_status()
        metadata = response.json()
        context = _positive_int(metadata.get("max_input_tokens"))
        output = _positive_int(metadata.get("max_tokens")) or output_fallback
        return ModelCapacity(context, output, "provider") if context else None

    return None


async def capacity(runtime, session):
    """Cache public provider metadata. Explicit operator context overrides remain valid."""
    settings = runtime.settings
    key = (settings.provider, session["model"])
    cache = getattr(runtime, "model_capacities", {})
    runtime.model_capacities = cache
    cached = cache.get(key)
    if cached and time.monotonic() - cached[0] < CAPACITY_CACHE_SECONDS:
        resolved = cached[1]
    else:
        resolved = _fallback_capacity(settings.provider, session["model"])
        try:
            metadata = await _provider_capacity(runtime, session["model"])
            if metadata is not None:
                resolved = metadata
        except Exception as error:
            logger.warning(
                "model_capacity_provider_fallback", extra={"error_type": type(error).__name__}
            )
        if resolved.source == "fallback":
            logger.warning(
                "model_context_unknown",
                extra={"model": session["model"], "context_tokens": resolved.context},
            )
        cache[key] = (time.monotonic(), resolved)
    window = settings.context_tokens or resolved.context
    if resolved.source != "fallback":
        window = min(window, resolved.context)
    return ModelCapacity(
        window,
        resolved.output,
        "operator" if settings.context_tokens else resolved.source,
    )


def options(runtime, session, limits):
    """Use the configured output limit unless the conversation supplies one."""
    # Keep the output setting intact. The harness summarizes input when both cannot fit.
    values = session_options(runtime.settings, session)
    if not any(
        key in values for key in ("max_output_tokens", "max_tokens", "max_completion_tokens")
    ):
        # Map the common output setting to the provider's supported wire parameter.
        provider = runtime.settings.provider
        key = (
            "max_tokens"
            if provider in {"openrouter", "anthropic", "llama"}
            else "max_output_tokens"
        )
        values[key] = min(runtime.settings.max_output_tokens, limits.output or 1_000_000)
    return values


def compaction(
    runtime,
    session,
    limits,
    research_id=None,
    *,
    persist_session=True,
    summary_model=None,
    summary_session=None,
    summary_limits=None,
):
    """Build the small rolling-summary config from application settings."""
    from .usage import message_model

    async def checkpoint(memory, history):
        # The harness calls this after all required summaries succeed and the request fits.
        # Save the combined checkpoint with its coverage boundary and complete transcript.
        if research_id:
            runtime.research.checkpoint(
                session["owner"],
                session["id"],
                research_id,
                history,
                memory,
                save_session=persist_session,
            )
        elif persist_session:
            with runtime.db.transaction():
                runtime.db.save_history(session["owner"], session["id"], history, memory.to_dict())

    async def record_summary(message):
        # History, split-turn, and shortening calls each report their own provider usage.
        runtime.record_usage(session, message.usage, model_id=message_model(message))

    summary_session = summary_session or session
    summary_limits = summary_limits or limits
    return CompactionConfig(
        **compaction_overrides(),
        options=options(runtime, summary_session, summary_limits),
        on_commit=checkpoint if persist_session or research_id else None,
        on_summary=record_summary,
        trigger_ratio=runtime.settings.compaction_trigger_ratio,
        tail_ratio=runtime.settings.compaction_tail_ratio,
        summary_model=summary_model,
        summary_window=summary_limits.context,
    )
