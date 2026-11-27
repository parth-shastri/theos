"""Gate Telegram access and collect the minimum profile before normal conversations."""

import hmac
import time

from theos.services import journeys
from theos.services.preferences.tools import preferences
from theos.storage.telegram_access import code_fingerprint, has_access

from . import menus


def enroll(bot, sender):
    """Reserve one user slot and save initial preferences in one transaction."""
    user_id = sender["id"]
    owner = f"telegram:{user_id}"
    # Count and insert without an await so concurrent starts cannot exceed the limit.
    # The transaction also makes the enrollment row and starter preferences appear together.
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
    """Render one shared profile step in the conversation."""
    current = journeys.state(bot.settings, bot.db, owner)
    step = current["step"]
    rows = []
    if step == "ready":
        text = "✅ You are ready. What would you like help with?\nYou can change your name or timezone in /settings."
        if current.get("pending_task"):
            text += "\n\nYour saved request: " + current["pending_task"]
            rows.append([{"text": "▶️ Continue my request", "callback_data": "onboarding:resume"}])
        rows.append([{"text": "⚙️ Settings", "callback_data": "settings:menu"}])
    elif step.startswith("confirm_"):
        text = f"{'👤 Call you' if step == 'confirm_name' else '🌐 Use timezone'} {current['candidate']}?"
        rows.append(
            [
                {"text": "✅ Yes", "callback_data": "onboarding:confirm"},
                {"text": "✏️ Change", "callback_data": "onboarding:change"},
            ]
        )
    elif step == "name":
        text = "👋 What should I call you? Send your preferred name, or start chatting now."
        if current.get("display_name"):
            rows.append(
                [{"text": "✅ Use " + current["display_name"], "callback_data": "onboarding:keep"}]
            )
    else:
        text = "🌐 Which timezone should I use for reminders? Send your city or timezone."
        rows.append([{"text": "✅ Use " + current["timezone"], "callback_data": "onboarding:keep"}])
        rows.extend(
            [{"text": zone, "callback_data": "onboarding:zone:" + zone}]
            for zone in current.get("choices", [])
        )
    if step != "ready":
        rows.append(
            [
                {"text": "⏭ Skip for now", "callback_data": "onboarding:skip"},
                {"text": "💬 Start chatting", "callback_data": "onboarding:finish"},
            ]
        )
    if current.get("notice"):
        text = current["notice"] + "\n\n" + text
    await menus.show(
        bot,
        owner,
        chat,
        topic,
        text,
        {"inline_keyboard": rows},
        "onboarding:profile",
        navigation=False,
    )


async def handle(bot, message, owner, channel, chat, topic, callback=None):
    """Handle setup; return True when it consumes the update before normal routing."""
    text = message.get("text", "").strip()
    action = text.partition(" ")[0].split("@")[0]
    user_id = (callback["from"] if callback else message["from"])["id"]
    row = bot.db.one("SELECT * FROM telegram_enrollments WHERE user_id=?", (user_id,))

    # 1. Check the optional access code before reserving a slot or running an account command.
    # The inbox stores a fingerprint, not the user's plain code, and compare_digest avoids
    # leaking a useful timing difference while comparing the submitted fingerprint.
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

    # 2. Collect profile details only in private chat. A group must not set personal details.
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

    # Only an explicit start claims a slot. Enrollment and access gates remain literal.
    if not row:
        if action != "/start" or callback:
            if callback:
                await bot.api(
                    "answerCallbackQuery",
                    {"callback_query_id": callback["id"], "text": "Send /start first."},
                )
            await bot.send(chat, "Send /start to register and start chatting.", topic)
            return True
        row = enroll(bot, message["from"])
        if row is None:
            await bot.send(chat, "Registration is full. Please try again later.", topic)
            return True

    current = journeys.state(bot.settings, bot.db, owner)
    data = (callback or {}).get("data", "")
    if callback and data.startswith("onboarding:"):
        await bot.api("answerCallbackQuery", {"callback_query_id": callback["id"], "text": ""})
        selected = data.removeprefix("onboarding:")
        if selected == "profile":
            await prompt(bot, owner, chat, topic)
            return True
        if selected == "resume" and current["step"] == "ready":
            task = current.get("pending_task", "")
            if not task:
                await prompt(bot, owner, chat, topic)
                return True
            # Consume the saved request before starting work; a repeated button cannot replay it.
            saved = journeys.record(bot.db, owner, "onboarding", "profile")
            saved["pending_task"] = ""
            bot.db.put_record(owner, "onboarding", "profile", saved)
            await menus.finish(bot, owner, chat)
            session = bot.session(owner, channel, f"{chat}:{topic or 0}")
            await bot.render(bot.runtime.start(owner, session["id"], task), chat, topic)
            return True
        try:
            if selected.startswith("zone:"):
                journeys.update(bot.settings, bot.db, owner, "reply", selected[5:])
            else:
                journeys.update(bot.settings, bot.db, owner, selected)
        except ValueError as error:
            await bot.send(chat, str(error), topic)
        await prompt(bot, owner, chat, topic)
        return True
    if not current["needed"]:
        if action == "/start" and not callback:
            await prompt(bot, owner, chat, topic)
            return True
        return False
    if callback:
        await bot.api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback["id"],
                "text": "Finish or skip the profile question first.",
            },
        )
        return True
    if action == "/start":
        await prompt(bot, owner, chat, topic)
        return True
    if not callback and any(message.get(key) for key in ("photo", "document", "voice", "audio")):
        journeys.update(bot.settings, bot.db, owner, "finish")
        await menus.finish(bot, owner, chat)
        return False
    if text.startswith("/") and action not in {"/skip", "/cancel", "/help"}:
        await bot.send(
            chat,
            "Choose Start chatting to use commands now. You can edit your profile later in /settings.",
            topic,
        )
        await prompt(bot, owner, chat, topic)
        return True
    if text:
        selected = {"/skip": "skip", "/cancel": "finish"}.get(action, "reply")
        try:
            journeys.update(bot.settings, bot.db, owner, selected, text)
        except ValueError as error:
            await bot.send(chat, str(error), topic)
    await prompt(bot, owner, chat, topic)
    return True
