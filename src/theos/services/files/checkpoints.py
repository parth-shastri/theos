"""Durable source objects and model checkpoints with an R2 transfer journal."""

import asyncio
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

from harness import message_to_dict


class Checkpoints:
    def __init__(self, files):
        self.files, self.db, self.settings = files, files.db, files.settings
        self.directory = self.settings.data_dir / "checkpoints"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.locks = {}

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
        await self.flush_one(owner, identity)
        return identity

    async def flush_one(self, owner, identity):
        row = self.db.one("SELECT * FROM context_objects WHERE id=? AND owner=?", (identity, owner))
        if not row or row["status"] == "saved" or not self.settings.storage.endpoint:
            return
        client = self.files.storage_client()
        try:
            await asyncio.to_thread(
                client.upload_file, row["path"], self.settings.storage.bucket, row["object_key"]
            )
            self.db.execute("UPDATE context_objects SET status='saved' WHERE id=?", (identity,))
        except Exception:
            # The durable local spool remains pending. Never repeat the connector action to retry a transfer.
            self.db.execute("UPDATE context_objects SET status='pending' WHERE id=?", (identity,))
        finally:
            client.close()

    async def get(self, owner, session, identity):
        row = self.db.one(
            "SELECT * FROM context_objects WHERE id=? AND owner=? AND session=?",
            (identity, owner, session),
        )
        if not row:
            raise LookupError("Source not found in this conversation.")
        path = Path(row["path"])
        if not path.exists():
            client = self.files.storage_client()
            try:
                await asyncio.to_thread(
                    client.download_file, self.settings.storage.bucket, row["object_key"], str(path)
                )
            finally:
                client.close()
            path.chmod(0o600)
        data = gzip.decompress(path.read_bytes())
        if hashlib.sha256(data).hexdigest() != row["digest"]:
            raise ValueError("Checkpoint checksum mismatch.")
        return json.loads(data)

    async def save(self, owner, session, history, memory, stage):
        lock = self.locks.setdefault(session, asyncio.Lock())
        async with lock:
            for row in self.db.rows(
                "SELECT id FROM context_objects WHERE owner=? AND session=? AND status='pending' ORDER BY created LIMIT 20",
                (owner, session),
            ):
                await self.flush_one(owner, row["id"])
            checkpoint = {
                "schema": 1,
                "session": session,
                "owner": owner,
                "stage": stage,
                "history": [message_to_dict(m) for m in history],
                "memory": memory.to_dict(),
                "tool_runs": self.db.rows("SELECT * FROM tool_runs WHERE session=?", (session,)),
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
            # Publish the recovery pointer only after every referenced object is durable in R2.
            pending = self.db.one(
                "SELECT id FROM context_objects WHERE owner=? AND session=? AND status!='saved' LIMIT 1",
                (owner, session),
            )
            if self.settings.storage.endpoint and not pending:
                client = self.files.storage_client()
                try:
                    await asyncio.to_thread(
                        client.put_object,
                        Bucket=self.settings.storage.bucket,
                        Key=self.key(owner, session, "latest.json"),
                        Body=json.dumps({"id": identity}).encode(),
                    )
                except Exception:
                    return identity
                finally:
                    client.close()
            return identity

    async def restore(self, owner, session):
        """Restore an interrupted conversation into an existing owned, empty session."""
        current = self.db.session(owner, session)
        if json.loads(current["history"]) or current["status"] == "running":
            raise ValueError("Restore requires an empty, inactive conversation.")
        client = self.files.storage_client()
        try:
            response = await asyncio.to_thread(
                client.get_object,
                Bucket=self.settings.storage.bucket,
                Key=self.key(owner, session, "latest.json"),
            )
            pointer = json.loads(await asyncio.to_thread(response["Body"].read))
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
            client.close()
        if snapshot["owner"] != owner or snapshot["session"] != session:
            raise PermissionError("Checkpoint owner mismatch.")
        from harness import message_from_dict

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
            if snapshot.get("workspace"):
                self.db.put_record(
                    owner, "workspace", session, json.loads(snapshot["workspace"]["value"])
                )
            self.db.save_history(
                owner,
                session,
                [message_from_dict(m) for m in snapshot["history"]],
                snapshot["memory"],
                "interrupted",
            )
        return snapshot
