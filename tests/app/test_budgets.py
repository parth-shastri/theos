"""Verify separate call allowances, their total ceiling, and runtime compaction."""

import asyncio

import pytest
from pydantic import ValidationError

from harness import AssistantMessage, UserMessage
from harness.testing import FakeModel
from theos.runtime.budgets import TurnBudget
from theos.settings import Settings

from .conftest import collect
from .test_recovery import install_read, read_call, session, use_models


@pytest.mark.parametrize(
    ("total", "compact", "research", "final"),
    [(1, 2, 1, 0), (2, 2, 1, 1), (3, 2, 1, 1), (12, 2, 9, 1), (24, 3, 20, 1)],
)
def test_allocations_retain_research_and_recovery(settings, total, compact, research, final):
    settings.max_model_calls = total
    settings.max_compaction_calls = compact
    budget = TurnBudget(settings)
    assert budget.research.max_model_calls == research
    assert budget.recovery.max_model_calls == final
    assert (
        sum(b.max_model_calls for b in (budget.research, budget.compaction, budget.recovery))
        == total
    )


async def test_concurrent_allowances_cannot_cross_the_total(settings):
    budget = TurnBudget(settings)

    async def consume(allowance):
        calls = 0
        for _ in range(100):
            calls += allowance.spend()
            await asyncio.sleep(0)
        return calls

    used = await asyncio.gather(
        *(consume(b) for b in (budget.research, budget.compaction, budget.recovery))
    )
    assert used == [9, 2, 1]
    assert budget.total.used == 12
    assert all(not b.spend() for b in (budget.research, budget.compaction, budget.recovery))


def test_environment_configures_allowances(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_MODEL_CALLS", "24")
    monkeypatch.setenv("AGENT_MAX_COMPACTION_CALLS", "3")
    monkeypatch.setenv("AGENT_MAX_RECOVERY_CALLS", "1")
    monkeypatch.setenv("AGENT_DELEGATE_MAX_MODEL_CALLS", "6")
    settings = Settings(_env_file=None, provider="fake")
    budget = TurnBudget(settings)
    assert budget.total.max_model_calls == 24
    assert budget.research.max_model_calls == 20
    assert budget.compaction.max_model_calls == 3
    assert settings.delegate_max_model_calls == 6


def test_release_defaults_scale_the_call_allowances():
    settings = Settings(_env_file=None, provider="fake")
    budget = TurnBudget(settings)
    assert budget.total.max_model_calls == 30
    assert budget.research.max_model_calls == 23
    assert budget.compaction.max_model_calls == 5
    assert budget.recovery.max_model_calls == 2
    assert settings.delegate_max_model_calls == 10


async def test_second_recovery_call_stays_tool_free_and_inside_total(runtime):
    runtime.settings.max_model_calls = 5
    runtime.settings.max_compaction_calls = 0
    runtime.settings.max_recovery_calls = 2
    count = await install_read(runtime)
    research = FakeModel([read_call("one"), read_call("two"), read_call("three")])
    failed = FakeModel([RuntimeError("temporary failure")])
    final = FakeModel([AssistantMessage("The park opens at 7 AM.")])
    use_models(runtime, research, failed, final)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Check the opening time."))
    assert events[-1]["status"] == "partial"
    assert "7 AM" in runtime.db.load_history("alice", row["id"])[-1].text
    assert count == [1, 1, 1]
    assert len(research.requests) + len(failed.requests) + len(final.requests) == 5
    assert not failed.requests[0].tools and not final.requests[0].tools
    assert failed.requests[0].messages[0].content == final.requests[0].messages[0].content


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_compaction_calls", -1),
        ("max_compaction_calls", 101),
        ("delegate_max_model_calls", 0),
        ("delegate_max_model_calls", 101),
    ],
)
def test_invalid_allowances_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, provider="fake", **{field: value})


@pytest.mark.parametrize("allowance", [0, 1, 2])
async def test_runtime_compaction_has_separate_allowance_and_safe_exhaustion(runtime, allowance):
    runtime.settings.max_model_calls = 5
    runtime.settings.max_compaction_calls = allowance
    runtime.settings.context_tokens = 4096
    await install_read(runtime)
    row = session(runtime)
    original = [
        UserMessage("Earlier preferences " + "a" * 10000),
        AssistantMessage("Earlier findings " + "b" * 10000),
    ]
    runtime.db.save_history("alice", row["id"], original)
    summaries = [
        AssistantMessage(
            "Keep the preferences and the earlier findings.",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
    ] * allowance
    model = FakeModel(
        [*summaries, read_call("source"), AssistantMessage("The park opens at 7 AM.")]
    )
    final = FakeModel([AssistantMessage("Earlier preferences are saved; more work is needed.")])
    use_models(runtime, model, final)
    events = await collect(runtime.start("alice", row["id"], "Check the opening time."))
    history = runtime.db.load_history("alice", row["id"])
    assert history[:2] == original
    assert len(model.requests) + len(final.requests) <= 5
    if allowance == 2:
        assert events[-1]["status"] == "completed"
        assert len(model.requests) == 4
        assert not final.requests
        assert history[-1].text == "The park opens at 7 AM."
        assert runtime.db.one("SELECT SUM(output_tokens) n FROM usage")["n"] == 10
        assert runtime.db.one("SELECT COUNT(*) n FROM usage")["n"] == 4
    else:
        assert events[-1]["status"] == "partial"
        assert len(model.requests) == allowance
        assert len(final.requests) == 1
        assert history[-1].text.startswith("Partial answer:")
        assert not final.requests[0].tools
        assert runtime.db.one("SELECT SUM(output_tokens) n FROM usage")["n"] == 5 * allowance
