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
from tests.context_fixtures import long_history
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
    assert root.attributes["theos.budget.total.limit"] == -1
    assert root.attributes["theos.budget.enforced"] is False
    assert root.attributes["theos.budget.total.used"] == 2
    assert root.attributes["theos.budget.research.limit"] == -1
    assert root.attributes["theos.budget.research.used"] == 2
    assert root.attributes["theos.budget.compaction.limit"] == -1
    assert root.attributes["theos.budget.compaction.used"] == 0
    assert root.attributes["theos.budget.recovery.used"] == 0
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


async def test_trace_keeps_the_actual_tool_count_when_content_keeps_only_sixteen(runtime, exporter):
    from harness import ModelRequest

    runtime.tracing.settings.capture_content = True
    model = runtime.tracing.model(
        FakeModel([AssistantMessage(tool_calls=[ToolCall(str(i), "read", {}) for i in range(35)])])
    )
    events = [event async for event in model.stream(ModelRequest([UserMessage("Read records.")]))]
    assert events
    output = await spans(runtime, exporter)
    span = output[-1]
    assert span.attributes["theos.model.tool_call_count"] == 35
    content = json.loads(span.attributes["gen_ai.output.messages"])
    assert len(content[0]["parts"]) == 16


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
    delegates = [
        s for s in output if s.name in {"invoke_agent research 1", "invoke_agent research 2"}
    ]
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


async def test_named_delegates_capture_tasks_and_preserve_child_identity(
    runtime, scripted_models, exporter
):
    runtime.tracing.settings.capture_content = True
    scripted_models.responses.extend(
        [
            [
                AssistantMessage(
                    tool_calls=[
                        ToolCall(
                            "delegate-id",
                            "delegate_tasks",
                            {
                                "tasks": [
                                    {"name": "Rain analyst", "task": "Assess rainfall"},
                                    {"name": "Heat analyst", "task": "Assess heat"},
                                ]
                            },
                        )
                    ]
                ),
                AssistantMessage("Comparison"),
            ],
            [AssistantMessage("Rain findings")],
            [AssistantMessage("Heat findings")],
        ]
    )
    result = await collect(runtime.start("alice", session(runtime)["id"], "Compare weather"))
    assert result[-1]["status"] == "completed"
    output = await spans(runtime, exporter)
    delegates = [
        s for s in output if s.name in {"invoke_agent Rain analyst", "invoke_agent Heat analyst"}
    ]
    assert len(delegates) == 2
    for delegate in delegates:
        assert "Assess" in delegate.attributes["gen_ai.input.messages"]
        assert "findings" in delegate.attributes["gen_ai.output.messages"]
        children = [s for s in output if s.parent and s.parent.span_id == delegate.context.span_id]
        assert children and all(
            s.attributes["gen_ai.agent.name"] == delegate.attributes["gen_ai.agent.name"]
            for s in children
        )
    tool_span = next(s for s in output if s.name == "execute_tool delegate_tasks")
    assert (
        json.loads(tool_span.attributes["gen_ai.tool.call.arguments"])["tasks"][0]["name"]
        == "Rain analyst"
    )
    assert json.loads(tool_span.attributes["gen_ai.tool.call.result"])[0]["name"] == "Rain analyst"
    final = next(
        s
        for s in output
        if s.attributes.get("gen_ai.output.messages")
        and "Comparison" in s.attributes["gen_ai.output.messages"]
    )
    assert final.attributes["gen_ai.agent.name"] == "Theos"


async def test_content_capture_bounds_wire_fields_and_links_tool_messages(
    runtime, scripted_models, exporter
):
    runtime.tracing.settings.capture_content = True
    runtime.tracing.settings.content_max_bytes = 512
    runtime.tracing.settings.span_content_max_bytes = 1024
    scripted_models.responses.append(
        [
            AssistantMessage(tool_calls=[ToolCall("skills-id", "list_skills", {})]),
            AssistantMessage("🙂" * 10000, reasoning="Do not capture private reasoning"),
        ]
    )
    result = await collect(runtime.start("alice", session(runtime)["id"], "List skills"))
    assert result[-1]["status"] == "completed"
    output = await spans(runtime, exporter)
    assert any(s.attributes.get("theos.content.truncated") for s in output)
    for s in output:
        fields = {
            k: v
            for k, v in s.attributes.items()
            if k
            in {
                "gen_ai.input.messages",
                "gen_ai.output.messages",
                "gen_ai.system_instructions",
                "gen_ai.tool.call.arguments",
                "gen_ai.tool.call.result",
            }
        }
        assert sum(len(v.encode("utf-8")) for v in fields.values()) <= 1024
        for value in fields.values():
            assert len(value.encode("utf-8")) <= 512
            json.loads(value)
    tool_span = next(s for s in output if s.name == "execute_tool list_skills")
    assert tool_span.attributes["gen_ai.tool.type"] == "function"
    assert json.loads(tool_span.attributes["gen_ai.tool.call.arguments"]) == {}
    assert json.loads(tool_span.attributes["gen_ai.tool.call.result"]) == []
    request = next(
        s for s in output if '"tool_call"' in s.attributes.get("gen_ai.output.messages", "")
    )
    assert "skills-id" in request.attributes["gen_ai.output.messages"]
    assert "Do not capture" not in repr([dict(s.attributes) for s in output])


def test_bounded_capture_handles_cycles_large_unicode_and_secret_keys():
    from theos.operations.trace_content import bounded_json

    value = {"text": "🙂" * 100000, "api_key": "never-export"}
    value["cycle"] = value
    encoded, truncated = bounded_json(value, 512)
    assert truncated and len(encoded.encode("utf-8")) <= 512
    json.loads(encoded)
    assert "never-export" not in encoded


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
    assert not any(event["type"] == "error" for event in result)
    output = await spans(runtime, exporter)
    assert len(output) == 3
    assert next(s for s in output if s.parent is None).attributes["theos.turn.status"] == "failed"
    assert all(s.end_time is not None and not s.events for s in output)
    assert "secret" not in repr([dict(s.attributes) for s in output])
    failed = next(s for s in output if s.attributes.get("error.type") == "RuntimeError")
    assert failed.status.status_code == StatusCode.ERROR
    final = next(s for s in output if s.name == "finalize answer")
    assert final.attributes["theos.recovery.reason"] == "provider_error"
    assert final.attributes["theos.recovery.mode"] == "failure"


async def test_budget_recovery_exports_partial_status_and_final_model_parent(
    runtime, scripted_models, exporter
):
    runtime.enforce_budgets = True
    runtime.settings.max_model_calls = 2
    scripted_models.responses.extend(
        [
            [AssistantMessage(tool_calls=[ToolCall("read", "get_preferences", {})])],
            [AssistantMessage("The preferences were read. More research remains incomplete.")],
        ]
    )
    result = await collect(runtime.start("alice", session(runtime)["id"], "Check my preferences."))
    assert result[-1]["status"] == "partial"
    output = await spans(runtime, exporter)
    root = next(s for s in output if s.parent is None)
    assert root.attributes["theos.turn.status"] == "partial"
    final = next(s for s in output if s.name == "finalize answer")
    assert root.attributes["theos.budget.total.used"] == 2
    assert root.attributes["theos.budget.research.used"] == 1
    assert root.attributes["theos.budget.recovery.used"] == 1
    assert final.attributes["theos.recovery.reason"] == "budget_limit"
    assert final.attributes["theos.recovery.mode"] == "model"
    final_model = next(s for s in output if s.parent and s.parent.span_id == final.context.span_id)
    assert final_model.name == "chat fake-1"
    assert final_model.attributes["gen_ai.agent.name"] == "Theos"
    assert all(s.context.trace_id == root.context.trace_id for s in output)


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


async def test_approval_pauses_without_executing_tool(
    runtime, scripted_models, exporter, checkout_tool
):
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[ToolCall("delete", "zepto_confirm_cart", {"name": "secret-table"})]
            )
        ]
    )
    result = await collect(runtime.start("alice", session(runtime)["id"], "Delete"))
    assert result[-1]["status"] == "waiting_for_approval"
    output = await spans(runtime, exporter)
    tool = next(s for s in output if s.name == "execute_tool zepto_confirm_cart")
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
                AssistantMessage("Final reply"),
            ]
        )
    )
    history = [*long_history(), UserMessage("Continue")]
    agent = Agent(
        model,
        context_window=100000,
        reserved_output_tokens=256,
        compaction=CompactionConfig("Summarize", {"max_tokens": 256}, 128),
    )
    with runtime.tracing.turn(session(runtime), False, "Theos"):
        await agent.run(history, memory=ContextMemory(), budget=Budget(8))
    output = await spans(runtime, exporter)
    root = next(s for s in output if s.parent is None)
    models = [s for s in output if s.name.startswith("chat ")]
    assert len(models) == 2
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
