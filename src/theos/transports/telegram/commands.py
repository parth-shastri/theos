"""Handle Telegram commands directly, outside the normal model/tool loop."""

import json

from theos.storage.telegram_access import account_access

from . import connections, menus
from . import settings as settings_ui


async def command(bot, session, command, argument, chat, topic):
    """Handle chat commands and enforce private account access."""
    owner = session["owner"]
    # Keep older command spellings working while routing all behavior to one implementation.
    aliases = {
        "/thinking": "/reasoning",
        "/connect_gmail": "/gmail",
        "/connect_calendar": "/calendar",
        "/connect_health": "/health",
        "/github": "/connect_github",
        "/slack": "/connect_slack",
        "/zepto": "/connect_zepto",
    }
    command = aliases.get(command, command)
    if command in {"/settings", "/model", "/reasoning"}:
        await settings_ui.handle(
            bot,
            {"text": command + (" " + argument if argument else "")},
            owner,
            session["channel"],
            chat,
            topic,
            None,
        )
        return
    # Account commands can reveal private data or grant external access. Gate them before
    # calling an account service, even though polling.py has already identified the sender.
    if command in {
        "/gmail",
        "/calendar",
        "/health",
        "/disconnect_gmail",
        "/disconnect_calendar",
        "/disconnect_health",
        "/health_summary",
        "/health_refresh",
        "/connect_github",
        "/connect_slack",
        "/disconnect_github",
        "/disconnect_slack",
        "/connect_zepto",
        "/disconnect_zepto",
        "/zepto_finish",
        "/connections",
    } and (
        session["channel"] != "telegram-private" or not account_access(bot.settings, bot.db, owner)
    ):
        await bot.send(
            chat, "Complete /start setup in a private chat before connecting accounts.", topic
        )
        return
    # These commands do not need a model turn: read/update the account service directly and
    # send a bounded, literal response to Telegram.
    if command in {
        "/disconnect_gmail",
        "/disconnect_calendar",
        "/disconnect_health",
        "/health_summary",
        "/health_refresh",
        "/disconnect_github",
        "/disconnect_slack",
        "/disconnect_zepto",
    }:
        if session["channel"] != "telegram-private":
            raise PermissionError("Use a private Telegram chat for account commands.")
        if command.startswith("/disconnect_"):
            service = command.removeprefix("/disconnect_")
            if service in {"github", "slack"}:
                if service == "github":
                    bot.runtime.github_events.disable(owner)
                await getattr(bot.runtime, service).disconnect(owner)
                await bot.send(
                    chat,
                    f"{service.title() if service == 'slack' else 'GitHub'} is disconnected from Theos. Revoke the app at the provider to end remote authorization.",
                    topic,
                )
                return
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
            result = await bot.runtime.health.read_summary(owner)
        await bot.send(chat, json.dumps(result, ensure_ascii=False), topic)
        return
    # Conversation commands either reply directly or deliberately start a runtime turn.
    if command in {"/start", "/help"}:
        await help_menu(
            bot, owner, chat, topic, private=session.get("channel") == "telegram-private"
        )
    elif command in {"/new", "/reset"}:
        await bot.runtime.reset(owner, session["id"])
        await bot.send(chat, "Conversation reset. Your saved records remain available.", topic)
    elif command == "/research":
        # Explicit command syntax is the user's consent to create saved research records.
        if not argument.strip():
            await bot.send(chat, "Use /research followed by your question.", topic)
            return
        await bot.render(
            bot.runtime.start(owner, session["id"], argument, mode="deep_research"), chat, topic
        )
    elif command == "/resume":
        # Resume saved pending tool calls or a turn stopped at a model-call boundary.
        await bot.render(bot.runtime.start(owner, session["id"]), chat, topic)
    elif command in {
        "/gmail",
        "/calendar",
        "/health",
        "/connect_github",
        "/connect_slack",
        "/connect_zepto",
    }:
        await connections.start(
            bot, owner, command.removeprefix("/connect_").lstrip("/"), chat, topic
        )
    elif command == "/connections":
        await connections.menu(bot, owner, chat, topic)
    elif command == "/zepto_finish":
        await connections.prompt_return(bot, owner, chat, topic)
    else:
        await bot.send(chat, "Unknown command. Send /help for available commands.", topic)


async def help_menu(bot, owner, chat, topic, *, private=True):
    text = (
        f"👋 I am {bot.settings.name}, your personal assistant.\n\n"
        "💬 Send a message, photo, document, or voice note.\n"
        "⚙️ /settings opens editable preferences.\n"
        "🔗 /connections manages your accounts.\n"
        "🌐 /web opens the browser sign-in flow.\n"
        "🔎 /research QUESTION starts deep research.\n"
        "▶️ /resume continues saved work.\n"
        "Use /new to reset this conversation, or /password to manage browser sign-in."
    )
    if not private:
        await bot.send(chat, text, topic)
        return
    await menus.show(
        bot,
        owner,
        chat,
        topic,
        text,
        {
            "inline_keyboard": [
                [
                    {"text": "⚙️ Settings", "callback_data": "settings:menu"},
                    {"text": "🔗 Accounts", "callback_data": "connect:menu"},
                ]
            ]
        },
        "help",
    )
