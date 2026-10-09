"""Telegram downloads, attachments, voice input, and file delivery."""

import mimetypes
from pathlib import Path


async def download(bot, file_id, name, media_type, owner):
    """Download a bounded attachment into the private file catalog."""
    info = await bot.api("getFile", {"file_id": file_id})
    if info.get("file_size", 0) > bot.settings.max_upload_bytes:
        raise ValueError("The Telegram file exceeds the upload limit.")
    url = (
        "https://api.telegram.org/file/bot"
        + bot.settings.telegram_token.get_secret_value()
        + "/"
        + info["file_path"]
    )
    data = bytearray()
    async with bot.http.stream("GET", url) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > bot.settings.max_upload_bytes:
                raise ValueError("The Telegram file exceeds the upload limit.")
    return bot.runtime.files.save(owner, name, media_type, bytes(data))


async def media(bot, message, owner):
    """Read an attachment or transcribe an incoming voice note."""
    if message.get("photo"):
        photo = message["photo"][-1]
        row = await bot.download(photo["file_id"], "photo.jpg", "image/jpeg", owner)
    else:
        item = message.get("document") or message.get("voice") or message.get("audio")
        if not item:
            return [], ""
        name = item.get("file_name", "voice.ogg")
        row = await bot.download(
            item["file_id"],
            name,
            item.get("mime_type") or mimetypes.guess_type(name)[0] or "application/octet-stream",
            owner,
        )
    if message.get("voice"):
        return [], await bot.runtime.files.transcribe(owner, row["id"])
    return [row["id"]], ""


async def deliver_file(bot, owner, chat, topic, file_id):
    """Send an owned catalog file to the selected chat and topic."""
    row = bot.runtime.files.get(owner, file_id)
    payload = {"chat_id": str(chat)}
    if topic:
        payload["message_thread_id"] = str(topic)
    audio = row["media_type"].startswith("audio/")
    field = "audio" if audio else "document"
    return await bot.api(
        "sendAudio" if audio else "sendDocument",
        payload,
        files={field: (row["name"], Path(row["path"]).read_bytes(), row["media_type"])},
    )
