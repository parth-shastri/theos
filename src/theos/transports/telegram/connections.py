"""Offer optional private account connections without starting model turns."""

from theos.services.account_setup import complete_setup, setup_status
from theos.storage.account_access import account_access

from . import commands


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
        "Gmail helps with email, Zepto with shopping, and Google Health with activity and vitals.\n"
        "All connections are optional. You can add them later.",
        topic,
        {"inline_keyboard": buttons},
    )


async def handle(bot, message, owner, channel, chat, topic, callback):
    if not callback or not callback.get("data", "").startswith("connect:"):
        return False
    if (
        channel != "telegram-private"
        or chat != callback["from"]["id"]
        or not account_access(bot.settings, bot.db, owner)
    ):
        await bot.api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback["id"],
                "text": "Use your private chat after completing setup.",
            },
        )
        return True
    service = callback["data"].partition(":")[2]
    if service == "skip":
        complete_setup(bot.settings, bot.db, owner)
        await bot.api(
            "answerCallbackQuery",
            {"callback_query_id": callback["id"], "text": "You can connect accounts later."},
        )
        await bot.send(
            chat, "You are ready to chat. Send /help whenever you need connection options.", topic
        )
        return True
    available = {
        account["id"]
        for account in setup_status(bot.settings, bot.db, owner, bot.runtime.zepto)["accounts"]
    }
    if service not in available:
        await bot.api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback["id"],
                "text": "This account is connected or unavailable.",
            },
        )
        return True
    await bot.api(
        "answerCallbackQuery", {"callback_query_id": callback["id"], "text": "Preparing sign-in…"}
    )
    await commands.command(
        bot, {"owner": owner, "channel": channel}, "/connect_" + service, "", chat, topic
    )
    return True
