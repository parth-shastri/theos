"""Parent tool ownership must survive nested streams and parallel execution."""

import asyncio

import pytest

from harness import Agent, AssistantMessage, RunContext, ToolCall, UserMessage, tool
from harness.events import ModelResponded, TextDelta, ToolFinished, ToolStarted
from harness.loop import TurnFinished
from harness.testing import FakeModel
from harness.tools import execute_tools
from renderer.adapters import HarnessAdapter


@pytest.mark.asyncio
async def test_parallel_subagents_preserve_event_ownership_and_reset_after_failure():
    entered = 0
    both_entered = asyncio.Event()

    @tool
    def lookup(label: str) -> str:
        """Look up a value."""
        return label

    @tool(parallel_safe=True)
    async def specialist(label: str, ctx: RunContext) -> str:
        """Run a specialist with its own tool."""
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        await both_entered.wait()
        child = Agent(FakeModel([
            AssistantMessage(tool_calls=[ToolCall(f"lookup-{label}", "lookup", {"label": label})]),
            AssistantMessage(text=f"Answer {label}"),
        ]), [lookup])
        async for event in child.run_stream([UserMessage(label)]):
            ctx.emit(event)
        if label == "b":
            raise ValueError("Specialist failed")
        return "complete"

    events = []
    await execute_tools(
        [ToolCall("a", "specialist", {"label": "a"}), ToolCall("b", "specialist", {"label": "b"})],
        [specialist], ctx=RunContext(None, emit=events.append),
    )
    adapter = HarnessAdapter()
    for event in events:
        if isinstance(event, ToolStarted):
            expected = event.call.id.removeprefix("lookup-") if event.call.name == "lookup" else None
        elif isinstance(event, ToolFinished):
            expected = event.result.call_id.removeprefix("lookup-") if event.result.name == "lookup" else None
        elif isinstance(event, (TextDelta, ModelResponded)):
            text = event.text if isinstance(event, TextDelta) else event.message.text
            if not text:
                continue
            expected = text.removeprefix("Answer ")
        else:
            continue
        assert event.parent_call_id == expected
        assert adapter(event).parent_call_id == expected
    assert TextDelta("Root text").parent_call_id is None
    assert {event.parent_call_id for event in events if isinstance(event, TurnFinished)} == {"a", "b"}
    assert any(isinstance(e, ToolFinished) and e.result.status == "failed" for e in events)


@pytest.mark.asyncio
async def test_forwarded_child_completion_does_not_finish_the_parent_stream():
    from renderer import render_stream

    @tool
    async def specialist(ctx: RunContext) -> str:
        """Get a specialist answer."""
        child = Agent(FakeModel([AssistantMessage(text="Child answer")]))
        async for event in child.run_stream([UserMessage("Investigate")]):
            ctx.emit(event)
        return "Child answer"

    class Capture:
        def __init__(self):
            self.events = []

        def handle(self, event):
            self.events.append(event)

        def fail(self, error):
            raise AssertionError("Parent stream failed") from error

        def close(self):
            pass

    parent = Agent(FakeModel([
        AssistantMessage(tool_calls=[ToolCall("child", "specialist", {})]),
        AssistantMessage(text="Main answer"),
    ]), [specialist])
    capture = Capture()
    result = await render_stream(parent.run_stream([UserMessage("Help")]), renderer=capture)
    assert result.message.text == "Main answer"
    from renderer import RunFinished
    endings = [event for event in capture.events if isinstance(event, RunFinished)]
    assert [event.parent_call_id for event in endings] == ["child", None]
