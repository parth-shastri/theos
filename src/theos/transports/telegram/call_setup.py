"""Offer private Telegram calling setup without involving the model."""

from theos.services.errors import ServiceError
from theos.storage.account_access import account_access


def offer_button(bot, owner):
    setup = bot.runtime.phone_calls.connections.status(owner)
    if setup.get("configured") and setup["status"] != "ready":
        return [{"text": "Enable Telegram calls", "callback_data": "calls:start"}]
    return []


async def show(bot, owner, chat, topic, status=None):
    service = bot.runtime.phone_calls.connections
    status = status or await service.refresh(owner)
    if not status.get("configured"):
        await bot.send(chat, "Telegram calls are unavailable on this deployment.", topic)
        return
    state, rows = status["status"], []
    if state == "waiting":
        text = "Open Theos calling in Telegram and send the prepared verification message. Then return here and check the connection. The link expires in 10 minutes."
        if status.get("url"):
            rows.append([{"text": "Open Theos calling", "url": status["url"]}])
        rows.append([{"text": "Check connection", "callback_data": "calls:status"}])
        rows.append([{"text": "Cancel setup", "callback_data": "calls:disconnect"}])
    elif state == "linked":
        if status.get("test_status"):
            text = "Answer the Telegram test call. Did you hear Theos clearly? Confirming enables reminder and approval calls. You can change these choices afterward."
            rows.append([{"text": "I heard the message", "callback_data": "calls:confirm"}])
            rows.append([{"text": "Check test status", "callback_data": "calls:status"}])
            rows.append([{"text": "Try test again", "callback_data": "calls:retry"}])
        else:
            text = "Your Telegram account is verified. Send one short test call to check the voice before enabling alerts."
            rows.append([{"text": "Call me for the test", "callback_data": "calls:test"}])
        rows.append([{"text": "Cancel setup", "callback_data": "calls:disconnect"}])
    elif state == "ready":
        text = (
            "Telegram calls are ready. Calls use Theos's voice. Approval decisions stay in Theos."
        )
        for name, label in (("reminders", "Reminder calls"), ("approvals", "Approval calls")):
            rows.append(
                [
                    {
                        "text": label + (": On" if status[name] else ": Off"),
                        "callback_data": "calls:" + name,
                    }
                ]
            )
        rows.append([{"text": "Disconnect calls", "callback_data": "calls:disconnect"}])
    else:
        text = "Connect your Telegram account to receive reminder and approval calls in Theos's voice. Setup is optional."
        if state == "expired":
            text = "The verification link expired. Start again to get a new link."
        rows.append([{"text": "Connect Telegram calls", "callback_data": "calls:start"}])
    rows.append([{"text": "Back to accounts", "callback_data": "connect:menu"}])
    await bot.send(chat, text, topic, {"inline_keyboard": rows})


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
        elif action == "confirm":
            status = service.confirm(owner, True, True)
        elif action == "retry":
            current = await service.refresh(owner)
            if current.get("test_status") == "accepted":
                raise ValueError("End the current Telegram call before another test.")
            service.retry_test(owner)
            status = service.test(owner, "telegram-private")
        elif action == "disconnect":
            status = await service.disconnect(owner)
        elif action in {"reminders", "approvals"}:
            current = service.status(owner)
            values = {key: current[key] for key in ("reminders", "approvals")}
            values[action] = not values[action]
            status = service.preferences(owner, **values)
        elif action != "status":
            raise ValueError("This call setup button is unavailable. Use /calls.")
        await show(bot, owner, chat, topic, status)
    except (ServiceError, ValueError, PermissionError) as error:
        await bot.send(chat, str(error), topic)
    return True
