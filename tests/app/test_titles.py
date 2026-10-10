"""Automatic names preserve replies, custom titles, and owner boundaries."""

import json

import pytest

from harness import AssistantMessage, ToolResultMessage, UserMessage
from harness.testing import FakeModel
from theos.runtime.titles import update_title
from theos.runtime.turn import Turn

from .conftest import collect


async def test_titles_generate_refine_once_and_account(runtime, scripted_models):
    runtime.settings.auto_titles = True
    session = runtime.db.create_session("alice", "test-model", "default")
    scripts = [
        [
            AssistantMessage("Let's plan."),
            AssistantMessage("A week in Japan", usage={"input_tokens": 20, "output_tokens": 5}),
        ],
        [AssistantMessage("Kyoto is a good stop.")],
        [AssistantMessage("Here is a route."), AssistantMessage("Japan itinerary with Kyoto")],
        [AssistantMessage("Enjoy your trip.")],
    ]
    for number, script in enumerate(scripts):
        scripted_models.responses.append(script)
        events = await collect(runtime.start("alice", session["id"], f"Plan Japan day {number}"))
        assert events[-1]["status"] == "completed"
        assert sum(event["type"] == "title" for event in events) == int(number in {0, 2})
    saved = runtime.db.session("alice", session["id"])
    assert saved["title"] == "Japan itinerary with Kyoto"
    assert saved["title_attempts"] == 2
    assert len(runtime.db.load_history("alice", session["id"])) == 8
    assert runtime.db.one("SELECT SUM(input_tokens) AS tokens FROM usage")["tokens"] == 20
    await runtime.reset("alice", session["id"])
    assert runtime.db.session("alice", session["id"])["title"] == "New conversation"
    assert runtime.db.session("alice", session["id"])["title_attempts"] == 0


async def test_custom_titles_and_other_transports_unchanged(runtime, scripted_models):
    runtime.settings.auto_titles = True
    for title, channel in [("My custom title", "browser"), ("New conversation", "telegram")]:
        session = runtime.db.create_session(
            "alice", "test-model", "default", title=title, channel=channel
        )
        scripted_models.responses.append([AssistantMessage("Reply")])
        events = await collect(runtime.start("alice", session["id"], "Talk about Kyoto"))
        assert not any(event["type"] == "title" for event in events)
        assert runtime.db.session("alice", session["id"])["title_attempts"] == 0
        if channel == "browser":
            await runtime.reset("alice", session["id"])
            assert runtime.db.session("alice", session["id"])["title"] == title


async def test_failed_title_keeps_completed_reply(runtime, scripted_models):
    runtime.settings.auto_titles = True
    session = runtime.db.create_session("alice", "test-model", "default")
    scripted_models.responses.append([AssistantMessage("A useful answer"), RuntimeError("offline")])
    events = await collect(runtime.start("alice", session["id"], "Plan a trip"))
    assert events[-1]["status"] == "completed"
    assert not any(event["type"] == "error" for event in events)
    assert runtime.db.session("alice", session["id"])["title"] == "Plan a trip"
    assert runtime.db.load_history("alice", session["id"])[-1].text == "A useful answer"


async def test_title_cannot_spend_reserved_compaction_or_recovery_calls(runtime, scripted_models):
    runtime.settings.auto_titles = True
    runtime.settings.max_model_calls = 4
    runtime.settings.max_compaction_calls = 2
    session = runtime.db.create_session("alice", "test-model", "default")
    scripted_models.responses.append([AssistantMessage("A useful answer")])
    events = await collect(runtime.start("alice", session["id"], "Plan a trip"))
    assert events[-1]["status"] == "completed"
    assert not any(event["type"] == "title" for event in events)
    assert runtime.db.session("alice", session["id"])["title_attempts"] == 0


async def test_title_request_is_bounded_tool_free_and_owner_scoped(runtime):
    runtime.settings.auto_titles = True
    session = runtime.db.create_session("alice", "gpt-5.6-luna", "high")
    model = FakeModel([AssistantMessage("Planning a Japan trip")])
    history = [
        UserMessage("Japan " * 2000),
        ToolResultMessage("c", "test_tool", "secret tool result"),
        AssistantMessage("Kyoto " * 1000),
    ]
    await update_title(runtime, Turn("alice", session["id"]), session, model, history)
    request = model.requests[0]
    transcript = json.loads(request.messages[-1].content)
    assert len(transcript[0]["text"]) == 1500
    assert len(transcript[1]["text"]) == 1000
    assert "secret tool result" not in request.messages[-1].content
    assert not request.tools
    with pytest.raises(LookupError):
        await update_title(runtime, Turn("bob", session["id"]), session, model, history)


async def test_title_update_preserves_concurrent_custom_name(runtime):
    runtime.settings.auto_titles = True
    session = runtime.db.create_session("alice", "test-model", "default")

    class RenamingModel(FakeModel):
        async def generate(self, request):
            runtime.db.execute(
                "UPDATE sessions SET title='Custom', title_auto=0 WHERE id=?", (session["id"],)
            )
            return await super().generate(request)

    await update_title(
        runtime,
        Turn("alice", session["id"]),
        session,
        RenamingModel([AssistantMessage("Generated")]),
        [UserMessage("Japan")],
    )
    assert runtime.db.session("alice", session["id"])["title"] == "Custom"
