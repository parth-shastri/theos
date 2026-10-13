"""Telegram response edits, tool progress, and approval buttons."""

import json
import time

from theos.runtime.approvals import requires_approval
from theos.runtime.reviews import approval_review, tool_icon, tool_label

from .formatting import format_approval, format_reply


async def render(bot, turn, chat, topic):
    """Display streamed text, progress, approvals, and generated files."""
    sent = await bot.send(chat, "Thinking…", topic)
    text, last_edit = "", 0.0
    messages = [(sent["message_id"], {"text": "Thinking…", "entities": []})]
    activities = {}
    compactions = {}

    async def activity(cache, key, value):
        part = format_reply(value)[0]
        if key in cache:
            message_id, previous = cache[key]
            if part != previous:
                await bot.api(
                    "editMessageText", {"chat_id": chat, "message_id": message_id, **part}
                )
                cache[key] = (message_id, part)
        else:
            posted = await bot.api(
                "sendMessage",
                {"chat_id": chat, **part, **({"message_thread_id": topic} if topic else {})},
            )
            cache[key] = (posted["message_id"], part)

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
        elif kind in {"assistant_complete", "answer_replace"}:
            text = event["text"] or ""
            await edit(text or "…")
        elif kind == "compaction":
            label = "research context" if event.get("parent_call_id") else "earlier conversation"
            state = event["status"]
            value = (
                "🗂 Organizing " + label + "…"
                if state in {"started", "progress"}
                else "🗂 Context ready. Continuing…"
                if state == "completed"
                else "⚠️ Context preparation stopped. Your conversation is saved."
            )
            await activity(
                compactions,
                event.get("compaction_id") or event.get("parent_call_id") or "parent",
                value,
            )
        elif kind == "tool":
            state = event["status"]
            icon = tool_icon(event["name"])
            outcome = {
                "running": "Requested" if requires_approval(event["name"]) else "In progress",
                "completed": "Complete",
                "failed": "Failed",
                "unknown": "Outcome unknown",
                "denied": "Denied",
            }.get(state, state.replace("_", " "))
            await activity(
                activities, event["call_id"], f"{icon} **{tool_label(event['name'])}**\n{outcome}"
            )
            if state == "running":
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
                fields = item.get("review") or approval_review(item["tool"], preview)
                if item.get("call_id") in activities:
                    await activity(
                        activities,
                        item["call_id"],
                        f"{tool_icon(item['tool'])} **{tool_label(item['tool'])}**\nWaiting for approval",
                    )
                parts = format_approval(item["tool"], fields)
                full_preview = (
                    "\n\n".join(
                        f"{field.get('group', '')}\n{field['label']}\n{field['text']}"
                        for field in fields
                    )
                    + "\n\nExact tool arguments\n"
                    + item.get("arguments", item["preview"])
                )
                # Preserve the full review in a file when the message limit would hide action details.
                if len(parts) > 4:
                    review_file = bot.runtime.files.save(
                        turn.owner, "approval-review.txt", "text/plain", full_preview.encode()
                    )
                    await bot.deliver_file(turn.owner, chat, topic, review_file["id"])
                    parts = [
                        {
                            "text": "Approval needed: "
                            + item["tool"].replace("_", " ")
                            + "\nRead approval-review.txt for the full action before you decide.",
                            "entities": [],
                        }
                    ]
                markup = {
                    "inline_keyboard": [
                        [
                            {"text": "Approve", "callback_data": "a:" + item["id"]},
                            {"text": "Deny", "callback_data": "d:" + item["id"]},
                        ]
                    ]
                }
                for index, part in enumerate(parts):
                    await bot.api(
                        "sendMessage",
                        {
                            "chat_id": chat,
                            **part,
                            **({"message_thread_id": topic} if topic else {}),
                            **({"reply_markup": markup} if index == len(parts) - 1 else {}),
                        },
                    )
        elif kind == "file":
            await bot.deliver_file(turn.owner, chat, topic, event["file_id"])
        elif kind == "error":
            text = event["message"]
        elif kind == "done":
            for key, (_, displayed) in list(compactions.items()):
                if "Organizing" in displayed["text"]:
                    await activity(
                        compactions,
                        key,
                        "⚠️ Context preparation stopped. Your conversation is saved.",
                    )
            final = text or {
                "waiting_for_approval": "Waiting for your approval.",
                "budget_exhausted": "This turn reached its model-call limit. Send /resume to continue.",
            }.get(event["status"], "The turn ended.")
            await edit(final)
