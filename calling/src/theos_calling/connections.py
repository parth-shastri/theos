"""Bind call recipients to expiring messages sent from their own Telegram account."""

import hashlib
import hmac
import re
import time
from urllib.parse import urlencode

from fastapi import HTTPException


class Connections:
    def __init__(self, db, key, caller):
        self.db, self.key, self.caller = db, key.encode(), caller
        db.execute(
            "CREATE TABLE IF NOT EXISTS connections ("
            "id TEXT PRIMARY KEY, expected INTEGER, recipient INTEGER, expires REAL, "
            "state TEXT NOT NULL CHECK(state IN ('waiting','verified','disabled')))"
        )

    def code(self, id):
        return hmac.new(self.key, id.encode(), hashlib.sha256).hexdigest()

    def status(self, id):
        row = self.db.execute("SELECT * FROM connections WHERE id=?", (id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Call setup not found.")
        if row["state"] == "waiting" and row["expires"] <= time.time():
            return {"status": "expired"}
        result = {"status": row["state"]}
        if row["state"] == "verified":
            result["recipient"] = row["recipient"]
        elif row["state"] == "waiting":
            profile = getattr(self.caller, "profile_url", "")
            if not profile.startswith("https://t.me/"):
                raise HTTPException(503, "The calling account has no Telegram contact link.")
            result.update(
                url=profile + "?" + urlencode({"text": f"connect {id} {self.code(id)}"}),
                expires=row["expires"],
            )
        return result

    def start(self, id, expected):
        self.db.execute(
            "DELETE FROM connections WHERE state!='verified' AND expires<?", (time.time(),)
        )
        self.db.execute(
            "INSERT OR IGNORE INTO connections VALUES (?,?,NULL,?,'waiting')",
            (id, expected, time.time() + 600),
        )
        row = self.db.execute("SELECT expected FROM connections WHERE id=?", (id,)).fetchone()
        if row["expected"] != expected:
            raise HTTPException(409, "Call setup is already in use.")
        return self.status(id)

    async def receive(self, recipient, text):
        match = re.fullmatch(r"connect ([a-f0-9]{32}) ([a-f0-9]{64})", text.strip())
        if not match:
            return
        id, code = match.groups()
        row = self.db.execute("SELECT * FROM connections WHERE id=?", (id,)).fetchone()
        if (
            not row
            or row["state"] != "waiting"
            or row["expires"] <= time.time()
            or (row["expected"] is not None and row["expected"] != recipient)
            or not hmac.compare_digest(code, self.code(id))
        ):
            return
        self.db.execute(
            "UPDATE connections SET state='verified',recipient=? WHERE id=? AND state='waiting'",
            (recipient, id),
        )

    def permitted(self, recipient):
        return bool(
            self.db.execute(
                "SELECT 1 FROM connections WHERE recipient=? AND state='verified'", (recipient,)
            ).fetchone()
        )

    def disable(self, id):
        self.db.execute(
            "INSERT INTO connections VALUES (?,NULL,NULL,?,'disabled') "
            "ON CONFLICT(id) DO UPDATE SET state='disabled'",
            (id, time.time() + 600),
        )
