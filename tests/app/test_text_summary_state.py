"""Rolling summary checkpoints happen before the next answer request."""

import json

import pytest

from harness import Agent, AssistantMessage, Budget, ContextMemory, UserMessage
from harness.compaction import DEFAULT_SUMMARY_PROMPT
from harness.testing import FakeModel
from tests.context_fixtures import long_history
from theos.runtime import context


def policy(runtime, session, research_id=None, *, parent=True):
    return context.compaction(
        runtime,
        session,
        context.ModelCapacity(100_000, 8192, "test"),
        research_id,
        persist_session=parent,
    )


@pytest.mark.parametrize("research", [False, True])
async def test_parent_saves_summary_before_the_next_answer_request(runtime, research):
    row = runtime.db.create_session("alice", "test", "none")
    run = runtime.research.create("alice", row["id"], "Parent", "Task") if research else None
    if run:
        runtime.research.save_scratchpad(
            "alice", row["id"], run, "source", {"text": "Saved source"}
        )
    history = [*long_history(), UserMessage("Continue the original task.")]
    original = list(history)
    memory = ContextMemory()

    class Main(FakeModel):
        async def stream(self, request):
            if request.messages and getattr(request.messages[0], "content", "").startswith(
                DEFAULT_SUMMARY_PROMPT
            ):
                assert "Saved source" not in request.messages[1].content
                async for event in super().stream(request):
                    yield event
                return

            saved = json.loads(runtime.db.session("alice", row["id"])["memory"])
            assert saved["summary"] == memory.summary
            assert saved["covered_messages"] == memory.covered_messages
            if run:
                saved_run = runtime.research.get("alice", row["id"], run)
                assert json.loads(saved_run["memory"]) == saved
                assert (
                    runtime.research.scratchpad_item(
                        "alice",
                        row["id"],
                        runtime.research.scratchpad("alice", row["id"], run)[0]["id"],
                    )["content"]["text"]
                    == "Saved source"
                )
            assert history == original
            async for event in super().stream(request):
                yield event

    model = Main(
        [
            AssistantMessage("Preserve the original task, evidence, and open work."),
            AssistantMessage("Complete."),
        ]
    )
    await Agent(
        model,
        context_window=100_000,
        reserved_output_tokens=8192,
        compaction=policy(runtime, row, run),
    ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))
    assert history[:-1] == original


async def test_failed_checkpoint_rolls_back_saved_and_active_memory(runtime, monkeypatch):
    row = runtime.db.create_session("alice", "test", "none")
    history = [*long_history(), UserMessage("Continue.")]
    memory = ContextMemory.from_dict(
        {"schema_version": 4, "summary": "Previous summary.", "covered_messages": 2}
    )
    runtime.db.save_history("alice", row["id"], history, memory.to_dict())
    previous = runtime.db.session("alice", row["id"])
    save = runtime.db.save_history

    def failed_save(*args, **kwargs):
        save(*args, **kwargs)
        raise RuntimeError("Checkpoint write failed")

    monkeypatch.setattr(runtime.db, "save_history", failed_save)
    model = FakeModel([AssistantMessage("A shorter summary.")])
    with pytest.raises(RuntimeError, match="Checkpoint write failed"):
        await Agent(
            model,
            context_window=100_000,
            reserved_output_tokens=8192,
            compaction=policy(runtime, row),
        ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))
    after = runtime.db.session("alice", row["id"])
    assert (after["history"], after["memory"]) == (previous["history"], previous["memory"])
    assert memory.summary == "Previous summary." and memory.covered_messages == 2
    assert memory.to_dict()["schema_version"] == 4
    assert history[1].content in memory.checkpoint(history)
    assert len(model.requests) == 1  # The summary request ran; the answer request did not.


async def test_split_turn_checkpoint_is_saved_before_continuation_and_restored_without_request_replay(
    runtime,
):
    row = runtime.db.create_session("alice", "test", "none")
    task = UserMessage("Compare papers A, B, and C.")
    history = [
        UserMessage("Earlier task."),
        AssistantMessage("Earlier task complete."),
        task,
        AssistantMessage("Research evidence. " * 15_000),
        AssistantMessage("Latest retained finding."),
    ]
    original = list(history)
    memory = ContextMemory()

    class Model(FakeModel):
        async def stream(self, request):
            if len(self.requests) == 2:
                saved = json.loads(runtime.db.session("alice", row["id"])["memory"])
                restored = ContextMemory.from_dict(saved)
                assert saved["schema_version"] == 5
                assert saved["covered_messages"] == 4
                assert "Original Request" in saved["summary"]
                assert restored.view(history) == memory.view(history)
                assert task not in request.messages
                assert request.messages[-1] == original[-1]
                assert history == original
            async for event in super().stream(request):
                yield event

    model = Model(
        [
            AssistantMessage("Earlier task complete."),
            AssistantMessage(
                f"## Original Request\n{task.content}\n\n## Progress So Far\nPapers A and B reviewed."
            ),
            AssistantMessage("Comparison complete."),
        ]
    )
    await Agent(
        model, context_window=100_000, reserved_output_tokens=8192, compaction=policy(runtime, row)
    ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))
    assert len(model.requests) == 3
    assert history[:-1] == original


@pytest.mark.parametrize("research", [False, True])
async def test_child_summary_cannot_replace_the_parent_session(runtime, research):
    row = runtime.db.create_session("alice", "test", "none")
    parent = [UserMessage("Parent private task.")]
    runtime.db.save_history("alice", row["id"], parent)
    run = runtime.research.create("alice", row["id"], "Child", "Child task") if research else None
    history = [*long_history(), UserMessage("Continue.")]
    memory = ContextMemory()
    model = FakeModel([AssistantMessage("Child summary."), AssistantMessage("Child answer.")])
    await Agent(
        model,
        context_window=100_000,
        reserved_output_tokens=8192,
        compaction=policy(runtime, row, run, parent=False),
    ).run(history, memory=memory, budget=Budget(8), compaction_budget=Budget(8))
    assert runtime.db.load_history("alice", row["id"]) == parent
    if research:
        saved = runtime.research.get("alice", row["id"], run)
        assert json.loads(saved["memory"])["summary"] == memory.summary
        assert len(json.loads(saved["history"])) == len(history) - 1


def test_summary_state_has_only_the_rolling_summary_and_coverage():
    memory = ContextMemory("Saved evidence.", 17)
    assert memory.to_dict() == {
        "schema_version": 5,
        "summary": "Saved evidence.",
        "covered_messages": 17,
    }
    assert ContextMemory.from_dict(memory.to_dict()) == memory
