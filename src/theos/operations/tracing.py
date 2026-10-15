"""Runtime-owned OpenTelemetry spans with bounded OTLP/HTTP content export."""

import asyncio
import logging
import time
from contextlib import aclosing, contextmanager
from contextvars import ContextVar
from dataclasses import replace
from importlib.metadata import version
from uuid import uuid4

from harness import SystemMessage, ToolOutput
from harness.events import (
    GenerationComplete,
    ModelCalled,
    ReasoningDelta,
    TextDelta,
    ToolCallDelta,
    _tool_scope,
)
from harness.model import collect_model_stream

from .trace_content import bounded_json, message_content

logger = logging.getLogger("theos")


class SafeExporter:
    """Report export failures without the receiver's response or credentials."""

    def __init__(self, exporter):
        self.exporter = exporter

    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult

        try:
            result = self.exporter.export(spans)
        except Exception as error:
            logger.warning("trace_export_failed", extra={"error_type": type(error).__name__})
            return SpanExportResult.FAILURE
        if result == SpanExportResult.FAILURE:
            logger.warning("trace_export_failed", extra={"error_type": "ExportFailure"})
        return result

    def shutdown(self):
        try:
            self.exporter.shutdown()
        except Exception as error:
            logger.warning("trace_export_failed", extra={"error_type": type(error).__name__})


class Tracing:
    """Own a provider per runtime. Never replace the process-wide provider."""

    def __init__(self, settings, *, exporter=None):
        self.provider = None
        self.tracer = None
        self.correlation = ContextVar("theos_trace_correlation", default=None)
        self.capture_budget = ContextVar("theos_trace_content_budget", default=None)
        self.turn_timing = ContextVar("theos_trace_turn_timing", default=None)
        self.settings = settings
        if not settings.enabled:
            return
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        # Bound the queue and export timeout. Network work runs outside the turn task.
        self.provider = TracerProvider(
            resource=Resource(
                {"service.name": settings.service_name, "service.version": version("theos")}
            ),
            sampler=TraceIdRatioBased(settings.sample_ratio),
            shutdown_on_exit=False,
        )
        self.provider.add_span_processor(
            BatchSpanProcessor(
                SafeExporter(
                    exporter
                    if exporter is not None
                    else OTLPSpanExporter(
                        endpoint=settings.endpoint,
                        headers={
                            key: value.get_secret_value() for key, value in settings.headers.items()
                        },
                        timeout=settings.timeout,
                    ),
                ),
                max_queue_size=2048,
                max_export_batch_size=256,
                schedule_delay_millis=1000,
                export_timeout_millis=int(settings.timeout * 1000),
            )
        )
        self.tracer = self.provider.get_tracer("theos.runtime", version("theos"))

    @contextmanager
    def span(self, name, attributes=None, *, client=False, root=False):
        """Keep only fixed attributes and exception types, never exception text."""
        if self.tracer is None:
            yield None
            return
        from opentelemetry.context import Context
        from opentelemetry.trace import SpanKind

        attributes = {**({} if root else self.correlation.get() or {}), **(attributes or {})}
        with self.tracer.start_as_current_span(
            name,
            context=Context() if root else None,
            kind=SpanKind.CLIENT if client else SpanKind.INTERNAL,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            budget_token = self.capture_budget.set(
                {"remaining": self.settings.span_content_max_bytes}
            )
            token = None
            if root or "gen_ai.agent.name" in attributes:
                token = self.correlation.set(
                    {
                        key: attributes[key]
                        for key in ("gen_ai.conversation.id", "theos.turn.id", "gen_ai.agent.name")
                        if key in attributes
                    }
                )
            try:
                yield span
            except BaseException as error:
                self.failed(span, type(error).__name__)
                if attributes and attributes.get("gen_ai.operation.name") == "execute_tool":
                    span.set_attribute(
                        "theos.tool.status",
                        "unknown"
                        if isinstance(error, (asyncio.CancelledError, TimeoutError))
                        or type(error).__name__ == "OutcomeUnknown"
                        else "failed",
                    )
                raise
            finally:
                if token is not None:
                    self.correlation.reset(token)
                self.capture_budget.reset(budget_token)

    def content(self, span, key, value):
        """Capture only when enabled and sampled. Each span owns a separate budget."""
        if span is None or not span.is_recording() or not self.settings.capture_content:
            return
        budget = self.capture_budget.get()
        limit = min(self.settings.content_max_bytes, budget["remaining"])
        if limit < 256:
            span.set_attribute("theos.content.truncated", True)
            return
        try:
            encoded, truncated = bounded_json(value, limit)
        except (ValueError, TypeError, RecursionError):
            span.set_attribute("theos.content.capture_error", True)
            return
        size = len(encoded.encode("utf-8"))
        budget["remaining"] -= size
        span.set_attribute(key, encoded)
        span.set_attribute(
            "theos.content.captured_bytes",
            self.settings.span_content_max_bytes - budget["remaining"],
        )
        if truncated:
            span.set_attribute("theos.content.truncated", True)

    @staticmethod
    def failed(span, error_type):
        """Mark an error without sending its payload or stack trace."""
        if span is not None:
            from opentelemetry.trace import StatusCode

            span.set_attribute("error.type", error_type)
            span.set_status(StatusCode.ERROR)

    @contextmanager
    def turn(self, session, scheduled, agent_name, *, started_at=None):
        with self.span(
            f"invoke_agent {agent_name}",
            {
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": agent_name,
                "gen_ai.conversation.id": session["id"],
                "theos.turn.id": uuid4().hex,
                "theos.transport": session["channel"],
                "theos.turn.scheduled": scheduled,
            },
            root=True,
        ) as span:
            timing = {
                "started_at": time.monotonic() if started_at is None else started_at,
                "span": span,
                "recorded": set(),
            }
            token = self.turn_timing.set(timing)
            try:
                yield span
            finally:
                self.turn_timing.reset(token)

    def turn_event(self, event):
        """Record query-to-first-model, reasoning, and text timings on the turn span."""
        if self.tracer is None:
            return
        if isinstance(event, ModelCalled):
            attribute, name = "theos.turn.time_to_first_model_call_seconds", "model_call"
        elif isinstance(event, ReasoningDelta):
            attribute, name = (
                "theos.turn.time_to_first_reasoning_chunk_seconds",
                "reasoning",
            )
        elif isinstance(event, TextDelta):
            attribute, name = "theos.turn.time_to_first_text_chunk_seconds", "text"
        elif isinstance(event, ToolCallDelta):
            attribute, name = None, None
        else:
            return
        timing = self.turn_timing.get()
        if timing is None:
            return
        elapsed = max(0, time.monotonic() - timing["started_at"])
        if isinstance(event, (ReasoningDelta, TextDelta, ToolCallDelta)):
            if "stream_chunk" not in timing["recorded"]:
                timing["span"].set_attribute(
                    "theos.turn.time_to_first_stream_chunk_seconds", elapsed
                )
                timing["recorded"].add("stream_chunk")
        if isinstance(event, TextDelta):
            timing["last_text_chunk_seconds"] = elapsed
        if name is None or name in timing["recorded"]:
            return
        timing["span"].set_attribute(
            attribute, elapsed
        )
        timing["recorded"].add(name)

    def finish_turn(self, status, budget_attributes=None):
        if self.tracer is not None:
            from opentelemetry.trace import get_current_span

            span = get_current_span()
            span.set_attribute("theos.turn.status", status)
            if budget_attributes:
                span.set_attributes(budget_attributes)
            timing = self.turn_timing.get()
            if timing is not None:
                timing["span"].set_attribute(
                    "theos.turn.duration_seconds",
                    max(0, time.monotonic() - timing["started_at"]),
                )
                if "last_text_chunk_seconds" in timing:
                    timing["span"].set_attribute(
                        "theos.turn.time_to_last_text_chunk_seconds",
                        timing["last_text_chunk_seconds"],
                    )
            if status in {"failed", "interrupted", "uncertain"}:
                self.failed(span, status)

    def model(self, model, *, reasoning=None, attributes=None):
        return (
            TracedModel(self, model, reasoning=reasoning, attributes=attributes)
            if self.tracer is not None
            else model
        )

    def tool(self, original):
        if self.tracer is None:
            return original

        async def execute(args, ctx):
            attrs = {
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": original.name,
                "gen_ai.tool.type": "function",
            }
            if call_id := _tool_scope.get():
                attrs["gen_ai.tool.call.id"] = call_id
            with self.span(f"execute_tool {original.name}", attrs) as span:
                self.content(span, "gen_ai.tool.call.arguments", args)
                result = await original.execute(args, ctx)
                self.content(
                    span,
                    "gen_ai.tool.call.result",
                    result.content if isinstance(result, ToolOutput) else result,
                )
                span.set_attribute("theos.tool.status", "completed")
                return result

        return replace(original, execute=execute)

    async def close(self):
        """Drain the batch processor without blocking the event loop."""
        if self.provider is not None:
            provider, self.provider = self.provider, None
            await asyncio.to_thread(provider.shutdown)


class TracedModel:
    """Preserve the model interface and trace all generation paths."""

    def __init__(self, tracing, model, *, reasoning=None, attributes=None):
        self.tracing, self.model = tracing, model
        self.reasoning = reasoning
        self.attributes = dict(attributes or {})

    def __getattr__(self, name):
        return getattr(self.model, name)

    async def stream(self, request):
        from .provider_diagnostics import failure, observe

        attrs = {
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": self.model.provider,
            "gen_ai.request.model": self.model.model_id,
            **self.attributes,
        }
        if self.reasoning is not None:
            attrs["theos.model.reasoning_effort"] = self.reasoning
        with (
            self.tracing.span(f"chat {self.model.model_id}", attrs, client=True) as span,
            observe(self.tracing, span),
        ):
            if self.tracing.settings.capture_content and span.is_recording():
                messages = request.messages[-32:]
                self.tracing.content(
                    span,
                    "gen_ai.system_instructions",
                    [
                        {"type": "text", "content": m.content}
                        for m in request.messages[:32]
                        if isinstance(m, SystemMessage)
                    ],
                )
                self.tracing.content(
                    span,
                    "gen_ai.input.messages",
                    [message_content(m) for m in messages if not isinstance(m, SystemMessage)],
                )
                if len(request.messages) > 32:
                    span.set_attribute("theos.content.truncated", True)
            started = time.monotonic()
            first = True
            first_reasoning = True
            first_text = True
            first_tool_call = True
            last_text_elapsed = None
            complete = False
            try:
                async with aclosing(self.model.stream(request)) as stream:
                    async for event in stream:
                        elapsed = time.monotonic() - started
                        if isinstance(event, TextDelta):
                            last_text_elapsed = elapsed
                        if first:
                            span.set_attribute(
                                "gen_ai.response.time_to_first_chunk", elapsed
                            )
                            first = False
                        if isinstance(event, ReasoningDelta) and first_reasoning:
                            span.set_attribute(
                                "theos.model.time_to_first_reasoning_chunk", elapsed
                            )
                            first_reasoning = False
                        elif isinstance(event, TextDelta) and first_text:
                            span.set_attribute("theos.model.time_to_first_text_chunk", elapsed)
                            first_text = False
                        elif isinstance(event, ToolCallDelta) and first_tool_call:
                            span.set_attribute(
                                "theos.model.time_to_first_tool_call_chunk", elapsed
                            )
                            first_tool_call = False
                        if isinstance(event, GenerationComplete):
                            span.set_attribute(
                                "theos.model.time_to_response_complete_seconds", elapsed
                            )
                            if last_text_elapsed is not None:
                                span.set_attribute(
                                    "theos.model.time_to_last_text_chunk_seconds",
                                    last_text_elapsed,
                                )
                            span.set_attribute(
                                "theos.model.tool_call_count", len(event.message.tool_calls)
                            )
                            self.tracing.content(
                                span, "gen_ai.output.messages", [message_content(event.message)]
                            )
                            complete = True
                            for key, attribute in {
                                "input_tokens": "input_tokens",
                                "output_tokens": "output_tokens",
                                "reasoning_tokens": "reasoning.output_tokens",
                                "cache_read_tokens": "cache_read.input_tokens",
                                "cache_write_tokens": "cache_write.input_tokens",
                            }.items():
                                span.set_attribute(
                                    f"gen_ai.usage.{attribute}", event.message.usage.get(key, 0)
                                )
                            if event.message.stop_reason:
                                span.set_attribute(
                                    "gen_ai.response.finish_reasons", [event.message.stop_reason]
                                )
                        yield event
            except Exception as error:
                failure(error)
                raise
            if not complete:
                self.tracing.failed(span, "IncompleteModelStream")

    async def generate(self, request):
        async with aclosing(self.stream(request)) as stream:
            return await collect_model_stream(stream)

    async def estimate_tokens(self, request):
        return await self.model.estimate_tokens(request)
