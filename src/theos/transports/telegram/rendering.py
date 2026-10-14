"""Telegram response edits, tool progress, and approval buttons."""

import json
import time

from theos.runtime.approvals import requires_approval
from theos.runtime.reviews import approval_review, tool_icon, tool_label
from theos.services.errors import ServiceError

from . import approval_messages
from .formatting import format_approval, format_reply


def format_stats(stats, status):
    """Describe measured calls and successfully loaded skills in literal text."""
    seconds = round(stats["elapsed_seconds"])
    minutes, seconds = divmod(seconds, 60)
    duration = f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"
    outcome = {
        "completed": "Complete",
        "partial": "Partial",
        "interrupted": "Interrupted",
        "failed": "Failed",
    }.get(status, status.replace("_", " ").capitalize())
    calls = stats["tool_calls"]
    lines = [f"⏱ {duration} · {calls} tool {'call' if calls == 1 else 'calls'} · {outcome}"]
    outcomes = stats.get("tool_outcomes", {})
    problems = [
        f"{outcomes[name]} {label}"
        for name, label in [
            ("failed", "failed"),
            ("unknown", "outcome unknown"),
            ("denied", "denied"),
            ("not_started", "not started"),
        ]
        if outcomes.get(name)
    ]
    if problems:
        lines.append("Tools: " + ", ".join(problems))
    lines.append("📚 Skills used: " + (", ".join(stats.get("skills", [])) or "None"))
    return "\n".join(lines)


async def render(bot, turn, chat, topic):
    """Display streamed text, progress, approvals, and generated files."""
    sent = await bot.send(chat, "Thinking…", topic)
    text, last_edit = "", 0.0
    messages = [(sent["message_id"], {"text": "Thinking…", "entities": []})]
    activities = {}
    compactions = {}
    started = time.monotonic()
    seen_tools, loaded_skills = {}, set()
    pending_approvals = set()
    if getattr(turn, "session_id", None):
        await approval_messages.remove_resolved(bot, turn.owner, turn.session_id)

    async def remove_activity(cache, key):
        if key not in cache:
            return
        try:
            await bot.api("deleteMessage", {"chat_id": chat, "message_id": cache[key][0]})
        except ServiceError:
            # Keep the reference for another cleanup attempt when the turn ends.
            try:
                await bot.api(
                    "editMessageText",
                    {"chat_id": chat, "message_id": cache[key][0], "text": "Live updates stopped."},
                )
            except ServiceError:
                pass
            return
        cache.pop(key, None)

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
                {
                    "chat_id": chat,
                    **part,
                    "disable_notification": True,
                    **({"message_thread_id": topic} if topic else {}),
                },
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

    try:
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
                label = (
                    "research context" if event.get("parent_call_id") else "earlier conversation"
                )
                state = event["status"]
                key = event.get("compaction_id") or event.get("parent_call_id") or "parent"
                if state in {"started", "progress"}:
                    await activity(compactions, key, "🗂 Organizing " + label + "…")
                else:
                    await remove_activity(compactions, key)
            elif kind == "tool":
                state = event["status"]
                key = event["call_id"]
                item = seen_tools.setdefault(key, {"skill": None})
                item["status"] = state
                if state == "running" and event["name"] == "load_skill":
                    item["skill"] = event.get("arguments", {}).get("name")
                if state == "completed" and isinstance(item["skill"], str):
                    loaded_skills.add(" ".join(item["skill"].split())[:128])
                icon = tool_icon(event["name"])
                if state == "running":
                    outcome = "Requested" if requires_approval(event["name"]) else "In progress"
                    await activity(
                        activities, key, f"{icon} **{tool_label(event['name'])}**\n{outcome}"
                    )
                else:
                    await remove_activity(activities, key)
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
                    if item["id"] in pending_approvals:
                        continue
                    pending_approvals.add(item["id"])
                    if bot.db.one(
                        "SELECT 1 FROM telegram_approval_messages WHERE approval_id=? AND chat_id=?",
                        (item["id"], chat),
                    ):
                        continue
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
                        posted = await bot.deliver_file(turn.owner, chat, topic, review_file["id"])
                        approval_messages.remember(bot, item["id"], chat, posted)
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
                        posted = await bot.api(
                            "sendMessage",
                            {
                                "chat_id": chat,
                                **part,
                                "disable_notification": index != len(parts) - 1,
                                **({"message_thread_id": topic} if topic else {}),
                                **({"reply_markup": markup} if index == len(parts) - 1 else {}),
                            },
                        )
                        approval_messages.remember(bot, item["id"], chat, posted)
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
                if event["status"] == "waiting_for_approval" and not text:
                    for approval_id in pending_approvals:
                        for message_id, _ in messages:
                            approval_messages.remember(
                                bot, approval_id, chat, {"message_id": message_id}
                            )
                elif event["status"] != "waiting_for_approval":
                    stats = event.get("stats") or {
                        "elapsed_seconds": time.monotonic() - started,
                        "tool_calls": len(seen_tools),
                        "tool_outcomes": {
                            state: sum(item["status"] == state for item in seen_tools.values())
                            for state in {item["status"] for item in seen_tools.values()}
                        },
                        "skills": sorted(loaded_skills),
                    }
                    await bot.send(chat, format_stats(stats, event["status"]), topic)
    finally:
        for cache in (activities, compactions):
            for key in list(cache):
                await remove_activity(cache, key)
