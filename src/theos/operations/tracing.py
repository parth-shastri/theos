"""Runtime-owned OpenTelemetry spans with content-free OTLP/HTTP export."""

import asyncio
import logging
import time
from contextlib import aclosing, contextmanager
from contextvars import ContextVar
from dataclasses import replace
from importlib.metadata import version
from uuid import uuid4

from harness.events import GenerationComplete, _tool_scope
from harness.model import collect_model_stream

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
            token = None
            if root:
                token = self.correlation.set(
                    {
                        key: attributes[key]
                        for key in ("gen_ai.conversation.id", "theos.turn.id")
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

    @staticmethod
    def failed(span, error_type):
        """Mark an error without sending its payload or stack trace."""
        if span is not None:
            from opentelemetry.trace import StatusCode

            span.set_attribute("error.type", error_type)
            span.set_status(StatusCode.ERROR)

    def turn(self, session, scheduled, agent_name):
        return self.span(
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
        )

    def finish_turn(self, status):
        if self.tracer is not None:
            from opentelemetry.trace import get_current_span

            span = get_current_span()
            span.set_attribute("theos.turn.status", status)
            if status in {"failed", "interrupted", "uncertain"}:
                self.failed(span, status)

    def model(self, model):
        return TracedModel(self, model) if self.tracer is not None else model

    def tool(self, original):
        if self.tracer is None:
            return original

        async def execute(args, ctx):
            attrs = {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": original.name}
            if call_id := _tool_scope.get():
                attrs["gen_ai.tool.call.id"] = call_id
            with self.span(f"execute_tool {original.name}", attrs) as span:
                result = await original.execute(args, ctx)
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

    def __init__(self, tracing, model):
        self.tracing, self.model = tracing, model

    def __getattr__(self, name):
        return getattr(self.model, name)

    async def stream(self, request):
        attrs = {
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": self.model.provider,
            "gen_ai.request.model": self.model.model_id,
        }
        with self.tracing.span(f"chat {self.model.model_id}", attrs, client=True) as span:
            started = time.monotonic()
            first = True
            complete = False
            async with aclosing(self.model.stream(request)) as stream:
                async for event in stream:
                    if first:
                        span.set_attribute(
                            "gen_ai.response.time_to_first_chunk", time.monotonic() - started
                        )
                        first = False
                    if isinstance(event, GenerationComplete):
                        complete = True
                        for key, attribute in {
                            "input_tokens": "input_tokens",
                            "output_tokens": "output_tokens",
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
            if not complete:
                self.tracing.failed(span, "IncompleteModelStream")

    async def generate(self, request):
        async with aclosing(self.stream(request)) as stream:
            return await collect_model_stream(stream)

    async def estimate_tokens(self, request):
        return await self.model.estimate_tokens(request)
