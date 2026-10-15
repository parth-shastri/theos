"""Durable source objects and model checkpoints with an R2 transfer journal."""

import asyncio
import gzip
import hashlib
import json
import logging
import os
import time
from contextlib import nullcontext
from contextvars import Context
from pathlib import Path

from harness import message_to_dict

logger = logging.getLogger("theos")


class Checkpoints:
    def __init__(self, files, tracing=None):
        self.files, self.db, self.settings = files, files.db, files.settings
        self.directory = self.settings.data_dir / "checkpoints"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.locks = {}
        self.tracing = tracing
        self.worker = None
        self.wake = asyncio.Event()
        self.stop = asyncio.Event()
        self.replication_lock = asyncio.Lock()
        self.client = None
        self.client_lock = asyncio.Lock()
        self.closed = False

    def span(self, name, attributes=None, *, root=False):
        return self.tracing.span(name, attributes, root=root) if self.tracing else nullcontext(None)

    def start(self):
        """Resume the durable transfer journal with one background worker."""
        if self.closed or not self.settings.storage.endpoint:
            return
        if self.worker is None or self.worker.done():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            # Background replication must not inherit the first caller's turn trace.
            self.worker = loop.create_task(self.replicate(), context=Context())
        self.wake.set()

    async def storage_client(self):
        async with self.client_lock:
            if self.client is None:
                self.client = await asyncio.to_thread(self.files.storage_client)
        return self.client

    async def replicate(self):
        while not self.closed:
            self.wake.clear()
            try:
                complete = await self.flush()
            except Exception as error:
                logger.warning(
                    "checkpoint_replication_failed", extra={"error_type": type(error).__name__}
                )
                complete = False
            if self.closed:
                return
            if complete:
                await self.wake.wait()
            else:
                # Back off storage failures. The local journal remains authoritative.
                try:
                    await asyncio.wait_for(self.stop.wait(), 5)
                except TimeoutError:
                    pass

    async def flush(self):
        """Replicate bounded batches without executing any assistant tool."""
        if not self.settings.storage.endpoint:
            return True
        async with self.replication_lock:
            rows = self.db.rows(
                "SELECT objects.* FROM context_objects objects "
                "LEFT JOIN records retry ON retry.owner=objects.owner "
                "AND retry.kind='context_replication_retry' AND retry.id=objects.id "
                "WHERE objects.status='pending' "
                "ORDER BY COALESCE(retry.updated,objects.created) LIMIT 20"
            )
            failed = False
            for row in rows:
                if self.closed:
                    return False
                failed = not await self.flush_one(row["owner"], row["id"]) or failed
            pointers = self.db.rows(
                "SELECT local.owner,local.id,local.value FROM records local "
                "LEFT JOIN records remote ON remote.owner=local.owner "
                "AND remote.kind='context_checkpoint_remote' AND remote.id=local.id "
                "WHERE local.kind='context_checkpoint' "
                "AND (remote.value IS NULL OR "
                "json_extract(remote.value,'$.id')!=json_extract(local.value,'$.id')) "
                "ORDER BY local.updated LIMIT 20"
            )
            for pointer in pointers:
                if self.closed:
                    return False
                failed = not await self.publish(pointer) or failed
            pending = self.db.one("SELECT id FROM context_objects WHERE status='pending' LIMIT 1")
            if not failed and (pending or len(pointers) == 20):
                self.wake.set()
            return not failed

    async def publish(self, pointer):
        owner, session = pointer["owner"], pointer["id"]
        identity = json.loads(pointer["value"])["id"]
        # Never publish a recovery pointer before its snapshot and all sources exist remotely.
        pending = self.db.one(
            "SELECT id FROM context_objects WHERE owner=? AND session=? AND status!='saved' LIMIT 1",
            (owner, session),
        )
        if pending:
            return True
        with self.span(
            "checkpoint publish", {"gen_ai.conversation.id": session}, root=True
        ) as span:
            client = await self.storage_client()
            try:
                await asyncio.to_thread(
                    client.put_object,
                    Bucket=self.settings.storage.bucket,
                    Key=self.key(owner, session, "latest.json"),
                    Body=json.dumps({"id": identity}).encode(),
                )
            except Exception as error:
                if self.tracing:
                    self.tracing.failed(span, type(error).__name__)
                logger.warning(
                    "checkpoint_replication_failed", extra={"error_type": type(error).__name__}
                )
                return False
            self.db.put_record(owner, "context_checkpoint_remote", session, {"id": identity})
        return True

    async def drain(self):
        """Wait for successful replication, primarily for backup and acceptance checks."""
        self.start()
        while True:
            if not await self.flush():
                return False
            if not self.settings.storage.endpoint:
                return True
            pending = self.db.one("SELECT id FROM context_objects WHERE status='pending' LIMIT 1")
            if not pending:
                return True

    async def close(self):
        """Stop the worker. Unfinished transfers remain in the durable journal."""
        self.closed = True
        self.wake.set()
        self.stop.set()
        if self.worker:
            # Finish the current storage operation before a replacement worker can publish.
            try:
                await asyncio.wait_for(asyncio.shield(self.worker), 35)
            except TimeoutError:
                self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        if self.client:
            await asyncio.to_thread(self.client.close)
            self.client = None

    def key(self, owner, session, suffix):
        scope = hashlib.sha256(owner.encode()).hexdigest()
        return f"theos/checkpoints/{scope}/{session}/{suffix}"

    async def put(self, owner, session, kind, value):
        self.db.session(owner, session)
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
        digest = hashlib.sha256(data).hexdigest()
        identity = hashlib.sha256(f"{owner}/{session}/{kind}/{digest}".encode()).hexdigest()
        path = self.directory / identity
        if not path.exists():
            temporary = path.with_suffix(".pending")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(gzip.compress(data, mtime=0))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        self.db.execute(
            "INSERT OR IGNORE INTO context_objects VALUES (?,?,?,?,?,?,?,?,?)",
            (
                identity,
                owner,
                session,
                kind,
                digest,
                str(path),
                self.key(owner, session, identity + ".json.gz"),
                "pending",
                time.time(),
            ),
        )
        self.start()
        return identity

    async def flush_one(self, owner, identity):
        row = self.db.one("SELECT * FROM context_objects WHERE id=? AND owner=?", (identity, owner))
        if not row or row["status"] == "saved" or not self.settings.storage.endpoint:
            return True
        with self.span(
            "checkpoint upload",
            {"gen_ai.conversation.id": row["session"], "theos.checkpoint.kind": row["kind"]},
            root=True,
        ) as span:
            client = await self.storage_client()
            try:
                await asyncio.to_thread(
                    client.upload_file, row["path"], self.settings.storage.bucket, row["object_key"]
                )
                self.db.execute("UPDATE context_objects SET status='saved' WHERE id=?", (identity,))
                self.db.execute(
                    "DELETE FROM records WHERE owner=? AND kind='context_replication_retry' AND id=?",
                    (owner, identity),
                )
                return True
            except Exception as error:
                if self.tracing:
                    self.tracing.failed(span, type(error).__name__)
                logger.warning(
                    "checkpoint_replication_failed", extra={"error_type": type(error).__name__}
                )
                self.db.put_record(owner, "context_replication_retry", identity, {"pending": True})
                return False

    async def get(self, owner, session, identity):
        row = self.db.one(
            "SELECT * FROM context_objects WHERE id=? AND owner=? AND session=?",
            (identity, owner, session),
        )
        if not row:
            raise LookupError("Source not found in this conversation.")
        path = Path(row["path"])
        if not path.exists():
            if row["status"] != "saved":
                raise FileNotFoundError("The pending source is missing from local storage.")
            client = await self.storage_client()
            await asyncio.to_thread(
                client.download_file, self.settings.storage.bucket, row["object_key"], str(path)
            )
            path.chmod(0o600)
        data = gzip.decompress(path.read_bytes())
        if hashlib.sha256(data).hexdigest() != row["digest"]:
            raise ValueError("Checkpoint checksum mismatch.")
        return json.loads(data)

    async def save(self, owner, session, history, memory, stage):
        lock = self.locks.setdefault(session, asyncio.Lock())
        async with lock:
            with self.span("checkpoint persist", {"theos.checkpoint.stage": stage}):
                checkpoint = {
                    "schema": 1,
                    "session": session,
                    "owner": owner,
                    "stage": stage,
                    "history": [message_to_dict(m) for m in history],
                    "memory": memory.to_dict(),
                    "tool_runs": self.db.rows(
                        "SELECT * FROM tool_runs WHERE session=?", (session,)
                    ),
                    "objects": self.db.rows(
                        "SELECT * FROM context_objects WHERE owner=? AND session=? AND kind!='checkpoint'",
                        (owner, session),
                    ),
                    "workspace": self.db.one(
                        "SELECT value FROM records WHERE owner=? AND kind='workspace' AND id=?",
                        (owner, session),
                    ),
                }
                identity = await self.put(owner, session, "checkpoint", checkpoint)
                self.db.put_record(
                    owner, "context_checkpoint", session, {"id": identity, "stage": stage}
                )
                self.start()
                return identity

    async def restore(self, owner, session):
        """Restore an interrupted conversation into an existing owned, empty session."""
        current = self.db.session(owner, session)
        if json.loads(current["history"]) or current["status"] == "running":
            raise ValueError("Restore requires an empty, inactive conversation.")
        client = await self.storage_client()
        response = None
        try:
            response = await asyncio.to_thread(
                client.get_object,
                Bucket=self.settings.storage.bucket,
                Key=self.key(owner, session, "latest.json"),
            )
            pointer = json.loads(await asyncio.to_thread(response["Body"].read))
            response["Body"].close()
            identity = pointer["id"]
            if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
                raise ValueError("Invalid checkpoint reference.")
            response = await asyncio.to_thread(
                client.get_object,
                Bucket=self.settings.storage.bucket,
                Key=self.key(owner, session, identity + ".json.gz"),
            )
            data = gzip.decompress(await asyncio.to_thread(response["Body"].read))
            digest = hashlib.sha256(data).hexdigest()
            expected = hashlib.sha256(f"{owner}/{session}/checkpoint/{digest}".encode()).hexdigest()
            if identity != expected:
                raise ValueError("Checkpoint checksum mismatch.")
            snapshot = json.loads(data)
        finally:
            if response is not None:
                response["Body"].close()
        if snapshot["owner"] != owner or snapshot["session"] != session:
            raise PermissionError("Checkpoint owner mismatch.")
        from harness import ToolResultMessage, message_from_dict, unanswered_calls

        restored = [message_from_dict(m) for m in snapshot["history"]]
        memory = snapshot["memory"]

        with self.db.transaction():
            for row in snapshot["objects"]:
                if row["owner"] != owner or row["session"] != session:
                    raise PermissionError("Source owner mismatch.")
                source_id = row["id"]
                if len(source_id) != 64 or any(c not in "0123456789abcdef" for c in source_id):
                    raise ValueError("Invalid source reference.")
                if row["object_key"] != self.key(owner, session, source_id + ".json.gz"):
                    raise ValueError("Invalid source object key.")
                self.db.execute(
                    "INSERT OR IGNORE INTO context_objects VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        row["id"],
                        owner,
                        session,
                        row["kind"],
                        row["digest"],
                        str(self.directory / row["id"]),
                        row["object_key"],
                        "saved",
                        row["created"],
                    ),
                )
            for row in snapshot["tool_runs"]:
                status = "unknown" if row["status"] == "running" else row["status"]
                self.db.execute(
                    "INSERT OR REPLACE INTO tool_runs VALUES (?,?,?,?,?)",
                    (session, row["call_id"], row["tool"], status, row["result"]),
                )
            # A remote snapshot can predate external effects, even without an attempt row.
            for call in unanswered_calls(restored):
                row = self.db.one(
                    "SELECT * FROM tool_runs WHERE session=? AND call_id=?", (session, call.id)
                )
                if row and row["result"]:
                    result = message_from_dict(json.loads(row["result"]))
                else:
                    result = ToolResultMessage(
                        call.id,
                        call.name,
                        "The remote checkpoint may predate this action. "
                        "Check the external service before repeating it.",
                        "unknown",
                    )
                    self.db.execute(
                        "INSERT OR REPLACE INTO tool_runs VALUES (?,?,?,?,?)",
                        (
                            session,
                            call.id,
                            call.name,
                            "unknown",
                            json.dumps(message_to_dict(result)),
                        ),
                    )
                restored.append(result)
            if snapshot.get("workspace"):
                self.db.put_record(
                    owner, "workspace", session, json.loads(snapshot["workspace"]["value"])
                )
            self.db.save_history(
                owner,
                session,
                restored,
                memory,
                "interrupted",
            )
            # The snapshot may omit actions that started after it was uploaded.
            self.db.put_record(owner, "remote_recovery_review", session, {"checkpoint": identity})
        snapshot["history"] = [message_to_dict(m) for m in restored]
        snapshot["tool_runs"] = self.db.rows("SELECT * FROM tool_runs WHERE session=?", (session,))
        return snapshot

    def confirm_restore_review(self, owner, session):
        """Let operator recovery code confirm external reconciliation, never an agent tool."""
        current = self.db.session(owner, session)
        if current["status"] == "running":
            raise ValueError("Wait for the restored turn to stop before confirming recovery.")
        self.db.execute(
            "DELETE FROM records WHERE owner=? AND kind='remote_recovery_review' AND id=?",
            (owner, session),
        )
