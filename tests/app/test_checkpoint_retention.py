"""Runtime retention preserves recovery roots and safely retries object deletion."""

import asyncio
import base64
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from pydantic import SecretStr

from harness import ContextMemory, UserMessage
from theos.services.files.checkpoints import Checkpoints

from .test_context_checkpoints import Objects


class Storage(Objects):
    def __init__(self):
        super().__init__()
        self.delete_fail = False
        self.partial_fail = set()
        self.deleted = []
        self.events = []
        self.block_delete = None

    def upload_file(self, path, bucket, key):
        super().upload_file(path, bucket, key)
        self.events.append(("upload", key))

    def delete_objects(self, *, Bucket, Delete):
        if self.block_delete:
            self.block_delete()
        if self.delete_fail:
            raise OSError("delete offline")
        errors = []
        for item in Delete["Objects"]:
            key = item["Key"]
            if key in self.partial_fail:
                errors.append({"Key": key, "Code": "InternalError"})
                continue
            self.objects.pop(key, None)
            self.deleted.append(key)
            self.events.append(("delete", key))
        return {"Errors": errors}


@pytest.fixture
def storage(runtime, monkeypatch):
    config = runtime.settings.storage
    config.endpoint, config.bucket = "https://example.invalid", "private"
    config.access_key, config.secret_key = SecretStr("test"), SecretStr("test")
    runtime.checkpoints.retention.last_run = time.time()
    client = Storage()
    monkeypatch.setattr(runtime.files, "storage_client", lambda: client)
    return client


def session(runtime, owner="alice"):
    return runtime.db.create_session(owner, "gpt-6-luna", "none")["id"]


async def version(runtime, sid, text, *, owner="alice", current=True):
    value = {
        "path": "/workspace/report.txt",
        "data": base64.b64encode(text.encode()).decode(),
        "digest": hashlib.sha256(text.encode()).hexdigest(),
    }
    identity = await runtime.checkpoints.put(owner, sid, "workspace_file", value)
    if current:
        runtime.db.put_record(
            owner,
            "workspace",
            sid,
            {
                "files": {
                    value["path"]: {"source_id": identity, "digest": value["digest"], "version": 1}
                }
            },
        )
    return identity, value


async def snapshot(runtime, sid, label, owner="alice"):
    return await runtime.checkpoints.save(
        owner, sid, [UserMessage(label)], ContextMemory(), "turn_end"
    )


def age(runtime):
    runtime.db.execute("UPDATE context_objects SET created=created-7200")


def exists(runtime, identity):
    return bool(runtime.db.one("SELECT id FROM context_objects WHERE id=?", (identity,)))


def key(runtime, sid, identity, owner="alice"):
    return runtime.checkpoints.key(owner, sid, identity + ".json.gz")


async def test_retention_keeps_current_versions_retained_checkpoints_and_attachments(
    runtime, storage
):
    runtime.settings.storage.checkpoint_keep = 2
    sid, other = session(runtime), session(runtime, "bob")
    sources, checkpoints = [], []
    for text in ["one", "two", "three", "four"]:
        identity, _ = await version(runtime, sid, text)
        sources.append(identity)
        checkpoints.append(await snapshot(runtime, sid, text))
    bob, _ = await version(runtime, other, "private", owner="bob")
    file = runtime.files.save("alice", "report.txt", "text/plain", b"attached version")
    await runtime.workspaces.save_attachment("alice", sid, {"file_id": file["id"]})
    attached = runtime.db.record("alice", "response_attachment", sid + ":" + file["id"])[
        "source_id"
    ]
    checkpoints[-1] = await snapshot(runtime, sid, "four with attachment")
    # Keep the two most recent snapshots, which now both refer to the fourth version.
    assert await runtime.checkpoints.drain()
    newest = await runtime.checkpoints.get("alice", sid, checkpoints[-1])
    assert sources[0] not in {row["id"] for row in newest["objects"]}
    age(runtime)
    storage.objects["unrelated/object"] = b"leave alone"
    await runtime.checkpoints.retention.collect(force=True)
    assert all(not exists(runtime, identity) for identity in sources[:3])
    assert exists(runtime, sources[3]) and exists(runtime, bob) and exists(runtime, attached)
    assert not exists(runtime, checkpoints[0])
    assert exists(runtime, checkpoints[-1])
    assert storage.objects["unrelated/object"] == b"leave alone"
    assert await runtime.files.read("alice", file["id"]) == b"attached version"
    assert key(runtime, sid, sources[0]) not in storage.objects
    assert not (runtime.checkpoints.directory / sources[0]).exists()


async def test_remote_recovery_pointer_survives_local_progress_and_upload_outage(runtime, storage):
    runtime.settings.storage.checkpoint_keep = 1
    sid = session(runtime)
    remote, _ = await version(runtime, sid, "published")
    checkpoint = await snapshot(runtime, sid, "published")
    assert await runtime.checkpoints.drain()
    storage.fail, storage.delete_fail = True, True
    latest, _ = await version(runtime, sid, "local progress")
    latest_checkpoint = await snapshot(runtime, sid, "local progress")
    age(runtime)
    await runtime.checkpoints.retention.collect(force=True)
    assert all(
        exists(runtime, identity) for identity in [remote, checkpoint, latest, latest_checkpoint]
    )
    assert (
        json.loads(storage.objects[runtime.checkpoints.key("alice", sid, "latest.json")])["id"]
        == checkpoint
    )
    storage.fail, storage.delete_fail = False, False
    assert await runtime.checkpoints.drain()
    await runtime.checkpoints.retention.collect(force=True)
    assert not exists(runtime, remote) and not exists(runtime, checkpoint)
    assert exists(runtime, latest) and exists(runtime, latest_checkpoint)


async def test_deletion_retries_after_restart_and_handles_partial_r2_failures(runtime, storage):
    sid = session(runtime)
    first, _ = await version(runtime, sid, "old one", current=False)
    second, _ = await version(runtime, sid, "old two", current=False)
    current, _ = await version(runtime, sid, "current")
    await snapshot(runtime, sid, "current")
    assert await runtime.checkpoints.drain()
    age(runtime)
    storage.partial_fail.add(key(runtime, sid, second))
    await runtime.checkpoints.retention.collect(force=True)
    assert not exists(runtime, first) and not exists(runtime, second)
    assert not (runtime.checkpoints.directory / first).exists()
    assert (
        runtime.db.one("SELECT attempts FROM context_deletions WHERE id=?", (second,))["attempts"]
        == 1
    )
    assert exists(runtime, current)
    await runtime.checkpoints.close()
    runtime.checkpoints = Checkpoints(runtime.files, runtime.tracing)
    runtime.checkpoints.retention.last_run = time.time()
    storage.partial_fail.clear()
    runtime.db.execute("UPDATE context_deletions SET due=0")
    await runtime.checkpoints.retention.collect()
    assert not runtime.db.rows("SELECT * FROM context_deletions")
    assert key(runtime, sid, second) not in storage.objects
    assert not (runtime.checkpoints.directory / second).exists()


async def test_recreated_content_survives_a_delete_in_flight_without_blocking_local_save(
    runtime, storage
):
    sid = session(runtime)
    old, value = await version(runtime, sid, "returning content", current=False)
    await version(runtime, sid, "current")
    await snapshot(runtime, sid, "current")
    assert await runtime.checkpoints.drain()
    age(runtime)
    started, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def block():
        loop.call_soon_threadsafe(started.set)
        if not release.wait(3):
            raise TimeoutError("blocked delete")

    storage.block_delete = block
    collection = asyncio.create_task(runtime.checkpoints.retention.collect(force=True))
    try:
        await asyncio.wait_for(started.wait(), 1)
        recreated = await asyncio.wait_for(
            runtime.checkpoints.put("alice", sid, "workspace_file", value), 1
        )
        assert recreated == old
        runtime.db.put_record(
            "alice",
            "workspace",
            sid,
            {"files": {value["path"]: {"source_id": old, "digest": value["digest"], "version": 2}}},
        )
        await asyncio.wait_for(snapshot(runtime, sid, "recreated"), 1)
        assert (
            runtime.db.one("SELECT status FROM context_objects WHERE id=?", (old,))["status"]
            == "pending"
        )
        assert runtime.db.one("SELECT id FROM context_deletions WHERE id=?", (old,))
    finally:
        release.set()
    await collection
    storage.block_delete = None
    assert await runtime.checkpoints.drain()
    assert not (runtime.checkpoints.directory / old).exists()
    assert (await runtime.checkpoints.get("alice", sid, old))["data"] == value["data"]
    events = [event for event in storage.events if event[1] == key(runtime, sid, old)]
    assert events[-2:] == [("delete", key(runtime, sid, old)), ("upload", key(runtime, sid, old))]


async def test_local_cleanup_observes_grace_active_sessions_and_recovery_review(runtime):
    runtime.checkpoints.retention.last_run = time.time()
    sid = session(runtime)
    old, _ = await version(runtime, sid, "old", current=False)
    current, _ = await version(runtime, sid, "current")
    await snapshot(runtime, sid, "current")
    age(runtime)
    fresh, _ = await version(runtime, sid, "new scratch", current=False)
    runtime.db.execute("UPDATE sessions SET status='running' WHERE id=?", (sid,))
    await runtime.checkpoints.retention.collect(force=True)
    assert exists(runtime, old)
    runtime.db.execute("UPDATE sessions SET status='idle' WHERE id=?", (sid,))
    runtime.db.put_record("alice", "remote_recovery_review", sid, {"checkpoint": "review"})
    await runtime.checkpoints.retention.collect(force=True)
    assert exists(runtime, old)
    runtime.db.delete_record("alice", "remote_recovery_review", sid)
    await runtime.checkpoints.retention.collect(force=True)
    assert not exists(runtime, old)
    assert not (runtime.checkpoints.directory / old).exists()
    assert exists(runtime, current) and exists(runtime, fresh)
    assert not runtime.db.rows("SELECT * FROM context_deletions")


async def test_unreadable_retained_checkpoint_defers_only_its_session(runtime):
    runtime.checkpoints.retention.last_run = time.time()
    sid, other = session(runtime), session(runtime, "bob")
    orphan, _ = await version(runtime, sid, "orphan", current=False)
    await version(runtime, sid, "current")
    retained = await snapshot(runtime, sid, "current")
    bob, _ = await version(runtime, other, "old", owner="bob", current=False)
    age(runtime)
    (runtime.checkpoints.directory / retained).write_bytes(b"broken")
    await runtime.checkpoints.retention.collect(force=True)
    assert exists(runtime, orphan)
    assert not exists(runtime, bob)


async def test_retention_drains_a_backlog_in_bounded_passes(runtime):
    runtime.checkpoints.retention.last_run = time.time()
    sid = session(runtime)
    for number in range(25):
        await version(runtime, sid, str(number), current=False)
    age(runtime)
    assert runtime.checkpoints.retention.mark(time.time()) == 20
    assert len(runtime.db.rows("SELECT id FROM context_objects")) == 5
    assert runtime.checkpoints.retention.mark(time.time()) == 5
    # A restart can leave more than one local deletion batch already marked.
    await runtime.checkpoints.retention.collect(force=True)
    assert len(runtime.db.rows("SELECT id FROM context_deletions")) == 5
    assert runtime.checkpoints.retention.next_delay() <= 1
    await runtime.checkpoints.retention.collect(force=True)
    assert not runtime.db.rows("SELECT id FROM context_objects")
    assert not runtime.db.rows("SELECT id FROM context_deletions")


async def test_complete_snapshot_can_publish_while_a_newer_unreferenced_upload_fails(
    runtime, storage
):
    sid = session(runtime)
    await version(runtime, sid, "current")
    first = await snapshot(runtime, sid, "first")
    assert await runtime.checkpoints.drain()
    orphan, _ = await version(runtime, sid, "unreferenced", current=False)
    original = storage.upload_file

    def selective_failure(path, bucket, object_key):
        if object_key == key(runtime, sid, orphan):
            raise OSError("orphan upload failed")
        original(path, bucket, object_key)

    storage.upload_file = selective_failure
    newest = await snapshot(runtime, sid, "second")
    assert newest != first
    await runtime.checkpoints.flush()
    pointer = json.loads(storage.objects[runtime.checkpoints.key("alice", sid, "latest.json")])
    assert pointer["id"] == newest
    assert (
        runtime.db.one("SELECT status FROM context_objects WHERE id=?", (orphan,))["status"]
        == "pending"
    )


async def test_worker_uploads_recreated_content_after_deletion_retry_without_another_command(
    runtime, storage
):
    sid = session(runtime)
    old, value = await version(runtime, sid, "returning", current=False)
    await version(runtime, sid, "current")
    await snapshot(runtime, sid, "current")
    assert await runtime.checkpoints.drain()
    age(runtime)
    storage.delete_fail = True
    await runtime.checkpoints.retention.collect(force=True)
    assert runtime.db.one("SELECT id FROM context_deletions WHERE id=?", (old,))
    await runtime.checkpoints.put("alice", sid, "workspace_file", value)
    runtime.db.put_record(
        "alice",
        "workspace",
        sid,
        {"files": {value["path"]: {"source_id": old, "digest": value["digest"], "version": 2}}},
    )
    newest = await snapshot(runtime, sid, "recreated")
    await runtime.checkpoints.flush()
    storage.delete_fail = False
    runtime.db.execute("UPDATE context_deletions SET due=0")
    runtime.checkpoints.wake.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        row = runtime.db.one("SELECT status FROM context_objects WHERE id=?", (old,))
        pointer = runtime.db.record("alice", "context_checkpoint_remote", sid)
        if row["status"] == "saved" and pointer["id"] == newest:
            break
        await asyncio.sleep(0.02)
    else:
        pytest.fail("The worker did not resume publication after deletion completed.")
    assert key(runtime, sid, old) in storage.objects


async def test_interrupted_upload_keeps_remote_delete_intent_when_storage_is_disabled(
    runtime, storage
):
    sid = session(runtime)
    uncertain, _ = await version(runtime, sid, "uncertain upload", current=False)
    local, _ = await version(runtime, sid, "local only", current=False)
    # Simulate a crash after the upload started and before its result was committed.
    runtime.db.put_record("alice", "context_replication_intent", uncertain, {"session": sid})
    storage.objects[key(runtime, sid, uncertain)] = (
        runtime.checkpoints.directory / uncertain
    ).read_bytes()
    runtime.settings.storage.endpoint = ""
    age(runtime)
    await runtime.checkpoints.retention.collect(force=True)
    pending = runtime.db.one("SELECT * FROM context_deletions WHERE id=?", (uncertain,))
    assert pending["remote_required"] == 1
    assert not exists(runtime, local) and not (runtime.checkpoints.directory / local).exists()
    assert storage.objects[key(runtime, sid, uncertain)]
    runtime.settings.storage.endpoint = "https://example.invalid"
    await runtime.checkpoints.retention.collect(force=True)
    assert not runtime.db.rows("SELECT * FROM context_deletions")
    assert key(runtime, sid, uncertain) not in storage.objects


async def test_uncertain_remote_publications_remain_roots_until_a_pointer_is_confirmed(
    runtime, storage
):
    runtime.settings.storage.checkpoint_keep = 1
    sid = session(runtime)
    first, _ = await version(runtime, sid, "confirmed")
    confirmed = await snapshot(runtime, sid, "confirmed")
    assert await runtime.checkpoints.drain()
    original = storage.put_object

    def lost_response(**kwargs):
        original(**kwargs)
        raise OSError("pointer response lost")

    storage.put_object = lost_response
    possible, _ = await version(runtime, sid, "possible remote state")
    uncertain = await snapshot(runtime, sid, "possible remote state")
    assert not await runtime.checkpoints.drain()
    current, _ = await version(runtime, sid, "latest local state")
    latest = await snapshot(runtime, sid, "latest local state")
    assert not await runtime.checkpoints.drain()
    age(runtime)
    await runtime.checkpoints.retention.collect(force=True)
    assert all(
        exists(runtime, identity)
        for identity in [first, confirmed, possible, uncertain, current, latest]
    )
    assert runtime.db.record("alice", "context_checkpoint_remote", sid)["id"] == confirmed
    assert (
        json.loads(storage.objects[runtime.checkpoints.key("alice", sid, "latest.json")])["id"]
        == latest
    )
    storage.put_object = original
    assert await runtime.checkpoints.drain()
    assert not runtime.db.rows("SELECT * FROM records WHERE kind='context_checkpoint_publish'")
    await runtime.checkpoints.retention.collect(force=True)
    assert not exists(runtime, first) and not exists(runtime, possible)
    assert exists(runtime, current) and exists(runtime, latest)


MIGRATION = (
    Path(__file__).parents[2] / "src/theos/storage/migrations/024_helper_copy_references.sql"
)


async def helper_copies(runtime, sid, count, *, owner="alice", start=0):
    """Save `count` helper copies with strictly increasing creation times."""
    identities = []
    for number in range(start, start + count):
        identity = await runtime.checkpoints.put(
            owner, sid, "delegate_checkpoint", {"stage": "before_model", "number": number}
        )
        # Sorting by creation time must not depend on the clock resolution.
        runtime.db.execute(
            "UPDATE context_objects SET created=? WHERE id=?", (1000.0 + number, identity)
        )
        identities.append(identity)
    return identities


def helper_ids(runtime, sid):
    rows = runtime.db.rows(
        "SELECT id FROM context_objects WHERE session=? AND kind='delegate_checkpoint'", (sid,)
    )
    return {row["id"] for row in rows}


def deletion_ids(runtime):
    return {row["id"] for row in runtime.db.rows("SELECT id FROM context_deletions")}


async def legacy_checkpoint(runtime, sid, owner="alice"):
    """Save a checkpoint as older releases did, listing every helper copy of the chat."""
    objects = runtime.db.rows(
        "SELECT * FROM context_objects WHERE owner=? AND session=? AND kind!='checkpoint'",
        (owner, sid),
    )
    value = {
        "schema": 2,
        "owner": owner,
        "session": sid,
        "stage": "turn_end",
        "history": [],
        "catalog_files": [],
        "memory": ContextMemory().to_dict(),
        "tool_runs": [],
        "objects": objects,
        "attachments": [],
        "workspace_inputs": None,
        "workspace": None,
    }
    identity = await runtime.checkpoints.put(owner, sid, "checkpoint", value)
    runtime.db.put_record(owner, "context_checkpoint", sid, {"id": identity, "stage": "turn_end"})
    return identity


def mark_until_done(runtime):
    while runtime.checkpoints.retention.mark(time.time()):
        pass


async def test_helper_trim_keeps_only_the_newest_copies_of_one_chat(runtime):
    runtime.checkpoints.retention.last_run = time.time()
    runtime.settings.storage.checkpoint_keep = 2
    sid, other = session(runtime), session(runtime)
    copies = await helper_copies(runtime, sid, 5)
    untouched = await helper_copies(runtime, other, 4)
    # The trim is synchronous, so check the journal before the worker can run.
    assert runtime.checkpoints.retention.trim_helper_copies("alice", sid) == 3
    assert helper_ids(runtime, sid) == set(copies[-2:])
    assert deletion_ids(runtime) == set(copies[:3])
    assert helper_ids(runtime, other) == set(untouched)


async def test_hourly_pass_reduces_a_legacy_helper_backlog(runtime):
    runtime.checkpoints.retention.last_run = time.time()
    sid = session(runtime)
    copies = await helper_copies(runtime, sid, 45)
    checkpoint = await legacy_checkpoint(runtime, sid)
    age(runtime)
    # Each pass retires a bounded batch. The backlog clears across passes.
    assert runtime.checkpoints.retention.mark(time.time()) == 20
    mark_until_done(runtime)
    assert helper_ids(runtime, sid) == set(copies[-3:])
    assert exists(runtime, checkpoint)


async def test_kept_checkpoint_file_neither_keeps_nor_requires_helper_copies(runtime):
    runtime.checkpoints.retention.last_run = time.time()
    sid = session(runtime)
    copies = await helper_copies(runtime, sid, 6)
    checkpoint = await legacy_checkpoint(runtime, sid)
    age(runtime)
    mark_until_done(runtime)
    assert helper_ids(runtime, sid) == set(copies[-3:])
    # The kept checkpoint now lists deleted helper copies. Retention must still run.
    orphan, _ = await version(runtime, sid, "orphan", current=False)
    age(runtime)
    mark_until_done(runtime)
    assert not exists(runtime, orphan)
    assert exists(runtime, checkpoint)


async def test_kept_checkpoint_references_neither_keep_nor_require_helper_copies(runtime, storage):
    runtime.settings.storage.checkpoint_keep = 2
    sid = session(runtime)
    copies = await helper_copies(runtime, sid, 5)
    checkpoint = await legacy_checkpoint(runtime, sid)
    assert await runtime.checkpoints.drain()
    assert not (runtime.checkpoints.directory / checkpoint).exists()
    # Older releases wrote every listed object, including helper copies, to the index.
    references = runtime.db.record("alice", "checkpoint_references", checkpoint)
    assert references["objects"] == []
    legacy = [{"id": identity, "owner": "alice", "session": sid} for identity in copies]
    runtime.db.put_record(
        "alice",
        "checkpoint_references",
        checkpoint,
        {"digest": references["digest"], "owner": "alice", "session": sid, "objects": legacy},
    )
    rows = runtime.db.rows("SELECT * FROM context_objects WHERE session=?", (sid,))
    # While the rows exist, retention recognizes the listed ids as helper copies.
    roots = runtime.checkpoints.retention.roots("alice", sid, rows)
    assert copies[0] not in roots and copies[-1] in roots
    runtime.db.connection.executescript(MIGRATION.read_text())
    assert runtime.db.record("alice", "checkpoint_references", checkpoint)["objects"] == []
    age(runtime)
    mark_until_done(runtime)
    assert helper_ids(runtime, sid) == set(copies[-2:])
    orphan, _ = await version(runtime, sid, "orphan", current=False)
    age(runtime)
    mark_until_done(runtime)
    assert not exists(runtime, orphan)
    assert exists(runtime, checkpoint)


async def test_reference_migration_removes_only_helper_copy_ids(runtime):
    sid = session(runtime)
    copies = await helper_copies(runtime, sid, 2)
    source, _ = await version(runtime, sid, "kept source")
    listed = [{"id": identity, "owner": "alice", "session": sid} for identity in copies]
    kept = {"id": source, "owner": "alice", "session": sid}
    mixed = {"digest": "a", "owner": "alice", "session": sid, "objects": [kept, *listed]}
    clean = {"digest": "b", "owner": "alice", "session": sid, "objects": [kept]}
    only_helpers = {"digest": "c", "owner": "alice", "session": sid, "objects": listed}
    runtime.db.put_record("alice", "checkpoint_references", "mixed", mixed)
    runtime.db.put_record("alice", "checkpoint_references", "clean", clean)
    runtime.db.put_record("alice", "checkpoint_references", "helpers", only_helpers)
    before = runtime.db.one("SELECT value FROM records WHERE id='clean'")["value"]
    runtime.db.connection.executescript(MIGRATION.read_text())
    for name in ["mixed", "clean", "helpers"]:
        stored = json.loads(
            runtime.db.one("SELECT value FROM records WHERE id=?", (name,))["value"]
        )
        # The objects value must stay a real JSON array of objects, not a quoted string.
        assert isinstance(stored["objects"], list)
        assert all(isinstance(item, dict) for item in stored["objects"])
    assert runtime.db.record("alice", "checkpoint_references", "mixed")["objects"] == [kept]
    assert runtime.db.record("alice", "checkpoint_references", "mixed")["digest"] == "a"
    assert runtime.db.record("alice", "checkpoint_references", "helpers")["objects"] == []
    assert runtime.db.one("SELECT value FROM records WHERE id='clean'")["value"] == before


async def test_new_checkpoints_and_references_omit_helper_copies(runtime, storage):
    sid = session(runtime)
    source, _ = await version(runtime, sid, "current")
    copies = await helper_copies(runtime, sid, 2)
    checkpoint = await snapshot(runtime, sid, "current")
    saved = await runtime.checkpoints.get("alice", sid, checkpoint)
    assert [row["id"] for row in saved["objects"]] == [source]
    assert await runtime.checkpoints.drain()
    references = runtime.db.record("alice", "checkpoint_references", checkpoint)
    assert [item["id"] for item in references["objects"]] == [source]
    assert helper_ids(runtime, sid) == set(copies)


async def test_legacy_checkpoint_publishes_and_restores_without_deleted_helper_copies(
    runtime, storage
):
    sid = session(runtime)
    copies = await helper_copies(runtime, sid, 2)
    checkpoint = await legacy_checkpoint(runtime, sid)
    # Retention can delete listed helper copies before the checkpoint is published.
    runtime.db.execute("DELETE FROM context_objects WHERE kind='delegate_checkpoint'")
    assert await runtime.checkpoints.drain()
    pointer = json.loads(storage.objects[runtime.checkpoints.key("alice", sid, "latest.json")])
    assert pointer["id"] == checkpoint
    runtime.db.execute("DELETE FROM context_objects WHERE session=?", (sid,))
    runtime.db.save_history("alice", sid, [], status="idle")
    restored = await runtime.checkpoints.restore("alice", sid)
    assert {row["id"] for row in restored["objects"]} == set(copies)
    assert not helper_ids(runtime, sid)
    assert exists(runtime, checkpoint)


async def test_checkpoint_keep_sets_the_limit_for_checkpoints_and_helper_copies(runtime):
    runtime.checkpoints.retention.last_run = time.time()
    runtime.settings.storage.checkpoint_keep = 1
    sid = session(runtime)
    checkpoints = []
    for label in ["one", "two", "three"]:
        checkpoints.append(await snapshot(runtime, sid, label))
        runtime.db.execute(
            "UPDATE context_objects SET created=? WHERE id=?",
            (2000.0 + len(checkpoints), checkpoints[-1]),
        )
    copies = await helper_copies(runtime, sid, 3)
    age(runtime)
    mark_until_done(runtime)
    assert [exists(runtime, identity) for identity in checkpoints] == [False, False, True]
    assert helper_ids(runtime, sid) == {copies[-1]}
