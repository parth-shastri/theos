"""Session state survives a restart without changing the model transcript."""

from contextlib import aclosing

import pytest

from harness import Agent, AssistantMessage, CompactionConfig, JsonlStore, MemoryStore, UserMessage
from harness.testing import FakeModel
from renderer import AgentSession


@pytest.mark.parametrize("persistent", [False, True])
async def test_session_metadata_timestamps_and_manual_title_survive_restart(tmp_path, persistent):
    store = JsonlStore(tmp_path) if persistent else MemoryStore()
    session = AgentSession(Agent(FakeModel([AssistantMessage(text="Done.")] * 3)), store)
    await session.create_session("work")
    original = (await session.session_details())[-1]
    for prompt in ("Hello!", "# IDE context\n## My request:\nPlease fix the tool nesting."):
        _ = [event async for event in session.stream(prompt, session_id="work")]
    assert await session.session_title("work") == "Fix the tool nesting"
    await session.rename_session("work", "Renderer changes")
    _ = [event async for event in session.stream("Continue", session_id="work")]
    await session.archive_session("work", True)
    times = await session.history_timestamps("work")
    assert len(times) == 6 and all(times)
    history = await session.history("work")
    reopened = AgentSession(session.agent, JsonlStore(tmp_path) if persistent else store)
    info = next(item for item in await reopened.session_details() if item.session_id == "work")
    assert info.title == "Renderer changes" and info.archived
    assert info.created_at == original.created_at
    assert info.cwd == original.cwd
    assert info.updated_at >= info.created_at
    assert await reopened.history_timestamps("work") == times
    assert await reopened.history("work") == history
    assert (await reopened.session_details()) == (await reopened.session_details())


async def test_resumed_session_uses_saved_compaction_memory(tmp_path):
    store = JsonlStore(tmp_path)
    history = [UserMessage("Compare both options. " + "x" * 5600),
               AssistantMessage(text="First option examined. " + "y" * 5600)]
    await store.save("research", history)
    config = CompactionConfig("Summarize the conversation.", {"max_tokens": 256}, 128)
    model = FakeModel([AssistantMessage(text="Compare both options; first option examined.")] * 3)
    session = AgentSession(Agent(model, context_window=2000, reserved_output_tokens=256,
                                 compaction=config), store)
    _ = [event async for event in session.stream("Continue with the other option.", session_id="research")]
    state = await store.load_state("research")
    assert state["memory"]["covered_messages"] == 2
    assert state["memory"]["summary"]
    assert (await store.load("research"))[:2] == history

    next_model = FakeModel([AssistantMessage(text="Here is the comparison.")])
    resumed = AgentSession(Agent(next_model, context_window=2000, reserved_output_tokens=256,
                                 compaction=config), JsonlStore(tmp_path))
    _ = [event async for event in resumed.stream("Explain further.", session_id="research")]
    assert len(next_model.requests) == 1
    assert state["memory"]["summary"] in str(next_model.requests[0].messages)
    assert "x" * 5600 not in str(next_model.requests[0].messages)


async def test_legacy_histories_and_state_isolation(tmp_path):
    store = JsonlStore(tmp_path)
    await store.save("old", [UserMessage("Explain bare-metal deployment")])
    session = AgentSession(Agent(FakeModel([])), store)
    assert await session.session_title("old") == "Explain bare-metal deployment"
    assert await session.history_timestamps("old") == ()
    await session.create_session("new")
    assert not await session.history("new")
    assert not (await store.load_state("new")).get("memory")
    assert len(await session.history("old")) == 1
    assert set(await store.keys()) == {"old", "new"}


async def test_closing_session_stream_closes_agent_and_saves_history():
    closed = []

    class StreamingAgent:
        async def run_stream(self, history, **kwargs):
            try:
                history.append(AssistantMessage(text="Partial response"))
                yield "partial"
            finally:
                closed.append(True)

    session = AgentSession(StreamingAgent())
    async with aclosing(session.stream("Hello", session_id="cancelled")) as stream:
        assert await anext(stream) == "partial"
    assert closed == [True]
    assert len(await session.history("cancelled")) == 2
    assert len(await session.history_timestamps("cancelled")) == 2
