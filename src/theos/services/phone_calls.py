"""Deliver opted-in reminder and approval calls through one configured provider."""

import asyncio
import hashlib
import logging
import re
import secrets
import time
from urllib.parse import urlsplit
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx

from harness import tool
from theos.services.call_connections import CallConnections
from theos.services.errors import ServiceError
from theos.storage.account_access import account_access

logger = logging.getLogger("theos")

APPROVAL_DELAY = 120
REMINDER_WINDOW = 900
MAX_REMINDER_TEXT = 360
_MEDIA_LIFETIME = 300
_MAX_AUDIO_BYTES = 2 * 1024 * 1024
_DAY = 86400


class PhoneCalls:
    """Use existing private account access and persist every call before dialing."""

    def __init__(self, settings, db, http, voice):
        self.settings = settings
        self.provider = "telegram" if settings.telegram_calls.enabled else "twilio"
        self.config = settings.telegram_calls if self.provider == "telegram" else settings.twilio
        self.db = db
        self.http = http
        self.voice = voice
        self.next_cleanup = 0
        self.connections = CallConnections(self)
        self.conversations = None

    def recipient(self, owner, channel, *, testing=False, purpose=None):
        if not self.available or channel not in {"browser", "telegram-private"}:
            return None
        recipient = (
            self.connections.recipient(owner, testing=testing, purpose=purpose)
            if self.provider == "telegram"
            else self.config.recipients.get(owner)
        )
        if recipient and account_access(self.settings, self.db, owner):
            return recipient if self.provider == "telegram" else recipient.get_secret_value()
        return None

    @property
    def available(self):
        if not self.config.configured or not self.settings.kokoro_url.strip():
            return False
        if self.provider == "twilio":
            return bool(
                self.settings.web_url.startswith("https://")
                and self.settings.frontend_secret
                and urlsplit(self.settings.web_url).hostname
                not in {"localhost", "127.0.0.1", "::1"}
            )
        return True

    def enqueue(self, id, owner, session, kind, source_id, due, expires):
        """Save the call in the same transaction as its reminder or approval."""
        self.db.execute(
            "INSERT OR IGNORE INTO phone_calls(id,owner,session,kind,source_id,due,expires,provider) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (id, owner, session, kind, source_id, due, expires, self.provider),
        )

    def tools(self, owner, session_id, channel):
        """Discover calling only for an enabled provider and a mapped private account."""
        if not self.recipient(owner, channel):
            return []

        @tool
        async def call_user(message: str):
            """Call your configured account now and play a message of up to 360 characters. Use only when the user asks for a call. A queued call does not prove that it was answered."""
            session = self.db.one(
                "SELECT channel FROM sessions WHERE id=? AND owner=?", (session_id, owner)
            )
            if not session or not self.recipient(owner, session["channel"]):
                raise ServiceError("Calls are unavailable for this conversation.")
            text = message.strip()
            if not text or len(text) > MAX_REMINDER_TEXT:
                raise ValueError(f"Supply a call message from 1 to {MAX_REMINDER_TEXT} characters.")
            with self.db.transaction():
                id = self.queue(owner, session_id, text)
            return {"id": id, "status": "queued", "delivery": "phone"}

        return [call_user]

    def queue(self, owner, session_id, text):
        id, now = uuid4().hex, time.time()
        self.db.execute(
            "INSERT INTO notifications(id,owner,session,text,created,delivered) VALUES (?,?,?,?,?,0)",
            (id, owner, session_id, text, now),
        )
        self.enqueue(id, owner, session_id, "request", id, now, now + 120)
        return id

    def _source(self, job):
        if job["kind"] == "request":
            notice = self.db.one(
                "SELECT text FROM notifications WHERE id=? AND owner=? AND session=?",
                (job["source_id"], job["owner"], job["session"]),
            )
            return notice["text"] if notice else None
        if job["kind"] == "approval":
            from theos.runtime.approvals import requires_approval

            approval = self.db.one(
                "SELECT tool FROM approvals WHERE id=? AND session=? AND status='pending' "
                "AND expires>?",
                (job["source_id"], job["session"], time.time()),
            )
            if approval and requires_approval(approval["tool"]):
                return f"A request is waiting for your approval. Open {self.settings.name} to review it."
            return None
        reminder = self.db.one(
            "SELECT n.text FROM notifications n JOIN reminders r ON r.id=? "
            "WHERE n.id=? AND n.owner=r.owner AND n.session=r.session AND r.status!='cancelled'",
            (job["source_id"], job["id"]),
        )
        return reminder["text"].strip() if reminder else None

    def _finish(self, id, status, sid=None):
        if status == "failed":
            self.db.execute(
                "UPDATE phone_calls SET status='failed',audio=NULL,audio_digest=NULL,"
                "audio_expires=NULL WHERE id=?",
                (id,),
            )
        else:
            self.db.execute(
                "UPDATE phone_calls SET status=?,call_sid=? WHERE id=?", (status, sid, id)
            )
        if status in {"failed", "uncertain", "rate_limited"}:
            logger.warning("phone_call_" + status)

    def _available(self, job):
        session = self.db.one(
            "SELECT channel FROM sessions WHERE id=? AND owner=?", (job["session"], job["owner"])
        )
        if session and job["expires"] > time.time() and job["provider"] == self.provider:
            connection = self.connections.row(job["owner"]) if self.provider == "telegram" else None
            testing = bool(connection and connection["test_call_id"] == job["id"])
            purpose = {"reminder": "reminders", "approval": "approvals"}.get(job["kind"])
            return self.recipient(
                job["owner"], session["channel"], testing=testing, purpose=purpose
            )
        return None

    async def _deliver(self, job):
        id = job["id"]
        recipient = self._available(job)
        text = self._source(job) if recipient else None
        if not text:
            return self._finish(id, "skipped")
        count = self.db.one(
            "SELECT count(*) AS count FROM phone_calls WHERE attempted>?", (time.time() - _DAY,)
        )["count"]
        if count >= self.config.daily_limit:
            return self._finish(id, "rate_limited")
        if self.conversations and self.conversations.available:
            return await self.conversations.dispatch(job, recipient, text)
        try:
            async with asyncio.timeout(35):
                audio = await self.voice.synthesize(
                    f"This is {self.settings.name}. {text}", max_bytes=_MAX_AUDIO_BYTES
                )
        except (ServiceError, TimeoutError):
            return self._finish(id, "failed")
        # A decision, cancellation, or access change can arrive during synthesis.
        if self._available(job) != recipient or self._source(job) is None:
            return self._finish(id, "skipped")
        if self.provider == "telegram":
            return await self._telegram(job, recipient, audio)
        token = secrets.token_urlsafe(32)
        now = time.time()
        claimed = self.db.execute(
            "UPDATE phone_calls SET status='sending',attempted=?,audio_digest=?,audio_expires=?,"
            "audio=? WHERE id=? AND status='pending'",
            (now, hashlib.sha256(token.encode()).hexdigest(), now + _MEDIA_LIFETIME, audio, id),
        )
        if not claimed.rowcount:
            return
        response = Element("Response")
        SubElement(
            response, "Play"
        ).text = f"{self.settings.web_url}/api/audio/phone-call/{token}.mp3"
        SubElement(response, "Hangup")
        try:
            result = await self.http.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.config.account_sid}/Calls.json",
                auth=(self.config.api_key_sid, self.config.api_key_secret.get_secret_value()),
                data={
                    "From": self.config.from_number,
                    "To": recipient,
                    "Twiml": tostring(response, encoding="unicode"),
                    "Timeout": "20",
                    "TimeLimit": "90",
                },
                timeout=10,
                follow_redirects=False,
            )
            if 400 <= result.status_code < 500 and result.status_code != 408:
                return self._finish(id, "failed")
            result.raise_for_status()
            sid = result.json()["sid"]
            if not isinstance(sid, str) or not re.fullmatch(r"CA[0-9a-fA-F]{32}", sid):
                raise ValueError("Invalid call SID.")
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            # A timeout or ambiguous reply can follow a successful dial request.
            return self._finish(id, "uncertain")
        return self._finish(id, "accepted", sid)

    async def _telegram(self, job, recipient, audio, *, interactive=False, dialogue_expires=None):
        claimed = self.db.execute(
            "UPDATE phone_calls SET status='sending',attempted=? WHERE id=? AND status='pending'",
            (time.time(), job["id"]),
        )
        if not claimed.rowcount:
            return
        try:
            response = await self.http.post(
                self.config.url.rstrip("/") + "/v1/calls/" + job["id"],
                params={
                    "recipient": recipient,
                    "expires": job["expires"],
                    **({"interactive": "true"} if interactive else {}),
                    **({"dialogue_expires": dialogue_expires} if dialogue_expires else {}),
                },
                content=audio,
                headers={
                    "Authorization": "Bearer " + self.config.key.get_secret_value(),
                    "Content-Type": "audio/mpeg",
                },
                timeout=10,
                follow_redirects=False,
            )
            if 400 <= response.status_code < 500 and response.status_code != 408:
                return self._finish(job["id"], "failed")
            response.raise_for_status()
            body = response.json()
            if body.get("id") != job["id"] or body.get("status") != "accepted":
                raise ValueError("Invalid calling gateway response.")
        except (httpx.HTTPError, AttributeError, TypeError, ValueError):
            return self._finish(job["id"], "uncertain")
        return self._finish(job["id"], "accepted", job["id"])

    async def tick(self, now):
        """Process a small batch without delaying other scheduler work."""
        if now >= self.next_cleanup:
            self.next_cleanup = now + 60
            self.db.execute(
                "UPDATE phone_calls SET audio_digest=NULL,audio_expires=NULL,audio=NULL "
                "WHERE audio_expires<=?",
                (now,),
            )
            self.db.execute(
                "UPDATE phone_calls SET status='skipped' WHERE status='pending' AND expires<=?",
                (now,),
            )
            self.db.execute("DELETE FROM phone_calls WHERE expires<?", (now - 30 * _DAY,))
        if self.available:
            for job in self.db.rows(
                "SELECT id,owner,session,kind,source_id,expires,provider FROM phone_calls "
                "WHERE status='pending' AND due<=? AND expires>? ORDER BY due,id LIMIT 5",
                (now, now),
            ):
                await self._deliver(job)

    def audio(self, token):
        """Return only the bytes authorized by an unexpired random media URL."""
        if (
            self.provider == "twilio"
            and self.available
            and re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
        ):
            row = self.db.one(
                "SELECT audio FROM phone_calls WHERE audio_digest=? AND audio_expires>?",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            )
            if row:
                return row["audio"]
        raise LookupError("Phone audio is unavailable.")
