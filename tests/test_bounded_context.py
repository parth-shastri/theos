"""Parity and integration checks for the single pinned compression policy."""

import asyncio
import json
from contextlib import asynccontextmanager
from math import inf

import pytest

from harness import (
    Agent,
    AssistantMessage,
    Budget,
    CompactionConfig,
    ContextMemory,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from harness.compression_policy import ContextCompressor
from harness.context_size import ContextOverflowError, request_size
from harness.lean_context import LeanModel, wire_messages
from harness.testing import FakeModel
from harness.types import ModelRequest, message_to_dict


def transcript():
    return (
        [UserMessage("Preserve dates and exact values.")]
        + [
            m
            for i in range(18)
            for m in (
                UserMessage(f"Question {i}"),
                AssistantMessage(f"Finding {i}: " + "Evidence text. " * 5000),
            )
        ]
        + [UserMessage("Make the report.")]
    )


@pytest.mark.parametrize(
    "window,output,trigger,tail,summary",
    [
        (100000, 8192, 68856, 10000, 5000),
        (1000000, 8192, 495904, 25000, 10000),
        (16000, 4096, 10118, 3200, 800),
    ],
)
def test_pinned_budget_formulas(window, output, trigger, tail, summary):
    policy = ContextCompressor(window, output)
    assert (policy.threshold_tokens, policy.tail_token_budget, policy.max_summary_tokens) == (
        trigger,
        tail,
        summary,
    )


def test_pruning_preserves_arguments_latest_small_round_and_original():
    call = ToolCall("1", "gmail_get_message", {"message_id": "exact"})
    history = [UserMessage("Earlier"), AssistantMessage("Earlier reply")] * 5 + [
        UserMessage("Analyze."),
        AssistantMessage(tool_calls=[call]),
        ToolResultMessage("1", "gmail_get_message", "x" * 400000),
    ]
    rows = wire_messages(history)
    before = json.dumps(rows)
    policy = ContextCompressor(100000, 8192)
    pruned, count = policy._prune_old_tool_results(rows, 20, policy.tail_token_budget)
    assert count and len(pruned[-1]["content"]) < 400
    assert pruned[-2]["tool_calls"] == rows[-2]["tool_calls"]
    assert json.dumps(rows) == before
    rows[-1]["content"] = "An invoice for USD 42.00."
    protected, count = policy._prune_old_tool_results(rows, 20, policy.tail_token_budget)
    assert protected[-1]["content"] == rows[-1]["content"]


def test_sampling_is_bounded_and_covers_head_middle_tail():
    policy = ContextCompressor(100000, 8192)
    records = [f"RECORD {i}: " + ("x" * 5000) for i in range(400)]
    sample, coverage = policy._sample_summary_records(records)
    assert len(sample) <= 160000
    assert "RECORD 0:" in sample and "RECORD 399:" in sample
    assert 8 <= coverage["sampled_record_count"] < 400
    assert coverage["omitted_chars"] > 0


async def test_single_auxiliary_call_protected_head_tail_and_iterative_summary():
    history = transcript()
    original = [message_to_dict(m) for m in history]
    summary = FakeModel(
        [AssistantMessage("## Goal\nReport expenses. Preserve date 2026-10-12 and USD 42.00.")] * 2
    )

    @asynccontextmanager
    async def auxiliary():
        yield summary

    config = CompactionConfig(
        "Unused compatibility prompt", summary_model=auxiliary, summary_window=100000
    )
    memory = ContextMemory()
    main = FakeModel([AssistantMessage("Useful report.")])
    result = await Agent(main, context_window=100000, compaction=config).run(
        history, budget=Budget(inf), memory=memory
    )
    assert result.message.text == "Useful report." and len(summary.requests) == 1
    assert [message_to_dict(m) for m in history[:-1]] == original
    assert memory.summary and memory.working_messages is not None
    assert main.requests[0].messages[-1].content == "Make the report."
    assert any(
        isinstance(m, UserMessage) and m.content == "Preserve dates and exact values."
        for m in main.requests[0].messages
    )
    assert request_size(main.requests[0]) < 100000 - 8192
    history.extend(transcript())
    second = FakeModel([AssistantMessage("Updated report.")])
    await Agent(second, context_window=100000, compaction=config).run(
        history, budget=Budget(inf), memory=memory
    )
    assert len(summary.requests) == 2
    assert "PREVIOUS SUMMARY:" in summary.requests[1].messages[0].content
    assert "USD 42.00" in summary.requests[1].messages[0].content


async def test_provider_usage_anchor_persists_and_invalidates_on_prefix_change():
    memory = ContextMemory()
    history = [UserMessage("one")]
    raw = FakeModel([AssistantMessage("answer", usage={"input_tokens": 777, "output_tokens": 10})])
    model = LeanModel(raw, 100000, CompactionConfig(""), memory, history, Budget(inf))
    request = ModelRequest(history)
    async for _ in model.stream(request):
        pass
    restored = ContextMemory.from_dict(memory.to_dict())
    resumed = LeanModel(raw, 100000, CompactionConfig(""), restored, history, Budget(inf))
    assert await resumed.estimate_tokens(request) == 777
    assert await resumed.estimate_tokens(ModelRequest([UserMessage("changed")])) != 777


async def test_cancelled_summary_keeps_previous_checkpoint():
    class Cancel(FakeModel):
        async def stream(self, request):
            raise asyncio.CancelledError()
            yield

    memory = ContextMemory()
    history = transcript()
    with pytest.raises(asyncio.CancelledError):
        await Agent(Cancel([]), context_window=100000, compaction=CompactionConfig("")).run(
            history, budget=Budget(inf), memory=memory
        )
    assert not memory.summary and memory.working_messages is None


async def test_access_failure_retains_transcript_and_arms_cooldown():
    class Denied(Exception):
        status_code = 401

    history = transcript()
    memory = ContextMemory()
    raw = FakeModel([Denied(), AssistantMessage("Answer from available evidence.")])
    result = await Agent(raw, context_window=100000, compaction=CompactionConfig("")).run(
        history, budget=Budget(inf), memory=memory
    )
    assert result.message.text == "Answer from available evidence."
    assert memory.summary and memory.state["failures"]["access"] == 1
    assert request_size(raw.requests[-1]) + 8192 <= 100000
    assert memory.state["cooldown_until"] > 0


async def test_overflow_compacts_without_reexecuting_tools():
    history = transcript()
    memory = ContextMemory()
    raw = FakeModel(
        [
            AssistantMessage("## Goal\nKeep the task."),
            ContextOverflowError(),
            AssistantMessage("## Goal\nSmaller summary."),
            AssistantMessage("Useful result."),
        ]
    )
    result = await Agent(raw, context_window=100000, compaction=CompactionConfig("")).run(
        history, budget=Budget(inf), memory=memory
    )
    assert result.message.text == "Useful result."
    assert "learned_window" not in memory.state  # Never invent a provider capacity.


async def test_distinct_auxiliary_failure_retries_main_once():
    history = transcript()
    memory = ContextMemory()
    auxiliary = FakeModel([RuntimeError("temporary auxiliary failure")])
    auxiliary.model_id = "cheap-summary"
    main = FakeModel(
        [
            AssistantMessage("Retained evidence and requirements."),
            AssistantMessage("Useful report."),
        ]
    )
    main.model_id = "main"

    @asynccontextmanager
    async def summaries():
        yield auxiliary

    config = CompactionConfig("", summary_model=summaries)
    result = await Agent(main, context_window=100000, compaction=config).run(
        history, memory=memory, budget=Budget(inf)
    )
    assert result.message.text == "Useful report."
    assert len(auxiliary.requests) == 1 and len(main.requests) == 2 and memory.summary


async def test_truncated_summary_keeps_original_middle_and_fits_a_recovery_handoff():
    history = transcript()
    memory = ContextMemory()
    auxiliary = FakeModel([AssistantMessage("Incomplete handoff", stop_reason="length")])

    @asynccontextmanager
    async def summaries():
        yield auxiliary

    main = FakeModel([AssistantMessage("Useful answer from existing evidence.")])
    await Agent(
        main, context_window=100000, compaction=CompactionConfig("", summary_model=summaries)
    ).run(history, memory=memory, budget=Budget(inf))
    assert memory.summary and "Incomplete handoff" not in memory.summary
    assert "Finding 10:" in str(history)
    assert request_size(main.requests[0]) + 8192 <= 100000
    assert memory.state["failures"]["truncated"] == 1


async def test_repeated_timeout_uses_recoverable_deterministic_handoff():
    history = transcript()
    memory = ContextMemory()
    auxiliary = FakeModel([TimeoutError(), TimeoutError()])

    @asynccontextmanager
    async def summaries():
        yield auxiliary

    model = LeanModel(
        FakeModel([]),
        100000,
        CompactionConfig("", summary_model=summaries),
        memory,
        history,
        Budget(inf),
    )
    request = ModelRequest(history)
    _ = [event async for event in model.prepare(request, force=True)]
    assert memory.summary and request_size(_[-1]) + 8192 <= 100000
    _ = [event async for event in model.prepare(request, force=True)]
    assert memory.summary and memory.state["last_compaction"]["method"] == "deterministic_fallback"
    assert "history_read" in memory.summary


async def test_saved_system_instructions_survive_compaction_without_duplicating_live_prefix():
    history = [SystemMessage("Saved policy."), *transcript()]
    model = FakeModel(
        [AssistantMessage("Retained task and evidence."), AssistantMessage("First answer.")]
    )
    memory = ContextMemory()
    await Agent(
        model, instructions="Live prefix.", context_window=100000, compaction=CompactionConfig("")
    ).run(history, memory=memory, budget=Budget(inf))
    resumed = FakeModel([AssistantMessage("Next answer.")])
    history.append(UserMessage("Continue."))
    await Agent(
        resumed, instructions="Live prefix.", context_window=100000, compaction=CompactionConfig("")
    ).run(history, memory=ContextMemory.from_dict(memory.to_dict()), budget=Budget(inf))
    policies = [m.content for m in resumed.requests[0].messages if isinstance(m, SystemMessage)]
    assert policies == ["Live prefix.", "Saved policy."]


def test_summary_timeout_classification_survives_provider_error_wrapping():
    from harness.lean_context import failure_kind

    inner = TimeoutError("provider timed out")
    outer = RuntimeError("safe provider message")
    outer.__cause__ = inner
    assert failure_kind(outer) == "timeout"


def test_protected_assistant_keeps_signed_replay_and_reasoning_budget():
    from harness.compression_policy import _estimate_msg_budget_tokens
    from harness.lean_context import restore_rows

    message = AssistantMessage(
        tool_calls=[ToolCall("pending", "read", {})],
        reasoning="Thinking. " * 400,
        provider_data={
            "anthropic": {
                "content": [{"type": "thinking", "signature": "signed", "thinking": "Thought"}]
            }
        },
    )
    rows = wire_messages([message])
    assert _estimate_msg_budget_tokens(rows[0]) > 500
    assert restore_rows(rows) == [message]
