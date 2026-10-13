"""Summary checkpoints before generation, rollback, and child isolation."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from math import inf

import pytest

from harness import Agent, AssistantMessage, Budget, ContextMemory, UserMessage
from harness.testing import FakeModel
from tests.test_bounded_context import transcript
from theos.runtime import context


def policy(runtime, session, research_id=None, *, parent=True):
    auxiliary = FakeModel([AssistantMessage("## Goal\nContinue the task.")])

    @asynccontextmanager
    async def summaries():
        yield auxiliary

    return replace(
        context.compaction(
            runtime,
            session,
            context.ModelCapacity(100000, 8192, "test"),
            research_id,
            persist_session=parent,
        ),
        summary_model=summaries,
        summary_window=100000,
    )


@pytest.mark.parametrize("research", [False, True])
async def test_parent_saves_text_and_references_before_the_answer_request(runtime, research):
    row = runtime.db.create_session("alice", "test", "none")
    run = runtime.research.create("alice", row["id"], "Parent", "Task") if research else None
    ids = []
    if run:
        ids.append(
            runtime.research.save_item("alice", row["id"], run, "source", {"text": "Evidence"})
        )
    history = transcript()
    memory = ContextMemory()

    class Main(FakeModel):
        async def stream(self, request):
            saved = json.loads(runtime.db.session("alice", row["id"])["memory"])
            assert isinstance(saved["summary"], str) and saved["summary"].startswith("[CONTEXT")
            assert saved["state"]["references"]["anchors"] == memory.state["references"]["anchors"]
            assert saved["state"]["references"]["record_ids"] == ids
            if run:
                saved_run = runtime.research.get("alice", row["id"], run)
                assert json.loads(saved_run["memory"]) == saved
            assert runtime.db.load_history("alice", row["id"]) == history
            async for event in super().stream(request):
                yield event

    await Agent(
        Main([AssistantMessage("Complete.")]),
        context_window=100000,
        compaction=policy(runtime, row, run),
    ).run(history, memory=memory, budget=Budget(inf))


async def test_failed_checkpoint_rolls_back_saved_and_active_memory(runtime, monkeypatch):
    row = runtime.db.create_session("alice", "test", "none")
    history = transcript()
    memory = ContextMemory("Previous summary.", 2)
    runtime.db.save_history("alice", row["id"], history, memory.to_dict())
    previous = runtime.db.session("alice", row["id"])
    save = runtime.db.save_history

    def failed_save(*args, **kwargs):
        save(*args, **kwargs)
        raise RuntimeError("Checkpoint write failed")

    monkeypatch.setattr(runtime.db, "save_history", failed_save)
    main = FakeModel([])
    with pytest.raises(RuntimeError, match="Checkpoint write failed"):
        await Agent(main, context_window=100000, compaction=policy(runtime, row)).run(
            history, memory=memory, budget=Budget(inf)
        )
    after = runtime.db.session("alice", row["id"])
    assert (after["history"], after["memory"]) == (previous["history"], previous["memory"])
    assert memory.summary == "Previous summary." and memory.working_messages is None
    assert not main.requests


@pytest.mark.parametrize("research", [False, True])
async def test_child_summary_cannot_replace_the_parent_session(runtime, research):
    row = runtime.db.create_session("alice", "test", "none")
    parent = [UserMessage("Parent private task.")]
    runtime.db.save_history("alice", row["id"], parent)
    run = runtime.research.create("alice", row["id"], "Child", "Child task") if research else None
    history = transcript()
    memory = ContextMemory()
    await Agent(
        FakeModel([AssistantMessage("Child answer.")]),
        context_window=100000,
        compaction=policy(runtime, row, run, parent=False),
    ).run(history, memory=memory, budget=Budget(inf))
    assert runtime.db.load_history("alice", row["id"]) == parent
    if research:
        saved = runtime.research.get("alice", row["id"], run)
        assert json.loads(saved["memory"])["summary"] == memory.summary
        assert len(json.loads(saved["history"])) == len(history) - 1


def test_tail_settings_keep_the_recovery_default_and_accept_explicit_choices(monkeypatch):
    from pydantic import ValidationError

    from theos.settings import Settings

    monkeypatch.delenv("AGENT_COMPACTION_TAIL_MODE", raising=False)
    assert Settings(_env_file=None).compaction_tail_mode == "lean"
    monkeypatch.setenv("AGENT_COMPACTION_TAIL_MODE", "current")
    monkeypatch.setenv("AGENT_COMPACTION_MIN_TAIL_USER_MESSAGES", "3")
    settings = Settings(_env_file=None)
    assert settings.compaction_tail_mode == "current"
    assert settings.compaction_min_tail_user_messages == 3
    with pytest.raises(ValidationError):
        Settings(_env_file=None, compaction_min_tail_user_messages=0)
