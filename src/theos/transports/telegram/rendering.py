"""Render Theos turn events as Telegram messages, progress, files, and approvals.

The runtime produces transport-neutral events. This file decides how Telegram should
display them; it does not decide what the model should do or execute the tools.
"""

import json
import time

from theos.runtime.approvals import requires_approval
from theos.runtime.reviews import approval_review, tool_icon, tool_label
from theos.services.errors import ServiceError

from . import approval_messages
from .formatting import format_approval, format_reply, format_tool_activity


def format_stats(stats, status):
    """Describe measured calls and successfully loaded skills in literal text."""
    # Keep the completion footer useful but small. Stats come from the turn, not a
    # model-generated claim about how long it ran or which tools succeeded.
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
    lines = [f"✔ {duration} · {calls} tool {'call' if calls == 1 else 'calls'} · {outcome}"]
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
    lines.append("Skills used: " + (", ".join(stats.get("skills", [])) or "None"))
    return "\n".join(lines)


async def render(bot, turn, chat, topic):
    """Display streamed text, progress, approvals, and generated files."""
    # Runtime.start() works in a background task. This placeholder tells the user the
    # turn exists while render() waits for that task's first display event.
    sent = await bot.send(chat, "Thinking…", topic)
    text, last_edit = "", 0.0
    # Keep Telegram message IDs so later events can edit or remove the right messages.
    messages = [(sent["message_id"], {"text": "Thinking…", "entities": []})]
    # Each cache tracks temporary messages by purpose and tool/call ID. Separate caches
    # stop one tool's cleanup from deleting a reasoning or compaction notice.
    activities = {}
    compactions = {}
    summaries = {}
    started = time.monotonic()
    seen_tools, loaded_skills = {}, set()
    pending_approvals = set()
    summary_text, last_summary_edit = "", 0.0
    if getattr(turn, "session_id", None):
        # A newer turn is a convenient time to remove approval cards resolved elsewhere.
        await approval_messages.remove_resolved(bot, turn.owner, turn.session_id)

    async def remove_activity(cache, key):
        # Temporary progress should disappear when its work ends. Keep a reference if
        # Telegram refuses deletion so the app can try cleanup again later.
        if key not in cache:
            return
        remaining = []
        for message_id, _ in cache[key]:
            try:
                await bot.api("deleteMessage", {"chat_id": chat, "message_id": message_id})
            except ServiceError:
                # Keep references when Telegram cannot delete temporary progress.
                try:
                    await bot.api(
                        "editMessageText",
                        {
                            "chat_id": chat,
                            "message_id": message_id,
                            "text": "Live updates stopped.",
                        },
                    )
                except ServiceError:
                    pass
                remaining.append((message_id, {"text": "Live updates stopped.", "entities": []}))
        if remaining:
            cache[key] = remaining
        else:
            cache.pop(key, None)

    async def activity_parts(cache, key, parts):
        # Reuse existing Telegram messages while an activity changes; send extra chunks
        # only when needed, because Telegram edits are less noisy than repeated sends.
        previous = cache.get(key, [])
        current = []
        for index, part in enumerate(parts):
            if index < len(previous):
                message_id, displayed = previous[index]
                if part != displayed:
                    await bot.api(
                        "editMessageText", {"chat_id": chat, "message_id": message_id, **part}
                    )
                current.append((message_id, part))
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
                current.append((posted["message_id"], part))
        for message_id, _ in previous[len(parts) :]:
            try:
                await bot.api("deleteMessage", {"chat_id": chat, "message_id": message_id})
            except ServiceError:
                try:
                    await bot.api(
                        "editMessageText",
                        {
                            "chat_id": chat,
                            "message_id": message_id,
                            "text": "Live updates stopped.",
                        },
                    )
                except ServiceError:
                    pass
                current.append((message_id, {"text": "Live updates stopped.", "entities": []}))
        if current:
            cache[key] = current
        else:
            cache.pop(key, None)

    async def activity(cache, key, value):
        await activity_parts(cache, key, format_reply(value))

    async def remove_thinking_placeholder():
        # Reasoning summaries can be the first visible update. Replace the placeholder
        # instead of leaving both "Thinking…" and the summary in the chat.
        if (
            not text
            and messages
            and messages[0][1].get("text") == "Thinking…"
            and "summary" not in summaries
        ):
            summaries["summary"] = [messages.pop(0)]

    async def clear_summary():
        # Once answer text arrives, remove temporary reasoning-summary messages.
        nonlocal summary_text
        if "summary" in summaries:
            await remove_activity(summaries, "summary")
        summary_text = ""

    async def edit(value):
        # Formatting is centralized in formatting.py, which converts Markdown into
        # Telegram entities and splits long messages without breaking entity offsets.
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
        # Turn.events() is the bridge from Runtime.publish_event() to this transport.
        # Each event below changes only the Telegram presentation of that turn.
        async for event in turn.events():
            kind = event["type"]
            if kind == "text":
                # Deltas arrive in small pieces. Accumulate them, then edit at most once
                # per second to avoid Telegram rate limits and unnecessary network calls.
                await clear_summary()
                text += event["text"]
                if time.monotonic() - last_edit >= 1:
                    await edit(text or "…")
                    last_edit = time.monotonic()
            elif kind == "reasoning" and event.get("display_summary"):
                # Only explicitly displayable summaries reach Telegram. Raw provider
                # reasoning is not rendered by this branch.
                summary_text += event["text"]
                await remove_thinking_placeholder()
                if time.monotonic() - last_summary_edit >= 1 or "summary" not in summaries:
                    await activity(
                        summaries,
                        "summary",
                        "🧠 **Reasoning summary**\n\n" + summary_text,
                    )
                    last_summary_edit = time.monotonic()
            elif kind == "thinking" and not text and not messages:
                sent = await bot.send(chat, "Thinking…", topic)
                messages.append((sent["message_id"], {"text": "Thinking…", "entities": []}))
            elif kind in {"assistant_complete", "answer_replace"}:
                # A complete response can replace streamed text, for example after a
                # recovery step produces the final answer.
                await clear_summary()
                text = event["text"] or ""
                if text:
                    await edit(text)
                elif not event.get("requested_tools"):
                    await edit("…")
            elif kind == "compaction":
                # Context compaction is background model work. Show a short notice instead
                # of exposing its internal prompt or summary content.
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
                # Tool events tell us when to show exact arguments and when that temporary
                # card can be removed. The call ID keeps parallel calls distinct.
                state = event["status"]
                key = (event.get("parent_call_id"), event["call_id"])
                item = seen_tools.setdefault(key, {"skill": None})
                item["status"] = state
                if state == "running" and event["name"] == "load_skill":
                    item["skill"] = event.get("arguments", {}).get("name")
                if state == "completed" and isinstance(item["skill"], str):
                    loaded_skills.add(" ".join(item["skill"].split())[:128])
                if state == "running":
                    needs_approval = requires_approval(event["name"])
                    outcome = "Waiting for approval" if needs_approval else "In progress"
                    arguments = json.dumps(
                        event.get("arguments", {}),
                        ensure_ascii=False,
                        indent=2,
                    )
                    verb = "Requesting" if needs_approval else "Calling"
                    await activity_parts(
                        activities,
                        key,
                        format_tool_activity(event["name"], arguments, outcome, verb),
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
                # Approval cards need stable message references so a later button press,
                # timeout, or decision in another client can remove them.
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
                    call_key = (None, item.get("call_id"))
                    if call_key in activities:
                        await activity(
                            activities,
                            call_key,
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
                        # Keep the entire review available when Telegram's message limit
                        # would otherwise make the action too long to inspect safely.
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
                        # Put buttons only on the last chunk so all parts refer to the same
                        # complete review and one approval decision.
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
                # The event contains a catalog ID; deliver_file checks that it belongs to
                # this turn's owner before opening and sending the file.
                await bot.deliver_file(turn.owner, chat, topic, event["file_id"])
            elif kind == "error":
                # Errors are displayed only after Runtime has converted them to a safe
                # user-facing message; provider exceptions stay out of Telegram.
                text = event["message"]
            elif kind == "done":
                # This is the terminal event. Send any final answer and measured footer,
                # or leave approval cards in place while the turn waits for a decision.
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
        # A cancelled turn must not leave temporary reasoning, tool, or compaction cards
        # looking active in the chat.
        for cache in (activities, compactions, summaries):
            for key in list(cache):
                await remove_activity(cache, key)
