"""Unified execution, response attachments, and automatic input availability."""

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from harness import ContextMemory, RunContext, ToolResultMessage, UserMessage
from theos.runtime import tools as registry
from theos.runtime.hooks import build_hooks
from theos.services.sandbox.tools import sandbox_tools

from .conftest import call_tool


@pytest.fixture
def workspace(runtime, monkeypatch):
    session = runtime.db.create_session("alice", "gpt-6-luna", "none")
    data, commands = {}, []

    async def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(
            error=None, exit_code=0, model_dump=lambda **kwargs: {"exit_code": 0}
        )

    async def read(path, range_header):
        return data[path][: runtime.settings.max_upload_bytes + 1]

    async def write(path, value):
        data[path] = value.encode() if isinstance(value, str) else value

    async def listing(spec):
        return [{"path": key, "entry_type": "file"} for key in data]

    box = SimpleNamespace(
        id="task-1",
        commands=SimpleNamespace(run=run),
        files=SimpleNamespace(read_bytes=read, write_file=write, list_directory=listing),
    )

    async def get(*args):
        return box

    monkeypatch.setattr(runtime.sandboxes, "get", get)
    return session, box, data, commands


async def test_registry_keeps_history_and_only_two_workspace_tools(runtime):
    runtime.settings.sandbox.enabled = True
    session = runtime.db.create_session("alice", "gpt-6-luna", "none")
    names = {tool.name for tool in await registry.build_tools(runtime, session)}
    assert {"run_command", "attach_file", "history_read", "history_search"} <= names
    assert not names & {
        "execute_code",
        "browser",
        "view_image",
        "read_file",
        "write_file",
        "list_files",
        "upload_file",
        "send_file_to_user",
        "list_user_files",
        "archive_user_file",
        "restore_user_file",
        "delete_user_file",
    }


async def test_inputs_stage_once_and_deletions_survive_replacement(runtime, workspace):
    session, box, data, commands = workspace
    runtime.settings.sandbox.enabled = True
    source = runtime.files.save("alice", "rows.csv", "text/csv", b"value\r\n42")
    message = runtime.input_message("alice", "Analyze this", [source["id"]])
    assert "file ID" not in message.content
    path = runtime.workspaces.input_path(source)
    assert path in message.content
    await runtime.workspaces.stage_inputs("alice", session["id"], [message])
    assert data[path] == b"value\r\n42"
    data["/workspace/result.txt"] = b"42"
    await runtime.workspaces.save("alice", session["id"])
    del data[path]
    await runtime.workspaces.save("alice", session["id"])
    box.id = "replacement"
    data.clear()
    await runtime.workspaces.stage_inputs("alice", session["id"], [message])
    await runtime.workspaces.prepare("alice", session["id"])
    assert path not in data
    assert data["/workspace/result.txt"] == b"42"
    with pytest.raises(LookupError):
        runtime.input_message("bob", "Analyze this", [source["id"]])


async def test_image_pixels_reach_model_without_attachment_event(runtime, workspace):
    session, box, data, commands = workspace
    image = io.BytesIO()
    Image.new("RGB", (3, 2), "green").save(image, "PNG")
    data["/workspace/chart.png"] = image.getvalue()
    tool = sandbox_tools(runtime.sandboxes, "alice", session["id"])[0]
    ctx = RunContext(None)
    result = await tool.execute(tool.input_model(inspect_images=["chart.png"]), ctx)
    assert result["image_errors"] == []
    assert "file_id" not in result
    request = SimpleNamespace(messages=[], options={})
    hooks = build_hooks(runtime, session)
    await hooks.after_tool(ToolResultMessage("inspect", "run_command", json.dumps(result)), ctx)
    # A new context models a restart after the command result, before image injection.
    ctx = RunContext(None)
    await hooks.before_model(request, ctx)
    assert len(request.messages) == 1
    assert request.messages[0].images[0].url.startswith("data:image/png;base64,")
    assert not ctx.state["view_images"] if "view_images" in ctx.state else True
    request2 = SimpleNamespace(messages=[], options={})
    await hooks.before_model(request2, ctx)
    assert not request2.messages


async def test_failed_image_inspection_does_not_repeat_a_completed_command(runtime, workspace):
    session, box, data, commands = workspace
    result = await call_tool(
        sandbox_tools(runtime.sandboxes, "alice", session["id"]),
        "run_command",
        command="python analysis.py",
        inspect_images=["missing.png"],
    )
    assert commands == ["python analysis.py"]
    assert result["exit_code"] == 0
    assert result["image_errors"] == [{"path": "missing.png", "error": "KeyError"}]


async def test_attachment_is_in_the_session_recovery_journal(runtime, workspace):
    session, box, data, commands = workspace
    data["/workspace/report.pdf"] = b"%PDF-1.7\r\noriginal\x00"
    tools = [
        runtime.workspaces.wrap(item, "alice", session["id"])
        for item in sandbox_tools(runtime.sandboxes, "alice", session["id"])
    ]
    attached = await call_tool(tools, "attach_file", path="report.pdf")
    data["/workspace/report.pdf"] = b"new version"
    row = runtime.db.record(
        "alice", "response_attachment", session["id"] + ":" + attached["file_id"]
    )
    saved = await runtime.checkpoints.get("alice", session["id"], row["source_id"])
    import base64

    assert base64.b64decode(saved["data"]) == b"%PDF-1.7\r\noriginal\x00"
    assert (
        Path(runtime.files.get("alice", attached["file_id"])["path"]).read_bytes()
        == b"%PDF-1.7\r\noriginal\x00"
    )
    await runtime.checkpoints.save(
        "alice", session["id"], [UserMessage("Report")], ContextMemory(), "test"
    )
    pointer = runtime.db.record("alice", "context_checkpoint", session["id"])
    checkpoint = await runtime.checkpoints.get("alice", session["id"], pointer["id"])
    assert checkpoint["attachments"][0]["file"]["id"] == attached["file_id"]
    assert "original" not in json.dumps(row)
