"""Durable, owner-bound Telegram menus with real navigation and single-use actions."""

import asyncio
import time
from contextvars import ContextVar
from uuid import uuid4

from theos.services.errors import ServiceError
from theos.services.journeys import record

interaction = ContextVar("telegram_menu", default=None)


def render_lock(bot, owner):
    # Provider callbacks can render through a different Telegram instance.
    locks = bot.runtime.__dict__.setdefault("telegram_menu_locks", {})
    return locks.setdefault(owner, asyncio.Lock())


def target(screen):
    if screen.startswith("connection:"):
        return "connect:status:" + screen.split(":", 1)[1]
    return {"accounts": "connect:menu", "calls": "calls:status"}.get(screen, screen)


async def retire(bot, chat, message_id):
    if message_id:
        try:
            await bot.api(
                "editMessageReplyMarkup",
                {
                    "chat_id": chat,
                    "message_id": message_id,
                    "reply_markup": {"inline_keyboard": []},
                },
            )
        except ServiceError:
            pass  # Saved action tokens are invalid even if Telegram cannot edit the message.


async def resolve(bot, owner, chat, message, callback):
    """Validate and consume a button before any service can run its action."""
    data = callback.get("data", "")
    if not data.startswith("ui:"):
        if data.startswith(("connect:", "calls:", "settings:", "onboarding:")):
            await bot.api(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback["id"],
                    "text": "This menu is old. Open /settings, /connections, or /start again.",
                },
            )
            return None
        return callback
    try:
        _, key, revision, index = data.split(":")
        saved = record(bot.db, owner, "telegram_menu", "active")
        if (
            saved.get("key") != key
            or saved.get("revision") != int(revision)
            or saved.get("chat") != chat
            or saved.get("message_id") != message["message_id"]
            or saved.get("expires", 0) < time.time()
            or saved.get("consumed")
            or (callback["from"]["id"] != chat and not owner.startswith("telegram-group:"))
            or index not in saved.get("actions", {})
        ):
            raise ValueError("Stale menu")
        action = saved["actions"][index]
    except (ValueError, KeyError, TypeError):
        await bot.api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback["id"],
                "text": "This menu changed. Use the latest menu or open /settings.",
            },
        )
        return None
    saved["consumed"] = True
    bot.db.put_record(owner, "telegram_menu", "active", saved)
    interaction.set({"owner": owner, **saved})
    if action == "nav:done":
        await bot.api("answerCallbackQuery", {"callback_query_id": callback["id"], "text": "Done"})
        await finish(bot, owner, chat)
        return None
    if action == "nav:back":
        if len(saved["stack"]) < 2:
            return None
        saved["stack"].pop()
        action = target(saved["stack"][-1])
        interaction.set({"owner": owner, **saved})
    return {**callback, "data": action}


async def show(bot, owner, chat, topic, text, markup, screen, *, navigation=True):
    """Update the active card; a direct command starts a fresh navigation stack."""
    async with render_lock(bot, owner):
        await _show(bot, owner, chat, topic, text, markup, screen, navigation=navigation)


async def _show(bot, owner, chat, topic, text, markup, screen, *, navigation):
    context = interaction.get()
    previous = record(bot.db, owner, "telegram_menu", "active")
    if context and context.get("owner") == owner:
        if previous.get("key") != context.get("key") or previous.get("closed"):
            return  # A delayed provider update must not resurrect a dismissed menu.
        context = {**context, **previous}
    if not context or context.get("owner") != owner:
        await retire(bot, previous.get("chat", chat), previous.get("message_id"))
        context = {"key": uuid4().hex[:12], "revision": 0, "stack": [], "owner": owner}
    stack = context["stack"]
    if screen in stack:
        stack[:] = stack[: stack.index(screen) + 1]
    else:
        stack.append(screen)
    rows = [[dict(button) for button in row] for row in markup.get("inline_keyboard", [])]
    if navigation:
        rows.append(
            [
                {
                    "text": (
                        "⬅️ Back to "
                        + {
                            "accounts": "accounts",
                            "settings:menu": "settings",
                            "calls": "calls",
                        }.get(stack[-2], "previous step")
                    )
                    if len(stack) > 1
                    else "✅ Done",
                    "callback_data": "nav:back" if len(stack) > 1 else "nav:done",
                }
            ]
        )
    revision = context["revision"] + 1
    actions = {}
    for row in rows:
        for button in row:
            if "callback_data" in button:
                index = str(len(actions))
                actions[index] = button["callback_data"]
                button["callback_data"] = f"ui:{context['key']}:{revision}:{index}"
    payload = {"chat_id": chat, "text": text, "reply_markup": {"inline_keyboard": rows}}
    message_id = context.get("message_id")
    if message_id:
        try:
            await bot.api("editMessageText", {**payload, "message_id": message_id})
        except ServiceError:
            await retire(bot, chat, message_id)
            message_id = None
    if not message_id:
        result = await bot.send(chat, text, topic, payload["reply_markup"])
        message_id = (result or {}).get("message_id")
    saved = {
        "key": context["key"],
        "revision": revision,
        "stack": stack,
        "chat": chat,
        "message_id": message_id,
        "actions": actions,
        "expires": time.time() + 3600,
        "consumed": False,
    }
    bot.db.put_record(owner, "telegram_menu", "active", saved)
    interaction.set({"owner": owner, **saved})


async def finish(bot, owner, chat):
    async with render_lock(bot, owner):
        await _finish(bot, owner, chat)


async def _finish(bot, owner, chat):
    saved = record(bot.db, owner, "telegram_menu", "active")
    if saved:
        saved["consumed"] = True
        saved["closed"] = True
        bot.db.put_record(owner, "telegram_menu", "active", saved)
        await retire(bot, chat, saved.get("message_id"))
    interaction.set(None)
