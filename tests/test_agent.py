"""Tests for harness.agent: configuration plus one method."""

from __future__ import annotations

from typing import Any

import harness.agent as agent_module
from harness.agent import Agent
from harness.context import RunContext, default_estimate
from harness.hooks import Hooks
from harness.inbox import Inbox
from harness.loop import TurnFinished, TurnResult, run_turn
from harness.tools import tool
from harness.types import AssistantMessage, Budget, ToolCall, UserMessage


@tool(parallel_safe=True)
async def lookup(order_id: str) -> str:
    """Look one order up."""
    return f"order {order_id} shipped"


def test_agent_defaults_leave_tools_empty_and_hooks_inert():
    blank = Agent(model=None)
    assert blank.tools == ()
    assert blank.hooks == Hooks()
    assert blank.instructions is None
    assert blank.max_context_tokens is None
    assert blank.estimate_tokens is default_estimate
    assert Agent(model=None).hooks is not blank.hooks


async def test_run_forwards_every_field_to_run_stream(fake_model, monkeypatch):
    captured: dict[str, Any] = {}

    async def spy(model, tools, history, **kwargs):
        captured["positional"] = (model, tools, history)
        captured.update(kwargs)
        yield TurnFinished(TurnResult("completed"))

    monkeypatch.setattr(agent_module, "run_turn_stream", spy)
    model = fake_model([])
    hooks = Hooks()
    inbox = Inbox()
    budget = Budget(max_model_calls=3)
    support = Agent(
        model=model,
        tools=[lookup],
        instructions="You are a support agent.",
        hooks=hooks,
        max_context_tokens=500,
    )
    history = [UserMessage("Where is my order?")]
    result = await support.run(history, deps="ada", inbox=inbox, budget=budget)
    assert result.status == "completed"
    assert captured["positional"] == (model, [lookup], history)
    assert captured == {
        "positional": (model, [lookup], history),
        "deps": "ada",
        "hooks": hooks,
        "instructions": "You are a support agent.",
        "inbox": inbox,
        "budget": budget,
        "max_context_tokens": 500,
        "estimate_tokens": default_estimate,
        "context_window": None,
        "reserved_output_tokens": 1024,
        "limits": support.limits,
        "compaction": None,
        "memory": None,
    }


async def test_two_agents_with_different_instructions_read_one_history(fake_model):
    model = fake_model(
        [AssistantMessage(text="Findings."), AssistantMessage(text="Approved.")]
    )
    researcher = Agent(model=model, instructions="Research the question.")
    reviewer = Agent(model=model, instructions="Review the findings.")
    history = [UserMessage("Is this covered by the warranty?")]

    first = await researcher.run(history)
    second = await reviewer.run(history)

    assert first.message.text == "Findings."
    assert second.message.text == "Approved."
    assert model.requests[0].messages[0].content == "Research the question."
    assert model.requests[1].messages[0].content == "Review the findings."
    assert history[0] == UserMessage("Is this covered by the warranty?")
    assert [type(m).__name__ for m in history] == [
        "UserMessage",
        "AssistantMessage",
        "AssistantMessage",
    ]


async def test_a_child_agent_spends_the_parent_budget(fake_model):
    child_model = fake_model(
        [
            AssistantMessage(tool_calls=[ToolCall("k1", "lookup", {"order_id": "1"})]),
            AssistantMessage(text="Policy allows a refund."),
        ]
    )
    researcher = Agent(model=child_model, tools=[lookup], instructions="Research.")

    @tool
    async def research(question: str, ctx: RunContext) -> str:
        """Research a policy question with read-only tools."""
        result = await researcher.run(
            [UserMessage(question)], deps=ctx.deps, budget=ctx.budget
        )
        return result.message.text or ""

    parent_model = fake_model(
        [
            AssistantMessage(
                tool_calls=[ToolCall("p1", "research", {"question": "refund policy?"})]
            ),
            AssistantMessage(text="Yes, we can refund."),
        ]
    )
    parent = Agent(model=parent_model, tools=[research], instructions="Support.")
    shared = Budget(max_model_calls=6)
    history = [UserMessage("Can I get a refund?")]

    result = await parent.run(history, budget=shared)

    assert result.status == "completed"
    assert result.message.text == "Yes, we can refund."
    assert len(parent_model.requests) == 2
    assert len(child_model.requests) == 2
    assert shared.used == 4
    assert "Policy allows a refund." in history[2].content


async def test_agent_run_matches_run_turn_on_the_same_script(fake_model):
    script = [AssistantMessage(text="It shipped.")]
    direct_history = [UserMessage("Where is my order?")]
    agent_history = [UserMessage("Where is my order?")]
    direct = await run_turn(
        fake_model(list(script)), [lookup], direct_history, instructions="Support."
    )
    through_agent = await Agent(
        model=fake_model(list(script)), tools=[lookup], instructions="Support."
    ).run(agent_history)
    assert direct.status == through_agent.status
    assert direct_history == agent_history


async def test_agent_run_returns_the_same_result_as_run_stream(fake_model):
    script = [AssistantMessage(text="It shipped.")]
    streamed_history = [UserMessage("Where is my order?")]
    buffered_history = [UserMessage("Where is my order?")]
    streamed_agent = Agent(model=fake_model(list(script)), instructions="Support.")
    buffered_agent = Agent(model=fake_model(list(script)), instructions="Support.")

    events = [event async for event in streamed_agent.run_stream(streamed_history)]
    result = await buffered_agent.run(buffered_history)

    assert events[-1] == TurnFinished(result)
    assert streamed_history == buffered_history
