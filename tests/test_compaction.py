"""The rolling summary keeps the working view small and the raw history complete."""

import json

import pytest

from harness import (
    Agent,
    AssistantMessage,
    Budget,
    CompactionConfig,
    ContextMemory,
    ContextOverflowError,
    Hooks,
    ModelRequest,
    RunContext,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    history_tools,
    tool,
)
from harness.compaction import (
    DEFAULT_SUMMARY_PROMPT,
    INITIAL_SUMMARY_PROMPT,
    SUMMARY_LABEL,
    TURN_PREFIX_LABEL,
    TURN_PREFIX_SUMMARY_PROMPT,
    UPDATE_SUMMARY_PROMPT,
    CompactingModel,
)
from harness.testing import FakeModel
from harness.types import message_to_dict
from tests.context_fixtures import long_history


@pytest.mark.parametrize(
    "mode,kwargs",
    [
        ("Initial override", {"tier": 0}),
        ("Update override", {"tier": 0, "update": True}),
        ("Split override", {"tier": 0, "turn_prefix": True}),
        ("Shorten one", {"tier": 1}),
        ("Shorten two", {"tier": 2}),
        ("Shorten three", {"tier": 3}),
    ],
)
async def test_configured_operation_prompts_reach_the_summary_model(mode, kwargs):
    config = CompactionConfig(
        prompt="Shared override",
        initial_prompt="Initial override",
        update_prompt="Update override",
        turn_prefix_prompt="Split override",
        shortening_prompts=("Shorten one", "Shorten two", "Shorten three"),
        additional_instructions="Keep {{ literal }} evidence.",
    )
    model = FakeModel([AssistantMessage("A valid checkpoint.")])
    compacting = CompactingModel(model, 100_000, config, ContextMemory(), [], Budget(8))
    await compacting._summarize("Supplied evidence.", **kwargs)
    request = model.requests[0]
    separator = "\n" if kwargs["tier"] else "\n\n"
    assert request.messages[0].content == (
        f"Shared override{separator}{mode}\n\nAdditional focus: Keep {{{{ literal }}}} evidence."
    )
    assert request.messages[1].content == "Supplied evidence."
    assert not request.tools


@pytest.mark.parametrize("prompts", [(), ("Only one",), "abc", ("One", "Two", "")])
def test_invalid_shortening_prompt_configuration_is_rejected(prompts):
    with pytest.raises(ValueError, match="three nonempty prompts"):
        CompactionConfig(shortening_prompts=prompts)


async def test_auto_compaction_uses_one_summary_and_preserves_verbatim_history():
    history = [*long_history(), UserMessage("Latest request: write the report.")]
    original = [message_to_dict(message) for message in history]
    memory = ContextMemory()
    model = FakeModel(
        [
            AssistantMessage("Keep the exact dates, values, and unresolved work."),
            AssistantMessage("Report complete."),
        ]
    )

    async def add_scratchpad(request, _ctx):
        request.messages.insert(1, AssistantMessage("SCRATCHPAD ONLY: saved source records"))
        return request

    result = await Agent(
        model,
        hooks=Hooks(before_model=add_scratchpad),
        context_window=100_000,
        reserved_output_tokens=8192,
        compaction=CompactionConfig("Update the rolling summary."),
    ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))

    assert result.message.text == "Report complete."
    assert len(model.requests) == 2
    summary_input = model.requests[0].messages[1].content
    assert "Finding 0" in summary_input and "Finding 17" in summary_input
    assert "Latest request: write the report." not in summary_input
    assert "SCRATCHPAD ONLY" not in summary_input
    assert memory.summary == "Keep the exact dates, values, and unresolved work."
    assert memory.covered_messages == len(original) - 1
    assert history[:-1] == [
        __import__("harness").message_from_dict(message) for message in original
    ]
    assert any(
        isinstance(message, UserMessage) and message.content == "Latest request: write the report."
        for message in model.requests[1].messages
    )
    assert not any(
        isinstance(message, AssistantMessage)
        and "Finding 0: Evidence text." in (message.text or "")
        for message in model.requests[1].messages
    )


@pytest.mark.parametrize(
    "previous", ["", "Earlier verified result: USD 37.42. Still awaiting approval."]
)
async def test_summary_prompt_distinguishes_initial_checkpoint_from_incremental_update(previous):
    history = [*long_history(), UserMessage("Current request stays exact.")]
    current_request = history[-1]
    memory = ContextMemory(previous, 5 if previous else 0)
    model = FakeModel([AssistantMessage("Updated checkpoint."), AssistantMessage("Finished.")])

    await Agent(
        model,
        context_window=100_000,
        reserved_output_tokens=8192,
        compaction=CompactionConfig(
            additional_instructions="Retain the approval state and invoice amount."
        ),
    ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))

    summary_request, answer_request = model.requests
    instructions = summary_request.messages[0].content
    source = json.loads(summary_request.messages[1].content)
    assert instructions.startswith(DEFAULT_SUMMARY_PROMPT)
    assert (UPDATE_SUMMARY_PROMPT if previous else INITIAL_SUMMARY_PROMPT) in instructions
    assert (INITIAL_SUMMARY_PROMPT if previous else UPDATE_SUMMARY_PROMPT) not in instructions
    assert TURN_PREFIX_SUMMARY_PROMPT not in instructions
    assert "Additional focus: Retain the approval state and invoice amount." in instructions
    assert not summary_request.tools
    assert "Current request stays exact." not in summary_request.messages[1].content
    assert all("scope" not in row for row in source)
    if previous:
        assert source[0] == {"kind": "previous_summary", "content": previous}
        assert "Finding 0:" not in summary_request.messages[1].content
    else:
        assert all(row.get("kind") != "previous_summary" for row in source)
        assert "Finding 0:" in summary_request.messages[1].content
    assert current_request in answer_request.messages


def split_turn_history():
    return [
        SystemMessage("Keep saved rules."),
        UserMessage("Earlier task."),
        AssistantMessage("Earlier task completed."),
        UserMessage("Compare papers A, B, and C."),
        AssistantMessage(
            tool_calls=[
                ToolCall("paper-a", "read_paper", {"paper": "A"}),
                ToolCall("paper-b", "read_paper", {"paper": "B"}),
            ]
        ),
        ToolResultMessage("paper-a", "read_paper", "Paper A finding."),
        ToolResultMessage("paper-b", "read_paper", "Evidence B. " * 20_000),
        AssistantMessage(tool_calls=[ToolCall("paper-c", "read_paper", {"paper": "C"})]),
        ToolResultMessage("paper-c", "read_paper", "Paper C finding."),
    ]


async def test_split_turn_has_separate_summaries_and_resumes_with_only_the_retained_tail():
    history = split_turn_history()
    original = list(history)
    task = history[3].content
    turn_summary = f"## Original Request\n{task}\n\n## Progress So Far\nPaper A reviewed. Paper B evidence saved."
    model = FakeModel(
        [
            AssistantMessage("Earlier task completed."),
            AssistantMessage(turn_summary),
            AssistantMessage("Comparison complete."),
        ]
    )
    recorded = []

    async def record_summary(message):
        recorded.append(message.text)

    memory = ContextMemory()
    agent = Agent(
        model,
        context_window=100_000,
        reserved_output_tokens=8192,
        compaction=CompactionConfig(on_summary=record_summary),
    )
    await agent.run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))

    old_request, prefix_request, answer = model.requests
    assert INITIAL_SUMMARY_PROMPT in old_request.messages[0].content
    assert TURN_PREFIX_SUMMARY_PROMPT not in old_request.messages[0].content
    assert task not in old_request.messages[1].content
    assert TURN_PREFIX_SUMMARY_PROMPT in prefix_request.messages[0].content
    assert INITIAL_SUMMARY_PROMPT not in prefix_request.messages[0].content
    assert UPDATE_SUMMARY_PROMPT not in prefix_request.messages[0].content
    source = json.loads(prefix_request.messages[1].content)
    assert source[0] == {"role": "user", "content": task}
    assert "paper-a" in prefix_request.messages[1].content
    assert "paper-b" in prefix_request.messages[1].content
    assert "paper-c" not in prefix_request.messages[1].content
    assert not old_request.tools and not prefix_request.tools
    assert recorded == ["Earlier task completed.", turn_summary]
    assert memory.covered_messages == 7
    assert (
        memory.summary == f"Earlier task completed.\n\n---\n\n{TURN_PREFIX_LABEL}\n\n{turn_summary}"
    )
    assert answer.messages[0] == original[0]
    assert isinstance(answer.messages[1], UserMessage)
    assert memory.summary in answer.messages[1].content
    assert answer.messages[2:] == original[7:]
    assert original[3] not in answer.messages
    assert history[:-1] == original

    # A later compaction updates the checkpoint instead of repeating its request.
    previous_summary = memory.summary
    history.extend(
        [AssistantMessage("Further evidence. " * 20_000), AssistantMessage("Latest progress.")]
    )
    next_model = FakeModel(
        [
            AssistantMessage(f"## Goal\n{task}\n\n## Progress\nPapers A, B, and C reviewed."),
            AssistantMessage("Updated comparison."),
        ]
    )
    await Agent(
        next_model,
        context_window=100_000,
        reserved_output_tokens=8192,
        compaction=CompactionConfig(),
    ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))
    assert len(next_model.requests) == 2
    update, continuation = next_model.requests
    assert UPDATE_SUMMARY_PROMPT in update.messages[0].content
    source = json.loads(update.messages[1].content)
    assert source[0] == {"kind": "previous_summary", "content": previous_summary}
    assert not any(row.get("role") == "user" and row.get("content") == task for row in source[1:])
    assert not any(
        isinstance(message, UserMessage) and message.content == task
        for message in continuation.messages
    )


@pytest.mark.parametrize("failure", ["budget", "truncated"])
@pytest.mark.parametrize("mandatory", [False, True])
async def test_split_turn_failure_never_commits_only_the_history_summary(failure, mandatory):
    history = split_turn_history()
    if mandatory:
        history[6] = ToolResultMessage("paper-b", "read_paper", "Evidence B. " * 40_000)
    original = list(history)
    script = [AssistantMessage("Earlier task completed.")]
    if failure == "truncated":
        script.append(AssistantMessage("Incomplete turn summary.", stop_reason="length"))
    script.append(AssistantMessage("Continue with the full history."))
    model = FakeModel(script)
    memory = ContextMemory()
    agent = Agent(
        model, context_window=100_000, reserved_output_tokens=8192, compaction=CompactionConfig()
    )
    kwargs = dict(
        memory=memory, budget=Budget(8), compaction_budget=Budget(1 if failure == "budget" else 8)
    )
    if mandatory:
        with pytest.raises(ContextOverflowError, match="could not be summarized safely"):
            await agent.run(history, **kwargs)
        assert history == original
    else:
        result = await agent.run(history, **kwargs)
        assert result.message.text == "Continue with the full history."
        assert model.requests[-1].messages == original
        assert history[:-1] == original
    assert memory.summary == "" and memory.covered_messages == 0


async def test_forced_compaction_keeps_an_unfinished_tool_batch_in_the_retained_tail():
    history = [
        UserMessage("Compare papers and preserve their differences. " * 1000),
        AssistantMessage(
            tool_calls=[
                ToolCall("paper-a", "read_paper", {"paper": "A"}),
                ToolCall("paper-b", "read_paper", {"paper": "B"}),
            ]
        ),
        ToolResultMessage("paper-a", "read_paper", "Paper A finding."),
    ]
    original = list(history)
    memory = ContextMemory()
    model = FakeModel(
        [AssistantMessage("Original request: compare papers and preserve their differences.")]
    )
    compacting = CompactingModel(model, 100_000, CompactionConfig(), memory, history, Budget(8))

    async def rebuild(messages):
        return ModelRequest(list(messages))

    prepared = [
        event
        async for event in compacting.prepare(ModelRequest(history), rebuild=rebuild, force=True)
        if isinstance(event, ModelRequest)
    ]
    assert len(prepared) == 1
    assert memory.covered_messages == 1
    assert history[0] not in prepared[0].messages
    assert prepared[0].messages[1:] == original[1:]
    assert history == original


@pytest.mark.parametrize("previous", ["", "Earlier requirement: approval is still pending."])
async def test_tool_batch_compacts_before_next_answer_and_never_runs_twice(previous):
    calls = 0

    @tool
    async def read_once():
        """Read one saved source."""
        nonlocal calls
        calls += 1
        return "Saved fact: 42. " + "source text " * 50_000

    class Model(FakeModel):
        async def stream(self, request):
            self.requests.append(request)
            has_summary = any(
                isinstance(message, UserMessage)
                and "Summary contains saved fact 42." in message.content
                for message in request.messages
            )
            if has_summary:
                item = AssistantMessage("The saved fact is 42.")
            elif request.tools:
                item = AssistantMessage(tool_calls=[ToolCall("read", "read_once", {})])
            elif request.messages and isinstance(request.messages[0], SystemMessage):
                item = AssistantMessage("Summary contains saved fact 42.")
            else:
                item = AssistantMessage("The saved fact is 42.")
            yield __import__("harness.events", fromlist=["GenerationComplete"]).GenerationComplete(
                item
            )

    model = Model([])
    earlier = (
        [UserMessage("Earlier task."), AssistantMessage("Approval is pending.")] if previous else []
    )
    history = [*earlier, UserMessage("Read the source and report its key fact.")]
    memory = ContextMemory(previous, len(earlier))
    result = await Agent(
        model,
        [read_once],
        context_window=200_000,
        reserved_output_tokens=8192,
        compaction=CompactionConfig(),
    ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))

    assert result.message.text == "The saved fact is 42."
    assert calls == 1
    assert len(model.requests) == 3  # tool call, rolling summary, next assistant response
    summary_request, answer_request = model.requests[1:]
    assert INITIAL_SUMMARY_PROMPT not in summary_request.messages[0].content
    assert UPDATE_SUMMARY_PROMPT not in summary_request.messages[0].content
    assert TURN_PREFIX_SUMMARY_PROMPT in summary_request.messages[0].content
    source = json.loads(summary_request.messages[1].content)
    assert source[0] == {"role": "user", "content": "Read the source and report its key fact."}
    assert all(row.get("kind") != "previous_summary" for row in source)
    if previous:
        assert memory.summary.startswith(previous)
    assert "large_message_available_in_history" in summary_request.messages[1].content
    assert f'"message_index": {len(earlier) + 2}' in summary_request.messages[1].content
    assert memory.summary.endswith(f"{TURN_PREFIX_LABEL}\n\nSummary contains saved fact 42.")
    assert not any(
        isinstance(message, UserMessage) and message.content.startswith("Read the source")
        for message in answer_request.messages
    )
    assert not any(isinstance(message, ToolResultMessage) for message in answer_request.messages)
    assert any(
        isinstance(message, ToolResultMessage) and "source text" in message.content
        for message in history
    )


async def test_shortening_passes_replace_structured_format_and_preserve_focus():
    history = [*long_history(), UserMessage("Continue the task.")]
    memory = ContextMemory()
    summaries = ["a" * 440_000, "b" * 430_000, "c" * 420_000]
    model = FakeModel(
        [
            *(AssistantMessage(summary) for summary in summaries),
            AssistantMessage("The invoice amount is verified and approval is pending."),
            AssistantMessage("Ready for the next step."),
        ]
    )
    await Agent(
        model,
        context_window=100_000,
        reserved_output_tokens=8192,
        compaction=CompactionConfig(additional_instructions="Preserve the pending approval."),
    ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))

    assert len(model.requests) == 5
    assert INITIAL_SUMMARY_PROMPT in model.requests[0].messages[0].content
    lengths = ["a short paragraph", "three short sentences", "one concise sentence"]
    for tier, (request, length) in enumerate(zip(model.requests[1:4], lengths, strict=True), 1):
        instructions = request.messages[0].content
        assert f"Shortening pass {tier}: reduce the previous summary to {length}" in instructions
        assert "Omit the structured headings" in instructions
        assert INITIAL_SUMMARY_PROMPT not in instructions
        assert UPDATE_SUMMARY_PROMPT not in instructions
        assert TURN_PREFIX_SUMMARY_PROMPT not in instructions
        assert "Additional focus: Preserve the pending approval." in instructions
        assert request.messages[1].content == summaries[tier - 1]
        assert not request.tools
    assert memory.summary == "The invoice amount is verified and approval is pending."


async def test_overflow_resends_shorten_summary_and_keep_completed_tool_batch_once():
    calls = 0

    @tool
    async def read_once():
        """Read a saved source."""
        nonlocal calls
        calls += 1
        return "Verified value 42. " + "detail " * 80_000

    model = FakeModel(
        [
            AssistantMessage(tool_calls=[ToolCall("read", "read_once", {})]),
            AssistantMessage("Summary tier one. " * 2000),
            ContextOverflowError("The request exceeds the context window."),
            AssistantMessage("Summary tier two. " * 700),
            ContextOverflowError("The request exceeds the context window."),
            AssistantMessage("Summary tier three."),
            AssistantMessage("The verified value is 42."),
        ]
    )
    history = [UserMessage("Read the source and report the verified value.")]
    memory = ContextMemory()
    result = await Agent(
        model,
        [read_once],
        context_window=200_000,
        reserved_output_tokens=8192,
        compaction=CompactionConfig("Update the rolling summary."),
    ).run(history, memory=memory, budget=Budget(20), compaction_budget=Budget(20))

    assert result.message.text == "The verified value is 42."
    assert calls == 1
    assert len(model.requests) == 7
    attempts = [model.requests[index] for index in (2, 4, 6)]
    from harness.context_size import request_size

    assert all(
        request_size(left) > request_size(right)
        for left, right in zip(attempts, attempts[1:], strict=False)
    )
    assert [message.name for message in history if isinstance(message, ToolResultMessage)] == [
        "read_once"
    ]
    assert not any(
        isinstance(message, AssistantMessage) and message.tool_calls
        for message in attempts[-1].messages
    )


async def test_summary_model_trigger_and_tail_are_configurable():
    history = [*long_history(), UserMessage("Latest request.")]
    main_model = FakeModel([AssistantMessage("Finished.")])
    summary_model = FakeModel([AssistantMessage("Compact facts.")])
    memory = ContextMemory()

    await Agent(
        main_model,
        context_window=100_000,
        reserved_output_tokens=2048,
        compaction=CompactionConfig(
            "Update the rolling summary.",
            {"max_tokens": 2000},
            trigger_ratio=0.01,
            tail_ratio=0.1,
            summary_model=summary_model,
            summary_window=10_000,
        ),
    ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))

    assert len(summary_model.requests) == 1
    assert summary_model.requests[0].options["max_tokens"] == 1000
    assert len(main_model.requests) == 1
    assert memory.summary == "Compact facts."


async def test_irreducible_current_request_stays_unchanged_and_stops_before_provider():
    history = [UserMessage("Do not omit this task. " * 20_000)]
    memory = ContextMemory("Previous summary.", 0)
    model = FakeModel([])
    with pytest.raises(ContextOverflowError, match="current task"):
        await Agent(
            model,
            context_window=16_000,
            reserved_output_tokens=8192,
            compaction=CompactionConfig("Summarize older messages."),
        ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))
    assert model.requests == []
    assert memory.summary == "Previous summary." and memory.covered_messages == 0
    assert history == [UserMessage("Do not omit this task. " * 20_000)]


def test_memory_view_places_checkpoint_before_tail_without_repeating_the_covered_request():
    history = [
        SystemMessage("Saved system rule."),
        UserMessage("Original task."),
        AssistantMessage("Older answer."),
        UserMessage("Current task, exactly as written."),
        AssistantMessage("Current tool result summary."),
    ]
    original = [message_to_dict(message) for message in history]
    memory = ContextMemory("Earlier facts.", 4)
    view = memory.view(history)
    assert view[0] == history[0]
    assert isinstance(view[1], UserMessage)
    assert view[1].content.startswith(SUMMARY_LABEL)
    assert "Earlier facts." in view[1].content
    assert history[3] not in view
    assert len(view) == 3
    assert view[-1] == history[4]
    assert ContextMemory.from_dict(memory.to_dict()) == memory
    assert [message_to_dict(message) for message in history] == original


async def test_version_four_checkpoint_carries_its_omitted_request_through_restart_and_update():
    history = [
        UserMessage("Compare papers A, B, and C."),
        AssistantMessage("Paper A reviewed."),
        AssistantMessage("Paper B reviewed."),
        AssistantMessage("Further evidence. " * 20_000),
        AssistantMessage("Latest progress."),
    ]
    memory = ContextMemory.from_dict(
        {
            "schema_version": 4,
            "summary": "Papers A and B reviewed.",
            "covered_messages": 3,
        }
    )
    saved = memory.to_dict()
    view = memory.view(history)
    assert history[0].content in view[0].content
    assert history[0] not in view
    assert view[1:] == history[3:]
    assert ContextMemory.from_dict(saved).view(history) == view
    model = FakeModel(
        [
            AssistantMessage("Compare papers A, B, and C. Papers A and B reviewed."),
            AssistantMessage("Comparison complete."),
        ]
    )
    await Agent(
        model, context_window=100_000, reserved_output_tokens=8192, compaction=CompactionConfig()
    ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))
    assert UPDATE_SUMMARY_PROMPT in model.requests[0].messages[0].content
    assert history[0].content in json.loads(model.requests[0].messages[1].content)[0]["content"]
    assert memory.to_dict()["schema_version"] == 5
    assert history[0] not in model.requests[-1].messages
    assert ContextMemory.from_dict(memory.to_dict()).view(history) == memory.view(history)


async def test_history_tools_return_verbatim_pages_and_search_the_raw_transcript():
    history = [
        UserMessage("Task"),
        ToolResultMessage("call-1", "mail_read", "Invoice Straße total USD 37.42."),
    ]
    tools_by_name = {item.name: item for item in history_tools()}
    ctx = RunContext(None, history=history)
    read = tools_by_name["history_read"]
    result = await read.execute(
        read.input_model.model_validate({"call_id": "call-1", "offset": 8, "limit": 13}), ctx
    )
    assert result["content"] == history[1].content[8:21]
    assert result["next_offset"] == 21

    search = tools_by_name["history_search"]
    found = await search.execute(search.input_model.model_validate({"query": "strasse"}), ctx)
    assert found["matches"][0]["message_index"] == 1
    assert "Straße" in found["matches"][0]["snippet"]
    assert history[1].content == "Invoice Straße total USD 37.42."
