"""Temporary progress, measured turn statistics, and durable review cleanup."""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from harness import AssistantMessage, ToolCall, ToolResultMessage
from harness.events import ToolFinished, ToolStarted
from theos.runtime.events import publish_event
from theos.runtime.turn import Turn
from theos.services.errors import ServiceError
from theos.transports.telegram import approval_messages
from theos.transports.telegram.polling import Telegram

from .conftest import collect


def fake_messages(bot):
    messages, calls = {}, []
    next_id = 0

    async def api(method, payload=None, files=None):
        nonlocal next_id
        calls.append((method, payload))
        if method in {"sendMessage", "sendDocument"}:
            next_id += 1
            messages[next_id] = payload.copy()
            return {"message_id": next_id}
        if method == "editMessageText":
            messages[payload["message_id"]] = payload.copy()
        elif method == "deleteMessage":
            messages.pop(payload["message_id"], None)
        return {}

    bot.api = api
    return messages, calls


@pytest.mark.parametrize("status", ["completed", "failed", "interrupted", "partial"])
async def test_progress_disappears_and_one_summary_follows_answer(runtime, status):
    bot = Telegram(runtime)
    messages, calls = fake_messages(bot)

    async def events():
        for index, state in enumerate(["completed", "failed", "unknown", "denied"]):
            yield {
                "type": "tool",
                "name": "gmail_get_message",
                "call_id": str(index),
                "status": "running",
            }
            yield {
                "type": "tool",
                "name": "gmail_get_message",
                "call_id": str(index),
                "status": state,
            }
            assert len(messages) == 1  # Every finished call has already disappeared.
        yield {"type": "assistant_complete", "text": "Saved final answer."}
        yield {"type": "compaction", "status": "started", "compaction_id": "unfinished"}
        yield {
            "type": "done",
            "status": status,
            "stats": {
                "elapsed_seconds": 125,
                "tool_calls": 7,
                "tool_outcomes": {"failed": 1, "unknown": 1, "denied": 1},
                "skills": ["pdf", "report-style"],
            },
        }

    await bot.render(SimpleNamespace(events=events), 123, 42)
    assert len(messages) == 2
    answer, stats = list(messages.values())
    assert answer["text"] == "Saved final answer."
    assert "2m 05s · 7 tool calls" in stats["text"]
    assert "1 failed, 1 outcome unknown, 1 denied" in stats["text"]
    assert "Skills used: pdf, report-style" in stats["text"]
    assert stats["message_thread_id"] == 42
    assert len([m for m, _ in calls if m == "deleteMessage"]) == 5


async def test_transport_disconnect_removes_progress_without_a_false_final_summary(runtime):
    bot = Telegram(runtime)
    messages, _ = fake_messages(bot)

    async def events():
        yield {"type": "tool", "name": "gmail_get_message", "call_id": "read", "status": "running"}
        yield {"type": "compaction", "status": "started", "compaction_id": "one"}
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await bot.render(SimpleNamespace(events=events), 123, None)
    assert [p["text"] for p in messages.values()] == ["Thinking…"]


def test_stats_include_delegate_calls_even_when_the_display_queue_discards_events(runtime):
    row = runtime.db.create_session("alice", "test", "none")
    turn = Turn("alice", row["id"], queue=asyncio.Queue(maxsize=1))
    for scope in [None, "delegate"]:
        call = ToolCall("same-id", "load_skill", {"name": "pdf"})
        publish_event(runtime, turn, ToolStarted(call, parent_call_id=scope), "running")
        publish_event(
            runtime,
            turn,
            ToolFinished(ToolResultMessage(call.id, call.name, "{}"), parent_call_id=scope),
            "running",
        )
    call = ToolCall("failed-skill", "load_skill", {"name": "missing"})
    publish_event(runtime, turn, ToolStarted(call), "running")
    publish_event(
        runtime,
        turn,
        ToolFinished(ToolResultMessage(call.id, call.name, "Not found", "failed")),
        "running",
    )
    stats = turn.stats()
    assert stats["tool_calls"] == 3 and stats["tool_outcomes"] == {"completed": 2, "failed": 1}
    assert stats["skills"] == ["pdf"]
    assert stats["elapsed_seconds"] >= 0


async def test_real_runtime_counts_only_successfully_loaded_skills(
    runtime, scripted_models, tmp_path
):
    runtime.settings.skills_dir = tmp_path / "skills"
    skill = runtime.settings.skills_dir / "pdf"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("Read a document.")
    row = runtime.db.create_session("alice", "test", "none")
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall("load", "load_skill", {"name": "pdf"}),
                    ToolCall("bad", "load_skill", {"name": "missing"}),
                ]
            ),
            AssistantMessage("Complete."),
        ]
    )
    events = await collect(runtime.start("alice", row["id"], "Read a document"))
    assert events[-1]["stats"]["skills"] == ["pdf"]
    assert events[-1]["stats"]["tool_calls"] == 2
    assert events[-1]["stats"]["tool_outcomes"] == {"completed": 1, "failed": 1}


def add_approval(runtime, owner, approval_id):
    row = runtime.db.create_session(owner, "test", "none")
    args = json.dumps({"name": "notes"})
    runtime.db.execute(
        "INSERT INTO approvals(id,session,call_id,tool,arguments,preview,created,expires) VALUES (?,?,?,?,?,?,?,?)",
        (
            approval_id,
            row["id"],
            "call",
            "delete_custom_table",
            args,
            args,
            time.time(),
            time.time() + 900,
        ),
    )
    return row


async def test_multipart_approval_notifies_once_stays_pending_and_is_not_posted_twice(runtime):
    row = add_approval(runtime, "alice", "review")
    bot = Telegram(runtime)
    messages, calls = fake_messages(bot)
    item = runtime.pending("alice", row["id"])[0]
    item["review"] = [{"label": "Code", "text": "😀" * 2500, "kind": "code"}]

    async def events():
        yield {"type": "approvals", "items": [item]}
        yield {"type": "approvals", "items": [item]}
        yield {"type": "done", "status": "waiting_for_approval"}

    turn = SimpleNamespace(events=events, owner="alice", session_id=row["id"])
    await bot.render(turn, 123, 42)
    cards = [p for p in messages.values() if p.get("text") != "Waiting for your approval."]
    assert len(cards) == 2
    assert [p["disable_notification"] for p in cards] == [True, False]
    assert "reply_markup" not in cards[0] and "reply_markup" in cards[-1]
    assert not any(m == "deleteMessage" for m, _ in calls)
    assert not any("Skills used:" in p["text"] for p in messages.values())
    references = runtime.db.rows("SELECT * FROM telegram_approval_messages")
    assert len(references) == 3
    runtime.db.execute("UPDATE approvals SET status='denied' WHERE id='review'")
    await approval_messages.remove_resolved(bot, "alice", row["id"])
    assert not messages and not runtime.db.rows("SELECT * FROM telegram_approval_messages")
    assert (
        runtime.db.one("SELECT preview FROM approvals WHERE id='review'")["preview"]
        == item["preview"]
    )


async def test_approval_cleanup_failure_removes_buttons_and_preserves_decision_for_retry(runtime):
    row = add_approval(runtime, "alice", "review")
    bot = Telegram(runtime)
    approval_messages.remember(bot, "review", 123, {"message_id": 8})
    runtime.db.execute("UPDATE approvals SET status='approved' WHERE id='review'")
    calls = []

    async def broken_api(method, payload=None, files=None):
        calls.append((method, payload))
        if method == "deleteMessage":
            raise ServiceError("Telegram unavailable")
        return {}

    bot.api = broken_api
    await approval_messages.remove_resolved(bot, "bob", row["id"])
    assert not calls
    await approval_messages.remove_resolved(bot, "alice", row["id"])
    assert calls[-1][0] == "editMessageReplyMarkup"
    assert calls[-1][1]["reply_markup"] == {"inline_keyboard": []}
    assert runtime.db.one("SELECT status FROM approvals WHERE id='review'")["status"] == "approved"
    assert runtime.db.rows("SELECT * FROM telegram_approval_messages")
    fake_messages(bot)
    await approval_messages.remove_resolved(bot, "alice", row["id"])
    assert not runtime.db.rows("SELECT * FROM telegram_approval_messages")


async def test_large_review_attachment_disappears_with_its_approval(runtime):
    row = add_approval(runtime, "alice", "review")
    bot = Telegram(runtime)
    messages, calls = fake_messages(bot)
    item = runtime.pending("alice", row["id"])[0]
    item["review"] = [{"label": "Code", "text": "print('large')\n" * 2000, "kind": "code"}]

    async def events():
        yield {"type": "approvals", "items": [item]}
        yield {"type": "done", "status": "waiting_for_approval"}

    await bot.render(SimpleNamespace(events=events, owner="alice", session_id=row["id"]), 123, 42)
    assert any(m == "sendDocument" for m, _ in calls)
    assert len(messages) == 3  # Waiting notice, complete review file, approval card.
    runtime.db.execute("UPDATE approvals SET status='approved' WHERE id='review'")
    await approval_messages.cleanup(bot)
    assert not messages
    assert runtime.db.one("SELECT preview,status FROM approvals WHERE id='review'") == {
        "preview": item["preview"],
        "status": "approved",
    }


async def test_poll_cleanup_removes_expired_reviews_and_keeps_pending_ones(runtime):
    expired = add_approval(runtime, "alice", "expired")
    pending = add_approval(runtime, "alice", "pending")
    bot = Telegram(runtime)
    messages, _ = fake_messages(bot)
    for approval_id in ["expired", "pending"]:
        posted = await bot.send(123, "Approval needed")
        approval_messages.remember(bot, approval_id, 123, posted)
    runtime.db.execute("UPDATE approvals SET expires=? WHERE id='expired'", (time.time() - 1,))
    await approval_messages.cleanup(bot)
    assert len(messages) == 1
    assert runtime.db.rows("SELECT approval_id FROM telegram_approval_messages") == [
        {"approval_id": "pending"}
    ]
    assert expired["id"] != pending["id"]


async def test_failed_progress_deletion_does_not_hide_the_answer_or_abort_delivery(runtime):
    bot = Telegram(runtime)
    messages, calls = fake_messages(bot)
    working_api = bot.api

    async def api(method, payload=None, files=None):
        if method == "deleteMessage":
            raise ServiceError("Telegram unavailable")
        return await working_api(method, payload, files)

    bot.api = api

    async def events():
        yield {"type": "tool", "name": "gmail_get_message", "call_id": "one", "status": "running"}
        yield {"type": "tool", "name": "gmail_get_message", "call_id": "one", "status": "completed"}
        yield {"type": "assistant_complete", "text": "Final answer."}
        yield {"type": "done", "status": "completed"}

    await bot.render(SimpleNamespace(events=events), 123, None)
    assert messages[1]["text"] == "Final answer."
    assert messages[2]["text"] == "Live updates stopped."
    assert "1 tool call · Complete" in messages[3]["text"]
    assert not any("In progress" in p["text"] for p in messages.values())
    assert any(m == "editMessageText" for m, _ in calls)
