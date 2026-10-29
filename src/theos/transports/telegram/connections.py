"""Offer optional private account connections without starting model turns."""

import logging

from cryptography.fernet import Fernet

from theos.services.account_setup import ACCOUNT_LABELS, complete_setup, setup_status
from theos.services.errors import ServiceError
from theos.storage.account_access import account_access

logger = logging.getLogger("theos")
LABELS = dict(ACCOUNT_LABELS)


async def offer(bot, owner, chat, topic):
    setup = setup_status(bot.settings, bot.db, owner, bot.runtime.zepto)
    if not setup["needed"]:
        return
    buttons = [
        [
            {
                "text": "Connect "
                + account["name"]
                + (" (optional)" if account["id"] == "health" else ""),
                "callback_data": "connect:" + account["id"],
            }
        ]
        for account in setup["accounts"]
    ]
    buttons.append([{"text": "Skip for now", "callback_data": "connect:skip"}])
    await bot.send(
        chat,
        "Would you like to connect your accounts?\n"
        "Gmail helps with email, Calendar with events, Zepto with shopping, and Google Health with activity and vitals.\n"
        "All connections are optional. You can add them later.",
        topic,
        {"inline_keyboard": buttons},
    )


def controls(service, url=None, manual=False, pending=True):
    """Keep URLs in URL buttons and account actions in short callback data."""
    rows = []
    if url:
        rows.append([{"text": "Sign in to " + LABELS[service], "url": url}])
    if manual and pending:
        rows.append([{"text": "Paste return link", "callback_data": "connect:paste:zepto"}])
    if pending:
        rows.append([{"text": "Check connection", "callback_data": "connect:status:" + service}])
        rows.append(
            [
                {"text": "Try again", "callback_data": "connect:retry:" + service},
                {"text": "Cancel setup", "callback_data": "connect:cancel:" + service},
            ]
        )
    rows.append([{"text": "Back to accounts", "callback_data": "connect:menu"}])
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
        if connected(bot, owner, service):
            lines.append(label + ": Connected")
        elif service in missing:
            lines.append(label + ": Not connected")
    rows = [
        [
            {
                "text": "Connect "
                + item["name"]
                + (" (optional)" if item["id"] == "health" else ""),
                "callback_data": "connect:" + item["id"],
            }
        ]
        for item in available
    ]
    rows.append([{"text": "Done", "callback_data": "connect:skip"}])
    lines.extend(["", "All connections are optional. Choose an account or tap Done."])
    await bot.send(chat, "\n".join(lines), topic, {"inline_keyboard": rows})


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
        await bot.send(chat, text, topic, controls(service, pending=False))
        return
    text = status.get("message", "Finish sign-in, then check the connection here.")
    if state == "waiting" and service == "zepto":
        text = "Finish Zepto sign-in, then tap Paste return link."
        if not status.get("manual_return"):
            text = "Finish Zepto sign-in in your browser, then return here."
    await bot.send(
        chat,
        LABELS[service] + "\n" + text,
        topic,
        controls(
            service,
            status.get("url") if waiting else None,
            manual=status.get("manual_return", False) and waiting,
        ),
    )


async def start(bot, owner, service, chat, topic):
    """Open provider sign-in through native Telegram URL buttons."""
    try:
        if service != "zepto":
            url = (
                (await getattr(bot.runtime, service).start(owner))["url"]
                if service in {"github", "slack"}
                else bot.runtime.oauth.start(owner, service)
            )
            await bot.send(
                chat,
                "Connect " + LABELS[service] + "\n"
                "Tap the sign-in button and approve access in your browser. "
                "Then return here and tap Check connection.",
                topic,
                controls(service, url),
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
            await bot.send(chat, text, topic, controls(service, url, manual))

        async def send_status(_):
            await show_status(bot, owner, service, chat, topic)

        await bot.send(chat, "Preparing your private Zepto sign-in link.", topic, controls(service))
        await bot.runtime.zepto.connect(owner, send_link, send_status)
    except (ValueError, ServiceError) as error:
        await bot.send(chat, str(error), topic, controls(service))


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
        await bot.send(chat, text, topic, controls("zepto", manual=True))
    else:
        await bot.send(
            chat,
            "The Zepto return was accepted. I will confirm the connection here after verification.",
            topic,
            controls("zepto"),
        )


async def handle(bot, message, owner, channel, chat, topic, callback):
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
            or action not in {"start", "retry", "status", "cancel", "paste"}
            or (action == "paste" and service != "zepto")
        ):
            await bot.send(chat, "This connection button is unavailable. Use /connections.", topic)
            return True
        try:
            if action == "status":
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
                    await bot.send(
                        chat,
                        "Setup cancelled. Your previously connected account is unchanged.",
                        topic,
                        controls(service, pending=False),
                    )
                else:
                    await start(bot, owner, service, chat, topic)
        except (ValueError, ServiceError) as error:
            await bot.send(chat, str(error), topic, controls(service))
    return True
