"""Contract tests for optional services, generated files, and background recovery."""

import json
import logging
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from pydantic import BaseModel

from harness import AssistantMessage, ToolCall
from theos.backup import backup, restore
from theos.operations.logging import SafeFormatter
from theos.runtime.scheduler import Scheduler
from theos.services.files.catalog import Files
from theos.services.google.oauth import OAuth
from theos.services.health.client import Health
from theos.services.information import information_tools
from theos.services.sandbox.client import Sandboxes
from theos.services.voice.tools import voice_tools

from .conftest import call_tool, collect
from .test_oauth_gmail_health import configure


async def test_search_fallback_weather_and_skill_resources(settings, tmp_path):
    from pydantic import SecretStr

    settings.exa_key = SecretStr("exa-key")
    settings.brave_key = SecretStr("brave-key")
    root = tmp_path / "skills"
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "SKILL.md").write_text("Read the note before answering.")
    settings.skills_dir = root
    seen = []

    def endpoint(request):
        seen.append(request)
        if request.url.host == "api.exa.ai":
            return httpx.Response(503)
        if request.url.host == "api.search.brave.com":
            assert request.headers["X-Subscription-Token"] == "brave-key"
            return httpx.Response(200, json={"web": {"results": [{"title": "Result"}]}})
        if request.url.host.startswith("geocoding"):
            return httpx.Response(
                200, json={"results": [{"name": "Pune", "latitude": 18.5, "longitude": 73.8}]}
            )
        return httpx.Response(200, json={"current": {"temperature_2m": 24}, "daily": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        tools = information_tools(settings, http)
        assert (await call_tool(tools, "web_search", query="test"))["web"]["results"]
        weather = await call_tool(tools, "get_weather", location="Pune", days=2)
        assert weather["forecast"]["current"]["temperature_2m"] == 24
        assert await call_tool(tools, "list_skills") == ["notes"]
        assert "Read the note" in (await call_tool(tools, "load_skill", name="notes"))["content"]
        with pytest.raises(LookupError):
            await call_tool(tools, "load_skill", name="notes", resource="../../config.py")


async def test_file_archive_restore_delete_and_ownership(runtime, monkeypatch):
    objects = {}

    class Storage:
        def upload_file(self, path, bucket, key):
            objects[key] = Path(path).read_bytes()

        def download_file(self, bucket, key, path):
            Path(path).write_bytes(objects[key])

        def delete_object(self, Bucket, Key):
            del objects[Key]

        def close(self):
            pass

    monkeypatch.setattr(runtime.files, "storage_client", lambda: Storage())
    row = runtime.files.save("alice", "../../report.txt", "text/plain", b"Report")
    assert row["name"] == "report.txt"
    await runtime.files.archive("alice", row["id"])
    Path(row["path"]).unlink()
    await runtime.files.restore("alice", row["id"])
    assert Path(row["path"]).read_bytes() == b"Report"
    with pytest.raises(LookupError):
        await runtime.files.delete("bob", row["id"])
    assert len(objects) == 1
    await runtime.files.delete("alice", row["id"])
    assert not objects and not Path(row["path"]).exists()


async def test_voice_contracts_and_generated_file(runtime):
    from pydantic import SecretStr

    runtime.settings.transcription_url = "http://speech/v1"
    runtime.settings.kokoro_url = "http://kokoro/v1"
    runtime.settings.kokoro_key = SecretStr("private-speech-key")

    def endpoint(request):
        if request.url.path.endswith("/transcriptions"):
            assert b"whisper-1" in request.content
            return httpx.Response(200, json={"text": "Please set a reminder."})
        payload = json.loads(request.content)
        assert payload["model"] == "kokoro" and payload["response_format"] == "mp3"
        assert payload["voice"] == "am_michael(0.7)+bm_george(0.3)"
        assert payload["speed"] == 0.9
        assert request.headers["Authorization"] == "Bearer private-speech-key"
        return httpx.Response(200, content=b"ID3audio", headers={"Content-Type": "audio/mpeg"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        files = Files(
            runtime.settings, runtime.db, http, speech_renderer=runtime.files.voice.prepare
        )
        voice = files.save("alice", "voice.ogg", "audio/ogg", b"voice")
        assert await files.transcribe("alice", voice["id"]) == "Please set a reminder."
        result = await call_tool(
            voice_tools(files.voice, "alice"), "send_text_to_speech", text="Hello"
        )
        assert files.get("alice", result["file_id"])["media_type"] == "audio/mpeg"
        with pytest.raises(LookupError):
            files.get("bob", result["file_id"])


@pytest.mark.parametrize("use_server_proxy", [False, True])
async def test_sandbox_contracts_and_isolated_state(runtime, monkeypatch, use_server_proxy):
    from code_interpreter import CodeInterpreter
    from opensandbox import Sandbox

    runtime.settings.sandbox.use_server_proxy = use_server_proxy

    class Result(BaseModel):
        output: str = "ok"

    output = BytesIO()
    Image.new("RGB", (2, 2)).save(output, format="PNG")
    remote_files = {"/tmp/image.png": output.getvalue()}
    commands, created, connected = [], [], []

    class RemoteFiles:
        async def write_file(self, path, data):
            remote_files[path] = data

        async def read_file(self, path, **kwargs):
            return remote_files[path]

        async def read_bytes(self, path, **kwargs):
            assert kwargs == {"range_header": f"bytes=0-{runtime.settings.max_upload_bytes}"}
            return remote_files[path][: runtime.settings.max_upload_bytes + 1]

        async def list_directory(self, entry):
            assert entry.path == "/tmp"
            return [Result(output="file")]

    async def run(command, **kwargs):
        commands.append(command)
        return Result()

    async def noop(*args, **kwargs):
        pass

    sandbox = SimpleNamespace(
        id="sandbox1",
        files=RemoteFiles(),
        commands=SimpleNamespace(run=run),
        close=noop,
        kill=noop,
        renew=noop,
        get_info=lambda: run("info"),
    )

    async def create(*args, **kwargs):
        created.append(kwargs)
        assert kwargs["env"] == {} and "volumes" not in kwargs
        assert kwargs["entrypoint"] == ["/opt/code-interpreter/code-interpreter.sh"]
        assert kwargs["connection_config"].use_server_proxy is use_server_proxy
        return sandbox

    async def connect(sandbox_id, **kwargs):
        connected.append(sandbox_id)
        assert kwargs["connection_config"].use_server_proxy is use_server_proxy
        return sandbox

    monkeypatch.setattr(Sandbox, "create", create)
    monkeypatch.setattr(Sandbox, "connect", connect)

    async def interpreter(**kwargs):
        return SimpleNamespace(codes=SimpleNamespace(run=run))

    monkeypatch.setattr(CodeInterpreter, "create", interpreter)
    tools = runtime.sandboxes.tools("alice", "session1")
    assert "manage_workspace" not in {item.name for item in tools}
    await call_tool(tools, "write_file", path="/tmp/note", content="hello")
    assert (await call_tool(tools, "read_file", path="/tmp/note"))["content"] == "hello"
    assert await call_tool(tools, "list_files", path="/tmp")
    await call_tool(tools, "run_command", command="pwd")
    await call_tool(tools, "execute_code", code="print(1)")
    await call_tool(tools, "browser", arguments=["open", "https://example.org/a;echo bad"])
    assert commands[-1] == "agent-browser open 'https://example.org/a;echo bad'"
    result = await call_tool(tools, "view_image", path="/tmp/image.png")
    assert runtime.files.image("alice", result["file_id"])
    assert (
        Path(runtime.files.get("alice", result["file_id"])["path"]).read_bytes()
        == output.getvalue()
    )
    payload = b"binary\r\n\x00\xff\r\n"
    upload = runtime.files.save("alice", "input.txt", "application/octet-stream", payload)
    await call_tool(tools, "upload_file", file_id=upload["id"], path="/tmp/input.txt")
    delivered = await call_tool(tools, "send_file_to_user", path="/tmp/input.txt")
    assert Path(runtime.files.get("alice", delivered["file_id"])["path"]).read_bytes() == payload
    runtime.settings.max_upload_bytes = 1024
    remote_files["/tmp/oversized.bin"] = b"x" * 1025
    with pytest.raises(ValueError, match="upload limit"):
        await call_tool(tools, "send_file_to_user", path="/tmp/oversized.bin")
    staged = await runtime.sandboxes.stage_result(
        "alice", "session1", "gmail_get_message", '{"body": "selected text"}'
    )
    assert staged["path"].startswith("/tmp/theos-results/gmail_get_message-")
    assert remote_files[staged["path"]] == b'{"body": "selected text"}'
    await runtime.sandboxes.close()
    restarted = Sandboxes(runtime.settings, runtime.db, runtime.files)
    await restarted.get("alice", "session1")
    assert connected == ["sandbox1"]
    assert len(created) == 1
    await restarted.get("bob", "session1")
    assert len(created) == 2
    await restarted.destroy("bob", "session1")
    with pytest.raises(LookupError):
        runtime.db.record("bob", "sandbox", "session1")
    await restarted.close()


async def test_health_import_normalizes_and_paginates(runtime):
    configure(runtime.settings)
    calls = []

    def endpoint(request):
        calls.append(request)
        if "/steps/" in request.url.path:
            component = {
                "steps": {
                    "count": 100,
                    "interval": {
                        "startTime": "2026-10-03T08:00:00Z",
                        "endTime": "2026-10-03T08:05:00Z",
                    },
                }
            }
            return httpx.Response(
                200,
                json={
                    "dataPoints": [component],
                    **({"nextPageToken": "next"} if "pageToken" not in request.url.params else {}),
                },
            )
        return httpx.Response(200, json={"dataPoints": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        oauth = OAuth(runtime.settings, runtime.db, http)
        oauth.save(
            "telegram:123", "health", {"access_token": "a", "expires_at": time.time() + 1000}
        )
        health = Health(oauth, runtime.settings, runtime.db, http)
        result = await health.import_summary("telegram:123")
        assert result["days"][0]["steps"] == 200
        assert "data" not in result
        assert len(calls) == 13


async def test_delegated_tasks_share_budget(runtime, scripted_models):
    runtime.enforce_budgets = True
    session = runtime.db.create_session("alice", "fake", "default")
    scripted_models.responses.extend(
        [
            [
                AssistantMessage(
                    tool_calls=[ToolCall("research", "delegate_tasks", {"tasks": ["one", "two"]})]
                ),
                AssistantMessage("Both tasks are complete."),
            ],
            [AssistantMessage("First result")],
            [AssistantMessage("Second result")],
        ]
    )
    events = await collect(runtime.start("alice", session["id"], "Research two topics"))
    assert events[-1]["status"] == "completed"
    assert len(runtime.db.rows("SELECT * FROM usage")) == 4
    results = runtime.db.load_history("alice", session["id"])[2].content
    assert "First result" in results and "Second result" in results


async def test_uncertain_notification_delivery_is_not_repeated(runtime):
    session = runtime.db.create_session(
        "telegram:123", "fake", "default", "telegram-private", "123:0"
    )
    runtime.db.execute(
        "INSERT INTO notifications VALUES ('n','telegram:123',?,'hello',0,0)", (session["id"],)
    )
    count = 0

    class FailedDelivery:
        async def send(self, *args):
            nonlocal count
            count += 1
            raise httpx.ReadTimeout("Response lost")

    scheduler = Scheduler(runtime, FailedDelivery())
    await scheduler.notifications()
    runtime.db.recover()
    await scheduler.notifications()
    assert count == 1
    assert runtime.db.one("SELECT delivered FROM notifications")["delivered"] == -1


def test_backup_restore_and_log_redaction(settings, tmp_path):
    from theos.storage.database import Database

    db = Database(settings.data_dir)
    session = db.create_session("alice", "fake", "default")
    with pytest.raises(RuntimeError, match="Stop the assistant"):
        backup(settings.data_dir, tmp_path / "snapshot.tar.gz")
    db.close()
    (settings.data_dir / "files").mkdir()
    (settings.data_dir / "files" / "f").write_text("saved file")
    backup(settings.data_dir, tmp_path / "snapshot.tar.gz")
    restored = tmp_path / "restored"
    restore(tmp_path / "snapshot.tar.gz", restored)
    db = Database(restored)
    assert db.session("alice", session["id"])["model"] == "fake"
    assert (restored / "files" / "f").read_text() == "saved file"
    db.close()
    record = logging.LogRecord("theos", logging.ERROR, "", 1, "token=very-secret", (), None)
    assert "very-secret" not in SafeFormatter().format(record)
