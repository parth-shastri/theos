"""Bounded provider classifications and request timing, without remote error prose."""

import logging
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

ERROR_TYPES = {
    "authentication",
    "content_policy_violation",
    "context_length_exceeded",
    "invalid_request",
    "invalid_prompt",
    "provider_overloaded",
    "provider_unavailable",
    "rate_limit_exceeded",
    "refusal",
    "server",
    "timeout",
    "connection_reset",
    "empty_response",
}
PROVIDERS = {
    "OpenAI",
    "Azure",
    "Anthropic",
    "Google",
    "Google AI Studio",
    "Google Vertex",
    "Amazon Bedrock",
    "DeepSeek",
    "Together",
    "Fireworks",
    "Groq",
    "Cerebras",
    "SambaNova",
    "Chutes",
    "Novita",
    "SiliconFlow",
    "Mistral",
    "xAI",
    "OpenRouter",
}
PROVIDER_CODES = ERROR_TYPES | {
    "server_error",
    "internal_error",
    "internal_server_error",
    "overloaded_error",
    "rate_limit_exceeded",
    "invalid_api_key",
    "insufficient_quota",
    "model_not_found",
    "upstream_error",
    "request_timeout",
    "content_filter",
    "context_window_exceeded",
}
REQUEST_ID = re.compile(r"(?:gen-(?:emb-)?\d{10,13}-[A-Za-z0-9]{6,80}|req_[A-Za-z0-9_-]{8,100})\Z")
OBSERVATION = ContextVar("theos_provider_observation", default=None)
logger = logging.getLogger("theos")


def clean(values):
    """Allow only known classifications and structurally valid request IDs."""
    result = {}
    for key in ("status_code", "http_status", "attempt"):
        value = values.get(key)
        if type(value) is int and 0 < value <= (599 if key != "attempt" else 100):
            result[key] = value
    for key in ("request_id", "generation_id"):
        value = values.get(key)
        if isinstance(value, str) and REQUEST_ID.fullmatch(value):
            result[key] = value
    for key, allowed in (
        ("provider_name", PROVIDERS),
        ("provider_error_type", ERROR_TYPES),
        ("provider_code", PROVIDER_CODES),
        ("provider_stage", {"request", "stream"}),
    ):
        value = values.get(key)
        if isinstance(value, str) and value in allowed:
            result[key] = value
    return result


def diagnostics(error, **extra):
    body = error if isinstance(error, dict) else getattr(error, "body", {})
    body = body if isinstance(body, dict) else {}
    body = body.get("error", body)
    body = body if isinstance(body, dict) else {}
    metadata = body.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    status = getattr(error, "status_code", None) or body.get("code")
    if isinstance(status, str) and status.isascii() and status.isdecimal() and len(status) == 3:
        status = int(status)
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
    values = {
        **getattr(error, "diagnostics", {}),
        "status_code": status,
        "provider_name": metadata.get("provider_name"),
        "provider_error_type": metadata.get("error_type", body.get("error_type")),
        "provider_code": metadata.get("provider_code"),
        "request_id": getattr(error, "request_id", None),
        "generation_id": body.get("id"),
        **extra,
    }
    if type(error).__name__ in {"APITimeoutError", "TimeoutError"} or isinstance(
        error, httpx.TimeoutException
    ):
        values.setdefault("provider_error_type", "timeout")
        values["provider_error_type"] = values["provider_error_type"] or "timeout"
    # Do not let absent wrapper fields erase an earlier safe classification.
    return clean(
        {**getattr(error, "diagnostics", {}), **{k: v for k, v in values.items() if v is not None}}
    )


def annotate(values):
    observation = OBSERVATION.get()
    if observation:
        observation["diagnostics"].update(clean(values))
        if observation["span"] is not None:
            for key, value in clean(values).items():
                observation["span"].set_attribute("theos.provider." + key, value)


def failure(error):
    observation = OBSERVATION.get()
    values = clean({**(observation["diagnostics"] if observation else {}), **diagnostics(error)})
    annotate(values)
    if observation:
        observation["last_failure"] = values
    if not getattr(error, "diagnostics_logged", False):
        if observation and observation["span"] is not None and values.get("provider_stage"):
            observation["span"].add_event("provider request failure", values)
        logger.warning(
            "provider_request_failed", extra={"error_type": type(error).__name__, **values}
        )
        if not isinstance(error, dict):
            error.diagnostics_logged = True
            error.diagnostics = values
    return values


def recovered(retries):
    state = OBSERVATION.get()
    if state and state["span"] is not None:
        state["span"].set_attribute("theos.provider.recovered", True)
        state["span"].set_attribute("theos.provider.transient_retries", retries)
        state["span"].set_attribute("theos.provider.status_code", 200)
        for key in ("provider_error_type", "provider_code"):
            last = state.get("last_failure", {}).get(key)
            if last:
                state["span"].set_attribute("theos.provider.last_failure_" + key, last)
            state["span"].set_attribute("theos.provider." + key, "")
            state["diagnostics"].pop(key, None)


@contextmanager
def observe(tracing, span):
    state = {
        "tracing": tracing,
        "span": span,
        "diagnostics": {},
        "requests": [],
        "started": time.monotonic(),
    }
    token = OBSERVATION.set(state)
    try:
        yield state
    finally:
        for request_span in state["requests"]:
            tracing.failed(request_span, "IncompleteRequest")
            request_span.end()
        OBSERVATION.reset(token)


async def request_hook(request):
    state = OBSERVATION.get()
    if state is None:
        return
    request.extensions["theos_started"] = time.monotonic()
    attempt = state["diagnostics"].get("attempt", 0) + 1
    for key in (
        "status_code",
        "http_status",
        "request_id",
        "generation_id",
        "provider_name",
        "provider_error_type",
        "provider_code",
    ):
        state["diagnostics"].pop(key, None)
    annotate({"attempt": attempt, "provider_stage": "request"})
    if state["tracing"].tracer:
        from opentelemetry.trace import SpanKind

        span = state["tracing"].tracer.start_span(
            "provider HTTP request",
            kind=SpanKind.CLIENT,
            attributes={
                **(state["tracing"].correlation.get() or {}),
                "theos.provider.attempt": attempt,
            },
        )
        state["requests"].append(span)
        request.extensions["theos_request_span"] = span


async def response_hook(response):
    state = OBSERVATION.get()
    if state is None:
        return
    values = {
        "http_status": response.status_code,
        "request_id": response.headers.get("x-request-id"),
        "generation_id": response.headers.get("x-generation-id"),
    }
    annotate(values)
    span = response.request.extensions.get("theos_request_span")
    if span is not None:
        for key, value in clean(values).items():
            span.set_attribute("theos.provider." + key, value)
        if response.status_code >= 400:
            state["tracing"].failed(span, "HTTPStatusError")
        span.end()
        state["requests"].remove(span)
    if state["span"] is not None:
        state["span"].set_attribute(
            "theos.provider.response_headers_seconds", time.monotonic() - state["started"]
        )
        state["span"].add_event(
            "provider response headers", {"http.response.status_code": response.status_code}
        )


def chunk(data):
    annotate(
        {
            "generation_id": data.get("id"),
            "provider_name": data.get("provider"),
            "provider_stage": "stream",
        }
    )
