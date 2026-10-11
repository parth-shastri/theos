"""Verify provider limits, complete context, reserved handoffs, and active answers."""

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from harness import (
    AssistantMessage,
    Budget,
    ContextMemory,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    tool,
)
from harness.testing import FakeModel
from theos.runtime import context, recovery, tools
from theos.runtime import models as runtime_models
from theos.runtime.budgets import TurnBudget
from theos.settings import Settings

from .conftest import collect
from .test_recovery import delegate_call, install_read, read_call, session, use_models


@pytest.mark.parametrize(
    "provider,parameter",
    [
        ("openai", "max_output_tokens"),
        ("gemini", "max_output_tokens"),
        ("openrouter", "max_tokens"),
        ("anthropic", "max_tokens"),
    ],
)
async def test_known_capacity_sets_only_the_provider_output_parameter(runtime, provider, parameter):
    runtime.settings.provider = provider
    model = (
        "gemini-3.8-flash"
        if provider == "gemini"
        else "claude-sonnet-5.5"
        if provider == "anthropic"
        else "gpt-6-luna"
    )
    row = runtime.db.create_session("alice", model, "default")
    limits = await context.capacity(runtime, row)
    policy = context.compaction(runtime, row, limits)
    values = context.options(runtime, row, limits)
    assert limits.context >= 1_000_000
    assert values[parameter] == (65536 if provider == "gemini" else 128000)
    assert policy.options[parameter] == values[parameter]
    assert policy.trigger_ratio == 0.6 and policy.target_ratio == 0.45
    assert policy.max_summary_tokens is None and policy.reduce_current_turn
    row["generation"] = json.dumps({"max_output_tokens": 5000})
    assert context.options(runtime, row, limits)[parameter] == 5000


async def test_provider_metadata_refresh_cache_and_operator_window(runtime):
    runtime.settings.provider = "openrouter"
    calls = []

    def catalog(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "qwen/qwen3.8-27b",
                        "context_length": 1_000_000,
                        "top_provider": {"context_length": 262144, "max_completion_tokens": 235929},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(catalog)) as client:
        runtime.http = client
        row = runtime.db.create_session("alice", "qwen-3.8-27b", "default")
        limits = await context.capacity(runtime, row)
        assert limits == context.ModelCapacity(262144, 235929, "provider")
        assert await context.capacity(runtime, row) == limits
        assert len(calls) == 1
        runtime.settings.context_tokens = 4096
        assert (await context.capacity(runtime, row)).context == 4096
        runtime.settings.context_tokens = 1_000_000
        assert (await context.capacity(runtime, row)).context == 262144


@pytest.mark.parametrize("ratio", [0.49, 0.71])
def test_context_trigger_stays_between_fifty_and_seventy_percent(ratio):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, compaction_trigger_ratio=ratio)


async def test_parent_response_larger_than_old_byte_limit_is_preserved(runtime):
    text = "Complete finding. " * 70000 + "FINAL SOURCE https://example.org/full"
    parent = FakeModel([AssistantMessage(text)])
    use_models(runtime, parent)
    row = runtime.db.create_session("alice", "gpt-6-luna", "default")
    events = await collect(runtime.start("alice", row["id"], "Give the complete findings."))
    assert events[-1]["status"] == "completed"
    assert runtime.db.load_history("alice", row["id"])[-1].text == text
    assert next(e for e in events if e["type"] == "assistant_complete")["text"] == text
    assert parent.requests[0].options["max_output_tokens"] == 128000


@pytest.mark.parametrize("final_response", [False, True])
async def test_requested_output_is_reserved_before_parent_or_final_generation(
    runtime, final_response
):
    from harness.model import default_estimate_tokens

    runtime.settings.context_tokens = 10000
    runtime.settings.max_compaction_calls = 5

    async def no_tools(current):
        return []

    runtime.tools = no_tools
    row = runtime.db.create_session("alice", "gpt-6-luna", "default")
    runtime.db.execute(
        "UPDATE sessions SET generation=? WHERE id=?",
        (json.dumps({"max_output_tokens": 8000}), row["id"]),
    )
    row = runtime.session("alice", row["id"])
    earlier = [
        UserMessage("Preserve the source dates."),
        AssistantMessage("Evidence. " + "x" * 6600),
    ]
    question = "Compare the evidence, keeping the original requirements. " + "q" * 2000
    original_text = earlier[-1].text
    model = FakeModel(
        [
            AssistantMessage("Keep source dates and the original requirements."),
            AssistantMessage("Complete answer."),
        ]
    )
    use_models(runtime, model)
    if final_response:
        history = [*earlier, UserMessage(question)]
        answer = await recovery.response_call(
            runtime,
            row,
            history,
            ContextMemory(),
            Budget(1),
            "Preserve the requirements.",
            "budget_limit",
            compact_budget=Budget(5),
        )
        assert answer.text == "Complete answer."
        assert history[-1].content == question
    else:
        runtime.db.save_history("alice", row["id"], earlier)
        events = await collect(runtime.start("alice", row["id"], question))
        assert events[-1]["status"] == "completed"
        assert runtime.db.load_history("alice", row["id"])[-1].text == "Complete answer."
    assert len(model.requests) == 2
    assert model.requests[0].messages[0].content == context.SUMMARY_PROMPT
    assert earlier[-1].text == original_text
    for request in model.requests:
        assert request.options["max_output_tokens"] == 8000
        assert default_estimate_tokens(request) + 8000 <= 10000


async def test_unfit_output_reservation_preserves_findings_without_lowering_limit(runtime):
    runtime.settings.context_tokens = 200000
    runtime.settings.max_compaction_calls = 0
    row = runtime.db.create_session("alice", "gpt-6-luna", "default")
    model, final = FakeModel([read_call("saved")]), FakeModel([])
    use_models(runtime, model, final)
    evidence = "Complete saved evidence. " * 15000 + "LAST SOURCE https://example.org/full"
    await install_read(runtime, evidence)
    events = await collect(runtime.start("alice", row["id"], "Give the complete findings."))
    assert events[-1]["status"] == "partial"
    assert len(model.requests) == 1 and model.requests[0].options["max_output_tokens"] == 128000
    assert not final.requests
    assert evidence in runtime.db.load_history("alice", row["id"])[-1].text


async def test_researcher_reserves_the_configured_output_before_generation(runtime, monkeypatch):
    from harness import RunContext
    from harness.model import default_estimate_tokens
    from harness.tools import execute_tool

    runtime.settings.context_tokens = 10000
    runtime.settings.max_compaction_calls = 5
    monkeypatch.setattr(tools, "information_tools", lambda *args: [])
    row = runtime.db.create_session("alice", "gpt-6-luna", "default")
    row["generation"] = json.dumps({"max_output_tokens": 8000})
    history = [
        UserMessage("Preserve the source dates."),
        AssistantMessage("x" * 6600),
        UserMessage("Keep the original requirements. " + "q" * 2000),
    ]
    model = FakeModel(
        [
            AssistantMessage("Keep source dates."),
            AssistantMessage("Keep source dates and the original requirements."),
            AssistantMessage("Complete research."),
        ]
    )
    use_models(runtime, model)
    delegate = next(t for t in await tools.build_tools(runtime, row) if t.name == "delegate_tasks")
    call = ToolCall(
        "research",
        "delegate_tasks",
        {
            "tasks": [
                {
                    "name": "sources",
                    "task": "Compare the sources.",
                    "context": "x" * 6600,
                    "requirements": ["Preserve the source dates."],
                }
            ]
        },
    )
    returned = await execute_tool(
        call,
        [delegate],
        ctx=RunContext(deps=None, history=history, budget=TurnBudget(runtime.settings).research),
    )
    result = json.loads(returned.content)
    assert result[0]["status"] == "completed" and result[0]["answer"] == "Complete research."
    assert len(model.requests) == 3
    for request in model.requests:
        assert request.options["max_output_tokens"] == 8000
        assert default_estimate_tokens(request) + 8000 <= 10000


class SlowModel(FakeModel):
    async def stream(self, request):
        await asyncio.sleep(0.3)
        async for event in super().stream(request):
            yield event


async def test_started_main_answer_can_finish_after_research_deadline(runtime):
    runtime.settings.turn_timeout = 0.15
    model = SlowModel([AssistantMessage("The complete answer survives the deadline.")])
    use_models(runtime, model)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Answer the question."))
    assert events[-1]["status"] == "completed"
    assert len(model.requests) == 1
    assert (
        runtime.db.load_history("alice", row["id"])[-1].text
        == "The complete answer survives the deadline."
    )


async def test_reserved_parent_response_can_finish_after_deadline(runtime):
    runtime.settings.max_model_calls = 2
    runtime.settings.turn_timeout = 0.15
    await install_read(runtime)
    research = FakeModel([read_call("source")])
    final = SlowModel([AssistantMessage("Verified opening time: 7 AM.")])
    use_models(runtime, research, final)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Check the opening time."))
    assert events[-1]["status"] == "partial"
    assert len(final.requests) == 1 and not final.requests[0].tools
    assert "7 AM" in runtime.db.load_history("alice", row["id"])[-1].text


async def test_gemini_has_idle_timeouts_without_a_server_generation_deadline(settings, monkeypatch):
    pytest.importorskip("google.genai")
    settings.provider = "gemini"
    settings.api_key = SecretStr("local-test-key")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "Complete answer"}]},
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        runtime_models.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)),
    )
    async with runtime_models.model_client(settings, "gemini-3.8-flash", "default") as model:
        result = await model.client.aio.models.generate_content(
            model="gemini-3.8-flash", contents="Hello"
        )
    assert result.text == "Complete answer"
    assert len(requests) == 1
    assert "X-Server-Timeout" not in requests[0].headers
    assert requests[0].extensions["timeout"]["read"] == 60
    assert requests[0].extensions["timeout"]["connect"] == 10


async def test_delegate_deadline_stops_new_tools_but_allows_its_final_response(
    runtime, monkeypatch
):
    monkeypatch.setattr(tools, "DELEGATE_SECONDS", 0.15)
    attempts = []

    @tool
    async def read_reference():
        """Read a source."""
        attempts.append(1)
        return "This tool must not start after the deadline."

    monkeypatch.setattr(tools, "information_tools", lambda *args: [read_reference])
    parent = FakeModel([delegate_call(), AssistantMessage("Park time needs verification.")])
    fast = FakeModel([AssistantMessage("Park opens at 7 AM.")])
    slow = SlowModel(
        [
            AssistantMessage(tool_calls=[ToolCall("late", "read_reference", {})]),
            AssistantMessage("Museum hours remain unverified. FULL HANDOFF END"),
        ]
    )
    use_models(runtime, parent, fast, slow)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Compare opening times."))
    assert events[-1]["status"] == "partial"
    assert len(slow.requests) == 2 and not slow.requests[1].tools
    assert "time limit" in slow.requests[1].messages[0].content
    assert attempts == []
    result = next(
        m
        for m in parent.requests[1].messages
        if isinstance(m, ToolResultMessage) and m.name == "delegate_tasks"
    )
    assert json.loads(result.content)[1]["answer"].endswith("FULL HANDOFF END")


async def test_each_delegate_reserves_a_full_handoff_and_receives_user_corrections(
    runtime, monkeypatch
):
    runtime.settings.max_model_calls = 7
    runtime.settings.max_compaction_calls = 0
    runtime.settings.delegate_max_model_calls = 2
    runtime.settings.context_tokens = 200000
    evidence = "Exact source evidence " * 2000 + "EVIDENCE END"

    @tool
    async def read_reference():
        """Read source evidence."""
        return evidence

    monkeypatch.setattr(tools, "information_tools", lambda *args: [read_reference])
    assignment = delegate_call()
    for task in assignment.tool_calls[0].arguments["tasks"]:
        task["requirements"] = [
            "Only primary sources published this year.",
            "Correction: include the publication date and opposing views.",
        ]
        task["context"] = "Earlier verified source https://example.org/earlier"
    parent = FakeModel([assignment, AssistantMessage("Comparison from both handoffs.")])
    answers = ["Research details " * 2000 + f"FINAL URL https://example.org/{i}" for i in range(2)]
    children = [
        FakeModel(
            [
                AssistantMessage(tool_calls=[ToolCall(f"source-{i}", "read_reference", {})]),
                AssistantMessage(answers[i]),
            ]
        )
        for i in range(2)
    ]
    use_models(runtime, parent, *children)
    row = session(runtime)
    earlier = [
        UserMessage("Only primary sources published this year."),
        AssistantMessage("Understood."),
        UserMessage("Correction: include the publication date and opposing views."),
        AssistantMessage(tool_calls=[ToolCall("old", "read_reference", {})]),
        ToolResultMessage(
            "old", "read_reference", "Earlier verified source https://example.org/earlier"
        ),
    ]
    runtime.db.save_history("alice", row["id"], earlier)
    events = await collect(runtime.start("alice", row["id"], "Compare the opening times."))
    assert events[-1]["status"] == "partial"
    for child in children:
        assert len(child.requests) == 2
        first, handoff = child.requests
        assert first.tools and not handoff.tools
        assert "model-call limit" in handoff.messages[0].content
        assert any(
            isinstance(m, UserMessage) and "Only primary" in m.content for m in first.messages
        )
        assert any(
            isinstance(m, UserMessage) and "Correction:" in m.content for m in handoff.messages
        )
        assert any(isinstance(m, AssistantMessage) and "/earlier" in m.text for m in first.messages)
        assert (
            next(m for m in handoff.messages if isinstance(m, ToolResultMessage)).content
            == evidence
        )
    handed = next(
        m
        for m in parent.requests[1].messages
        if isinstance(m, ToolResultMessage) and m.name == "delegate_tasks"
    )
    assert [d["answer"] for d in json.loads(handed.content)] == answers
    assert len(parent.requests) + sum(len(c.requests) for c in children) == 6


async def test_compaction_sends_every_piece_without_rewriting_the_transcript(runtime):
    from harness import Agent, Hooks

    runtime.settings.context_tokens = 4096
    row = session(runtime)
    row["generation"] = json.dumps({"max_output_tokens": 512})
    limits = await context.capacity(runtime, row)
    old_text = "abcdefghijklmnopqrstuvwxyz " * 1200
    history = [
        UserMessage("Earlier task"),
        AssistantMessage(old_text),
        UserMessage("Continue with the original requirements."),
    ]
    original = list(history)
    summary = "Keep the original task and evidence. " * 100
    model = FakeModel([AssistantMessage(summary)] * 20)
    memory = ContextMemory()

    async def configure(request, ctx):
        request.options.update(context.options(runtime, row, limits))
        return request

    result = await Agent(
        model,
        hooks=Hooks(before_model=configure),
        context_window=limits.context,
        compaction=context.compaction(runtime, row, limits),
    ).run(history, memory=memory, budget=Budget(1), compaction_budget=Budget(20))
    chunks = [json.loads(r.messages[1].content) for r in model.requests[:-1]]
    supplied = "".join(
        m["content"] or ""
        for chunk in chunks
        for m in chunk["messages"]
        if m["role"] == "assistant"
    )
    assert result.status == "completed" and len(chunks) > 1
    assert supplied == old_text
    assert history[:3] == original
    assert memory.summary and memory.covered_messages == 2
    assert memory.summary == summary.strip()


def test_long_context_summary_survives_storage_round_trip():
    memory = ContextMemory("Saved evidence. " * 2000, 2)
    assert ContextMemory.from_dict(memory.to_dict()) == memory


def test_held_delegate_calls_survive_shared_research_exhaustion(settings):
    allowance = TurnBudget(settings).research
    reserved = [allowance.reserve(), allowance.reserve()]
    while allowance.spend():
        pass
    assert all(response.spend() for response in reserved)
    assert allowance.used == allowance.max_model_calls
    assert not allowance.spend()
    assert not any(response.spend() for response in reserved)
