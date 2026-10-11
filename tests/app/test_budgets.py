"""Verify separate call allowances, their total ceiling, and runtime compaction."""

import asyncio

import pytest
from pydantic import ValidationError

from harness import AssistantMessage, ToolResultMessage, UserMessage
from harness.testing import FakeModel
from theos.runtime.budgets import TurnBudget
from theos.settings import Settings

from .conftest import collect
from .test_recovery import install_read, read_call, session, use_models


@pytest.mark.parametrize(
    ("total", "compact", "research", "final"),
    [(1, 2, 0, 1), (2, 2, 1, 1), (3, 2, 1, 1), (12, 2, 9, 1), (24, 3, 20, 1)],
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
        *(
            consume(b)
            for b in (budget.research, budget.compaction, budget.recovery, budget.final_compaction)
        )
    )
    assert used == [9, 1, 1, 1]
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
    assert budget.research.max_model_calls == 24
    assert budget.compaction.max_model_calls == 5
    assert budget.recovery.max_model_calls == 1
    assert settings.delegate_max_model_calls is None
    assert settings.max_compaction_calls is None
    assert budget.delegate_limit == 10


async def test_failed_response_call_does_not_retry_or_display_findings(runtime):
    runtime.settings.max_model_calls = 5
    runtime.settings.max_compaction_calls = 0
    runtime.settings.max_recovery_calls = 2
    count = await install_read(runtime)
    research = FakeModel([read_call(str(i)) for i in range(4)])
    failed = FakeModel([RuntimeError("temporary failure")])
    use_models(runtime, research, failed)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Check the opening time."))
    assert events[-1]["status"] == "failed"
    history = runtime.db.load_history("alice", row["id"])
    assert "7 AM" not in history[-1].text
    assert any(isinstance(m, ToolResultMessage) and "7 AM" in m.content for m in history)
    assert count == [1, 1, 1, 1]
    assert len(research.requests) + len(failed.requests) == 5
    assert not failed.requests[0].tools


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


@pytest.mark.parametrize("allowance", [0, 1, 2, 3])
async def test_runtime_compaction_has_separate_allowance_and_safe_exhaustion(runtime, allowance):
    runtime.settings.max_model_calls = 6
    runtime.settings.max_compaction_calls = allowance
    runtime.settings.context_tokens = 4096
    await install_read(runtime)
    row = session(runtime)
    runtime.db.execute(
        "UPDATE sessions SET generation=? WHERE id=?",
        ('{"max_output_tokens":512}', row["id"]),
    )
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
    ] * max(0, allowance - 1)
    model = FakeModel(
        [*summaries, read_call("source"), AssistantMessage("The park opens at 7 AM.")]
    )
    final = FakeModel([AssistantMessage("Earlier preferences are saved; more work is needed.")])
    use_models(runtime, model, final)
    events = await collect(runtime.start("alice", row["id"], "Check the opening time."))
    history = runtime.db.load_history("alice", row["id"])
    assert history[:2] == original
    assert len(model.requests) + len(final.requests) <= 6
    if allowance == 3:
        assert events[-1]["status"] == "completed"
        assert len(model.requests) == 4
        assert not final.requests
        assert history[-1].text == "The park opens at 7 AM."
        assert runtime.db.one("SELECT SUM(output_tokens) n FROM usage")["n"] == 10
        assert runtime.db.one("SELECT COUNT(*) n FROM usage")["n"] == 4
    else:
        assert events[-1]["status"] == "failed"
        assert len(model.requests) == max(0, allowance - 1)
        assert len(final.requests) == int(allowance > 0)
        assert "model context" in history[-1].text
        assert runtime.db.one("SELECT COALESCE(SUM(output_tokens),0) n FROM usage")["n"] == 5 * max(
            0, allowance - 1
        )


@pytest.mark.parametrize(
    "total,summaries,research,delegate",
    [
        (1, 0, 0, 0),
        (2, 0, 1, 1),
        (3, 1, 1, 1),
        (12, 2, 9, 4),
        (30, 5, 24, 10),
        (50, 9, 40, 17),
        (100, 17, 82, 34),
    ],
)
def test_omitted_counts_derive_from_total(total, summaries, research, delegate):
    settings = Settings(_env_file=None, provider="fake", max_model_calls=total)
    budget = TurnBudget(settings)
    assert budget.compaction.max_model_calls == summaries
    assert budget.research.max_model_calls == research
    assert budget.delegate_limit == delegate
    assert budget.recovery.max_model_calls == 1
    assert research + summaries + 1 == total


def test_environment_only_total_scales_omitted_counts(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_MODEL_CALLS", "50")
    monkeypatch.delenv("AGENT_MAX_COMPACTION_CALLS", raising=False)
    monkeypatch.delenv("AGENT_DELEGATE_MAX_MODEL_CALLS", raising=False)
    budget = TurnBudget(Settings(_env_file=None, provider="fake"))
    assert budget.compaction.max_model_calls == 9
    assert budget.delegate_limit == 17
    assert budget.research.max_model_calls == 40


def test_each_explicit_count_overrides_only_its_own_ratio():
    summaries = TurnBudget(
        Settings(_env_file=None, provider="fake", max_model_calls=50, max_compaction_calls=3)
    )
    assert summaries.compaction.max_model_calls == 3
    assert summaries.research.max_model_calls == 46
    assert summaries.delegate_limit == 17
    delegates = TurnBudget(
        Settings(_env_file=None, provider="fake", max_model_calls=50, delegate_max_model_calls=6)
    )
    assert delegates.compaction.max_model_calls == 9
    assert delegates.delegate_limit == 6
    disabled = TurnBudget(
        Settings(_env_file=None, provider="fake", max_model_calls=50, max_compaction_calls=0)
    )
    assert disabled.compaction.max_model_calls == 0
    assert disabled.research.max_model_calls == 49


def test_ratios_are_configurable_from_environment(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_MODEL_CALLS", "50")
    monkeypatch.setenv("AGENT_COMPACTION_CALL_RATIO", "0.2")
    monkeypatch.setenv("AGENT_DELEGATE_CALL_RATIO", "0.4")
    budget = TurnBudget(Settings(_env_file=None, provider="fake"))
    assert budget.compaction.max_model_calls == 10
    assert budget.delegate_limit == 20
    assert budget.research.max_model_calls == 39


@pytest.mark.parametrize(
    "field,value",
    [
        ("compaction_call_ratio", -0.1),
        ("compaction_call_ratio", 1.1),
        ("compaction_call_ratio", float("nan")),
        ("delegate_call_ratio", 0),
        ("delegate_call_ratio", 1.1),
        ("delegate_call_ratio", float("inf")),
    ],
)
def test_invalid_ratios_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, provider="fake", **{field: value})


def test_small_totals_and_large_overrides_stay_within_shared_pool():
    for total in range(1, 101):
        for override in (None, 0, 100):
            settings = Settings(
                _env_file=None,
                provider="fake",
                max_model_calls=total,
                max_compaction_calls=override,
                delegate_max_model_calls=100,
            )
            budget = TurnBudget(settings)
            assert budget.delegate_limit == budget.research.max_model_calls
            assert (
                budget.research.max_model_calls
                + budget.compaction.max_model_calls
                + budget.recovery.max_model_calls
                == total
            )
            while budget.research.spend():
                pass
            while budget.compaction.spend():
                pass
            while budget.final_compaction.spend():
                pass
            assert budget.recovery.spend()
            assert budget.total.used == total
            assert not budget.total.spend()


async def test_fifty_calls_with_derived_delegate_limit_is_enforced(runtime, monkeypatch):
    from harness import ToolCall, tool
    from theos.runtime import tools

    from .test_recovery import delegate_call

    runtime.settings.max_model_calls = 50
    runtime.settings.max_compaction_calls = None
    runtime.settings.delegate_max_model_calls = None

    @tool
    async def read_reference():
        """Read the test source."""
        return "Saved finding."

    monkeypatch.setattr(tools, "information_tools", lambda *args: [read_reference])
    parent = FakeModel([delegate_call(), AssistantMessage("Combined findings.")])
    children = [
        FakeModel(
            [
                AssistantMessage(tool_calls=[ToolCall(f"child-{i}-{j}", "read_reference", {})])
                for j in range(16)
            ]
            + [AssistantMessage("Complete handoff.")]
        )
        for i in range(2)
    ]
    use_models(runtime, parent, *children)
    row = session(runtime)
    result = await collect(runtime.start("alice", row["id"], "Compare sources."))
    assert result[-1]["status"] == "partial"
    assert all(len(child.requests) == 17 for child in children)
    assert all(not child.requests[-1].tools for child in children)
    assert len(parent.requests) == 2
    assert sum(len(model.requests) for model in [parent, *children]) == 36
