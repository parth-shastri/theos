"""Send a disposable fake-model turn to an OTLP receiver, without model API calls."""

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from harness import AssistantMessage, ToolCall
from harness.testing import FakeModel
from theos.runtime import Runtime
from theos.settings import Settings, TracingSettings
from theos.storage.database import Database


async def check(endpoint, viewer):
    scripts = [
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall(
                        "delegate-check", "delegate_tasks", {"tasks": ["Check one", "Check two"]}
                    )
                ]
            ),
            AssistantMessage("Check complete"),
        ],
        [
            AssistantMessage(tool_calls=[ToolCall("child-one", "list_skills", {})]),
            AssistantMessage("One complete"),
        ],
        [
            AssistantMessage(tool_calls=[ToolCall("child-two", "list_skills", {})]),
            AssistantMessage("Two complete"),
        ],
    ]

    class DelayedModel(FakeModel):
        async def stream(self, request):
            await asyncio.sleep(0.1)
            async for event in super().stream(request):
                yield event

    @asynccontextmanager
    async def factory(*args):
        yield DelayedModel(scripts.pop(0))

    with TemporaryDirectory(prefix="theos-tracing-check-") as directory:
        settings = Settings(
            _env_file=None,
            data_dir=Path(directory),
            provider="fake",
            auto_titles=False,
            tracing=TracingSettings(enabled=True, endpoint=endpoint),
        )
        db = Database(settings.data_dir)
        runtime = Runtime(settings, db, models=factory)
        local = InMemorySpanExporter()
        runtime.tracing.provider.add_span_processor(SimpleSpanProcessor(local))
        try:
            row = db.create_session("trace-check", "fake-1", "default")
            turn = runtime.start("trace-check", row["id"], "Check delegated trace ownership")
            events = [event async for event in turn.events()]
            await turn.task
            assert events[-1]["status"] == "completed"
        finally:
            await runtime.close()
            db.close()
        spans = local.get_finished_spans()
        root = next(s for s in spans if s.parent is None)
        trace_id = format(root.context.trace_id, "032x")
        print(
            json.dumps(
                {
                    "trace_id": trace_id,
                    "spans": len(spans),
                    "viewer": f"{viewer.rstrip('/')}/trace/{trace_id}",
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:4318/v1/traces")
    parser.add_argument("--viewer", default="http://127.0.0.1:16686")
    args = parser.parse_args()
    asyncio.run(check(args.endpoint, args.viewer))
