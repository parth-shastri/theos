"""Approval presentation retains complete arguments and Unicode formatting."""

import json
import time
from types import SimpleNamespace

from theos.runtime.reviews import approval_fields
from theos.transports.telegram.formatting import format_approval, utf16_length
from theos.transports.telegram.polling import Telegram


def test_nested_review_preserves_newlines_code_and_empty_values():
    original = {
        "payload": {"message": "**Hello**\nSecond line", "enabled": False},
        "code": 'print("hello\\nworld")\nprint("next")',
        "items": ["one", "two"],
        "empty": [],
        "missing": None,
    }
    before = json.dumps(original)
    fields = approval_fields(original)
    by_label = {f["label"]: f for f in fields}
    assert by_label["Payload / Message"] == {
        "label": "Payload / Message",
        "text": "**Hello**\nSecond line",
        "kind": "markdown",
    }
    assert by_label["Code"]["text"] == original["code"]
    assert by_label["Code"]["kind"] == "code"
    assert by_label["Payload / Enabled"]["text"] == "No"
    assert by_label["Items / 2"]["text"] == "two"
    assert by_label["Empty"]["text"] == "None"
    assert by_label["Missing"]["text"] == "Not set"
    assert json.dumps(original) == before


def test_telegram_review_formats_prose_and_preserves_literal_code():
    code = 'print("😀\\n**literal**")\nprint("next")'
    fields = approval_fields({"description": "**Review**\n- First\n- Second", "code": code})
    parts = format_approval("sandbox_execute_code", fields)
    assert len(parts) == 1
    assert "**Review**" not in parts[0]["text"]
    assert "Review\n\n• First\n• Second" in parts[0]["text"]
    assert code in parts[0]["text"]
    for entity in parts[0]["entities"]:
        assert entity["offset"] + entity["length"] <= utf16_length(parts[0]["text"])
    literal = next(e for e in parts[0]["entities"] if e["type"] == "pre")
    encoded = parts[0]["text"].encode("utf-16-le")
    assert (
        encoded[literal["offset"] * 2 : (literal["offset"] + literal["length"]) * 2].decode(
            "utf-16-le"
        )
        == code
    )


async def test_pending_review_keeps_exact_snapshot(runtime):
    row = runtime.db.create_session("alice", "test-model", "default")
    arguments = json.dumps({"code": "print('hello')\nprint('world')"})
    runtime.db.execute(
        "INSERT INTO approvals(id,session,call_id,tool,arguments,preview,created,expires) VALUES (?,?,?,?,?,?,?,?)",
        (
            "review",
            row["id"],
            "call",
            "zepto_confirm_cart",
            arguments,
            arguments,
            time.time(),
            time.time() + 900,
        ),
    )
    item = runtime.pending("alice", row["id"])[0]
    assert item["arguments"] == item["preview"] == arguments
    assert item["review"][0]["text"] == "print('hello')\nprint('world')"


async def test_telegram_review_buttons_follow_complete_unicode_review(runtime):
    bot = Telegram(runtime)
    sent = []

    async def api(method, payload=None, files=None):
        if method == "sendMessage":
            sent.append(payload)
            return {"message_id": len(sent)}
        return {}

    bot.api = api
    code = "😀" * 2500 + "\nFINAL LINE"
    preview = json.dumps({"code": code})
    row = runtime.db.create_session("alice", "test", "none")
    runtime.db.execute(
        "INSERT INTO approvals(id,session,call_id,tool,arguments,preview,created,expires) VALUES (?,?,?,?,?,?,?,?)",
        (
            "approval",
            row["id"],
            "call",
            "sandbox_execute_code",
            preview,
            preview,
            time.time(),
            time.time() + 900,
        ),
    )

    async def events():
        yield {
            "type": "approvals",
            "items": [{"id": "approval", "tool": "sandbox_execute_code", "preview": preview}],
        }
        yield {"type": "done", "status": "waiting_for_approval"}

    await bot.render(SimpleNamespace(events=events, owner="alice"), 123, 42)
    review = sent[1:]
    assert code in "".join(p["text"] for p in review)
    assert all(utf16_length(p["text"]) <= 3900 for p in review)
    assert all("reply_markup" not in p for p in review[:-1])
    assert review[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "a:approval"
    assert all(p["message_thread_id"] == 42 for p in review)
