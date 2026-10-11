"""Exercise real runtime limits, bounded recovery, and preservation of completed work."""

import asyncio
import json
import time
from contextlib import asynccontextmanager

import pytest

from harness import AssistantMessage, ToolCall, ToolResultMessage, UserMessage, tool
from harness.testing import FakeModel
from theos.runtime import recovery, tools

from .conftest import collect


def session(runtime):
    return runtime.db.create_session("alice", "test-model", "default")


def use_models(runtime, *models):
    remaining = iter(models)

    @asynccontextmanager
    async def factory(*args):
        yield next(remaining)

    runtime.models = factory


async def install_read(runtime, content="Verified finding: the park opens at 7 AM."):
    count = []

    @tool
    async def read_source():
        """Read the test source."""
        count.append(1)
        return content

    async def registry(current):
        return [runtime.journal_tool(read_source, current)]

    runtime.tools = registry
    return count


def read_call(identifier):
    return AssistantMessage(tool_calls=[ToolCall(identifier, "read_source", {})])


async def test_provider_failure_without_findings_returns_clear_failure(runtime):
    count = await install_read(runtime)
    research = FakeModel([RuntimeError("private provider credential")])
    use_models(runtime, research)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Create a reminder."))
    assert events[-1] == {"type": "done", "status": "failed"}
    assert runtime.session("alice", row["id"])["status"] == "failed"
    answer = runtime.db.load_history("alice", row["id"])[-1].text
    assert answer.startswith("Request failed:")
    assert "No answer was generated" in answer
    assert "Partial answer" not in answer
    assert "private provider credential" not in answer
    assert count == []
    assert len(research.requests) == 1


async def test_failed_recovery_without_findings_does_not_claim_partial_answer(runtime):
    runtime.settings.turn_timeout = 0.12
    count = await install_read(runtime)
    use_models(runtime, WaitingModel([]), FakeModel([RuntimeError("unavailable")]))
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Read the source."))
    assert events[-1]["status"] == "failed"
    assert runtime.db.load_history("alice", row["id"])[-1].text.startswith("Request failed:")
    assert count == []


def assert_partial(runtime, row, events, finding="7 AM"):
    assert events[-1] == {"type": "done", "status": "partial"}
    assert not any(e["type"] == "error" for e in events)
    history = runtime.db.load_history("alice", row["id"])
    assert history[-1].text.startswith("Partial answer:")
    assert finding in history[-1].text
    assert runtime.session("alice", row["id"])["status"] == "partial"
    return history


async def test_budget_reserves_one_tool_free_answer_with_unchanged_instructions(runtime):
    runtime.settings.max_model_calls = 3
    runtime.settings.max_compaction_calls = 0
    count = await install_read(runtime)
    research = FakeModel([read_call("one"), read_call("two")])
    final = FakeModel([AssistantMessage("The park opens at 7 AM.", usage={"output_tokens": 9})])
    use_models(runtime, research, final)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Plan a morning walk."))
    assert_partial(runtime, row, events)
    assert count == [1, 1]
    assert len(research.requests) + len(final.requests) == 3
    request = final.requests[0]
    assert not request.tools
    assert request.messages[0].content == research.requests[0].messages[0].content
    assert any(isinstance(m, ToolResultMessage) and "7 AM" in m.content for m in request.messages)
    assert runtime.db.one("SELECT SUM(output_tokens) n FROM usage")["n"] == 9
    # A later user turn must work without replaying either completed tool call.
    use_models(runtime, FakeModel([AssistantMessage("You can walk there tomorrow.")]))
    assert (await collect(runtime.start("alice", row["id"], "What about tomorrow?")))[-1][
        "status"
    ] == "completed"
    assert count == [1, 1]


async def test_single_call_budget_returns_saved_findings_without_extra_request(runtime):
    runtime.settings.max_model_calls = 1
    count = await install_read(runtime)
    research = FakeModel([read_call("one")])
    use_models(runtime, research)
    row = session(runtime)
    assert_partial(
        runtime, row, await collect(runtime.start("alice", row["id"], "Read the source."))
    )
    assert count == [1]
    assert len(research.requests) == 1


class WaitingModel(FakeModel):
    async def stream(self, request):
        if len(self.requests) >= len(self.script):
            self.requests.append(request)
            await asyncio.Event().wait()
        async for event in super().stream(request):
            yield event


async def test_turn_timeout_preserves_results_and_finishes_inside_deadline(runtime):
    runtime.settings.turn_timeout = 0.15
    await install_read(runtime)
    research = WaitingModel([read_call("one")])
    final = FakeModel([AssistantMessage("The park opens at 7 AM.")])
    use_models(runtime, research, final)
    row = session(runtime)
    started = time.monotonic()
    events = await collect(runtime.start("alice", row["id"], "Read the opening time."))
    assert_partial(runtime, row, events)
    assert time.monotonic() - started < 0.4
    assert "time limit" in runtime.db.load_history("alice", row["id"])[-1].text
    assert len(final.requests) == 1
    assert not final.requests[0].tools


async def test_recovery_timeout_falls_back_without_retry(runtime, monkeypatch):
    runtime.settings.max_model_calls = 2
    monkeypatch.setattr(recovery, "FINAL_SECONDS", 0.03)
    count = await install_read(runtime)
    research, final = FakeModel([read_call("one")]), WaitingModel([])
    use_models(runtime, research, final)
    row = session(runtime)
    assert_partial(
        runtime, row, await collect(runtime.start("alice", row["id"], "Read the source."))
    )
    assert len(final.requests) == 1
    assert count == [1]


class OversizedModel(FakeModel):
    async def estimate_tokens(self, request):
        if any(isinstance(m, ToolResultMessage) for m in request.messages):
            return 1_000_000
        return await super().estimate_tokens(request)


@pytest.mark.parametrize("recovery_fits", [True, False])
async def test_context_limit_recovers_from_actual_request_sizing(runtime, recovery_fits):
    runtime.settings.context_tokens = 4096
    content = "Verified opening time: 7 AM. " + "source material " * 5000
    count = await install_read(runtime, content)
    research = OversizedModel([read_call("one")])
    final_class = FakeModel if recovery_fits else OversizedModel
    final = final_class([AssistantMessage("The park opens at 7 AM.")])
    use_models(runtime, research, final)
    row = session(runtime)
    history = assert_partial(
        runtime, row, await collect(runtime.start("alice", row["id"], "Read the source."))
    )
    assert "available model context" in history[-1].text
    assert next(m for m in history if isinstance(m, ToolResultMessage)).content == content
    assert count == [1]
    assert len(final.requests) == (1 if recovery_fits else 0)


async def test_large_results_are_bounded_for_model_but_retained_in_storage(runtime):
    content = "Park opening time: 7 AM. " + "source material " * 5000
    await install_read(runtime, content)
    research = FakeModel([read_call("one"), AssistantMessage("It opens at 7 AM.")])
    use_models(runtime, research)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Read the source."))
    assert events[-1]["status"] == "completed"
    sent = next(m for m in research.requests[-1].messages if isinstance(m, ToolResultMessage))
    assert len(sent.content) < 8100
    assert sent.content.endswith("[Result shortened.]")
    saved = next(
        m for m in runtime.db.load_history("alice", row["id"]) if isinstance(m, ToolResultMessage)
    )
    assert saved.content == content


async def test_final_model_failure_and_tool_request_use_saved_findings(runtime):
    runtime.settings.max_model_calls = 2
    for response in (RuntimeError("private credential"), read_call("must-not-run")):
        count = await install_read(runtime)
        use_models(runtime, FakeModel([read_call("one")]), FakeModel([response]))
        row = session(runtime)
        events = await collect(runtime.start("alice", row["id"], "Read the source."))
        assert_partial(runtime, row, events)
        assert "private credential" not in json.dumps(events)
        assert count == [1]


async def test_explicit_cancellation_does_not_start_recovery(runtime):
    research = WaitingModel([])
    use_models(runtime, research)
    row = session(runtime)
    turn = runtime.start("alice", row["id"], "Wait.")
    while not research.requests:
        await asyncio.sleep(0)
    turn.task.cancel()
    events = await collect(turn)
    assert events[-1]["status"] == "interrupted"
    assert len(research.requests) == 1
    assert not any(e["type"] == "text" for e in events)


def delegate_call():
    return AssistantMessage(
        tool_calls=[
            ToolCall(
                "delegates",
                "delegate_tasks",
                {
                    "tasks": [
                        {"name": "Park hours", "task": "Check park opening hours."},
                        {"name": "Museum hours", "task": "Check museum opening hours."},
                    ]
                },
            )
        ]
    )


async def test_one_delegate_timeout_preserves_sibling_answer(runtime, monkeypatch):
    monkeypatch.setattr(tools, "DELEGATE_SECONDS", 0.03)
    parent = FakeModel(
        [
            delegate_call(),
            AssistantMessage("The park opens at 7 AM; museum hours remain unverified."),
        ]
    )
    fast, slow = FakeModel([AssistantMessage("Park opens at 7 AM.")]), WaitingModel([])
    use_models(runtime, parent, fast, slow)
    row = session(runtime)
    history = assert_partial(
        runtime, row, await collect(runtime.start("alice", row["id"], "Compare the opening times."))
    )
    result = next(
        m for m in history if isinstance(m, ToolResultMessage) and m.name == "delegate_tasks"
    )
    delegates = json.loads(result.content)
    assert delegates[0]["status"] == "completed"
    assert delegates[0]["answer"] == "Park opens at 7 AM."
    assert delegates[1]["status"] == "partial"
    assert delegates[1]["reason"] == "timeout"
    assert len(parent.requests) == 2


async def test_turn_timeout_during_delegation_preserves_completed_sibling(runtime):
    runtime.settings.turn_timeout = 0.15
    parent = FakeModel([delegate_call()])
    fast, slow = FakeModel([AssistantMessage("Park opens at 7 AM.")]), WaitingModel([])
    final = FakeModel([AssistantMessage("The park opens at 7 AM. Museum hours remain unverified.")])
    use_models(runtime, parent, fast, slow, final)
    row = session(runtime)
    history = assert_partial(
        runtime, row, await collect(runtime.start("alice", row["id"], "Compare the opening times."))
    )
    result = next(
        m for m in history if isinstance(m, ToolResultMessage) and m.name == "delegate_tasks"
    )
    assert result.status == "completed"
    by_name = {d["name"]: d for d in json.loads(result.content)}
    assert by_name["Park hours"]["answer"] == "Park opens at 7 AM."
    assert by_name["Museum hours"]["status"] == "partial"
    assert (
        runtime.db.one("SELECT status FROM tool_runs WHERE call_id='delegates'")["status"]
        == "completed"
    )
    assert not final.requests[0].tools


async def test_timed_out_write_is_unknown_and_never_repeated(runtime):
    runtime.settings.turn_timeout = 0.15
    attempts = []

    @tool
    async def write_action():
        """Attempt a write."""
        attempts.append(1)
        await asyncio.Event().wait()

    async def registry(current):
        return [runtime.journal_tool(write_action, current)]

    runtime.tools = registry
    # Use an unprotected test name to exercise checkpoint uncertainty directly.
    parent = FakeModel([AssistantMessage(tool_calls=[ToolCall("write", "write_action", {})])])
    final = FakeModel(
        [AssistantMessage("The action outcome is unknown. Check the external service.")]
    )
    use_models(runtime, parent, final)
    row = session(runtime)
    history = assert_partial(
        runtime,
        row,
        await collect(runtime.start("alice", row["id"], "Attempt the action.")),
        "unknown",
    )
    assert next(m for m in history if isinstance(m, ToolResultMessage)).status == "unknown"
    assert attempts == [1]
    use_models(runtime, FakeModel([AssistantMessage("Please check the service first.")]))
    await collect(runtime.start("alice", row["id"], "What happened?"))
    assert attempts == [1]


async def test_output_limit_returns_explicit_partial_answer(runtime):
    parent = FakeModel([AssistantMessage("Park opens at 7 AM. More details", stop_reason="length")])
    final = FakeModel([AssistantMessage("Park opens at 7 AM; other details remain unverified.")])
    use_models(runtime, parent, final)
    row = session(runtime)
    assert_partial(runtime, row, await collect(runtime.start("alice", row["id"], "Plan a walk.")))


@pytest.mark.parametrize("max_calls", [6, 12])
@pytest.mark.parametrize("delegate_calls", [2, 4, 6])
async def test_delegate_iterations_are_enforced_and_parent_can_answer(
    runtime, monkeypatch, max_calls, delegate_calls
):
    runtime.settings.max_model_calls = max_calls
    runtime.settings.max_compaction_calls = 0
    runtime.settings.delegate_max_model_calls = delegate_calls

    @tool
    async def read_reference():
        """Read a reference."""
        return "Park opens at 7 AM."

    monkeypatch.setattr(tools, "information_tools", lambda *args: [read_reference])
    parent = FakeModel(
        [delegate_call(), AssistantMessage("Park opens at 7 AM; research is incomplete.")]
    )
    children = [
        FakeModel(
            [
                AssistantMessage(tool_calls=[ToolCall(f"child-{i}-{j}", "read_reference", {})])
                for j in range(10)
            ]
        )
        for i in range(2)
    ]
    use_models(runtime, parent, *children)
    row = session(runtime)
    assert_partial(
        runtime, row, await collect(runtime.start("alice", row["id"], "Compare the opening times."))
    )
    assert len(parent.requests) == 2
    assert all(len(child.requests) <= delegate_calls for child in children)
    assert sum(len(m.requests) for m in [parent, *children]) <= max_calls - 1
    if max_calls >= 2 * delegate_calls + 3:
        assert all(len(child.requests) == delegate_calls for child in children)


def test_saved_findings_keep_both_delegate_answers_within_total_bound():
    delegates = [
        {
            "name": "Mumbai itinerary",
            "status": "completed",
            "answer": "Mumbai museum opens at 10 AM. " + "source details " * 2000,
        },
        {
            "name": "Bengaluru itinerary",
            "status": "completed",
            "answer": "Bengaluru gallery opens at 11 AM. " + "source details " * 2000,
        },
    ]
    history = [
        UserMessage("Compare the cities."),
        ToolResultMessage("research", "delegate_tasks", json.dumps(delegates)),
    ]
    answer = recovery.findings(history, 1)
    assert "Mumbai museum opens at 10 AM" in answer
    assert "Bengaluru gallery opens at 11 AM" in answer
    assert len(answer) <= 8100
