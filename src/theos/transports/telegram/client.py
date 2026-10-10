"""Telegram Bot API requests and plain text messages."""

import httpx

from theos.services.errors import ServiceError

from .formatting import plain_messages


async def api(bot, method, payload=None, files=None):
    """Call the Bot API without exposing credentials in errors."""
    try:
        if files:
            response = await bot.http.post(
                bot.base + "/" + method, data=payload, files=files, timeout=60
            )
        else:
            response = await bot.http.post(bot.base + "/" + method, json=payload or {}, timeout=40)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise ValueError("Telegram returned ok=false")
        return result["result"]
    except (httpx.HTTPError, ValueError, KeyError) as error:
        raise ServiceError("The Telegram request failed. Check the bot connection.") from error


async def send(bot, chat, text, topic=None, markup=None):
    """Send literal text in bounded chunks, with controls after the complete review."""
    parts = plain_messages(text)
    for index, part in enumerate(parts):
        payload = {
            "chat_id": chat,
            "text": part["text"],
            **({"message_thread_id": topic} if topic else {}),
        }
        if markup and index == len(parts) - 1:
            payload["reply_markup"] = markup
        result = await bot.api("sendMessage", payload)
    return result
