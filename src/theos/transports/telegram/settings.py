"""Editable Telegram settings, scoped to the account or current conversation."""

import re
import time

from theos.runtime.model_catalog import model_choices, reasoning_choices
from theos.services import conversation_settings, journeys
from theos.services.preferences.tools import preferences

from . import menus


async def show(bot, owner, chat, topic, section="menu", notice=""):
    private = owner.startswith("telegram:")
    session = bot.session(
        owner, "telegram-private" if private else "telegram-group", f"{chat}:{topic or 0}"
    )
    profile = preferences(bot.db, owner, bot.settings.timezone)
    rows = []
    if section == "menu":
        text = "⚙️ Settings\n\n"
        if private:
            text += f"Your account\nName: {profile.get('display_name') or 'Not set'}\nTimezone: {profile.get('timezone', bot.settings.timezone)}\n\n"
            rows.append(
                [
                    {"text": "👤 Profile", "callback_data": "settings:display_name"},
                    {"text": "🌐 Timezone", "callback_data": "settings:timezone"},
                ]
            )
        text += f"This conversation\nModel: {session['model']}\nReasoning: {session['reasoning']}"
        rows += [
            [
                {"text": "🧠 Model", "callback_data": "settings:model"},
                {"text": "💭 Reasoning", "callback_data": "settings:reasoning"},
            ],
        ]
        if private:
            rows.append([{"text": "🔗 Accounts", "callback_data": "connect:menu"}])
        if private and bot.runtime.phone_calls.connections.configured:
            rows.append([{"text": "📞 Calls", "callback_data": "calls:status"}])
    elif section in {"model", "reasoning"}:
        values = (
            model_choices(bot.settings)
            if section == "model"
            else reasoning_choices(bot.settings.provider, session["model"])
        )
        text = f"{'🧠 Model' if section == 'model' else '💭 Reasoning effort'}\nApplies to this conversation. Choose a value to save it."
        rows = [
            [
                {
                    "text": ("✅ " if value == session[section] else "") + value,
                    "callback_data": f"settings:set:{section}:{value}",
                }
            ]
            for value in values
        ]
    elif section in {"display_name", "timezone"}:
        label = "preferred name" if section == "display_name" else "timezone or city"
        text = f"{'👤 Profile' if section == 'display_name' else '🌐 Timezone'}\nCurrent: {profile.get(section) or 'Not set'}\n\nSend your {label}. I will ask you to confirm before saving."
        bot.db.put_record(owner, "telegram_settings", "input", {"field": section})
    elif section == "confirm":
        draft = journeys.record(bot.db, owner, "telegram_settings", "input")
        text = f"Save {draft.get('candidate', '')} as your {'name' if draft.get('field') == 'display_name' else 'timezone'}?\nApplies to your account in Telegram and the browser."
        rows = [
            [
                {"text": "✅ Save", "callback_data": "settings:save"},
                {"text": "✏️ Change", "callback_data": "settings:" + draft["field"]},
            ]
        ]
    else:
        raise ValueError("Open /settings to choose a setting.")
    if notice:
        text = notice + "\n\n" + text
    await menus.show(
        bot, owner, chat, topic, text, {"inline_keyboard": rows}, "settings:" + section
    )


async def handle(bot, message, owner, channel, chat, topic, callback):
    data = (callback or {}).get("data", "")
    text = message.get("text", "").strip()
    command, _, argument = text.partition(" ")
    command = command.split("@")[0]
    direct = not callback and command in {"/settings", "/model", "/reasoning", "/thinking"}
    draft = journeys.record(bot.db, owner, "telegram_settings", "input")
    active = journeys.record(bot.db, owner, "telegram_menu", "active")
    entering = (
        not callback
        and not text.startswith("/")
        and draft.get("field")
        and active.get("stack", [""])[-1] in {"settings:display_name", "settings:timezone"}
        and not active.get("consumed")
        and active.get("expires", 0) > time.time()
    )
    if not direct and not data.startswith("settings:") and not entering:
        return False
    personal = entering or data in {
        "settings:display_name",
        "settings:timezone",
        "settings:confirm",
        "settings:save",
    }
    if channel != "telegram-private" and personal:
        if callback:
            await bot.api(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback["id"],
                    "text": "Use your private chat for settings.",
                },
            )
        else:
            await bot.send(chat, "Open /settings in your private Telegram chat.", topic)
        return True
    if callback:
        await bot.api("answerCallbackQuery", {"callback_query_id": callback["id"], "text": ""})
    try:
        notice = ""
        if entering:
            if (
                re.match(r"(?i)^(help|can you|please|remind|plan|find|search)\b", text)
                or "?" in text
            ):
                await menus.finish(bot, owner, chat)
                return False
            menus.interaction.set({"owner": owner, **active})
            field = draft["field"]
            if field == "timezone":
                choices = journeys.timezone_choices(text)
                if len(choices) != 1:
                    raise ValueError(
                        "Send an exact timezone such as Asia/Kolkata, or a city with one timezone such as London."
                    )
                text = choices[0]
            draft["candidate"] = journeys.validate_profile(field, text)
            bot.db.put_record(owner, "telegram_settings", "input", draft)
            section = "confirm"
        elif direct:
            section = {"/settings": "menu", "/model": "model"}.get(command, "reasoning")
            if argument and section != "menu":
                session = bot.session(owner, channel, f"{chat}:{topic or 0}")
                conversation_settings.save(bot.runtime, owner, session["id"], **{section: argument})
                notice = "✅ Saved for this conversation."
        else:
            section = data.removeprefix("settings:")
            if section.startswith("set:"):
                _, field, value = section.split(":", 2)
                if field not in {"model", "reasoning"}:
                    raise ValueError("Choose a supported setting.")
                session = bot.session(owner, channel, f"{chat}:{topic or 0}")
                conversation_settings.save(bot.runtime, owner, session["id"], **{field: value})
                notice, section = "✅ Saved for this conversation.", field
            elif section == "save":
                field = draft.get("field")
                value = journeys.validate_profile(field, draft.get("candidate", ""))
                current = preferences(bot.db, owner, bot.settings.timezone)
                current[field] = value
                bot.db.put_record(owner, "preferences", "settings", current)
                section, notice = "menu", "✅ Saved for your account."
        await show(bot, owner, chat, topic, section, notice)
    except ValueError as error:
        await show(bot, owner, chat, topic, "menu", str(error))
    return True
