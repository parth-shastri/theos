"""R2 checkpoint durability, connector paging, and sandbox workspace recovery."""

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from harness import ContextMemory, RunContext, UserMessage, tool
from theos.runtime.connector_wrappers import ConnectorResults

from .conftest import call_tool


class Objects:
    def __init__(self):
        self.objects = {}
        self.fail = False

    def upload_file(self, path, bucket, key):
        if self.fail:
            raise OSError("storage offline")
        self.objects[key] = Path(path).read_bytes()

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.objects[key])

    def put_object(self, **kwargs):
        if self.fail:
            raise OSError("storage offline")
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

    def close(self):
        pass


@pytest.fixture
def storage(runtime, monkeypatch):
    runtime.settings.storage.endpoint = "https://example.invalid"
    runtime.settings.storage.bucket = "private"
    runtime.settings.storage.access_key = SecretStr("test")
    runtime.settings.storage.secret_key = SecretStr("test")
    client = Objects()
    monkeypatch.setattr(runtime.files, "storage_client", lambda: client)
    return client


async def test_gmail_wrapper_preserves_raw_source_pages_and_owner_boundary(runtime, storage):
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    body = "Invoice USD 42.00\n" + "Details. " * 6000
    raw = {
        "id": "receipt-1",
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
        },
    }
    calls = []

    @tool
    async def gmail_get_message(message_id: str):
        """Read a message."""
        calls.append(message_id)
        return raw

    adapters = ConnectorResults(runtime, row)
    wrapped = adapters.wrap(gmail_get_message)
    result = await wrapped.execute(
        wrapped.input_model(message_id="receipt-1"), RunContext(deps=None)
    )
    assert (
        calls == ["receipt-1"] and result["next_offset"] == 12000 and result["storage"] == "pending"
    )
    assert (
        "Invoice USD 42.00" in result["content"]
        and raw["payload"]["body"]["data"] not in result["content"]
    )
    source = result["source_id"]
    assert await runtime.checkpoints.drain()
    record = runtime.db.one("SELECT * FROM context_objects WHERE id=?", (source,))
    Path(record["path"]).unlink()
    saved = await runtime.checkpoints.get("alice", row["id"], source)
    assert saved["raw"] == raw
    page = await call_tool(adapters.tools(), "source_read", source_id=source, offset=12000)
    assert page["content"] == saved["text"][12000:16000]
    with pytest.raises(LookupError):
        await runtime.checkpoints.get("bob", row["id"], source)
    other = runtime.db.create_session("alice", "gpt-6-luna", "none")
    with pytest.raises(LookupError):
        await runtime.checkpoints.get("alice", other["id"], source)
    assert len(calls) == 1


async def test_health_wrapper_preserves_units_and_complete_source(runtime, storage):
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")

    @tool
    async def get_health_summary():
        """Read daily health."""
        return {
            "days": [
                {"date": f"2026-10-{i:02}", "steps": 12000, "distance": {"value": 8, "unit": "km"}}
                for i in range(1, 31)
            ],
            "status": "complete",
        }

    adapters = ConnectorResults(runtime, row)
    wrapper = adapters.wrap(get_health_summary)
    result = await wrapper.execute(wrapper.input_model(), RunContext(deps=None))
    saved = await runtime.checkpoints.get("alice", row["id"], result["source_id"])
    assert saved["raw"]["days"][0]["distance"] == {"value": 8, "unit": "km"}
    assert saved["raw"]["status"] == "complete"


async def test_pending_transfer_retries_without_repeating_connector(runtime, storage):
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    storage.fail = True
    identity = await runtime.checkpoints.put(
        "alice", row["id"], "source", {"raw": {"value": 42}, "text": "42"}
    )
    assert (
        runtime.db.one("SELECT status FROM context_objects WHERE id=?", (identity,))["status"]
        == "pending"
    )
    memory = ContextMemory()
    await runtime.checkpoints.save("alice", row["id"], [UserMessage("task")], memory, "after_tool")
    assert not await runtime.checkpoints.flush()
    assert runtime.checkpoints.key("alice", row["id"], "latest.json") not in storage.objects
    storage.fail = False
    await runtime.checkpoints.save(
        "alice", row["id"], [UserMessage("task")], memory, "before_model"
    )
    assert await runtime.checkpoints.drain()
    assert runtime.checkpoints.key("alice", row["id"], "latest.json") in storage.objects


async def test_r2_restore_recovers_model_state_and_uncertain_actions(runtime, storage):
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    sid = row["id"]
    runtime.db.execute(
        "INSERT INTO tool_runs VALUES (?,?,?,?,?)",
        (sid, "call1", "gmail_send_draft", "running", None),
    )
    memory = ContextMemory(
        "summary",
        1,
        working_messages=[{"type": "user", "content": "task", "images": []}],
        state={
            "compression_count": 2,
            "usage_anchor": {"tokens": 42000},
            "references": {"anchors": [], "record_ids": ["Ssaved-source"], "unknown_tools": []},
        },
    )
    await runtime.checkpoints.save("alice", sid, [UserMessage("task")], memory, "after_model")
    assert await runtime.checkpoints.drain()
    runtime.db.execute("DELETE FROM tool_runs WHERE session=?", (sid,))
    await runtime.checkpoints.restore("alice", sid)
    restored = runtime.session("alice", sid)
    assert json.loads(restored["memory"])["state"]["usage_anchor"]["tokens"] == 42000
    assert json.loads(restored["memory"])["state"]["references"] == memory.state["references"]
    assert (
        runtime.db.one("SELECT status FROM tool_runs WHERE call_id=?", ("call1",))["status"]
        == "unknown"
    )
    assert runtime.db.load_history("alice", sid)[0].content == "task"
    with pytest.raises(ValueError):
        await runtime.checkpoints.restore("alice", sid)


async def test_workspace_saves_changed_versions_and_restores_after_loss(
    runtime, storage, monkeypatch
):
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    sid = row["id"]
    data = {}

    async def run(*args, **kwargs):
        return SimpleNamespace(error=None)

    async def write(path, content):
        data[path] = content.encode() if isinstance(content, str) else content

    async def read(path, limit):
        return data[path][:limit]

    async def listing(spec):
        return [{"path": p, "entry_type": "file"} for p in data]

    sandbox = SimpleNamespace(
        id="sandbox-1",
        commands=SimpleNamespace(run=run),
        files=SimpleNamespace(write_file=write, read_bytes=read, list_directory=listing),
    )

    async def get(*args):
        return sandbox

    monkeypatch.setattr(runtime.sandboxes, "get", get)
    first = await runtime.workspaces.write("alice", sid, "purchases.csv", "amount,currency\n42,USD")
    assert first["workspace"]["files"]["/workspace/purchases.csv"]["version"] == 1
    second = await runtime.workspaces.write(
        "alice", sid, "purchases.csv", "amount,currency\n84,USD"
    )
    assert second["workspace"]["files"]["/workspace/purchases.csv"]["version"] == 2
    data.clear()
    sandbox.id = "sandbox-2"
    await runtime.workspaces.save("alice", sid)
    assert b"84,USD" in data["/workspace/purchases.csv"]
    with pytest.raises(ValueError):
        await runtime.workspaces.write("alice", sid, "../escape", "bad")


async def test_workspace_reconnect_keeps_newer_files_and_walks_nested_directories(
    runtime, storage, monkeypatch
):
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    sid = row["id"]
    data = {"/workspace/nested/result.csv": b"amount\n42"}

    async def run(*args, **kwargs):
        return SimpleNamespace(error=None)

    async def listing(spec):
        if spec.path == "/workspace":
            return [{"path": "/workspace/nested", "entry_type": "directory"}]
        return [{"path": p, "entry_type": "file"} for p in data]

    async def read(path, limit):
        return data[path][:limit]

    async def write(path, value):
        data[path] = value

    sandbox = SimpleNamespace(
        id="same-live-sandbox",
        commands=SimpleNamespace(run=run),
        files=SimpleNamespace(list_directory=listing, read_bytes=read, write_file=write),
    )

    async def get(*args):
        return sandbox

    monkeypatch.setattr(runtime.sandboxes, "get", get)
    await runtime.workspaces.save("alice", sid)
    data["/workspace/nested/result.csv"] = b"amount\n84"
    await runtime.workspaces.prepare("alice", sid)
    assert data["/workspace/nested/result.csv"] == b"amount\n84"
    manifest = await runtime.workspaces.save("alice", sid)
    assert manifest["files"]["/workspace/nested/result.csv"]["version"] == 2


async def test_wrappers_preserve_execution_metadata_and_save_failed_command_files(
    runtime, monkeypatch
):
    from dataclasses import replace

    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    saved = []

    @tool
    async def sandbox_run_command(command: str):
        """Execute in the workspace."""
        raise RuntimeError("command failed after writing output")

    original = replace(sandbox_run_command, parallel_safe=True, view="command", timeout_s=12)
    wrapped = runtime.workspaces.wrap(original, "alice", row["id"])

    async def prepare(*args):
        pass

    async def save(*args):
        saved.append(True)

    monkeypatch.setattr(runtime.workspaces, "prepare", prepare)
    monkeypatch.setattr(runtime.workspaces, "save", save)
    assert wrapped.parallel_safe and wrapped.view == "command" and wrapped.timeout_s == 12
    with pytest.raises(RuntimeError):
        await wrapped.execute(wrapped.input_model(command="example"), RunContext(None))
    assert saved == [True]


async def test_slow_replication_never_blocks_local_checkpoint_or_recovery(runtime, storage):
    import asyncio
    import threading

    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    upload = storage.upload_file

    def blocked(*args):
        loop.call_soon_threadsafe(started.set)
        if not release.wait(3):
            raise TimeoutError("blocked diagnostic storage")
        return upload(*args)

    storage.upload_file = blocked
    try:
        identity = await runtime.checkpoints.save(
            "alice", row["id"], [UserMessage("saved task")], ContextMemory(), "before_model"
        )
        await asyncio.wait_for(started.wait(), 1)
        second = await asyncio.wait_for(
            runtime.checkpoints.save(
                "alice",
                row["id"],
                [UserMessage("saved correction")],
                ContextMemory(),
                "after_model",
            ),
            1,
        )
        assert identity != second
        assert (await runtime.checkpoints.get("alice", row["id"], second))["history"][0][
            "content"
        ] == "saved correction"
        assert runtime.checkpoints.key("alice", row["id"], "latest.json") not in storage.objects
        assert len([t for t in asyncio.all_tasks() if t is runtime.checkpoints.worker]) == 1
    finally:
        release.set()
    assert await runtime.checkpoints.drain()
    pointer = json.loads(
        storage.objects[runtime.checkpoints.key("alice", row["id"], "latest.json")]
    )
    assert pointer["id"] == second


async def test_replication_restarts_from_local_journal_without_replaying_actions(runtime, storage):
    from theos.services.files.checkpoints import Checkpoints

    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    storage.fail = True
    runtime.db.execute(
        "INSERT INTO tool_runs VALUES (?,?,?,?,?)",
        (row["id"], "sent-once", "gmail_send_draft", "unknown", None),
    )
    identity = await runtime.checkpoints.save(
        "alice", row["id"], [UserMessage("task")], ContextMemory(), "turn_end"
    )
    assert not await runtime.checkpoints.flush()
    await runtime.checkpoints.close()
    storage.fail = False
    runtime.checkpoints = Checkpoints(runtime.files, runtime.tracing)
    assert await runtime.checkpoints.drain()
    assert (
        runtime.db.one("SELECT status FROM context_objects WHERE id=?", (identity,))["status"]
        == "saved"
    )
    assert (
        runtime.db.one("SELECT status FROM tool_runs WHERE call_id=?", ("sent-once",))["status"]
        == "unknown"
    )


async def test_failed_pointer_is_retried_even_when_objects_are_saved(runtime, storage):
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    put = storage.put_object

    def fail_pointer(**kw):
        raise OSError("storage outage")

    storage.put_object = fail_pointer
    await runtime.checkpoints.save(
        "alice", row["id"], [UserMessage("task")], ContextMemory(), "turn_end"
    )
    assert not await runtime.checkpoints.flush()
    assert (
        runtime.db.one("SELECT COUNT(*) AS count FROM context_objects WHERE status='pending'")[
            "count"
        ]
        == 0
    )
    storage.put_object = put
    assert await runtime.checkpoints.drain()
    assert runtime.checkpoints.key("alice", row["id"], "latest.json") in storage.objects


async def test_failed_transfer_batch_does_not_starve_another_owner(runtime, storage):
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    other = runtime.db.create_session("bob", "gpt-6-luna", "none")
    for i in range(20):
        identity = await runtime.checkpoints.put("alice", row["id"], "source", {"raw": i})
        Path(
            runtime.db.one("SELECT path FROM context_objects WHERE id=?", (identity,))["path"]
        ).unlink()
    identity = await runtime.checkpoints.save(
        "bob", other["id"], [UserMessage("safe task")], ContextMemory(), "turn_end"
    )
    assert not await runtime.checkpoints.flush()
    await runtime.checkpoints.flush()
    assert (
        runtime.db.one("SELECT status FROM context_objects WHERE id=?", (identity,))["status"]
        == "saved"
    )
    pointer = json.loads(
        storage.objects[runtime.checkpoints.key("bob", other["id"], "latest.json")]
    )
    assert pointer["id"] == identity
