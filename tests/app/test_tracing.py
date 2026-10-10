"""Verify waterfall ownership, redaction, cancellation, and real OTLP wire data."""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from pydantic import ValidationError

from harness import (
    Agent,
    AssistantMessage,
    Budget,
    CompactionConfig,
    ContextMemory,
    ToolCall,
    UserMessage,
    tool,
)
from harness.testing import FakeModel
from theos.operations.tracing import Tracing
from theos.settings import TracingSettings

from .conftest import collect


@pytest.fixture
def exporter(runtime):
    output = InMemorySpanExporter()
    runtime.tracing = Tracing(TracingSettings(enabled=True), exporter=output)
    return output


async def spans(runtime, exporter):
    await asyncio.to_thread(runtime.tracing.provider.force_flush)
    return exporter.get_finished_spans()


def session(runtime):
    return runtime.db.create_session("alice", "test-model", "default")


async def test_turn_models_and_tool_are_siblings(runtime, scripted_models, exporter):
    row = session(runtime)
    scripted_models.responses.append(
        [
            AssistantMessage(tool_calls=[ToolCall("read", "get_preferences", {})]),
            AssistantMessage(
                "private reply",
                reasoning="private reasoning",
                usage={"input_tokens": 9, "output_tokens": 4, "cache_read_tokens": 2},
            ),
        ]
    )
    result = await collect(runtime.start("alice", row["id"], "private prompt"))
    assert result[-1]["status"] == "completed"
    output = await spans(runtime, exporter)
    root = next(s for s in output if s.parent is None)
    assert root.attributes["theos.turn.status"] == "completed"
    assert root.attributes["gen_ai.conversation.id"] == row["id"]
    children = [s for s in output if s.parent is not None]
    assert len(children) == 3
    assert all(s.parent.span_id == root.context.span_id for s in children)
    assert all(s.context.trace_id == root.context.trace_id for s in output)
    assert all(root.start_time <= s.start_time <= s.end_time <= root.end_time for s in children)
    model = next(s for s in children if s.attributes.get("gen_ai.usage.input_tokens") == 9)
    assert model.attributes["gen_ai.usage.output_tokens"] == 4
    assert model.attributes["gen_ai.usage.cache_read.input_tokens"] == 2
    serialized = repr([(dict(s.attributes), s.events) for s in output])
    for private in ("private prompt", "private reply", "private reasoning", "alice"):
        assert private not in serialized


async def test_parallel_delegates_keep_separate_model_and_tool_parents(runtime, exporter):
    both_started = asyncio.Event()
    count = 0
    models = []

    class ChildModel(FakeModel):
        async def stream(self, request):
            nonlocal count
            if not self.requests:
                count += 1
                if count == 2:
                    both_started.set()
                await both_started.wait()
            async for event in super().stream(request):
                yield event

    @asynccontextmanager
    async def factory(settings, model_id, reasoning):
        if not models:
            model = FakeModel(
                [
                    AssistantMessage(
                        tool_calls=[
                            ToolCall(
                                "delegation",
                                "delegate_tasks",
                                {"tasks": ["secret task one", "secret task two"]},
                            )
                        ]
                    ),
                    AssistantMessage("Parent answer"),
                ]
            )
        else:
            model = ChildModel(
                [
                    AssistantMessage(tool_calls=[ToolCall("same-child-id", "list_skills", {})]),
                    AssistantMessage("Child answer"),
                ]
            )
        models.append(model)
        yield runtime.tracing.model(model)

    runtime.models = factory
    await asyncio.wait_for(collect(runtime.start("alice", session(runtime)["id"], "Delegate")), 5)
    output = await spans(runtime, exporter)
    root = next(s for s in output if s.parent is None)
    delegate_tool = next(s for s in output if s.name == "execute_tool delegate_tasks")
    assert delegate_tool.parent.span_id == root.context.span_id
    delegates = [s for s in output if s.attributes.get("gen_ai.agent.name") == "research"]
    assert len(delegates) == 2
    assert all(s.parent.span_id == delegate_tool.context.span_id for s in delegates)
    for delegate in delegates:
        children = [s for s in output if s.parent and s.parent.span_id == delegate.context.span_id]
        assert len(children) == 3
        assert sum(s.name == "execute_tool list_skills" for s in children) == 1
    first_calls = sorted(
        [
            s
            for s in output
            if s.name.startswith("chat")
            and s.parent.span_id in {d.context.span_id for d in delegates}
        ],
        key=lambda s: s.start_time,
    )[:2]
    assert first_calls[0].end_time >= first_calls[1].start_time
    assert "secret task" not in repr([dict(s.attributes) for s in output])


async def test_concurrent_turns_and_resume_have_distinct_traces(runtime, exporter):
    first, second = session(runtime), session(runtime)
    await asyncio.gather(
        collect(runtime.start("alice", first["id"], "One")),
        collect(runtime.start("alice", second["id"], "Two")),
    )
    await collect(runtime.start("alice", first["id"], "Again"))
    output = await spans(runtime, exporter)
    roots = [s for s in output if s.parent is None]
    assert len(roots) == 3
    assert len({s.context.trace_id for s in roots}) == 3
    assert len({s.attributes["theos.turn.id"] for s in roots}) == 3
    for model in (s for s in output if s.parent):
        root = next(r for r in roots if r.context.span_id == model.parent.span_id)
        assert root.context.trace_id == model.context.trace_id
        assert (
            model.attributes["gen_ai.conversation.id"] == root.attributes["gen_ai.conversation.id"]
        )
        assert model.attributes["theos.turn.id"] == root.attributes["theos.turn.id"]
    assert sum(r.attributes["gen_ai.conversation.id"] == first["id"] for r in roots) == 2
    with runtime.tracing.span("outside a turn") as outside:
        assert outside.is_recording()
    assert "gen_ai.conversation.id" not in (await spans(runtime, exporter))[-1].attributes


async def test_model_failure_has_sanitized_error_and_closed_root(
    runtime, scripted_models, exporter
):
    scripted_models.responses.append([RuntimeError("secret credential payload")])
    result = await collect(runtime.start("alice", session(runtime)["id"], "secret input"))
    assert result[-1]["status"] == "failed"
    output = await spans(runtime, exporter)
    assert len(output) == 2
    assert all(s.status.status_code == StatusCode.ERROR for s in output)
    assert all(s.end_time is not None and not s.events for s in output)
    assert "secret" not in repr([dict(s.attributes) for s in output])
    assert next(s for s in output if s.parent).attributes["error.type"] == "RuntimeError"


async def test_cancellation_closes_running_model_and_turn(runtime, exporter):
    started = asyncio.Event()

    class BlockedModel(FakeModel):
        async def stream(self, request):
            started.set()
            await asyncio.Event().wait()
            if False:
                yield

    @asynccontextmanager
    async def factory(*args):
        yield runtime.tracing.model(BlockedModel([]))

    runtime.models = factory
    turn = runtime.start("alice", session(runtime)["id"], "Wait")
    await started.wait()
    turn.task.cancel()
    result = await collect(turn)
    await asyncio.gather(turn.task, return_exceptions=True)
    assert result[-1]["status"] == "interrupted"
    output = await spans(runtime, exporter)
    assert len(output) == 2 and all(s.end_time for s in output)
    assert all(s.status.status_code == StatusCode.ERROR for s in output)


async def test_approval_pauses_without_executing_tool(runtime, scripted_models, exporter):
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[ToolCall("delete", "delete_custom_table", {"name": "secret-table"})]
            )
        ]
    )
    result = await collect(runtime.start("alice", session(runtime)["id"], "Delete"))
    assert result[-1]["status"] == "waiting_for_approval"
    output = await spans(runtime, exporter)
    tool = next(s for s in output if s.name == "execute_tool delete_custom_table")
    assert tool.attributes["theos.tool.status"] == "waiting_for_approval"
    assert not runtime.db.rows("SELECT * FROM tool_runs")
    assert "secret-table" not in repr([dict(s.attributes) for s in output])


async def test_export_failure_does_not_fail_turn(runtime, caplog):
    class BrokenExporter(SpanExporter):
        def export(self, batch):
            raise RuntimeError("secret backend response")

    runtime.tracing = Tracing(TracingSettings(enabled=True), exporter=BrokenExporter())
    result = await collect(runtime.start("alice", session(runtime)["id"], "Hello"))
    await asyncio.to_thread(runtime.tracing.provider.force_flush)
    assert result[-1]["status"] == "completed"
    assert "trace_export_failed" in caplog.text
    assert "secret backend response" not in caplog.text


@pytest.mark.parametrize(
    "error,status",
    [
        (ValueError("private tool error"), "failed"),
        (httpx.ReadTimeout("private connection error"), "unknown"),
    ],
)
async def test_tool_errors_and_uncertain_results(runtime, scripted_models, exporter, error, status):
    @tool
    async def checked_tool():
        """Exercise the existing durable tool error boundary."""
        raise error

    async def tools(row):
        return [runtime.journal_tool(checked_tool, row)]

    runtime.tools = tools
    scripted_models.responses.append(
        [
            AssistantMessage(tool_calls=[ToolCall("checked", "checked_tool", {})]),
            AssistantMessage("Handled failure"),
        ]
    )
    await collect(runtime.start("alice", session(runtime)["id"], "Check"))
    output = await spans(runtime, exporter)
    checked = next(s for s in output if s.name == "execute_tool checked_tool")
    assert checked.status.status_code == StatusCode.ERROR
    assert checked.attributes["theos.tool.status"] == status
    root = next(s for s in output if s.parent is None)
    assert root.attributes["theos.turn.status"] == (
        "uncertain" if status == "unknown" else "completed"
    )
    assert "private" not in repr([dict(s.attributes) for s in output])


async def test_title_model_has_its_own_parent_without_duplicate_model_spans(
    runtime, scripted_models, exporter
):
    runtime.settings.auto_titles = True
    scripted_models.responses.append(
        [AssistantMessage("A reply"), AssistantMessage("A useful title")]
    )
    await collect(runtime.start("alice", session(runtime)["id"], "Name this conversation"))
    output = await spans(runtime, exporter)
    root = next(s for s in output if s.parent is None)
    title = next(s for s in output if s.name == "generate_title")
    models = [s for s in output if s.name.startswith("chat ")]
    assert len(output) == 4 and len(models) == 2
    assert title.parent.span_id == root.context.span_id
    assert {s.parent.span_id for s in models} == {root.context.span_id, title.context.span_id}


async def test_compaction_model_calls_remain_in_turn_trace(runtime, exporter):
    model = runtime.tracing.model(
        FakeModel(
            [
                AssistantMessage("First summary"),
                AssistantMessage("Combined summary"),
                AssistantMessage("Final reply"),
            ]
        )
    )
    history = [UserMessage("a" * 5600), AssistantMessage("b" * 5600), UserMessage("Continue")]
    agent = Agent(
        model,
        context_window=2000,
        reserved_output_tokens=256,
        compaction=CompactionConfig("Summarize", {"max_tokens": 256}, 128),
    )
    with runtime.tracing.turn(session(runtime), False, "Theos"):
        await agent.run(history, memory=ContextMemory(), budget=Budget(8))
    output = await spans(runtime, exporter)
    root = next(s for s in output if s.parent is None)
    models = [s for s in output if s.name.startswith("chat ")]
    assert len(models) == 3
    assert all(s.parent.span_id == root.context.span_id for s in models)


async def test_shutdown_flushes_pending_spans(runtime, exporter):
    await collect(runtime.start("alice", session(runtime)["id"], "Hello"))
    await runtime.close()
    assert len(exporter.get_finished_spans()) == 2
    await runtime.tracing.close()


async def test_zero_sampling_preserves_turn(runtime):
    exporter = InMemorySpanExporter()
    runtime.tracing = Tracing(TracingSettings(enabled=True, sample_ratio=0), exporter=exporter)
    result = await collect(runtime.start("alice", session(runtime)["id"], "Hello"))
    assert result[-1]["status"] == "completed"
    assert not await spans(runtime, exporter)


async def test_disabled_tracing_never_creates_exporter(runtime, monkeypatch):
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as module

    def forbidden(**kwargs):
        pytest.fail("Disabled tracing constructed an exporter")

    monkeypatch.setattr(module, "OTLPSpanExporter", forbidden)
    tracing = Tracing(TracingSettings())
    assert tracing.provider is None
    with tracing.span("unused") as span:
        assert span is None
    assert (await collect(runtime.start("alice", session(runtime)["id"], "Hello")))[-1][
        "status"
    ] == "completed"


async def test_otlp_http_protobuf_endpoint_headers_and_payload(runtime):
    captured = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            captured.append(
                (self.path, self.headers, ExportTraceServiceRequest.FromString(payload))
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        runtime.tracing = Tracing(
            TracingSettings(
                enabled=True,
                endpoint=f"http://127.0.0.1:{server.server_port}/v1/traces",
                headers={"Authorization": "Bearer private-export-token"},
            )
        )
        await collect(runtime.start("alice", session(runtime)["id"], "private input"))
        await asyncio.to_thread(runtime.tracing.provider.force_flush)
        path, headers, payload = captured[0]
        assert path == "/v1/traces"
        assert headers["Content-Type"] == "application/x-protobuf"
        assert headers["Authorization"] == "Bearer private-export-token"
        wire_spans = [
            s for r in payload.resource_spans for scope in r.scope_spans for s in scope.spans
        ]
        assert len(wire_spans) == 2
        assert len({s.trace_id for s in wire_spans}) == 1
        assert "private" not in str(payload)
    finally:
        await runtime.tracing.close()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        worker.join()


@pytest.mark.parametrize(
    "changes",
    [
        {"sample_ratio": 1.1},
        {"timeout": 0},
        {"endpoint": "file:///tmp/traces"},
        {"endpoint": "https://user:secret@example.com/v1/traces"},
        {"service_name": " "},
    ],
)
def test_invalid_tracing_settings(changes):
    with pytest.raises(ValidationError):
        TracingSettings(**changes)


def test_authentication_headers_are_redacted():
    settings = TracingSettings(headers={"Authorization": "Bearer private-token"})
    assert "private-token" not in settings.model_dump_json()
    assert json.loads(settings.model_dump_json())["headers"]["Authorization"] == "**********"
