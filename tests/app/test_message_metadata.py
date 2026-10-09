"""Message display values survive checkpoints without entering provider state."""

import json
from types import SimpleNamespace

import pytest

from harness import AssistantMessage, ToolCall, UserMessage, message_to_dict
from theos.runtime import hooks
from theos.storage.database import Database
from theos.storage.messages import display_metadata, stamp_message

from .conftest import collect


async def test_each_generation_has_its_own_duration(runtime, scripted_models, monkeypatch):
    session = runtime.db.create_session("alice", "test-model", "default")
    monotonic = iter([10.0, 10.125, 15.0, 15.5])
    created = iter([1000.0, 1005.0])
    monkeypatch.setattr(
        hooks,
        "time",
        SimpleNamespace(monotonic=lambda: next(monotonic), time=lambda: next(created)),
    )
    scripted_models.responses.append(
        [
            AssistantMessage(
                "Checking preferences",
                tool_calls=[ToolCall("prefs", "get_preferences", {})],
                usage={"input_tokens": 9, "output_tokens": 5},
            ),
            AssistantMessage("Answer", usage={"input_tokens": 20, "output_tokens": 7}),
        ]
    )
    events = await collect(runtime.start("alice", session["id"], "Hello"))
    complete = [event for event in events if event["type"] == "assistant_complete"]
    assert [event["display"] for event in complete] == [
        {"created_at": 1000.0, "duration_ms": 125},
        {"created_at": 1005.0, "duration_ms": 500},
    ]
    assert [event["usage"]["output_tokens"] for event in complete] == [5, 7]
    assert all(
        event["display"]["created_at"] > 0 for event in events if event["type"] == "thinking"
    )
    saved = json.loads(runtime.db.session("alice", session["id"])["history"])
    assert [value["display"] for value in saved if value["type"] == "assistant"] == [
        event["display"] for event in complete
    ]


def test_display_values_survive_reopen_and_do_not_enter_provider_messages(tmp_path):
    db = Database(tmp_path)
    session = db.create_session("alice", "test-model", "default")
    user = stamp_message(UserMessage("Hello"), created_at=1000)
    assistant = stamp_message(AssistantMessage("Answer"), created_at=1001, duration_ms=1250)
    db.save_history("alice", session["id"], [user, assistant])
    db.close()
    reopened = Database(tmp_path)
    try:
        history = reopened.load_history("alice", session["id"])
        assert display_metadata(history[0]) == {"created_at": 1000}
        assert display_metadata(history[1]) == {"created_at": 1001, "duration_ms": 1250}
        assert "display" not in message_to_dict(history[1])
        assert history[1].provider_data == {}
        reopened.save_history("alice", session["id"], history)
        assert display_metadata(
            reopened.load_history("alice", session["id"])[1]
        ) == display_metadata(assistant)
        with pytest.raises(LookupError):
            reopened.load_history("bob", session["id"])
    finally:
        reopened.close()


def test_legacy_history_keeps_unknown_timestamps(db):
    session = db.create_session("alice", "test-model", "default")
    legacy = [
        message_to_dict(UserMessage("Old question")),
        message_to_dict(AssistantMessage("Old answer")),
    ]
    db.execute("UPDATE sessions SET history=? WHERE id=?", (json.dumps(legacy), session["id"]))
    history = db.load_history("alice", session["id"])
    assert all(display_metadata(message) == {} for message in history)
    history.append(stamp_message(UserMessage("New question"), created_at=2000))
    db.save_history("alice", session["id"], history)
    saved = json.loads(db.session("alice", session["id"])["history"])
    assert "display" not in saved[0] and "display" not in saved[1]
    assert saved[2]["display"] == {"created_at": 2000}
