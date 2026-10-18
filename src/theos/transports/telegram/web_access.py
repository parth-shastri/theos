"""Telegram actions for starting, confirming, or revoking browser sign-in."""

from theos.storage import browser_access


async def send_link(bot, owner, chat, topic):
    """Send a short-lived fragment link after private onboarding completes."""
    if not bot.settings.web_url:
        await bot.send(
            chat, "Web access is unavailable. Ask the operator to set AGENT_WEB_URL.", topic
        )
        return
    # Create an owner-bound, expiring invitation. The browser must bring it back to Telegram
    # for confirmation before it can issue a browser session.
    secret = browser_access.invite(bot.settings, bot.db, owner)
    await bot.send(
        chat,
        "Open your chat UI and personal usage view. This link expires in 10 minutes.\n"
        "Confirm the matching browser code here before signing in.",
        topic,
        {
            "inline_keyboard": [
                [{"text": "Open Theos", "url": f"{bot.settings.web_url}/#onboard={secret}"}]
            ]
        },
    )


async def handle(bot, message, owner, channel, chat, topic, callback):
    """Handle web access outside model turns and conversation creation."""
    if callback:
        # Only browser-enrollment buttons belong here. Other buttons (tool approvals) are
        # left for polling.py, which owns their separate conversation-resume flow.
        data = callback.get("data", "")
        if not data.startswith(("web:", "webdeny:")):
            return False
        try:
            # Confirm or reject only in the private chat of the owner who started sign-in.
            if channel != "telegram-private":
                raise ValueError("Confirm web access in your private Telegram chat.")
            approved = data.startswith("web:")
            code = browser_access.confirm(
                bot.settings, bot.db, owner, data.split(":", 1)[1], approved
            )
            text = f"Browser {code} {'approved' if approved else 'denied'}."
        except (PermissionError, ValueError) as error:
            text = str(error)
        await bot.api("answerCallbackQuery", {"callback_query_id": callback["id"], "text": text})
        return True
    # Telegram appends @botname when a command is used in some contexts; strip it so /web
    # has one stable spelling in both private and group chats.
    command, _, argument = message.get("text", "").strip().partition(" ")
    command = command.split("@")[0]
    if command == "/start" and channel == "telegram-private" and bot.settings.web_url:
        # Send browser guidance but return False: the regular /start command may still
        # need to run after this optional web-access side effect.
        await send_link(bot, owner, chat, topic)
        return False
    if command != "/web":
        return False
    if channel != "telegram-private":
        # Browser credentials belong to a person, not to a shared group conversation.
        await bot.send(chat, "Open web access from your private Telegram chat.", topic)
    elif argument.strip() == "revoke":
        # Revoke generated browser tokens and device sessions without deleting chat history.
        browser_access.revoke(bot.db, owner)
        await bot.send(
            chat,
            "Your web tokens and device sessions are revoked. Send /web for a new sign-in link.",
            topic,
        )
    elif argument.strip():
        await bot.send(chat, "Send /web to sign in, or /web revoke to end all web access.", topic)
    else:
        await send_link(bot, owner, chat, topic)
    return True
