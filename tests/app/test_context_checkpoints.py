"""R2 checkpoint durability and sandbox workspace recovery."""

import base64
import io
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from harness import ContextMemory, RunContext, UserMessage, tool
from theos.services.health.imports import SUMMARY_VERSION

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


async def test_gmail_detail_is_bounded_and_omits_attachment_payloads(runtime):
    body = "Invoice USD 42.00\n" + "Details. " * 600
    raw = {
        "id": "receipt-1",
        "threadId": "thread-1",
        "snippet": "Invoice USD 42.00",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "billing@example.com"},
                {"name": "Subject", "value": "October invoice"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
                },
                {
                    "filename": "invoice.pdf",
                    "mimeType": "application/pdf",
                    "body": {"attachmentId": "pdf-1", "size": 480_000, "data": "large-pdf"},
                },
            ],
        },
    }
    calls = []

    async def request(owner, method, path, **kwargs):
        calls.append(path)
        return raw

    runtime.gmail.request = request
    tools = runtime.gmail.tools("alice")
    result = await call_tool(
        tools,
        "gmail_get_message",
        message_id="receipt-1",
        body_limit=100,
    )
    assert calls == ["messages/receipt-1"]
    assert result["subject"] == "October invoice"
    assert len(result["body"]) == 100 and result["next_body_offset"] == 100
    assert result["attachments"] == [
        {
            "attachment_id": "pdf-1",
            "filename": "invoice.pdf",
            "mime_type": "application/pdf",
            "size": 480_000,
        }
    ]
    assert "large-pdf" not in json.dumps(result)
    later = await call_tool(
        tools,
        "gmail_get_message",
        message_id="receipt-1",
        body_offset=100,
        body_limit=100,
    )
    assert later["body"] == body[100:200]


async def test_gmail_search_returns_small_metadata_and_pagination(runtime):
    calls = []

    async def request(owner, method, path, **kwargs):
        calls.append((path, kwargs.get("params", {})))
        if path == "messages":
            return {
                "messages": [{"id": "mail-1"}],
                "nextPageToken": "page-2",
                "resultSizeEstimate": 80,
            }
        return {
            "threadId": "thread-1",
            "snippet": "Invoice from Northwind",
            "labelIds": ["INBOX", "CATEGORY_PROMOTIONS"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "billing@example.com"},
                    {"name": "Subject", "value": "October invoice"},
                ],
                "body": {"data": "large-message-body"},
            },
            "internalPayload": "not for the model",
        }

    runtime.gmail.request = request
    result = await call_tool(
        runtime.gmail.tools("alice"),
        "gmail_search_messages",
        query="from:billing@example.com",
        max_results=5,
    )
    assert result == {
        "messages": [
            {
                "id": "mail-1",
                "thread_id": "thread-1",
                "snippet": "Invoice from Northwind",
                "labels": ["INBOX"],
                "from": "billing@example.com",
                "subject": "October invoice",
            }
        ],
        "next_page_token": "page-2",
        "total_results": 80,
    }
    assert calls[0][1]["maxResults"] == 5
    assert "-in:spam -in:trash" in calls[0][1]["q"]


async def test_health_tool_returns_compact_summary_and_selected_detail(runtime):
    snapshot = {
        "schema_version": SUMMARY_VERSION,
        "from": "2026-10-01T00:00:00+00:00",
        "to": "2026-10-04T00:00:00+00:00",
        "days": [
            {
                "date": "2026-10-01",
                "source": "google_health",
                "steps": 12000,
                "distance_meters": 8000,
                "sleep": [{"minutes": 420, "stages": [{"stage": "deep", "minutes": 80}]}],
                "workouts": [{"type": "run", "minutes": 30, "calories_kcal": 240}],
                "heart_rate_zone_thresholds": [{"zone": "moderate", "min_bpm": 100}],
            },
            {"date": "2026-10-02", "steps": 9000, "distance_meters": 6000},
        ],
    }
    runtime.db.put_record("alice", "health", "summary", snapshot)
    tools = runtime.health.tools("alice")
    summary = await call_tool(tools, "get_health_summary")
    assert summary["days"][0] == {
        "date": "2026-10-01",
        "steps": 12000,
        "distance_meters": 8000,
        "sleep_minutes": 420,
        "workout_count": 1,
        "workout_minutes": 30,
    }
    assert "sleep" not in summary["days"][0]

    detail = await call_tool(
        tools,
        "get_health_summary",
        start_date="2026-10-01",
        end_date="2026-10-01",
        metrics=["sleep", "heart_rate_zone_thresholds"],
    )
    assert detail["days"] == [
        {
            "date": "2026-10-01",
            "sleep": [{"minutes": 420, "stages": [{"stage": "deep", "minutes": 80}]}],
            "heart_rate_zone_thresholds": [{"zone": "moderate", "min_bpm": 100}],
        }
    ]

    requested = {}

    async def import_summary(owner, start_date, end_date, *, save):
        requested.update(start=start_date, end=end_date, save=save)
        return {
            "from": "2026-10-05T00:00:00+00:00",
            "to": "2026-10-06T00:00:00+00:00",
            "days": [{"date": "2026-10-05", "sleep": [{"minutes": 360}]}],
        }

    runtime.health.import_summary = import_summary
    older = await call_tool(
        tools,
        "get_health_summary",
        start_date="2026-10-05",
        end_date="2026-10-05",
        metrics=["sleep"],
    )
    assert requested == {
        "start": date.fromisoformat("2026-10-05"),
        "end": date.fromisoformat("2026-10-05"),
        "save": False,
    }
    assert older["days"] == [{"date": "2026-10-05", "sleep": [{"minutes": 360}]}]

    assert {tool.name for tool in tools}.isdisjoint({"source_read", "source_to_workspace"})


async def test_pending_transfer_retries_without_repeating_connector(runtime, storage):
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    storage.fail = True
    identity = await runtime.checkpoints.put("alice", row["id"], "test_object", {"value": 42})
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
    memory = ContextMemory("summary", 1)
    await runtime.checkpoints.save("alice", sid, [UserMessage("task")], memory, "after_model")
    assert await runtime.checkpoints.drain()
    runtime.db.execute("DELETE FROM tool_runs WHERE session=?", (sid,))
    await runtime.checkpoints.restore("alice", sid)
    restored = runtime.session("alice", sid)
    assert json.loads(restored["memory"]) == memory.to_dict()
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

    async def read(path, *, range_header):
        assert range_header == f"bytes=0-{runtime.settings.max_upload_bytes}"
        return data[path][: runtime.settings.max_upload_bytes + 1]

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
        "alice", sid, "purchases.csv", "amount,currency\r\n84,USD"
    )
    assert second["workspace"]["files"]["/workspace/purchases.csv"]["version"] == 2
    data.clear()
    sandbox.id = "sandbox-2"
    await runtime.workspaces.save("alice", sid)
    assert data["/workspace/purchases.csv"] == b"amount,currency\r\n84,USD"
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

    async def read(path, *, range_header):
        assert range_header == f"bytes=0-{runtime.settings.max_upload_bytes}"
        return data[path][: runtime.settings.max_upload_bytes + 1]

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
    async def run_command(command: str):
        """Execute in the workspace."""
        raise RuntimeError("command failed after writing output")

    original = replace(run_command, parallel_safe=True, view="command", timeout_s=12)
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


async def test_read_only_workspace_tools_do_not_require_a_checkpoint(runtime, monkeypatch):
    row = runtime.db.create_session("alice", "gpt-6-luna", "none")

    @tool
    async def read_file(path: str):
        """Read a staged file."""
        return {"content": f"read {path}"}

    wrapped = runtime.workspaces.wrap(read_file, "alice", row["id"])

    async def prepare(*args):
        pass

    async def save(*args):
        pytest.fail("a read-only operation must not checkpoint /workspace")

    monkeypatch.setattr(runtime.workspaces, "prepare", prepare)
    monkeypatch.setattr(runtime.workspaces, "save", save)
    result = await wrapped.execute(
        wrapped.input_model(path="/tmp/theos-results/read.json"), RunContext(None)
    )
    assert result == {"content": "read /tmp/theos-results/read.json"}


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


@pytest.mark.parametrize("working_view", [False, True])
async def test_remote_restore_never_executes_calls_that_lack_attempt_records(
    runtime, storage, working_view
):
    from contextlib import asynccontextmanager

    from harness import AssistantMessage, ToolCall, ToolResultMessage, message_to_dict
    from harness.testing import FakeModel

    from .conftest import collect

    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    call = ToolCall("old-call", "save_once", {"value": 42})
    history = [UserMessage("Save this value."), AssistantMessage(tool_calls=[call])]
    memory = (
        ContextMemory.from_dict(
            {
                "schema_version": 3,
                "summary": "Keep the task and uncertain outcomes.",
                "covered_messages": len(history),
                "working_messages": [message_to_dict(message) for message in history],
            }
        )
        if working_view
        else ContextMemory("Keep the task and uncertain outcomes.", 0)
    )
    await runtime.checkpoints.save("alice", row["id"], history, memory, "after_model")
    assert await runtime.checkpoints.drain()
    # The actual effect occurred after the uploaded snapshot. Local state was then lost.
    effects = [42]

    @tool
    async def save_once(value: int):
        effects.append(value)
        return {"saved": value}

    async def registry(session):
        return [runtime.journal_tool(save_once, session)]

    runtime.tools = registry
    restored = await runtime.checkpoints.restore("alice", row["id"])
    restored_memory = json.loads(runtime.session("alice", row["id"])["memory"])
    assert restored_memory["summary"] == memory.summary
    model = FakeModel([AssistantMessage("Check the external service before another write.")])

    @asynccontextmanager
    async def factory(*args):
        yield model

    runtime.models = factory
    result = await collect(runtime.start("alice", row["id"], "Continue safely."))
    assert result[-1]["status"] == "completed"
    assert effects == [42]
    record = runtime.db.one(
        "SELECT status FROM tool_runs WHERE session=? AND call_id=?", (row["id"], call.id)
    )
    assert record["status"] == "unknown"
    replies = [
        m
        for m in model.requests[0].messages
        if isinstance(m, ToolResultMessage) and m.call_id == call.id
    ]
    assert len(replies) == 1 and replies[0].status == "unknown"
    assert restored["history"][-1]["status"] == "unknown"


async def test_remote_snapshot_without_call_intents_requires_explicit_reconciliation(
    runtime, storage, scripted_models
):
    from harness import AssistantMessage, ToolCall

    from .conftest import collect

    row = runtime.db.create_session("alice", "gpt-6-luna", "none")
    await runtime.checkpoints.save(
        "alice", row["id"], [UserMessage("Create an entry.")], ContextMemory(), "before_model"
    )
    assert await runtime.checkpoints.drain()
    await runtime.checkpoints.restore("alice", row["id"])
    assert await runtime.tools(runtime.session("alice", row["id"])) == []
    effects = []

    @tool
    async def write_entry(value: int):
        effects.append(value)
        return {"saved": value}

    async def registry(session):
        return [runtime.journal_tool(write_entry, session)]

    runtime.tools = registry
    scripted_models.responses.append(
        [
            AssistantMessage(tool_calls=[ToolCall("new-call", "write_entry", {"value": 42})]),
            AssistantMessage("Operator review is required."),
        ]
    )
    result = await collect(runtime.start("alice", row["id"], "Continue."))
    assert result[-1]["status"] == "completed"
    assert effects == []
    assert runtime.db.one("SELECT id FROM records WHERE kind='remote_recovery_review'") is not None
    with pytest.raises(LookupError):
        runtime.checkpoints.confirm_restore_review("bob", row["id"])
    runtime.checkpoints.confirm_restore_review("alice", row["id"])
    scripted_models.responses.append(
        [
            AssistantMessage(tool_calls=[ToolCall("reviewed-call", "write_entry", {"value": 42})]),
            AssistantMessage("New action completed after review."),
        ]
    )
    await collect(
        runtime.start("alice", row["id"], "I reconciled the external service. Make a new entry.")
    )
    assert effects == [42]
