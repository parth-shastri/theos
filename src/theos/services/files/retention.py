"""Runtime-owned checkpoint retention and retryable local/R2 garbage collection."""

import gzip
import hashlib
import json
import logging
import time

logger = logging.getLogger("theos")
COLLECTIBLE = {"checkpoint", "workspace_file", "response_attachment"}
BATCH_SIZE = 20


def live_sources(db, owner, session):
    """Return current workspace and response-attachment roots without historic versions."""
    workspace = db.one(
        "SELECT value FROM records WHERE owner=? AND kind='workspace' AND id=?", (owner, session)
    )
    sources = set()
    if workspace:
        sources.update(
            item["source_id"] for item in json.loads(workspace["value"])["files"].values()
        )
    for row in db.rows(
        "SELECT value FROM records WHERE owner=? AND kind='response_attachment' "
        "AND json_extract(value,'$.session')=?",
        (owner, session),
    ):
        sources.add(json.loads(row["value"])["source_id"])
    return sources


class Retention:
    def __init__(self, checkpoints):
        self.checkpoints = checkpoints
        self.db = checkpoints.db
        self.settings = checkpoints.settings.storage
        self.last_run = 0.0

    def snapshot(self, row):
        """Fail closed when a retained snapshot cannot prove its references locally."""
        data = gzip.decompress((self.checkpoints.directory / row["id"]).read_bytes())
        if hashlib.sha256(data).hexdigest() != row["digest"]:
            raise ValueError("Retained checkpoint checksum mismatch.")
        value = json.loads(data)
        if value["owner"] != row["owner"] or value["session"] != row["session"]:
            raise ValueError("Retained checkpoint scope mismatch.")
        return value

    def roots(self, owner, session, rows):
        indexed = {row["id"]: row for row in rows}
        keep = live_sources(self.db, owner, session)
        snapshots = sorted(
            (row for row in rows if row["kind"] == "checkpoint"),
            key=lambda row: (row["created"], row["id"]),
            reverse=True,
        )
        keep.update(row["id"] for row in snapshots[: self.settings.checkpoint_keep])
        # Local and remote pointers can differ during an R2 outage. Protect both.
        for pointer in self.db.rows(
            "SELECT value FROM records WHERE owner=? AND id=? AND kind IN "
            "('context_checkpoint','context_checkpoint_remote')",
            (owner, session),
        ):
            keep.add(json.loads(pointer["value"])["id"])
        for pointer in self.db.rows(
            "SELECT value FROM records WHERE owner=? AND kind='context_checkpoint_publish' "
            "AND json_extract(value,'$.session')=?",
            (owner, session),
        ):
            keep.add(json.loads(pointer["value"])["id"])
        for identity in list(keep):
            row = indexed.get(identity)
            if row is None:
                raise ValueError("A retained checkpoint source is missing.")
            if row["kind"] != "checkpoint":
                continue
            for source in self.snapshot(row).get("objects", []):
                if source["owner"] != owner or source["session"] != session:
                    raise ValueError("Retained source scope mismatch.")
                if source["id"] not in indexed:
                    raise ValueError("A retained checkpoint source is missing.")
                keep.add(source["id"])
        return keep

    def mark(self, now):
        """Retire a bounded set synchronously so roots cannot change during the decision."""
        marked = 0
        for session in self.db.rows("SELECT id,owner,status FROM sessions ORDER BY updated"):
            if session["status"] == "running" or self.db.one(
                "SELECT id FROM records WHERE owner=? AND kind='remote_recovery_review' AND id=?",
                (session["owner"], session["id"]),
            ):
                continue
            owner, identity = session["owner"], session["id"]
            rows = self.db.rows(
                "SELECT * FROM context_objects WHERE owner=? AND session=?", (owner, identity)
            )
            try:
                keep = self.roots(owner, identity, rows)
            except (ValueError, KeyError, OSError, EOFError):
                logger.warning("checkpoint_retention_deferred")
                continue
            for row in rows:
                if (
                    row["kind"] not in COLLECTIBLE
                    or row["id"] in keep
                    or row["created"] > now - self.settings.gc_grace_seconds
                ):
                    continue
                expected_id = hashlib.sha256(
                    f"{owner}/{identity}/{row['kind']}/{row['digest']}".encode()
                ).hexdigest()
                expected_key = self.checkpoints.key(owner, identity, row["id"] + ".json.gz")
                if (
                    row["id"] != expected_id
                    or row["object_key"] != expected_key
                    or row["path"] != str(self.checkpoints.directory / row["id"])
                ):
                    logger.warning("checkpoint_retention_invalid_path")
                    continue
                retry = self.db.one(
                    "SELECT id FROM records WHERE owner=? AND kind IN ('context_replication_retry','context_replication_intent') AND id=?",
                    (owner, row["id"]),
                )
                remote = bool(self.settings.endpoint or row["status"] == "saved" or retry)
                # Removing the live row retires the version. A future put of identical
                # content creates a new pending row, which waits for this deletion.
                with self.db.transaction():
                    self.db.execute(
                        "INSERT OR IGNORE INTO context_deletions VALUES (?,?,?,?,?,?,0,?)",
                        (row["id"], owner, identity, expected_key, int(remote), now, now),
                    )
                    self.db.execute(
                        "DELETE FROM context_objects WHERE id=? AND owner=?", (row["id"], owner)
                    )
                    self.db.execute(
                        "DELETE FROM records WHERE owner=? AND kind IN ('context_replication_retry','context_replication_intent') AND id=?",
                        (owner, row["id"]),
                    )
                marked += 1
                if marked >= BATCH_SIZE:
                    return marked
        return marked

    def finish(self, row):
        # A command can recreate this content while the remote delete is in flight.
        # Its local bytes and pending upload must survive completion of the old delete.
        if not self.db.one("SELECT id FROM context_objects WHERE id=?", (row["id"],)):
            (self.checkpoints.directory / row["id"]).unlink(missing_ok=True)
        else:
            self.checkpoints.wake.set()
        self.db.execute(
            "DELETE FROM context_deletions WHERE id=? AND owner=?", (row["id"], row["owner"])
        )

    async def delete_batch(self, now):
        rows = self.db.rows(
            "SELECT * FROM context_deletions WHERE due<=? AND (remote_required=0 OR ?) "
            "ORDER BY due,created LIMIT ?",
            (now, bool(self.settings.endpoint), BATCH_SIZE),
        )
        remote = []
        for row in rows:
            if not row["remote_required"]:
                self.finish(row)
            else:
                remote.append(row)
        if not remote:
            return
        import asyncio

        failed = {row["object_key"] for row in remote}
        try:
            client = await self.checkpoints.storage_client()
            result = await asyncio.to_thread(
                client.delete_objects,
                Bucket=self.settings.bucket,
                Delete={"Objects": [{"Key": row["object_key"]} for row in remote], "Quiet": True},
            )
            failed = {item["Key"] for item in result.get("Errors", [])}
        except Exception as error:
            logger.warning(
                "checkpoint_gc_delete_failed", extra={"error_type": type(error).__name__}
            )
        for row in remote:
            if row["object_key"] in failed:
                delay = min(3600, 5 * 2 ** min(row["attempts"], 9))
                self.db.execute(
                    "UPDATE context_deletions SET attempts=attempts+1,due=? WHERE id=?",
                    (now + delay, row["id"]),
                )
            else:
                self.finish(row)

    async def collect(self, *, force=False):
        now = time.time()
        async with self.checkpoints.replication_lock:
            # Mark only on the configured cadence. Retry durable deletions every worker pass.
            if force or now - self.last_run >= self.settings.gc_interval_seconds:
                marked = self.mark(now)
                self.last_run = now
                if marked >= BATCH_SIZE:
                    # Continue a backlog in bounded passes instead of limiting cleanup
                    # to one batch per hour.
                    self.last_run = now - self.settings.gc_interval_seconds + 1
            await self.delete_batch(now)

    def next_delay(self):
        now = time.time()
        delay = max(1, self.last_run + self.settings.gc_interval_seconds - now)
        pending = self.db.one(
            "SELECT MIN(due) AS due FROM context_deletions WHERE remote_required=0 OR ?",
            (bool(self.settings.endpoint),),
        )
        if pending and pending["due"] is not None:
            delay = min(delay, max(1, pending["due"] - now))
        return delay
