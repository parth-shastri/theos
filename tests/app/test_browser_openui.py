"""OpenUI display metadata and actions retain runtime and owner boundaries."""

from contextlib import asynccontextmanager

import pytest

from harness import AssistantMessage, message_to_dict
from harness.testing import FakeModel
from theos.storage.messages import display_metadata, update_display_metadata
from theos.transports.browser.openui import reminder_submission

from .conftest import collect
from .test_browser_auth import browser

SOURCE = 'root = TheosAnswer(summary, [])\nsummary = AnswerSummary("A saved fact.")'
MESSAGE_ID = "d" * 32


def saved_answer(runtime):
    session = runtime.db.create_session("alice", "test-model", "default")
    answer = update_display_metadata(
        AssistantMessage(SOURCE),
        {
            "format": "openui-lang",
            "library_version": "theos-openui-2",
            "openui_message_id": MESSAGE_ID,
        },
    )
    runtime.db.save_history("alice", session["id"], [answer])
    return session


async def test_browser_format_is_saved_without_changing_generic_message_serialization(
    runtime, scripted_models
):
    session = runtime.db.create_session("alice", "test-model", "default")
    scripted_models.responses.append([AssistantMessage(SOURCE)])
    events = await collect(runtime.start("alice", session["id"], "Show a fact.", browser_ui=True))
    format_event = next(event for event in events if event["type"] == "assistant_format")
    answer = runtime.db.load_history("alice", session["id"])[-1]
    display = display_metadata(answer)
    assert display["format"] == "openui-lang"
    assert display["library_version"] == "theos-openui-2"
    assert display["openui_message_id"] == format_event["openui_message_id"]
    assert "display" not in message_to_dict(answer)
    scripted_models.responses.append([AssistantMessage("A plain answer.")])
    events = await collect(runtime.start("alice", session["id"], "Use the terminal."))
    assert not any(event["type"] == "assistant_format" for event in events)
    assert "format" not in display_metadata(runtime.db.load_history("alice", session["id"])[-1])


async def test_saved_drafts_reject_other_owners_unknown_messages_and_unsupported_fields(runtime):
    session = saved_answer(runtime)
    path = f"/api/sessions/{session['id']}/openui-state"
    body = {
        "message_id": MESSAGE_ID,
        "state": {"reminder_text": "Drink water"},
        "summary": "A fact.",
    }
    async with browser(runtime) as client:
        await client.post("/api/auth/login", json={"token": "a" * 32})
        assert (await client.put(path, json=body)).status_code == 200
        answer = runtime.db.load_history("alice", session["id"])[-1]
        assert display_metadata(answer)["openui_state"] == body["state"]
        assert display_metadata(answer)["openui_summary"] == "A fact."
        assert (await client.put(path, json={**body, "message_id": "e" * 32})).status_code == 400
        assert (
            await client.put(path, json={**body, "state": {"arbitrary": "value"}})
        ).status_code == 400
        await client.post("/api/auth/login", json={"token": "b" * 32})
        assert (await client.put(path, json=body)).status_code == 404


async def test_text_recovery_uses_saved_information_without_exposing_tools(runtime):
    session = saved_answer(runtime)
    model = FakeModel([AssistantMessage("A fact from this conversation.")])

    @asynccontextmanager
    async def factory(*args):
        yield model

    runtime.models = factory
    async with browser(runtime) as client:
        await client.post("/api/auth/login", json={"token": "a" * 32})
        response = await client.post(
            f"/api/sessions/{session['id']}/openui-actions",
            json={"type": "explain_in_text", "message_id": MESSAGE_ID},
        )
        assert response.status_code == 200
        assert '"status": "completed"' in response.text
        assert model.requests and all(not request.tools for request in model.requests)
        answer = runtime.db.load_history("alice", session["id"])[-1]
        assert answer.text == "A fact from this conversation."
        assert "format" not in display_metadata(answer)


@pytest.mark.parametrize(
    "date,time",
    [("2030-11-03", "01:30"), ("2030-03-10", "02:30")],
)
def test_reminder_form_rejects_ambiguous_and_nonexistent_local_times(runtime, date, time):
    with pytest.raises(ValueError, match="daylight-saving"):
        reminder_submission(
            runtime,
            "alice",
            {
                "reminder_text": "Water",
                "reminder_date": date,
                "reminder_time": time,
                "reminder_timezone": "America/New_York",
            },
        )
