"""Telegram entity formatting and streaming regression checks."""

from types import SimpleNamespace

from theos.transports.telegram.formatting import format_reply, utf16_length
from theos.transports.telegram.polling import Telegram


def entity_text(part, entity):
    encoded = part["text"].encode("utf-16-le")
    start = entity["offset"] * 2
    end = start + entity["length"] * 2
    return encoded[start:end].decode("utf-16-le")


def test_markdown_becomes_text_and_entities():
    part = format_reply("# Plan\n\n**Bold**, *italic*, ~~old~~, `x < 2`.\n\n- One\n- Two")[0]
    assert part["text"] == "Plan\n\nBold, italic, old, x < 2.\n\n• One\n• Two"
    assert [(e["type"], entity_text(part, e)) for e in part["entities"]] == [
        ("bold", "Plan"),
        ("bold", "Bold"),
        ("italic", "italic"),
        ("strikethrough", "old"),
        ("code", "x < 2"),
    ]


def test_literal_html_and_links_are_safe():
    part = format_reply("<b>literal & text</b> [site](https://example.com?q=1&x=2)")[0]
    assert part["text"] == "<b>literal & text</b> site"
    assert part["entities"] == [
        {
            "type": "text_link",
            "offset": 22,
            "length": 4,
            "url": "https://example.com?q=1&x=2",
        }
    ]
    unsafe = format_reply("[bad](javascript:alert(1)) ![photo](https://example.com/photo.png)")[0]
    assert all(e.get("url", "").startswith("https://") for e in unsafe["entities"])
    assert "photo" in unsafe["text"]


def test_utf16_offsets_and_code_nesting():
    part = format_reply("😀 **bold `code` end**")[0]
    assert part["text"] == "😀 bold code end"
    assert [(e["offset"], e["type"], entity_text(part, e)) for e in part["entities"]] == [
        (3, "bold", "bold "),
        (8, "code", "code"),
        (12, "bold", " end"),
    ]


def test_long_fence_chunks_keep_code_and_all_content():
    content = "😀x < y\n" * 1300
    parts = format_reply("```python\n" + content + "```", limit=3900)
    assert "".join(p["text"] for p in parts) == content.rstrip("\n")
    assert len(parts) > 2
    for part in parts:
        assert utf16_length(part["text"]) <= 3900
        assert part["entities"] == [
            {
                "type": "pre",
                "offset": 0,
                "length": utf16_length(part["text"]),
                "language": "python",
            }
        ]


def test_tables_and_nested_lists_have_readable_rows():
    part = format_reply(
        "| Name | Value |\n| --- | --- |\n| A | 2 |\n\n3. First\n   - Child\n4. Next"
    )[0]
    assert part["text"] == "Name | Value\nA | 2\n\n3. First\n  • Child\n4. Next"


def test_empty_incomplete_and_punctuation():
    assert format_reply("")[0] == {"text": "…", "entities": []}
    assert format_reply("**unfinished")[0]["text"] == "**unfinished"
    part = format_reply("Done\u2014next. `x\u2014y`")[0]
    assert part["text"] == "Done-next. x-y"
    assert format_reply("A &mdash; B &#8212; C &#x2014; D")[0]["text"] == "A - B - C - D"


async def test_stream_recovers_split_markdown_and_preserves_topics(runtime, monkeypatch):
    bot = Telegram(runtime)
    calls, messages = [], {}

    async def api(method, payload=None, files=None):
        calls.append((method, payload))
        if method == "sendMessage":
            message_id = len(messages) + 1
            messages[message_id] = payload
            return {"message_id": message_id}
        if method == "editMessageText":
            messages[payload["message_id"]] = payload
        elif method == "deleteMessage":
            del messages[payload["message_id"]]

    bot.api = api
    ticks = iter(range(1, 100))
    monkeypatch.setattr("theos.transports.telegram.rendering.time.monotonic", lambda: next(ticks))

    async def events():
        yield {"type": "text", "text": "**Title"}
        yield {"type": "text", "text": "**\n\n```python\n" + "😀x\n" * 1300}
        yield {"type": "text", "text": "```\n\n[Link](https://example.com)"}
        yield {"type": "done", "status": "completed"}

    await bot.render(SimpleNamespace(events=events), 123, 42)
    expected = format_reply(
        "**Title**\n\n```python\n" + "😀x\n" * 1300 + "```\n\n[Link](https://example.com)"
    )
    assert [{k: p.get(k, []) for k in ("text", "entities")} for p in messages.values()] == expected
    assert all(p["message_thread_id"] == 42 for method, p in calls if method == "sendMessage")
    assert all("parse_mode" not in p for _, p in calls)


async def test_plain_commands_and_approval_previews_stay_literal(runtime):
    bot = Telegram(runtime)
    calls = []

    async def api(method, payload=None, files=None):
        calls.append(payload)
        return {"message_id": 1}

    bot.api = api
    await bot.send(123, "**Literal preview** <unchanged>\u2014done", markup={"inline_keyboard": []})
    assert calls[0]["text"] == "**Literal preview** <unchanged>-done"
    assert "entities" not in calls[0] and "parse_mode" not in calls[0]
    assert "reply_markup" in calls[0]


async def test_unicode_review_is_complete_before_approval_controls(runtime):
    bot = Telegram(runtime)
    calls = []

    async def api(method, payload=None, files=None):
        assert utf16_length(payload["text"]) <= 3900
        calls.append(payload)
        return {"message_id": len(calls)}

    bot.api = api
    preview = "😀" * 2500
    await bot.send(123, preview, 42, {"inline_keyboard": []})
    assert "".join(p["text"] for p in calls) == preview
    assert all(p["message_thread_id"] == 42 for p in calls)
    assert "reply_markup" not in calls[0] and "reply_markup" in calls[-1]


async def test_closing_markdown_removes_obsolete_chunk(runtime, monkeypatch):
    bot = Telegram(runtime)
    messages = {}
    deleted = []

    async def api(method, payload=None, files=None):
        if method == "sendMessage":
            message_id = len(messages) + 1
            messages[message_id] = payload
            return {"message_id": message_id}
        if method == "editMessageText":
            messages[payload["message_id"]] = payload
        elif method == "deleteMessage":
            deleted.append(payload["message_id"])
            del messages[payload["message_id"]]

    bot.api = api
    ticks = iter(range(1, 100))
    monkeypatch.setattr("theos.transports.telegram.rendering.time.monotonic", lambda: next(ticks))

    async def events():
        yield {"type": "text", "text": "**" + "x" * 3899}
        yield {"type": "text", "text": "**"}
        yield {"type": "done", "status": "completed"}

    await bot.render(SimpleNamespace(events=events), 123, None)
    assert deleted == [2]
    assert messages[1]["text"] == "x" * 3899
    assert messages[1]["entities"] == [{"type": "bold", "offset": 0, "length": 3899}]
