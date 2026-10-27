"""Browser owner isolation, profile recovery, and private login controls."""

import asyncio
import io
import json
import sqlite3
import tarfile
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from theos.services.sandbox import profile
from theos.services.sandbox.browser import ARCHIVE
from theos.transports.browser.app import create_app


@pytest.fixture
def browser_boxes(runtime, monkeypatch):
    owners, commands = {}, []
    image = io.BytesIO()
    Image.new("RGB", (4, 3), "green").save(image, "PNG")

    class Box:
        def __init__(self, owner):
            self.id = owner + "-browser-1"
            self.data, self.tabs, self.active = {}, {}, None
            self.profile = False
            self.commands = SimpleNamespace(run=self.run)
            self.files = SimpleNamespace(write_file=self.write, read_bytes=self.read)

        async def write(self, path, value):
            self.data[path] = value

        async def read(self, path, **kwargs):
            return self.data[path]

        async def run(self, command, **kwargs):
            import shlex

            commands.append((self.id, command))
            code, result = 0, {"success": True, "data": {}}
            if command.startswith("test -d"):
                code = 0 if self.profile else 1
            elif command.endswith("profile.py restore"):
                assert self.data[ARCHIVE] == b"private profile cookies and IndexedDB"
                self.profile = True
            elif command.endswith("profile.py snapshot"):
                self.data[ARCHIVE] = b"private profile cookies and IndexedDB"
            elif command.startswith("agent-browser "):
                args = shlex.split(command)[4:]
                if args[:2] == ["tab", "new"]:
                    self.active = args[3]
                    self.tabs[self.active] = "about:blank"
                elif args[0] == "tab":
                    if args[1] not in self.tabs:
                        code, result = 1, {"success": False, "error": "missing tab"}
                    else:
                        self.active = args[1]
                elif args[0] == "open":
                    self.profile = True
                    self.tabs[self.active] = args[1]
                elif args[0] == "get":
                    result["data"] = {"url": self.tabs.get(self.active, "about:blank")}
                elif args[0] == "screenshot":
                    self.data[args[1]] = image.getvalue()
            return SimpleNamespace(
                error=None,
                exit_code=code,
                logs=SimpleNamespace(stdout=[SimpleNamespace(text=json.dumps(result))]),
            )

    async def get(owner, session):
        assert session == "persistent-browser"
        return owners.setdefault(owner, Box(owner))

    async def destroy(owner, session):
        owners.pop(owner, None)

    monkeypatch.setattr(runtime.browsers.boxes, "get", get)
    monkeypatch.setattr(runtime.browsers.boxes, "destroy", destroy)
    return owners, commands, Box


async def test_browser_reuses_owner_profile_and_keeps_conversation_tabs(runtime, browser_boxes):
    owners, commands, Box = browser_boxes
    runtime.db.ensure_user("alice")
    runtime.db.ensure_user("bob")
    browser = runtime.browsers
    await browser.execute("alice", "chat-1", ["open", "https://one.example"])
    await browser.execute("alice", "chat-2", ["open", "https://two.example"])
    await browser.execute("bob", "chat-3", ["open", "https://other.example"])
    one, two = await asyncio.gather(
        browser.execute("alice", "chat-1", ["get", "url"]),
        browser.execute("alice", "chat-2", ["get", "url"]),
    )
    assert one["data"]["url"] == "https://one.example"
    assert two["data"]["url"] == "https://two.example"
    assert len(owners) == 2
    row = runtime.db.one(
        "SELECT encrypted FROM credentials WHERE owner='alice' AND service='browser'"
    )
    assert "private profile" not in row["encrypted"]
    assert (
        browser.encryption().decrypt(row["encrypted"].encode())
        == b"private profile cookies and IndexedDB"
    )
    assert (runtime.settings.data_dir / "browser.key").stat().st_mode & 0o777 == 0o600
    replacement = Box("alice")
    replacement.id = "alice-browser-2"
    owners["alice"] = replacement
    await browser.execute("alice", "chat-1", ["open", "https://one.example"])
    assert replacement.data[ARCHIVE] == b"private profile cookies and IndexedDB"
    before = len(commands)
    for args in [
        ["open", "https://site", "--profile=/another"],
        ["state", "save", "/workspace/secret"],
        ["tab", "other"],
    ]:
        with pytest.raises(ValueError):
            await browser.execute("alice", "chat-1", args)
    assert len(commands) == before
    await browser.disconnect("alice")
    assert not browser.status("alice")["saved"]
    assert browser.status("bob")["saved"]
    assert "bob" in owners


async def test_browser_screenshot_enters_workspace_without_profile_files(runtime, browser_boxes):
    owners, commands, Box = browser_boxes
    runtime.db.ensure_user("alice")
    data = {}

    async def run(*args, **kwargs):
        pass

    async def write(path, content):
        data[path] = content

    task = SimpleNamespace(
        commands=SimpleNamespace(run=run), files=SimpleNamespace(write_file=write)
    )
    result = await runtime.browsers.execute(
        "alice", "chat", ["screenshot", "/workspace/page.png"], task
    )
    assert result["data"] == {"path": "/workspace/page.png"}
    assert set(data) == {"/workspace/page.png"}
    Image.open(io.BytesIO(data["/workspace/page.png"])).verify()


async def test_browser_private_controls_require_owner_authentication(runtime, browser_boxes):
    runtime.settings.sandbox.enabled = True
    app = create_app(runtime.settings, runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/api/connections/browser/action", json={"action": "refresh"})
        ).status_code == 401
        headers = {"Authorization": "Bearer " + "a" * 32}
        result = await client.post(
            "/api/connections/browser/action",
            headers=headers,
            json={"action": "open", "url": "https://login.example"},
        )
        assert result.status_code == 200
        assert result.json()["image"].startswith("data:image/png;base64,")
        result = await client.post(
            "/api/connections/browser/action",
            headers=headers,
            json={"action": "type", "text": "private-password"},
        )
        assert result.status_code == 200
        assert not runtime.db.rows("SELECT * FROM tool_runs")
        assert not runtime.db.rows("SELECT * FROM traces")
        assert "private-password" not in json.dumps(result.json())
        result = await client.post(
            "/api/connections/browser/action",
            headers=headers,
            json={"action": "open", "url": "file:///etc/passwd"},
        )
        assert result.status_code == 400
        result = await client.post(
            "/api/connections/browser/action",
            headers=headers,
            json={"action": "refresh", "owner": "bob"},
        )
        assert result.status_code == 422
        result = await client.post("/api/connections/browser/disconnect", headers=headers)
        assert result.status_code == 200
        assert result.json() == {"disconnected": True}


def test_profile_snapshot_preserves_sqlite_wal_and_rejects_unsafe_archives(tmp_path, monkeypatch):
    root, archive = tmp_path / "profile", tmp_path / "profile.tar.gz"
    root.mkdir()
    monkeypatch.setattr(profile, "PROFILE", root)
    monkeypatch.setattr(profile, "ARCHIVE", archive)
    (root / "Cache").mkdir()
    (root / "Cache" / "noise").write_bytes(b"cache")
    (root / "Preferences").write_text('{"setting": true}')
    (root / "SingletonLock").symlink_to("/does/not/exist")
    with sqlite3.connect(root / "Cookies") as database:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("CREATE TABLE cookies (value TEXT)")
        database.execute("INSERT INTO cookies VALUES ('session')")
        database.commit()
        profile.snapshot()
    with tarfile.open(archive) as content:
        assert {"Preferences", "Cookies"} <= set(content.getnames())
        assert "Cache/noise" not in content.getnames()
        assert "Cookies-shm" not in content.getnames()
    destination = tmp_path / "restored"
    monkeypatch.setattr(profile, "PROFILE", destination)
    profile.restore()
    with sqlite3.connect(destination / "Cookies") as database:
        assert database.execute("SELECT value FROM cookies").fetchone() == ("session",)
    with tarfile.open(archive, "w:gz") as content:
        entry = tarfile.TarInfo("../escape")
        entry.size = 3
        content.addfile(entry, io.BytesIO(b"bad"))
    with pytest.raises(ValueError, match="invalid entry"):
        profile.restore()
    assert not (tmp_path / "escape").exists()


def test_profile_watchdog_resumes_browser_after_snapshot_process_dies(tmp_path):
    import subprocess
    import sys
    import time

    root, heartbeat = tmp_path / "profile", tmp_path / "heartbeat"
    root.mkdir()
    worker = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
            "exec('while True:\\n p.write_text(str(time.time()))\\n time.sleep(0.02)')",
            str(heartbeat),
            "--user-data-dir=" + str(root),
        ]
    )
    try:
        deadline = time.monotonic() + 5
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert heartbeat.exists()
        script = (
            "import os,sys; from pathlib import Path; "
            "from theos.services.sandbox import profile; profile.PROFILE=Path(sys.argv[1]); "
            "exec('with profile.paused_browser():\\n os._exit(0)')"
        )
        subprocess.run([sys.executable, "-c", script, str(root)], check=True, timeout=5)
        previous = heartbeat.read_text()
        deadline = time.monotonic() + 3
        while heartbeat.read_text() == previous and time.monotonic() < deadline:
            time.sleep(0.02)
        assert heartbeat.read_text() != previous
    finally:
        worker.kill()
        worker.wait(timeout=5)
