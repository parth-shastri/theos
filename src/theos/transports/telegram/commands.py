"""Telegram commands for conversations, settings, and private accounts."""

import json

from theos.runtime.model_catalog import model_choices, reasoning_choices
from theos.services.errors import ServiceError
from theos.storage.telegram_access import account_access


async def command(bot, session, command, argument, chat, topic):
    """Handle chat commands and enforce private account access."""
    owner = session["owner"]
    aliases = {
        "/thinking": "/reasoning",
        "/connect_gmail": "/gmail",
        "/connect_health": "/health",
        "/zepto": "/connect_zepto",
    }
    command = aliases.get(command, command)
    if command in {
        "/gmail",
        "/health",
        "/disconnect_gmail",
        "/disconnect_health",
        "/health_summary",
        "/health_refresh",
        "/connect_zepto",
        "/disconnect_zepto",
        "/zepto_finish",
    } and (
        session["channel"] != "telegram-private" or not account_access(bot.settings, bot.db, owner)
    ):
        await bot.send(
            chat, "Complete /start setup in a private chat before connecting accounts.", topic
        )
        return
    if command in {
        "/disconnect_gmail",
        "/disconnect_health",
        "/health_summary",
        "/health_refresh",
        "/disconnect_zepto",
    }:
        if session["channel"] != "telegram-private":
            raise PermissionError("Use a private Telegram chat for account commands.")
        if command.startswith("/disconnect_"):
            service = command.removeprefix("/disconnect_")
            if service == "zepto":
                await bot.runtime.zepto.disconnect(owner)
                await bot.send(
                    chat,
                    "Zepto is disconnected from Theos. Revoke its access in Zepto if you want to end the remote authorization.",
                    topic,
                )
                return
            result = await bot.runtime.oauth.disconnect(owner, service)
        elif command == "/health_refresh":
            result = await bot.runtime.health.import_summary(owner)
        else:
            result = bot.db.record(owner, "health", "summary")
        await bot.send(chat, json.dumps(result, ensure_ascii=False)[:4000], topic)
        return
    if command in {"/start", "/help"}:
        await bot.send(
            chat,
            f"I am {bot.settings.name}, your personal assistant.\n\n"
            "Send a message, photo, document, or voice note. Commands: /new, /resume, /model NAME, /reasoning default|none|low|medium|high, /settings, /gmail, /health, /connect_zepto.",
            topic,
        )
    elif command in {"/new", "/reset"}:
        await bot.runtime.reset(owner, session["id"])
        await bot.send(chat, "Conversation reset. Your saved records remain available.", topic)
    elif command == "/resume":
        await bot.render(bot.runtime.start(owner, session["id"]), chat, topic)
    elif command == "/model":
        allowed = model_choices(bot.settings)
        if argument not in allowed:
            await bot.send(chat, "Available models: " + ", ".join(allowed), topic)
        else:
            bot.db.execute("UPDATE sessions SET model=? WHERE id=?", (argument, session["id"]))
            await bot.send(chat, "Model saved: " + argument, topic)
    elif command == "/reasoning":
        choices = reasoning_choices(bot.settings.provider, session["model"])
        if argument not in choices:
            raise ValueError("Use one of: " + ", ".join(choices))
        bot.db.execute("UPDATE sessions SET reasoning=? WHERE id=?", (argument, session["id"]))
        await bot.send(chat, "Reasoning setting saved.", topic)
    elif command in {"/gmail", "/health"}:
        if session["channel"] != "telegram-private":
            raise PermissionError("Connect accounts in a private Telegram chat.")
        await bot.send(chat, bot.runtime.oauth.start(owner, command[1:]), topic)
    elif command == "/connect_zepto":
        if session["channel"] != "telegram-private":
            raise PermissionError("Connect Zepto in a private Telegram chat.")

        async def send_link(url):
            local_callback = bot.settings.zepto_redirect_uri.startswith("http://localhost/") or (
                bot.settings.zepto_redirect_uri.startswith("http://127.0.0.1/")
            )
            instructions = (
                "Open the Zepto sign-in link and approve access. When your browser returns to localhost, "
                "copy the full address-bar URL and send `/zepto_finish <url>` here."
                if local_callback
                else "Open the Zepto sign-in link and approve access. Return to this chat after sign-in."
            )
            await bot.send(
                chat,
                instructions,
                topic,
                {"inline_keyboard": [[{"text": "Sign in to Zepto", "url": url}]]},
            )

        async def send_status(text):
            await bot.send(chat, text, topic)

        await bot.send(chat, "I am preparing a private Zepto sign-in link.", topic)
        try:
            await bot.runtime.zepto.connect(owner, send_link, send_status)
        except ServiceError as error:
            await bot.send(chat, str(error), topic)
    elif command == "/zepto_finish":
        await bot.send(
            chat,
            "Send the full localhost return URL as `/zepto_finish <url>` in this private chat.",
            topic,
        )
    elif command == "/settings":
        await bot.send(
            chat,
            f"Model: {session['model']}\nReasoning: {session['reasoning']}\nSession: {session['id']}",
            topic,
        )
    else:
        await bot.send(chat, "Unknown command. Send /help for available commands.", topic)
