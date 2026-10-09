"""Record nutrition export intent within the caller's meal transaction."""

import json
import time
from uuid import uuid4


def queue_nutrition(db, owner, meal_id, meal, operation="save"):
    """Save the export intent in the same transaction as the meal change."""
    if not db.one("SELECT 1 FROM credentials WHERE owner=? AND service='health'", (owner,)):
        return
    db.put_record(owner, "backfill", meal_id, {"queued": True})
    payload = {"meal_id": meal_id, "meal": meal, "operation": operation}
    now = time.time()
    db.execute(
        "INSERT INTO jobs(id,owner,kind,payload,due,updated) VALUES (?,?,?,?,?,?)",
        (uuid4().hex, owner, "nutrition", json.dumps(payload), now, now),
    )
