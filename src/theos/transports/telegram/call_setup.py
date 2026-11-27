"""Offer private Telegram calling setup without involving the model."""

from theos.services.errors import ServiceError
from theos.services.journeys import record
from theos.storage.account_access import account_access

from . import menus


def offer_button(bot, owner):
    setup = bot.runtime.phone_calls.connections.status(owner)
    if setup.get("configured") and setup["status"] != "ready":
        return [{"text": "📞 Enable Telegram calls", "callback_data": "calls:start"}]
    return []


async def show(bot, owner, chat, topic, status=None, *, choices=False):
    service = bot.runtime.phone_calls.connections
    status = status or await service.refresh(owner)
    if not status.get("configured"):
        await bot.send(chat, "Telegram calls are unavailable on this deployment.", topic)
        return
    state, rows = status["status"], []
    if choices:
        draft = record(
            bot.db, owner, "telegram_calls", "choices", {"reminders": False, "approvals": False}
        )
        text = "📞 When should I call? Choose reminder and approval calls separately, then save. Written notifications remain available."
        for key, label in (("reminders", "Reminder calls"), ("approvals", "Approval calls")):
            rows.append(
                [
                    {
                        "text": ("✅ " if draft[key] else "◻️ ") + label,
                        "callback_data": f"calls:choice:{key}:{int(not draft[key])}",
                    }
                ]
            )
        rows.append([{"text": "✅ Save call preferences", "callback_data": "calls:confirm"}])
    elif state == "waiting":
        text = "Open Theos calling in Telegram and send the prepared verification message. Then return here and check the connection. The link expires in 10 minutes."
        if status.get("url"):
            rows.append([{"text": "📞 Open Theos calling", "url": status["url"]}])
        rows.append([{"text": "🔄 Check connection", "callback_data": "calls:status"}])
        rows.append([{"text": "✖️ Cancel setup", "callback_data": "calls:disconnect"}])
    elif state == "linked":
        if status.get("test_status"):
            text = "Answer the Telegram test call. Did you hear Theos clearly? Next you can choose when to receive calls."
            if status.get("test_status") in {"completed", "uncertain"}:
                rows.append([{"text": "✅ I heard the message", "callback_data": "calls:audio"}])
            rows.append([{"text": "🔄 Check test status", "callback_data": "calls:status"}])
            rows.append([{"text": "🔄 Try test again", "callback_data": "calls:retry"}])
        else:
            text = "Your Telegram account is verified. Send one short test call to check the voice before enabling alerts."
            rows.append([{"text": "📞 Call me for the test", "callback_data": "calls:test"}])
        rows.append([{"text": "✖️ Cancel setup", "callback_data": "calls:disconnect"}])
    elif state == "ready":
        text = (
            "Telegram calls are ready. Calls use Theos's voice. Approval decisions stay in Theos."
        )
        for name, label in (("reminders", "Reminder calls"), ("approvals", "Approval calls")):
            rows.append(
                [
                    {
                        "text": label + (": On" if status[name] else ": Off"),
                        "callback_data": f"calls:set:{name}:{int(not status[name])}",
                    }
                ]
            )
        rows.append([{"text": "✖️ Disconnect calls", "callback_data": "calls:disconnect"}])
    else:
        text = "Connect your Telegram account to receive reminder and approval calls in Theos's voice. Setup is optional."
        if state == "expired":
            text = "The verification link expired. Start again to get a new link."
        rows.append([{"text": "📞 Connect Telegram calls", "callback_data": "calls:start"}])
    await menus.show(
        bot,
        owner,
        chat,
        topic,
        text,
        {"inline_keyboard": rows},
        "calls:preferences" if choices else "calls",
    )


async def handle(bot, message, owner, channel, chat, topic, callback):
    data = (callback or {}).get("data", "")
    command = message.get("text", "").partition(" ")[0].split("@")[0]
    if not data.startswith("calls:") and (callback or command != "/calls"):
        return False
    allowed = channel == "telegram-private" and account_access(bot.settings, bot.db, owner)
    if callback:
        allowed = allowed and callback["from"]["id"] == chat
        await bot.api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback["id"],
                "text": "" if allowed else "Use your private chat to set up calls.",
            },
        )
    if not allowed:
        return True
    service = bot.runtime.phone_calls.connections
    action = data.removeprefix("calls:") if callback else "status"
    try:
        status = None
        if action == "start":
            status = await service.start(owner)
        elif action == "test":
            status = service.test(owner, "telegram-private")
        elif action == "audio":
            current = await service.refresh(owner)
            if current.get("test_status") not in {"completed", "uncertain"}:
                raise ValueError("Finish the test call before confirming the audio.")
            bot.db.put_record(
                owner, "telegram_calls", "choices", {"reminders": False, "approvals": False}
            )
            await show(bot, owner, chat, topic, current, choices=True)
            return True
        elif action.startswith("choice:"):
            _, key, value = action.split(":")
            if key not in {"reminders", "approvals"} or value not in {"0", "1"}:
                raise ValueError("Choose a valid call preference.")
            draft = record(
                bot.db, owner, "telegram_calls", "choices", {"reminders": False, "approvals": False}
            )
            draft[key] = value == "1"
            bot.db.put_record(owner, "telegram_calls", "choices", draft)
            await show(bot, owner, chat, topic, choices=True)
            return True
        elif action == "preferences":
            await show(bot, owner, chat, topic, choices=True)
            return True
        elif action == "confirm":
            draft = record(
                bot.db, owner, "telegram_calls", "choices", {"reminders": False, "approvals": False}
            )
            status = service.confirm(owner, draft["reminders"], draft["approvals"])
        elif action == "retry":
            current = await service.refresh(owner)
            if current.get("test_status") == "accepted":
                raise ValueError("End the current Telegram call before another test.")
            service.retry_test(owner)
            status = service.test(owner, "telegram-private")
        elif action == "disconnect":
            status = await service.disconnect(owner)
        elif action.startswith("set:"):
            _, key, value = action.split(":")
            if key not in {"reminders", "approvals"} or value not in {"0", "1"}:
                raise ValueError("Choose a valid call preference.")
            current = service.status(owner)
            values = {key: current[key] for key in ("reminders", "approvals")}
            values[key] = value == "1"
            status = service.preferences(owner, **values)
        elif action != "status":
            raise ValueError("This call setup button is unavailable. Use /calls.")
        await show(bot, owner, chat, topic, status)
    except (ServiceError, ValueError, PermissionError) as error:
        await show(bot, owner, chat, topic)
        await bot.send(chat, str(error), topic)
    return True
