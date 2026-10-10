"""Durable private-chat enrollment before commands, media, or model turns."""

import hmac
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from theos.services.preferences.tools import preferences
from theos.storage.telegram_access import code_fingerprint, has_access

from .web_access import send_link


def enroll(bot, sender):
    """Reserve one user slot and save initial preferences in one transaction."""
    user_id = sender["id"]
    owner = f"telegram:{user_id}"
    # Count and insert without an await so concurrent starts cannot exceed the limit.
    with bot.db.transaction():
        row = bot.db.one("SELECT * FROM telegram_enrollments WHERE user_id=?", (user_id,))
        if row:
            return row
        count = bot.db.one("SELECT COUNT(*) AS total FROM telegram_enrollments")["total"]
        if count >= bot.settings.telegram_max_users:
            return None
        current = preferences(bot.db, owner, bot.settings.timezone)
        name = " ".join(sender.get(key, "") for key in ("first_name", "last_name")).strip()
        if name and "display_name" not in current:
            current["display_name"] = name[:200]
        bot.db.put_record(owner, "preferences", "settings", current)
        bot.db.execute(
            "INSERT INTO telegram_enrollments VALUES (?,?,'name',?)",
            (user_id, owner, time.time()),
        )
        return bot.db.one("SELECT * FROM telegram_enrollments WHERE user_id=?", (user_id,))


async def prompt(bot, owner, chat, topic):
    """Ask for the pending preference without sending setup text to the model."""
    current = preferences(bot.db, owner, bot.settings.timezone)
    row = bot.db.one("SELECT state FROM telegram_enrollments WHERE owner=?", (owner,))
    if row["state"] == "name":
        text = "What should I call you? Send your preferred name (up to 200 characters)."
        if current.get("display_name"):
            text += f"\nSend /skip to use {current['display_name']}."
        await bot.send(chat, text, topic)
        return
    await bot.send(
        chat,
        "What is your timezone? Send a name such as Asia/Kolkata or UTC.\n"
        f"Send /skip to use {current['timezone']}.",
        topic,
    )


async def handle(bot, message, owner, channel, chat, topic, callback=None):
    """Return true when enrollment consumes an update before normal routing."""
    text = message.get("text", "").strip()
    action = text.partition(" ")[0].split("@")[0]
    user_id = (callback["from"] if callback else message["from"])["id"]
    row = bot.db.one("SELECT * FROM telegram_enrollments WHERE user_id=?", (user_id,))

    # 1. Validate the code before reserving a slot or running any account command.
    fingerprint = code_fingerprint(bot.settings)
    if message.get("_theos_access_attempt") and not callback:
        try:
            await bot.api("deleteMessage", {"chat_id": chat, "message_id": message["message_id"]})
        except Exception:
            # Authorization must not depend on permission to delete Telegram messages.
            pass
    if not has_access(bot.settings, bot.db, f"telegram:{user_id}"):
        supplied = message.get("_theos_access_fingerprint", "")
        if (
            channel != "telegram-private"
            or callback
            or action != "/start"
            or not fingerprint
            or not hmac.compare_digest(supplied, fingerprint)
        ):
            if callback:
                await bot.api(
                    "answerCallbackQuery",
                    {"callback_query_id": callback["id"], "text": "Access required"},
                )
            await bot.send(
                chat, "Send /start followed by your access code in a private chat.", topic
            )
            return True
        row = enroll(bot, message["from"])
        if row is None:
            await bot.send(chat, "Registration is full. Please try again later.", topic)
            return True
        bot.db.execute(
            "INSERT INTO telegram_access VALUES (?,?,?) ON CONFLICT(owner) DO UPDATE SET "
            "code_fingerprint=excluded.code_fingerprint,granted=excluded.granted",
            (owner, fingerprint, time.time()),
        )

    # 2. Enrollment always belongs to the sender's private identity, never a group.
    if channel != "telegram-private":
        if not row or row["state"] != "ready" or action == "/start":
            if callback:
                await bot.api(
                    "answerCallbackQuery",
                    {
                        "callback_query_id": callback["id"],
                        "text": "Complete /start in a private chat.",
                    },
                )
            await bot.send(chat, "Send /start in a private chat with me to complete setup.", topic)
            return True
        return False

    # 3. Only /start can claim a slot. Pending setup counts toward the same cap.
    if not row:
        if action != "/start" or callback:
            if callback:
                await bot.api(
                    "answerCallbackQuery",
                    {"callback_query_id": callback["id"], "text": "Send /start to register first."},
                )
            await bot.send(chat, "Send /start to register and complete setup.", topic)
            return True
        row = enroll(bot, message["from"])
        if row is None:
            await bot.send(
                chat,
                f"Registration is full. The current limit is {bot.settings.telegram_max_users} users. Please try again later.",
                topic,
            )
            return True
        await bot.send(
            chat,
            f"I am {bot.settings.name}, your personal assistant.\n"
            "Your place is reserved.\n"
            "Let us set your preferred name and timezone.",
            topic,
        )

    # 4. Validate and commit preferences before allowing any model or media work.
    if row["state"] == "ready":
        return False
    if callback:
        await bot.api(
            "answerCallbackQuery",
            {"callback_query_id": callback["id"], "text": "Complete setup first."},
        )
    elif text and (not text.startswith("/") or action == "/skip"):
        current = preferences(bot.db, owner, bot.settings.timezone)
        if row["state"] == "name":
            name = current.get("display_name", "") if action == "/skip" else text
            name = " ".join(name.split())
            if not 1 <= len(name) <= 200:
                await bot.send(chat, "Send a name from 1 to 200 characters.", topic)
            else:
                current["display_name"] = name
                with bot.db.transaction():
                    bot.db.put_record(owner, "preferences", "settings", current)
                    bot.db.execute(
                        "UPDATE telegram_enrollments SET state='timezone' WHERE user_id=?",
                        (user_id,),
                    )
                await bot.send(chat, f"I will call you {name}.", topic)
            await prompt(bot, owner, chat, topic)
            return True
        timezone = current["timezone"] if action == "/skip" else text
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            await bot.send(
                chat, "That timezone is not valid. Use a name such as Asia/Kolkata or UTC.", topic
            )
        else:
            current["timezone"] = timezone
            with bot.db.transaction():
                bot.db.put_record(owner, "preferences", "settings", current)
                bot.db.execute(
                    "UPDATE telegram_enrollments SET state='ready' WHERE user_id=?", (user_id,)
                )
            await bot.send(
                chat,
                f"Setup complete. Timezone: {timezone}.\n"
                "Send a message, photo, document, or voice note. Send /help for commands.\n"
                "You can ask me to change your name or timezone later.",
                topic,
            )
            if bot.settings.web_url:
                await send_link(bot, owner, chat, topic)
            return True
    await prompt(bot, owner, chat, topic)
    return True
