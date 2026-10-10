"""Telegram response edits, tool progress, and approval buttons."""

import json
import time

from .formatting import format_reply


async def render(bot, turn, chat, topic):
    """Display streamed text, progress, approvals, and generated files."""
    sent = await bot.send(chat, "Thinking…", topic)
    text, last_edit = "", 0.0
    messages = [(sent["message_id"], {"text": "Thinking…", "entities": []})]

    async def edit(value):
        parts = format_reply(value)
        # Reparse the whole reply so split fences and partial links recover on later deltas.
        for index, part in enumerate(parts):
            if index < len(messages):
                message_id, displayed = messages[index]
                if part != displayed:
                    await bot.api(
                        "editMessageText",
                        {"chat_id": chat, "message_id": message_id, **part},
                    )
                    messages[index] = (message_id, part)
            else:
                sent = await bot.api(
                    "sendMessage",
                    {
                        "chat_id": chat,
                        **part,
                        **({"message_thread_id": topic} if topic else {}),
                    },
                )
                messages.append((sent["message_id"], part))
        # Closing Markdown can shorten the visible text and remove a trailing chunk.
        while len(messages) > len(parts):
            message_id, _ = messages[-1]
            await bot.api("deleteMessage", {"chat_id": chat, "message_id": message_id})
            messages.pop()

    async for event in turn.events():
        kind = event["type"]
        if kind == "text":
            text += event["text"]
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
            await edit(final)
