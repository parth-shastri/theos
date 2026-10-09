"""Framework-neutral renderer composition and adapter tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from renderer import (
    CompositeRenderer,
    LangGraphAdapter,
    ModelFinished,
    ModelStarted,
    RenderEvent,
    RunFinished,
    RunStarted,
    SmolAgentsAdapter,
    TextDelta,
    ToolFinished,
    ToolStarted,
    make_event_handler,
    render_stream,
)


@dataclass
class CaptureRenderer:
    events: list[RenderEvent] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)
    closed: bool = False

    def handle(self, event: RenderEvent) -> None:
        self.events.append(event)

    def fail(self, error: BaseException) -> None:
        self.errors.append(error)

    def close(self) -> None:
        self.closed = True


async def test_one_call_renders_a_plain_sync_stream() -> None:
    capture = CaptureRenderer()

    result = await render_stream(
        iter(["Hello", " world"]),
        renderer=capture,
        title="Portable agent",
        prompt="Say hello",
    )

    assert result == " world"
    assert capture.events == [
        RunStarted("Portable agent", "Say hello"),
        TextDelta("Hello"),
        TextDelta(" world"),
        RunFinished("completed", " world"),
    ]
    assert capture.closed


async def test_custom_adapter_is_only_one_function() -> None:
    capture = CaptureRenderer()
    chunks = [
        {"kind": "token", "value": "custom "},
        {"kind": "token", "value": "agent"},
        {"kind": "done", "value": {"answer": 42}},
    ]

    def adapt(chunk: dict[str, Any]):
        if chunk["kind"] == "token":
            return TextDelta(chunk["value"])
        return RunFinished("completed", chunk["value"])

    result = await render_stream(chunks, adapter=adapt, renderer=capture)

    assert result == {"answer": 42}
    assert [event.text for event in capture.events if isinstance(event, TextDelta)] == [
        "custom ",
        "agent",
    ]


def test_langgraph_adapter_handles_message_and_tool_streams() -> None:
    adapter = LangGraphAdapter()

    message = type("AIMessageChunk", (), {"content": "token"})()
    assert adapter((message, {"langgraph_node": "agent"})) == TextDelta("token")
    assert adapter(
        {
            "event": "on_tool_start",
            "name": "search",
            "run_id": "call-1",
            "data": {"input": {"query": "agents"}},
        }
    ) == ToolStarted("call-1", "search", {"query": "agents"})
    assert adapter(
        {
            "event": "on_tool_end",
            "name": "search",
            "run_id": "call-1",
            "data": {"output": "found"},
        }
    ) == ToolFinished("call-1", "search", "found")


def test_langgraph_adapter_normalizes_nested_cached_token_usage() -> None:
    adapter = LangGraphAdapter()

    event = adapter(
        {
            "event": "on_chat_model_end",
            "data": {
                "output": {
                    "content": "done",
                    "usage_metadata": {
                        "input_tokens": 120,
                        "output_tokens": 8,
                        "input_token_details": {
                            "cache_read": 90,
                            "cache_creation": 12,
                        },
                    },
                }
            },
        }
    )

    assert event == ModelFinished(
        text="done",
        usage={
            "input_tokens": 120,
            "output_tokens": 8,
            "cache_read_tokens": 90,
            "cache_write_tokens": 12,
        },
    )


def test_json_event_protocol_is_framework_independent() -> None:
    adapter = LangGraphAdapter()

    assert adapter({"type": "text_delta", "text": "portable"}) == TextDelta("portable")
    assert adapter(
        {
            "type": "tool_finished",
            "name": "fetch",
            "toolCallId": "call-2",
            "data": {"output": {"ok": True}, "status": "completed"},
        }
    ) == ToolFinished("call-2", "fetch", '{"ok": true}')


def test_smolagents_adapter_uses_public_stream_step_shapes() -> None:
    adapter = SmolAgentsAdapter()
    delta = type("ChatMessageStreamDelta", (), {"content": "hello"})()
    final = type("FinalAnswerStep", (), {"output": "done"})()

    delta_events = list(adapter(delta) or [])
    final_events = list(adapter(final) or [])

    assert isinstance(delta_events[0], ModelStarted)
    assert delta_events[1] == TextDelta("hello")
    assert final_events == [
        ModelFinished(text="done"),
        RunFinished("completed", "done"),
    ]


def test_composite_renderer_fans_out_normalized_events() -> None:
    first = CaptureRenderer()
    second = CaptureRenderer()
    composite = CompositeRenderer(first, second)
    event = ModelFinished(text="done")

    composite.handle(event)
    composite.close()

    assert first.events == second.events == [event]
    assert first.closed and second.closed


def test_push_style_streams_can_use_an_adapted_handler() -> None:
    capture = CaptureRenderer()
    handle = make_event_handler(
        capture,
        adapter=lambda chunk: TextDelta(chunk["token"]),
    )

    handle({"token": "pushed"})

    assert capture.events == [TextDelta("pushed")]
