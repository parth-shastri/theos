"""Ordered Health jobs with bounded retries and restart reconciliation."""

import time
from uuid import uuid4

import httpx

from theos.services.errors import ServiceError


async def tick(client):
    """Run bounded background work from the application's single scheduler."""
    now = time.time()
    # 1. Queue due imports and any meals that lack an export marker.
    for connection in client.db.rows("SELECT owner FROM credentials WHERE service='health'"):
        owner = connection["owner"]
        try:
            previous = client.db.record(owner, "health", "last_import")["at"]
        except LookupError:
            previous = 0
        if now - previous >= client.settings.health_interval and not client.db.one(
            "SELECT 1 FROM jobs WHERE owner=? AND kind='health_import' AND status IN ('pending','reconcile','running')",
            (owner,),
        ):
            client.db.execute(
                "INSERT INTO jobs(id,owner,kind,payload,due,updated) VALUES (?,?,?,?,?,?)",
                (uuid4().hex, owner, "health_import", "{}", now, now),
            )
        client.backfill(owner)
    # 2. Keep jobs in order per owner and kind so older meal edits cannot replace newer ones.
    jobs = client.db.rows(
        "SELECT j.* FROM jobs j WHERE j.status IN ('pending','reconcile') AND j.due<=? AND NOT "
        "EXISTS (SELECT 1 FROM jobs prior WHERE prior.owner=j.owner AND prior.kind=j.kind AND "
        "prior.rowid<j.rowid AND prior.status NOT IN ('completed','cancelled')) ORDER BY "
        "j.rowid LIMIT 5",
        (now,),
    )
    # 3. Claim each job before its network request. Restart recovery will reconcile it.
    for job in jobs:
        if not client.db.one(
            "SELECT 1 FROM credentials WHERE owner=? AND service='health'", (job["owner"],)
        ):
            continue
        client.db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (now, job["id"]))
        try:
            if job["kind"] == "health_import":
                await client.import_summary(job["owner"])
                done = True
            else:
                done = await client.export(job)
            client.db.execute(
                "UPDATE jobs SET status=?,due=?,updated=?,result=NULL WHERE id=? AND status='running'",
                ("completed" if done else "reconcile", now + 30, time.time(), job["id"]),
            )
        except (httpx.HTTPError, ServiceError, KeyError, ValueError) as error:
            # Back off between attempts. A cancelled job must remain cancelled after the request returns.
            attempts = job["attempts"] + 1
            client.db.execute(
                "UPDATE jobs SET status=?,attempts=?,due=?,result=?,updated=? WHERE id=? AND status='running'",
                (
                    "failed" if attempts >= 5 else "reconcile",
                    attempts,
                    now + min(3600, 30 * 2**attempts),
                    type(error).__name__,
                    time.time(),
                    job["id"],
                ),
            )
