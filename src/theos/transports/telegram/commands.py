"""Handle Telegram commands directly, outside the normal model/tool loop."""

import json

from theos.runtime.model_catalog import model_choices, reasoning_choices
from theos.storage.telegram_access import account_access

from . import connections


async def command(bot, session, command, argument, chat, topic):
    """Handle chat commands and enforce private account access."""
    owner = session["owner"]
    # Keep older command spellings working while routing all behavior to one implementation.
    aliases = {
        "/thinking": "/reasoning",
        "/connect_gmail": "/gmail",
        "/connect_health": "/health",
        "/github": "/connect_github",
        "/gitlab": "/connect_gitlab",
        "/slack": "/connect_slack",
        "/zepto": "/connect_zepto",
    }
    command = aliases.get(command, command)
    # Account commands can reveal private data or grant external access. Gate them before
    # calling an account service, even though polling.py has already identified the sender.
    if command in {
        "/gmail",
        "/health",
        "/disconnect_gmail",
        "/disconnect_health",
        "/health_summary",
        "/health_refresh",
        "/connect_github",
        "/connect_gitlab",
        "/connect_slack",
        "/disconnect_github",
        "/disconnect_gitlab",
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
        "/disconnect_health",
        "/health_summary",
        "/health_refresh",
        "/disconnect_github",
        "/disconnect_gitlab",
        "/disconnect_slack",
        "/disconnect_zepto",
    }:
        if session["channel"] != "telegram-private":
            raise PermissionError("Use a private Telegram chat for account commands.")
        if command.startswith("/disconnect_"):
            service = command.removeprefix("/disconnect_")
            if service in {"github", "slack", "gitlab"}:
                if service == "github":
                    bot.runtime.github_events.disable(owner)
                await getattr(bot.runtime, service).disconnect(owner)
                await bot.send(
                    chat,
                    f"{connections.LABELS[service]} is disconnected from Theos. Revoke the app at the provider to end remote authorization.",
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
        await bot.send(
            chat,
            f"I am {bot.settings.name}, your personal assistant.\n\n"
            "Send a message, photo, document, or voice note. Commands: /connections, /web, /new, /resume, /research QUESTION, /model NAME, /reasoning default|none|low|medium|high, /settings, /gmail, /health, /connect_github, /connect_gitlab, /connect_slack, /connect_zepto.",
            topic,
        )
    elif command in {"/new", "/reset"}:
        await bot.runtime.reset(owner, session["id"])
        await bot.send(chat, "Conversation reset. Your saved records remain available.", topic)
    elif command == "/research":
        # Explicit command syntax is the user's consent to create saved research records.
        if not argument.strip():
            raise ValueError("Use /research followed by your question.")
        await bot.render(
            bot.runtime.start(owner, session["id"], argument, mode="deep_research"), chat, topic
        )
    elif command == "/resume":
        # Resume saved pending tool calls or a turn stopped at a model-call boundary.
        await bot.render(bot.runtime.start(owner, session["id"]), chat, topic)
    elif command == "/model":
        # Validate choices against operator-supported models before changing session state.
        allowed = model_choices(bot.settings)
        if argument not in allowed:
            await bot.send(chat, "Available models: " + ", ".join(allowed), topic)
        else:
            bot.db.execute("UPDATE sessions SET model=? WHERE id=?", (argument, session["id"]))
            await bot.send(chat, "Model saved: " + argument, topic)
    elif command == "/reasoning":
        # Reasoning options vary by model/provider, so only persist a supported choice.
        choices = reasoning_choices(bot.settings.provider, session["model"])
        if argument not in choices:
            raise ValueError("Use one of: " + ", ".join(choices))
        bot.db.execute("UPDATE sessions SET reasoning=? WHERE id=?", (argument, session["id"]))
        await bot.send(chat, "Reasoning setting saved.", topic)
    elif command in {
        "/gmail",
        "/health",
        "/connect_github",
        "/connect_gitlab",
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
    elif command == "/settings":
        await bot.send(
            chat,
            f"Model: {session['model']}\nReasoning: {session['reasoning']}\nSession: {session['id']}",
            topic,
        )
    else:
        await bot.send(chat, "Unknown command. Send /help for available commands.", topic)
