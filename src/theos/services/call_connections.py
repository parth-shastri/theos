"""Verify each owner's Telegram recipient before enabling calls."""

import time
from uuid import uuid4

import httpx

from theos.storage.account_access import account_access

from .errors import ServiceError


class CallConnections:
    def __init__(self, calls):
        self.calls = calls
        self.db = calls.db

    @property
    def configured(self):
        return self.calls.provider == "telegram" and self.calls.available

    def row(self, owner):
        return self.db.one("SELECT * FROM call_connections WHERE owner=?", (owner,))

    def recipient(self, owner, *, testing=False, purpose=None):
        row = self.row(owner)
        if row:
            if row["state"] != "ready" and not (testing and row["state"] == "linked"):
                return None
            if purpose in {"reminders", "approvals"} and not row[purpose]:
                return None
            return row["recipient"]
        return self.calls.config.recipients.get(owner)

    def default_phone(self, owner):
        if not self.configured:
            return False
        row = self.row(owner)
        return bool(row and row["state"] == "ready" and row["reminders"])

    def status(self, owner):
        if not self.configured:
            return {"configured": False}
        row = self.row(owner)
        if not row:
            mapped = bool(self.calls.config.recipients.get(owner))
            return {
                "configured": True,
                "status": "ready" if mapped else "disconnected",
                "reminders": False,
                "approvals": mapped,
            }
        state = row["state"]
        if state == "waiting" and row["updated"] + 600 <= time.time():
            state = "expired"
        result = {
            "configured": True,
            "status": state,
            "reminders": bool(row["reminders"]),
            "approvals": bool(row["approvals"]),
        }
        if row["test_call_id"]:
            job = self.db.one("SELECT status FROM phone_calls WHERE id=?", (row["test_call_id"],))
            result["test_status"] = job["status"] if job else "skipped"
        return result

    def authorize(self, owner):
        if not self.configured or not account_access(self.calls.settings, self.db, owner):
            raise PermissionError("Telegram calls are unavailable for this account.")

    async def gateway(self, method, path, **kwargs):
        try:
            response = await self.calls.http.request(
                method,
                self.calls.config.url.rstrip("/") + path,
                headers={"Authorization": "Bearer " + self.calls.config.key.get_secret_value()},
                timeout=5,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ServiceError("Telegram call setup is unavailable. Try again shortly.") from error

    async def start(self, owner):
        self.authorize(owner)
        if self.recipient(owner):
            raise ValueError("Telegram calls are already connected.")
        old = self.row(owner)
        id = uuid4().hex
        expected = int(owner.removeprefix("telegram:")) if owner.startswith("telegram:") else None
        self.db.execute(
            "INSERT INTO call_connections(owner,connection_id,state,updated) VALUES (?,?,'waiting',?) "
            "ON CONFLICT(owner) DO UPDATE SET connection_id=excluded.connection_id,recipient=NULL,"
            "state='waiting',reminders=0,approvals=0,test_call_id=NULL,updated=excluded.updated",
            (owner, id, time.time()),
        )
        if old and old["connection_id"]:
            await self.gateway("DELETE", "/v1/connections/" + old["connection_id"])
        result = await self.gateway(
            "POST", "/v1/connections/" + id, json={"expected_recipient": expected}
        )
        current = self.row(owner)
        if current["connection_id"] != id or current["state"] != "waiting":
            raise ValueError("Call setup was cancelled. Connect again when you are ready.")
        return {
            **self.status(owner),
            **{key: result[key] for key in ("url", "expires") if key in result},
        }

    async def refresh(self, owner):
        if not self.configured:
            return self.status(owner)
        row = self.row(owner)
        if row and row["state"] == "waiting" and row["updated"] + 600 > time.time():
            result = await self.gateway("GET", "/v1/connections/" + row["connection_id"])
            if result.get("status") == "verified":
                recipient = result.get("recipient")
                if type(recipient) is not int or recipient <= 0:
                    raise ServiceError("The Telegram account could not be verified.")
                if owner.startswith("telegram:") and owner != f"telegram:{recipient}":
                    raise ServiceError("Use your own Telegram account to connect calls.")
                # Compare the ID again after the request so a cancelled setup stays cancelled.
                self.db.execute(
                    "UPDATE call_connections SET recipient=?,state='linked',updated=? "
                    "WHERE owner=? AND connection_id=? AND state='waiting'",
                    (recipient, time.time(), owner, row["connection_id"]),
                )
            elif result.get("status") == "waiting":
                return {**self.status(owner), "url": result["url"], "expires": result["expires"]}
        status = self.status(owner)
        if row and row["test_call_id"] and status.get("status") == "linked":
            job = self.db.one("SELECT status FROM phone_calls WHERE id=?", (row["test_call_id"],))
            if job and job["status"] == "accepted":
                result = await self.gateway("GET", "/v1/calls/" + row["test_call_id"])
                status["test_status"] = result["status"]
        return status

    def test(self, owner, channel):
        self.authorize(owner)
        row = self.row(owner)
        if not row or row["state"] != "linked":
            raise ValueError("Connect your Telegram account before the test call.")
        if row["test_call_id"]:
            raise ValueError("Confirm the previous test or choose Try test again first.")
        with self.db.transaction():
            address = (
                owner.removeprefix("telegram:") + ":0" if channel == "telegram-private" else ""
            )
            session = self.db.one(
                "SELECT id FROM sessions WHERE owner=? AND channel=? AND address=? ORDER BY updated DESC LIMIT 1",
                (owner, channel, address),
            ) or self.db.create_session(
                owner,
                self.calls.settings.model,
                self.calls.settings.reasoning,
                channel,
                address=address,
                title="Telegram call setup",
            )
            id = self.calls.queue(
                owner,
                session["id"],
                "Your Telegram calls are ready. Return to Theos and confirm that you heard this message.",
            )
            self.db.execute("UPDATE call_connections SET test_call_id=? WHERE owner=?", (id, owner))
        return self.status(owner)

    def confirm(self, owner, reminders, approvals):
        self.authorize(owner)
        row = self.row(owner)
        if not row or row["state"] != "linked" or not row["test_call_id"]:
            raise ValueError("Complete a test call before enabling calls.")
        job = self.db.one("SELECT status FROM phone_calls WHERE id=?", (row["test_call_id"],))
        if not job or job["status"] not in {"accepted", "uncertain"}:
            raise ValueError("Wait for the test call before confirming the audio.")
        self.db.execute(
            "UPDATE call_connections SET state='ready',reminders=?,approvals=?,updated=? WHERE owner=?",
            (reminders, approvals, time.time(), owner),
        )
        return self.status(owner)

    def retry_test(self, owner):
        self.authorize(owner)
        row = self.row(owner)
        if not row or row["state"] != "linked" or not row["test_call_id"]:
            raise ValueError("No test call is waiting for another attempt.")
        job = self.db.one("SELECT status FROM phone_calls WHERE id=?", (row["test_call_id"],))
        if job and job["status"] in {"pending", "sending"}:
            raise ValueError("Wait for the current test call to finish.")
        self.db.execute("UPDATE call_connections SET test_call_id=NULL WHERE owner=?", (owner,))
        return self.status(owner)

    def preferences(self, owner, reminders, approvals):
        self.authorize(owner)
        recipient = self.recipient(owner)
        if not recipient:
            raise ValueError("Connect and test Telegram calls before changing call preferences.")
        self.db.execute(
            "INSERT INTO call_connections(owner,recipient,state,reminders,approvals,updated) "
            "VALUES (?,?,'ready',?,?,?) ON CONFLICT(owner) DO UPDATE SET "
            "reminders=excluded.reminders,approvals=excluded.approvals,updated=excluded.updated",
            (owner, recipient, reminders, approvals, time.time()),
        )
        return self.status(owner)

    async def disconnect(self, owner):
        self.authorize(owner)
        row = self.row(owner)
        self.db.execute(
            "INSERT INTO call_connections(owner,state,updated) VALUES (?,'disabled',?) "
            "ON CONFLICT(owner) DO UPDATE SET state='disabled',recipient=NULL,reminders=0,approvals=0",
            (owner, time.time()),
        )
        if row and row["connection_id"]:
            await self.gateway("DELETE", "/v1/connections/" + row["connection_id"])
        return self.status(owner)
