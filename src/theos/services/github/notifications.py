"""Signed GitHub deliveries, owner subscriptions, and durable alert delivery."""

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from uuid import uuid4

import httpx

from theos.services.errors import ServiceError
from theos.storage.account_access import account_access

from .events import EVENTS, attention, positive_id

logger = logging.getLogger("theos")
MAX_BODY = 1024 * 1024


class AccessDenied(Exception):
    """The current account cannot receive the selected repository event."""


class GitHubNotifications:
    def __init__(self, settings, db, http, account):
        self.settings, self.db, self.http, self.account = settings, db, http, account
        self.next_cleanup = 0

    @property
    def available(self):
        return bool(self.settings.github_webhook_secret.get_secret_value())

    def telegram_available(self, owner):
        return bool(
            self.settings.telegram_token.get_secret_value()
            and re.fullmatch(r"telegram:[1-9][0-9]*", owner)
            and account_access(self.settings, self.db, owner)
        )

    def subscription(self, owner):
        return self.db.one("SELECT * FROM github_subscriptions WHERE owner=?", (owner,))

    def status(self, owner):
        row = self.subscription(owner) or {}
        return {
            "available": self.available,
            "enabled": bool(row.get("enabled")) and self.account.connected(owner),
            "telegram": bool(row.get("telegram")),
            "telegram_available": self.telegram_available(owner),
            "items": self.inbox(owner),
        }

    def disable(self, owner):
        self.db.execute(
            "UPDATE github_subscriptions SET enabled=0,revision=revision+1,updated=? WHERE owner=?",
            (time.time(), owner),
        )
        self.db.execute(
            "UPDATE github_notifications SET telegram='blocked' WHERE owner=? AND telegram='pending'",
            (owner,),
        )

    async def api(self, token, path):
        try:
            response = await self.http.get(
                "https://api.github.com" + path,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
                timeout=10,
                follow_redirects=False,
            )
            if response.status_code == 429 or (
                response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0"
            ):
                raise ServiceError("GitHub access checks are temporarily unavailable.")
            if response.status_code in {401, 403, 404}:
                raise AccessDenied
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (httpx.HTTPError, ValueError) as error:
            raise ServiceError("GitHub access checks are temporarily unavailable.") from error

    async def identity(self, owner, repo_id=None):
        self.account.authorize(owner)
        token = await self.account.access_token(owner)
        user = await self.api(token, "/user")
        if (
            not positive_id(user.get("id"))
            or not isinstance(user.get("login"), str)
            or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", user["login"])
        ):
            raise AccessDenied
        if repo_id:
            repo = await self.api(token, f"/repositories/{repo_id}")
            if repo.get("id") != repo_id:
                raise AccessDenied
        # A disconnect or account replacement during the reads invalidates their result.
        if self.account.read(owner).get("access_token") != token:
            raise AccessDenied
        return user

    async def configure(self, owner, enabled, telegram=False):
        self.account.authorize(owner)
        if not enabled:
            self.disable(owner)
            return self.status(owner)
        if not self.available:
            raise ServiceError("GitHub event notifications need operator setup.")
        if telegram and not self.telegram_available(owner):
            raise PermissionError("Use your verified private Telegram account for Telegram alerts.")
        try:
            user = await self.identity(owner)
        except AccessDenied as error:
            raise ServiceError("Reconnect GitHub before enabling event notifications.") from error
        self.db.ensure_user(owner)
        self.db.execute(
            "INSERT INTO github_subscriptions VALUES (?,?,?,?,?,1,?) ON CONFLICT(owner) DO UPDATE SET "
            "github_id=excluded.github_id,login=excluded.login,enabled=1,telegram=excluded.telegram,"
            "revision=github_subscriptions.revision+1,updated=excluded.updated",
            (owner, user["id"], user["login"], 1, int(telegram), time.time()),
        )
        return self.status(owner)

    def receive(self, body, signature, delivery, event):
        """Authenticate exact bytes before parsing or saving any provider content."""
        if not self.available:
            raise ServiceError("GitHub webhooks are not configured.")
        if len(body) > MAX_BODY:
            raise OverflowError
        expected = (
            "sha256="
            + hmac.new(
                self.settings.github_webhook_secret.get_secret_value().encode(),
                body,
                hashlib.sha256,
            ).hexdigest()
        )
        if not isinstance(signature, str) or not hmac.compare_digest(
            expected.encode(), signature.encode()
        ):
            raise PermissionError("Invalid GitHub webhook signature.")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", delivery) or not re.fullmatch(
            r"[a-z_]{1,64}", event
        ):
            raise ValueError("Invalid GitHub delivery headers.")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError, RecursionError) as error:
            raise ValueError("Invalid GitHub webhook payload.") from error
        for field in (
            "repository",
            "issue",
            "pull_request",
            "comment",
            "review",
            "changes",
            "workflow_run",
            "sender",
            "assignee",
            "requested_reviewer",
        ):
            if payload.get(field) is not None and not isinstance(payload[field], dict):
                raise ValueError("Invalid GitHub webhook payload.")
        digest = hashlib.sha256(body).hexdigest()
        old = self.db.one("SELECT digest,event FROM github_deliveries WHERE id=?", (delivery,))
        if old:
            if old["digest"] != digest or old["event"] != event:
                raise ValueError("This GitHub delivery ID has already been used.")
            return {"accepted": True, "duplicate": True}
        pending = event in EVENTS and positive_id((payload.get("repository") or {}).get("id"))
        pending = bool(
            pending and self.db.one("SELECT 1 FROM github_subscriptions WHERE enabled=1")
        )
        if (
            pending
            and self.db.one(
                "SELECT COUNT(*) AS count FROM github_deliveries WHERE status='pending'"
            )["count"]
            >= 1000
        ):
            raise ServiceError("The GitHub event queue is full. Redeliver later.")
        now = time.time()
        encrypted = self.account.cipher.encrypt(body).decode() if pending else None
        self.db.execute(
            "INSERT INTO github_deliveries(id,event,digest,encrypted,created,due,status) VALUES (?,?,?,?,?,?,?)",
            (delivery, event, digest, encrypted, now, now, "pending" if pending else "ignored"),
        )
        return {"accepted": True, "duplicate": False}

    def current(self, row):
        sub = self.subscription(row["owner"])
        return bool(
            sub
            and sub["enabled"]
            and sub["revision"] == row["revision"]
            and sub["github_id"] == row["github_id"]
            and self.account.connected(row["owner"])
        )

    def inbox(self, owner, unread=False):
        return self.db.rows(
            "SELECT id,text,url,created,read,telegram FROM github_notifications WHERE owner=? "
            + ("AND read=0 " if unread else "")
            + "ORDER BY created DESC LIMIT 20",
            (owner,),
        )

    def mark_read(self, owner, notice_id):
        if not self.db.execute(
            "UPDATE github_notifications SET read=1 WHERE owner=? AND id=?", (owner, notice_id)
        ).rowcount:
            raise LookupError("Notification not found.")
        return {"read": True}

    async def process(self, row):
        payload = json.loads(self.account.cipher.decrypt(row["encrypted"].encode()))
        repo_id = payload["repository"]["id"]
        subs = self.db.rows(
            "SELECT * FROM github_subscriptions WHERE enabled=1 AND owner>? AND updated<=? "
            "ORDER BY owner LIMIT 10",
            (row["cursor"], row["created"]),
        )
        if not subs:
            self.db.execute(
                "UPDATE github_deliveries SET status='completed',encrypted=NULL WHERE id=?",
                (row["id"],),
            )
            return
        for sub in subs:
            result = attention(row["event"], payload, sub["github_id"], sub["login"])
            if result and self.account.connected(sub["owner"]):
                try:
                    user = await self.identity(sub["owner"], repo_id)
                    if user["id"] != sub["github_id"]:
                        self.disable(sub["owner"])
                        result = None
                    else:
                        result = attention(row["event"], payload, user["id"], user["login"])
                except (AccessDenied, PermissionError):
                    result = None
            if result and self.current(sub):
                text, url = result
                self.db.execute(
                    "INSERT OR IGNORE INTO github_notifications VALUES (?,?,?,?,?,?,?,?,?,0,?,?)",
                    (
                        uuid4().hex,
                        row["id"],
                        sub["owner"],
                        sub["github_id"],
                        sub["revision"],
                        repo_id,
                        text,
                        url,
                        time.time(),
                        "pending" if sub["telegram"] else "not_requested",
                        time.time(),
                    ),
                )
            self.db.execute(
                "UPDATE github_deliveries SET cursor=? WHERE id=?", (sub["owner"], row["id"])
            )

    async def deliver(self, telegram):
        if telegram is None:
            return
        for row in self.db.rows(
            "SELECT * FROM github_notifications WHERE telegram='pending' AND due<=? ORDER BY created LIMIT 10",
            (time.time(),),
        ):
            if not self.current(row) or not self.telegram_available(row["owner"]):
                self.db.execute(
                    "UPDATE github_notifications SET telegram='blocked' WHERE id=?", (row["id"],)
                )
                continue
            try:
                user = await self.identity(row["owner"], row["repo_id"])
                if user["id"] != row["github_id"] or not self.current(row):
                    raise AccessDenied
            except (AccessDenied, PermissionError):
                self.db.execute(
                    "UPDATE github_notifications SET telegram='blocked' WHERE id=?", (row["id"],)
                )
                continue
            except ServiceError:
                self.db.execute(
                    "UPDATE github_notifications SET due=? WHERE id=?",
                    (time.time() + 60, row["id"]),
                )
                continue
            self.db.execute(
                "UPDATE github_notifications SET telegram='sending' WHERE id=?", (row["id"],)
            )
            try:
                await telegram.send(
                    int(row["owner"].split(":")[1]), f"GitHub: {row['text']}\n{row['url']}"
                )
            except asyncio.CancelledError:
                self.db.execute(
                    "UPDATE github_notifications SET telegram='uncertain' WHERE id=?", (row["id"],)
                )
                raise
            except Exception:
                self.db.execute(
                    "UPDATE github_notifications SET telegram='uncertain' WHERE id=?", (row["id"],)
                )
                logger.warning("github_notification_delivery_uncertain")
            else:
                self.db.execute(
                    "UPDATE github_notifications SET telegram='delivered' WHERE id=?", (row["id"],)
                )

    async def tick(self, telegram=None):
        now = time.time()
        if now >= self.next_cleanup:
            self.db.execute(
                "UPDATE github_deliveries SET status='expired',encrypted=NULL WHERE encrypted IS NOT NULL AND created<?",
                (now - 7 * 86400,),
            )
            self.db.execute(
                "DELETE FROM github_deliveries WHERE id IN (SELECT id FROM github_deliveries WHERE created<? LIMIT 1000)",
                (now - 30 * 86400,),
            )
            self.next_cleanup = now + 3600
        if not self.available:
            return
        for row in self.db.rows(
            "SELECT * FROM github_deliveries WHERE status='pending' AND due<=? ORDER BY created LIMIT 5",
            (now,),
        ):
            try:
                await self.process(row)
            except Exception:
                attempts = row["attempts"] + 1
                self.db.execute(
                    "UPDATE github_deliveries SET attempts=?,due=?,status=? WHERE id=?",
                    (
                        attempts,
                        now + min(3600, 15 * 2 ** min(attempts, 8)),
                        "failed" if attempts >= 8 else "pending",
                        row["id"],
                    ),
                )
                logger.warning("github_event_processing_failed")
        await self.deliver(telegram)
