"""Telegram response edits, tool progress, and approval buttons."""

import json
import time


async def render(bot, turn, chat, topic):
    """Display streamed text, progress, approvals, and generated files."""
    sent = await bot.send(chat, "Thinking…", topic)
    message_id, text, last_edit = sent["message_id"], "", 0.0
    displayed = "Thinking…"

    async def edit(value):
        nonlocal displayed
        # Telegram rejects identical edits. Compare with the last confirmed display text.
        if value != displayed:
            await bot.api(
                "editMessageText", {"chat_id": chat, "message_id": message_id, "text": value}
            )
            displayed = value

    async for event in turn.events():
        kind = event["type"]
        if kind == "text":
            text += event["text"]
            # One provider delta can span several messages. Split until every chunk fits.
            while len(text) > 3900:
                await edit(text[:3900])
                text = text[3900:]
                displayed = text[:3900] or "…"
                sent = await bot.send(chat, displayed, topic)
                message_id = sent["message_id"]
            if time.monotonic() - last_edit >= 1:
                await edit(text or "…")
                last_edit = time.monotonic()
        elif kind == "tool" and event["status"] == "running":
            if not text:
                await edit("Using " + event["name"] + "…")
            await bot.api(
                "sendChatAction",
                {
                    "chat_id": chat,
                    "action": "typing",
                    **({"message_thread_id": topic} if topic else {}),
                },
            )
        elif kind == "approvals":
            for item in event["items"]:
                preview = json.loads(item["preview"])
                full_preview = json.dumps(preview, ensure_ascii=False, indent=2)
                # Preserve the full review in a file when the message limit would hide action details.
                if len(full_preview) > 3500:
                    review_file = bot.runtime.files.save(
                        turn.owner, "approval-review.txt", "text/plain", full_preview.encode()
                    )
                    await bot.deliver_file(turn.owner, chat, topic, review_file["id"])
                    full_preview = (
                        full_preview[:3000]
                        + "\n[Preview shortened. Read approval-review.txt for the full action.]"
                    )
                await bot.send(
                    chat,
                    f"Approve {item['tool']}?\n" + full_preview,
                    topic,
                    {
                        "inline_keyboard": [
                            [
                                {"text": "Approve", "callback_data": "a:" + item["id"]},
                                {"text": "Deny", "callback_data": "d:" + item["id"]},
                            ]
                        ]
                    },
                )
        elif kind == "file":
            await bot.deliver_file(turn.owner, chat, topic, event["file_id"])
        elif kind == "error":
            text = event["message"]
        elif kind == "done":
            final = text or {
                "waiting_for_approval": "Waiting for your approval.",
                "budget_exhausted": "This turn reached its model-call limit. Send /resume to continue.",
            }.get(event["status"], "The turn ended.")
            await edit(final[:4000])
