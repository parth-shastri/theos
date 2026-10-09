"""Telegram polling, durable updates, media, commands, and approval buttons."""

import asyncio
import json
import logging
import time

import httpx
from cryptography.fernet import Fernet

from theos.services.errors import ServiceError
from theos.services.zepto.auth import prepare_telegram_update as prepare_zepto_update
from theos.storage.telegram_access import prepare_update as prepare_access_update

from . import client, commands, media, onboarding, rendering

logger = logging.getLogger("theos")


def prepare_update(settings, update):
    """Redact one-time account credentials before the durable Telegram inbox."""
    return prepare_zepto_update(settings, prepare_access_update(settings, update))


class Telegram:
    """Keep transport access checks outside model-controlled tool arguments."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.settings = runtime.settings
        self.db = runtime.db
        self.http = runtime.http
        self.base = "https://api.telegram.org/bot" + self.settings.telegram_token.get_secret_value()
        self.stopping = asyncio.Event()
        self.tasks = set()
        self.chat_locks = {}

    async def api(self, method, payload=None, files=None):
        """Use the Telegram client workflow."""
        return await client.api(self, method, payload, files)

    async def send(self, chat, text, topic=None, markup=None):
        """Use the Telegram client workflow."""
        return await client.send(self, chat, text, topic, markup)

    def identity(self, message, sender=None):
        """Authenticate the sender and derive an isolated owner identity."""
        sender = sender or message.get("from", {})
        user_id = sender.get("id")
        chat = message.get("chat", {})
        chat_id, kind = chat.get("id"), chat.get("type")
        if type(user_id) is not int or user_id <= 0 or sender.get("is_bot"):
            raise PermissionError("This Telegram sender is not a user.")
        if self.settings.telegram_users and user_id not in self.settings.telegram_users:
            raise PermissionError("This Telegram user is not allowed.")
        if kind == "private":
            if chat_id != user_id:
                raise PermissionError("The private chat identity does not match its sender.")
            owner, channel = f"telegram:{user_id}", "telegram-private"
        elif kind in {"group", "supergroup"} and chat_id in self.settings.telegram_chats:
            # Group conversations cannot access the sender's private records or accounts.
            owner, channel = (
                f"telegram-group:{chat_id}:{message.get('message_thread_id', 0)}:{user_id}",
                "telegram-group",
            )
        else:
            raise PermissionError("This Telegram chat is not allowed.")
        topic = message.get("message_thread_id", 0)
        return owner, channel, f"{chat_id}:{topic}", chat_id, topic or None

    def session(self, owner, channel, address):
        """Find or create the conversation for this owner and chat address."""
        row = self.db.one(
            "SELECT * FROM sessions WHERE owner=? AND channel=? AND address=?",
            (owner, channel, address),
        )
        return row or self.db.create_session(
            owner,
            self.settings.model,
            self.settings.reasoning,
            channel,
            address,
            "Telegram conversation",
        )

    async def download(self, file_id, name, media_type, owner):
        """Use the Telegram media workflow."""
        return await media.download(self, file_id, name, media_type, owner)

    async def media(self, message, owner):
        """Use the Telegram media workflow."""
        return await media.media(self, message, owner)

    async def deliver_file(self, owner, chat, topic, file_id):
        """Use the Telegram media workflow."""
        return await media.deliver_file(self, owner, chat, topic, file_id)

    async def render(self, turn, chat, topic):
        """Use the Telegram rendering workflow."""
        return await rendering.render(self, turn, chat, topic)

    async def command(self, session, command, argument, chat, topic):
        """Use the Telegram commands workflow."""
        return await commands.command(self, session, command, argument, chat, topic)

    async def handle(self, updates):
        """Route an authenticated update group to a command, approval, or turn."""
        updates = [prepare_update(self.settings, update) for update in updates]
        first = updates[0]
        callback = first.get("callback_query")
        message = (callback or {}).get("message") or first.get("message")
        if not message:
            return
        sensitive_return = "_theos_zepto_return" in message or message.get(
            "_theos_zepto_return_invalid"
        )
        if sensitive_return and not callback:
            try:
                await self.api(
                    "deleteMessage",
                    {"chat_id": message["chat"]["id"], "message_id": message["message_id"]},
                )
            except Exception:
                # Inbox redaction protects the code when Telegram cannot delete the message.
                pass
        owner, channel, address, chat, topic = self.identity(
            message, callback.get("from") if callback else None
        )
        async with self.chat_locks.setdefault((owner, address), asyncio.Lock()):
            if await onboarding.handle(self, message, owner, channel, chat, topic, callback):
                return
            if sensitive_return:
                if callback or channel != "telegram-private":
                    await self.send(chat, "Finish Zepto setup in a private Telegram chat.", topic)
                    return
                if message.get("_theos_zepto_return_invalid"):
                    await self.send(
                        chat,
                        "The Zepto return URL is too long or encryption is unavailable. Start again with /connect_zepto.",
                        topic,
                    )
                    return
                key = self.settings.token_encryption_key.get_secret_value()
                try:
                    return_url = (
                        Fernet(key.encode())
                        .decrypt(message["_theos_zepto_return"].encode())
                        .decode()
                    )
                    await self.runtime.zepto.finish_from_telegram(owner, return_url)
                except Exception as error:
                    if isinstance(error, (ValueError, ServiceError, PermissionError)):
                        await self.send(chat, str(error), topic)
                    else:
                        logger.warning(
                            "zepto_return_failed",
                            extra={"error_type": type(error).__name__},
                        )
                        await self.send(
                            chat,
                            "The Zepto return link could not be accepted. Start again with /connect_zepto.",
                            topic,
                        )
                else:
                    await self.send(
                        chat,
                        "The Zepto return was accepted. I will confirm the connection here.",
                        topic,
                    )
                return
            session = self.session(owner, channel, address)
            if callback:
                data = callback.get("data", "")
                if not data.startswith(("a:", "d:")):
                    raise ValueError("Unknown approval response.")
                turn = self.runtime.start(
                    owner, session["id"], approval=(data[2:], data.startswith("a:"))
                )
                await self.api(
                    "answerCallbackQuery",
                    {"callback_query_id": callback["id"], "text": "Decision saved."},
                )
                await self.render(turn, chat, topic)
                return
            text = message.get("text", "")
            if text.startswith("/"):
                command, _, argument = text.partition(" ")
                await self.command(session, command.split("@")[0], argument.strip(), chat, topic)
                return
            texts, files = [], []
            for update in updates:
                item = update["message"]
                if self.identity(item)[:3] != (owner, channel, address):
                    raise PermissionError("An album contains messages from different identities.")
                attached, transcript = await self.media(item, owner)
                files.extend(attached)
                texts.append(item.get("text") or item.get("caption") or transcript)
            turn = self.runtime.start(
                owner,
                session["id"],
                "\n".join(t for t in texts if t) or "Please examine the attached files.",
                files,
            )
            await self.render(turn, chat, topic)

    async def process(self, updates):
        """Record the outcome of one accepted update group."""
        ids = [u["update_id"] for u in updates]
        for update_id in ids:
            self.db.execute("UPDATE telegram_updates SET status='running' WHERE id=?", (update_id,))
        status = "completed"
        try:
            await self.handle(updates)
        except asyncio.CancelledError:
            # Shutdown can interrupt a reply after an external write succeeds.
            status = "uncertain"
            raise
        except PermissionError:
            status = "denied"
        except Exception as error:
            status = "uncertain"
            logger.error("telegram_update_failed", extra={"error_type": type(error).__name__})
            message = updates[0].get("message")
            if message:
                try:
                    _, _, _, chat, topic = self.identity(message)
                    await self.send(
                        chat,
                        "This request failed. Check the integration settings. Review external actions before you repeat the request.",
                        topic,
                    )
                except (PermissionError, ServiceError):
                    pass
        finally:
            for update_id in ids:
                update = next((item for item in updates if item["update_id"] == update_id), None)
                if update:
                    message = update.get("message", {})
                    if "_theos_zepto_return" in message or message.get(
                        "_theos_zepto_return_invalid"
                    ):
                        message.pop("_theos_zepto_return", None)
                        message.pop("_theos_zepto_return_invalid", None)
                        message["text"] = "/zepto_finish"
                        self.db.execute(
                            "UPDATE telegram_updates SET payload=? WHERE id=?",
                            (json.dumps(update), update_id),
                        )
                self.db.execute(
                    "UPDATE telegram_updates SET status=? WHERE id=?", (status, update_id)
                )

    async def receive_updates(self):
        """Poll from the last offset committed with the inbox records."""
        saved = self.db.one("SELECT value FROM application_state WHERE key='telegram_offset'")
        offset = int(saved["value"]) if saved else 0
        return await self.api(
            "getUpdates",
            {"offset": offset, "timeout": 1, "allowed_updates": ["message", "callback_query"]},
        )

    def save_updates(self, updates):
        """Commit the inbox and offset together before the next poll."""
        # A crash must not leave an acknowledged update outside the durable inbox.
        with self.db.transaction():
            for update in updates:
                self.db.execute(
                    "INSERT OR IGNORE INTO telegram_updates(id,payload,received) VALUES (?,?,?)",
                    (
                        update["update_id"],
                        json.dumps(prepare_update(self.settings, update)),
                        time.time(),
                    ),
                )
            if updates:
                next_offset = max(update["update_id"] for update in updates) + 1
                self.db.execute(
                    "INSERT OR REPLACE INTO application_state VALUES ('telegram_offset',?)",
                    (str(next_offset),),
                )

    def pending_groups(self):
        """Group pending album parts without including uncertain updates."""
        pending = self.db.rows(
            "SELECT payload,received FROM telegram_updates "
            "WHERE status='pending' ORDER BY id LIMIT 100"
        )
        groups = {}
        for row in pending:
            update = json.loads(row["payload"])
            message = update.get("message", {})
            key = (
                message.get("chat", {}).get("id"),
                message.get("media_group_id") or str(update["update_id"]),
            )
            groups.setdefault(key, []).append((update, row["received"]))
        return groups.values()

    def dispatch_updates(self):
        """Reserve pending work before its task can yield control."""
        for entries in self.pending_groups():
            updates = [entry[0] for entry in entries]
            is_album = updates[0].get("message", {}).get("media_group_id")
            last_received = max(entry[1] for entry in entries)
            # Telegram sends album parts separately. Wait for a short quiet interval.
            if is_album and time.time() - last_received < 1.5:
                continue
            if len(self.tasks) >= self.settings.max_concurrent_turns:
                break
            # Claim before scheduling so the next poll cannot start the same update twice.
            for update in updates:
                self.db.execute(
                    "UPDATE telegram_updates SET status='running' WHERE id=?",
                    (update["update_id"],),
                )
            task = asyncio.create_task(self.process(updates))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def run(self):
        """Poll, persist, and dispatch updates until shutdown."""
        while not self.stopping.is_set():
            try:
                # 1. Read from the saved offset so a restart can recover accepted messages.
                updates = await self.receive_updates()
                # 2. Save before acknowledgment. The next poll acknowledges this offset.
                self.save_updates(updates)
                # 3. Start bounded work from the inbox, including messages saved before restart.
                self.dispatch_updates()
            except (ServiceError, httpx.HTTPError):
                # Delay connection retries without repeating an uncertain tool or reply.
                await asyncio.sleep(2)

    async def close(self):
        """Stop polling and await cancellation of active handlers."""
        self.stopping.set()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
