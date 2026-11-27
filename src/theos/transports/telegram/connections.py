"""Offer optional private account connections without starting model turns."""

import logging

from cryptography.fernet import Fernet

from theos.services.account_setup import ACCOUNT_LABELS, complete_setup, setup_status
from theos.services.errors import ServiceError
from theos.services.journeys import bind_connection, record, remember_connection
from theos.storage.account_access import account_access

from . import call_setup, menus

logger = logging.getLogger("theos")
LABELS = dict(ACCOUNT_LABELS)


async def offer(bot, owner, chat, topic):
    setup = setup_status(bot.settings, bot.db, owner, bot.runtime.zepto)
    if not setup["needed"]:
        return
    buttons = [
        [
            {
                "text": "🔗 Connect "
                + account["name"]
                + (" (optional)" if account["id"] == "health" else ""),
                "callback_data": "connect:" + account["id"],
            }
        ]
        for account in setup["accounts"]
    ]
    if call_setup.offer_button(bot, owner):
        buttons.append(call_setup.offer_button(bot, owner))
    buttons.append([{"text": "⏭ Skip for now", "callback_data": "connect:skip"}])
    await menus.show(
        bot,
        owner,
        chat,
        topic,
        "Would you like to connect your accounts?\n"
        "Gmail helps with email, Calendar with events, Zepto with shopping, and Google Health with activity and vitals.\n"
        + (
            "Telegram calls can also alert you about reminders and pending approvals.\n"
            if setup["calling"]
            else ""
        )
        + "All connections are optional. You can add them later.",
        {"inline_keyboard": buttons},
        "accounts",
    )


def controls(service, url=None, manual=False, pending=True):
    """Keep URLs in URL buttons and account actions in short callback data."""
    rows = []
    if url:
        rows.append([{"text": "🔗 Sign in to " + LABELS[service], "url": url}])
    if manual and pending:
        rows.append([{"text": "📋 Paste return link", "callback_data": "connect:paste:zepto"}])
    if pending:
        rows.append([{"text": "🔄 Check connection", "callback_data": "connect:status:" + service}])
        rows.append(
            [
                {"text": "🔄 Try again", "callback_data": "connect:retry:" + service},
                {"text": "✖️ Cancel setup", "callback_data": "connect:cancel:" + service},
            ]
        )
    else:
        rows.append(
            [{"text": "🔗 Connect " + LABELS[service], "callback_data": "connect:retry:" + service}]
        )
    return {"inline_keyboard": rows}


def connected(bot, owner, service):
    if service in {"github", "slack"}:
        return getattr(bot.runtime, service).connected(owner)
    if service == "zepto":
        return bot.runtime.zepto.connected(owner)
    return bool(
        bot.db.one("SELECT 1 FROM credentials WHERE owner=? AND service=?", (owner, service))
    )


async def menu(bot, owner, chat, topic):
    """Reopen optional account setup after onboarding or a completed connection."""
    available = setup_status(bot.settings, bot.db, owner, bot.runtime.zepto)["accounts"]
    missing = {item["id"] for item in available}
    lines = ["Your accounts", ""]
    for service, label in ACCOUNT_LABELS:
        if not (
            bool(bot.settings.zepto_url)
            if service == "zepto"
            else getattr(bot.settings, service).enabled
        ):
            continue
        if connected(bot, owner, service):
            lines.append(label + ": Connected")
        elif service in missing:
            lines.append(label + ": Not connected")
    rows = [
        [
            {
                "text": "🔗 Connect "
                + item["name"]
                + (" (optional)" if item["id"] == "health" else ""),
                "callback_data": "connect:" + item["id"],
            }
        ]
        for item in available
    ]
    if bot.runtime.phone_calls.connections.configured:
        rows.append([{"text": "📞 Telegram call settings", "callback_data": "calls:status"}])
    for service, label in ACCOUNT_LABELS:
        enabled = (
            bool(bot.settings.zepto_url)
            if service == "zepto"
            else getattr(bot.settings, service).enabled
        )
        if enabled and connected(bot, owner, service):
            rows.append([{"text": "✅ " + label, "callback_data": "connect:status:" + service}])
    lines.extend(["", "All connections are optional. Choose an account or tap Done."])
    await menus.show(
        bot, owner, chat, topic, "🔗 " + "\n".join(lines), {"inline_keyboard": rows}, "accounts"
    )


async def show_status(bot, owner, service, chat, topic):
    status = (
        bot.runtime.zepto.connection_status(owner)
        if service == "zepto"
        else getattr(bot.runtime, service).status(owner)["setup"]
        if service in {"github", "slack"}
        else bot.runtime.oauth.connection_status(owner, service)
    )
    state = status["status"]
    waiting = state in {"starting", "waiting"}
    if connected(bot, owner, service) and not waiting:
        text = LABELS[service] + " is connected."
        if service == "zepto":
            text += " Ask me to choose a saved delivery address before shopping."
        markup = {
            "inline_keyboard": [
                [{"text": "🔄 Reconnect", "callback_data": "connect:retry:" + service}],
                [{"text": "✖️ Disconnect", "callback_data": "connect:disconnect:" + service}],
            ]
        }
        await menus.show(bot, owner, chat, topic, text, markup, "connection:" + service)
        return
    text = status.get("message", "Finish sign-in, then check the connection here.")
    if state == "waiting" and service == "zepto":
        text = "Finish Zepto sign-in, then tap Paste return link."
        if not status.get("manual_return"):
            text = "Finish Zepto sign-in in your browser, then return here."
    await menus.show(
        bot,
        owner,
        chat,
        topic,
        LABELS[service] + "\n" + text,
        controls(
            service,
            status.get("url") if waiting else None,
            manual=status.get("manual_return", False) and waiting,
            pending=state not in {"idle", "cancelled"},
        ),
        "connection:" + service,
    )


async def start(bot, owner, service, chat, topic):
    """Open provider sign-in through native Telegram URL buttons."""
    try:
        remember_connection(bot.db, owner, service, None, "telegram")
        if service != "zepto":
            url = (
                (await getattr(bot.runtime, service).start(owner))["url"]
                if service in {"github", "slack"}
                else bot.runtime.oauth.start(owner, service)
            )
            bind_connection(bot.db, owner, service, url)
            await menus.show(
                bot,
                owner,
                chat,
                topic,
                "Connect " + LABELS[service] + "\n"
                "Tap the sign-in button and approve access in your browser. "
                "Then return here and tap Check connection.",
                controls(service, url),
                "connection:" + service,
            )
            return
        status = bot.runtime.zepto.connection_status(owner)
        if status["status"] == "expired":
            await bot.runtime.zepto.cancel(owner)
        elif status["status"] in {"starting", "waiting"}:
            await show_status(bot, owner, service, chat, topic)
            return

        async def send_link(url):
            manual = not bot.settings.zepto_redirect_uri.startswith("https://")
            text = (
                "Connect Zepto\n"
                "1. Tap Sign in to Zepto and complete phone verification.\n"
                "2. When the browser opens localhost, copy the full address-bar link. "
                "The page may show a connection error. This is expected.\n"
                "3. Return here and tap Paste return link."
                if manual
                else "Connect Zepto\nTap Sign in to Zepto and approve access. Then return to this chat."
            )
            await menus.show(
                bot,
                owner,
                chat,
                topic,
                text,
                controls(service, url, manual),
                "connection:" + service,
            )

        async def send_status(_):
            await show_status(bot, owner, service, chat, topic)

        await menus.show(
            bot,
            owner,
            chat,
            topic,
            "Preparing your private Zepto sign-in link.",
            controls(service),
            "connection:" + service,
        )
        await bot.runtime.zepto.connect(owner, send_link, send_status)
    except (ValueError, ServiceError) as error:
        await menus.show(
            bot, owner, chat, topic, str(error), controls(service), "connection:" + service
        )


def return_prompts(db, owner):
    try:
        return db.record(owner, "telegram_connections", "zepto_return")["messages"]
    except LookupError:
        return []


def is_return_reply(db, update):
    """Recognize replies before inbox persistence so even invalid input is encrypted."""
    message = update.get("message", {})
    chat = message.get("chat", {})
    sender = message.get("from", {}).get("id")
    return bool(
        db is not None
        and chat.get("type") == "private"
        and chat.get("id") == sender
        and message.get("reply_to_message", {}).get("message_id")
        in return_prompts(db, f"telegram:{sender}")
    )


async def prompt_return(bot, owner, chat, topic):
    status = bot.runtime.zepto.connection_status(owner)
    if status["status"] != "waiting" or not status.get("manual_return"):
        await show_status(bot, owner, "zepto", chat, topic)
        return
    result = await bot.send(
        chat,
        "Paste the full Zepto return link from your browser address bar as a reply to this message.\n"
        "It starts with http://localhost/callback or http://127.0.0.1/callback. "
        "Use Cancel setup on the sign-in card to stop.",
        topic,
        {"force_reply": True, "input_field_placeholder": "Paste the full Zepto return link"},
    )
    if result and result.get("message_id"):
        ids = return_prompts(bot.db, owner)
        bot.db.put_record(
            owner,
            "telegram_connections",
            "zepto_return",
            {
                "messages": (ids + [result["message_id"]])[-10:],
            },
        )


async def accept_return(bot, message, owner, chat, topic):
    """Consume only encrypted account handoffs, outside conversation history."""
    active = record(bot.db, owner, "telegram_menu", "active")
    if active.get("stack", [""])[-1] == "connection:zepto":
        menus.interaction.set({"owner": owner, **active})
    try:
        if message.get("_theos_zepto_return_invalid"):
            raise ValueError(
                "This return link could not be read. Copy the full browser address and try again."
            )
        key = bot.settings.token_encryption_key.get_secret_value()
        return_url = Fernet(key.encode()).decrypt(message["_theos_zepto_return"].encode()).decode()
        await bot.runtime.zepto.finish_from_telegram(owner, return_url)
    except Exception as error:
        if isinstance(error, (ValueError, ServiceError, PermissionError)):
            text = str(error)
        else:
            logger.warning("zepto_return_failed", extra={"error_type": type(error).__name__})
            text = "The Zepto return link could not be accepted. Try connecting again."
        await menus.show(
            bot, owner, chat, topic, text, controls("zepto", manual=True), "connection:zepto"
        )
    else:
        await menus.show(
            bot,
            owner,
            chat,
            topic,
            "The Zepto return was accepted. I will confirm the connection here after verification.",
            controls("zepto"),
            "connection:zepto",
        )


async def handle(bot, message, owner, channel, chat, topic, callback):
    if await call_setup.handle(bot, message, owner, channel, chat, topic, callback):
        return True
    data = (callback or {}).get("data", "")
    command = message.get("text", "").split(" ", 1)[0].split("@")[0]
    direct = (
        not callback
        and command
        in {
            "/connections",
            "/github_notifications",
            "/github",
            "/connect_github",
            "/slack",
            "/connect_slack",
            "/gmail",
            "/connect_gmail",
            "/calendar",
            "/connect_calendar",
            "/health",
            "/connect_health",
            "/zepto",
            "/connect_zepto",
            "/zepto_finish",
        }
        and not ("_theos_zepto_return" in message or message.get("_theos_zepto_return_invalid"))
    )
    if not data.startswith("connect:") and not direct:
        return False
    allowed = channel == "telegram-private" and account_access(bot.settings, bot.db, owner)
    if callback:
        allowed = allowed and chat == callback["from"]["id"]
        await bot.api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback["id"],
                "text": "" if allowed else "Use your private chat after completing setup.",
            },
        )
    if not allowed:
        if direct:
            await bot.send(
                chat, "Complete /start setup in a private chat before connecting accounts.", topic
            )
        return True
    if direct:
        if command == "/github_notifications":
            argument = message.get("text", "").partition(" ")[2].strip().lower()
            if argument not in {"on", "off"}:
                await bot.send(
                    chat, "Use /github_notifications on or /github_notifications off.", topic
                )
                return True
            try:
                await bot.runtime.github_events.configure(owner, argument == "on", argument == "on")
                await bot.send(chat, "GitHub event notifications are " + argument + ".", topic)
            except (ValueError, ServiceError, PermissionError) as error:
                await bot.send(chat, str(error), topic)
        elif command == "/connections":
            await menu(bot, owner, chat, topic)
        elif command == "/zepto_finish":
            await prompt_return(bot, owner, chat, topic)
        else:
            service = {
                "/gmail": "gmail",
                "/calendar": "calendar",
                "/health": "health",
                "/zepto": "zepto",
                "/github": "github",
                "/slack": "slack",
            }.get(command, command.removeprefix("/connect_"))
            await start(bot, owner, service, chat, topic)
        return True
    action, _, service = data.removeprefix("connect:").partition(":")
    if action == "skip":
        complete_setup(bot.settings, bot.db, owner)
        await menus.finish(bot, owner, chat)
        await bot.send(
            chat, "You are ready to chat. Use /connections to add accounts later.", topic
        )
    elif action == "menu":
        await menu(bot, owner, chat, topic)
    else:
        if not service:
            service, action = action, "start"
        if (
            service not in LABELS
            or action not in {"start", "retry", "status", "cancel", "paste", "disconnect", "remove"}
            or (action == "paste" and service != "zepto")
        ):
            await bot.send(chat, "This connection button is unavailable. Use /connections.", topic)
            return True
        try:
            if action == "disconnect":
                await menus.show(
                    bot,
                    owner,
                    chat,
                    topic,
                    "Disconnect " + LABELS[service] + " from your account?",
                    {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "✖️ Disconnect " + LABELS[service],
                                    "callback_data": "connect:remove:" + service,
                                }
                            ]
                        ]
                    },
                    "disconnect:" + service,
                )
            elif action == "remove":
                if service in {"github", "slack", "zepto"}:
                    if service == "github":
                        bot.runtime.github_events.disable(owner)
                    await getattr(bot.runtime, service).disconnect(owner)
                else:
                    await bot.runtime.oauth.disconnect(owner, service)
                context = menus.interaction.get() or {}
                if "accounts" in context.get("stack", []):
                    await menu(bot, owner, chat, topic)
                else:
                    await show_status(bot, owner, service, chat, topic)
            elif action == "status":
                await show_status(bot, owner, service, chat, topic)
            elif action == "paste" and service == "zepto":
                await prompt_return(bot, owner, chat, topic)
            else:
                if action in {"retry", "cancel"}:
                    if service in {"github", "slack"}:
                        await getattr(bot.runtime, service).cancel(owner)
                    elif service == "zepto":
                        await bot.runtime.zepto.cancel(owner)
                    else:
                        await bot.runtime.oauth.cancel(owner, service)
                if action == "cancel":
                    await menus.show(
                        bot,
                        owner,
                        chat,
                        topic,
                        "Setup cancelled. Your previously connected account is unchanged.",
                        controls(service, pending=False),
                        "connection:" + service,
                    )
                else:
                    await start(bot, owner, service, chat, topic)
        except (ValueError, ServiceError) as error:
            await menus.show(
                bot, owner, chat, topic, str(error), controls(service), "connection:" + service
            )
    return True
