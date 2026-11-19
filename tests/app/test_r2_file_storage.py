"""Verified R2 payloads leave the local spool and remain usable on demand."""

import base64
import hashlib
import io
import json
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr

from harness import AssistantMessage, ContextMemory, UserMessage
from harness.testing import FakeModel
from theos.backup import archive_backup, backup, restore, restore_remote
from theos.server import create_app
from theos.services.errors import ServiceError

from .conftest import collect
from .test_context_checkpoints import Objects


@pytest.fixture
def objects(runtime, monkeypatch):
    config = runtime.settings.storage
    config.endpoint, config.bucket = "https://example.invalid", "private"
    config.access_key, config.secret_key = SecretStr("test"), SecretStr("test")
    storage = Objects()
    monkeypatch.setattr(runtime.files, "storage_client", lambda: storage)
    return storage


async def test_catalog_bytes_live_in_r2_and_reads_do_not_refill_disk(runtime, objects):
    saved = runtime.files.save("alice", "report.txt", "text/plain", b"report bytes")
    assert await runtime.checkpoints.drain()
    assert not Path(saved["path"]).exists()
    assert await runtime.files.read("alice", saved["id"]) == b"report bytes"
    assert not Path(saved["path"]).exists()
    with pytest.raises(LookupError):
        await runtime.files.read("bob", saved["id"])


async def test_upload_failure_keeps_spool_until_verified_retry(runtime, objects):
    objects.fail = True
    saved = runtime.files.save("alice", "report.txt", "text/plain", b"pending bytes")
    assert not await runtime.checkpoints.drain()
    assert Path(saved["path"]).read_bytes() == b"pending bytes"
    assert runtime.files.get("alice", saved["id"])["object_key"] is None
    objects.fail = False
    assert await runtime.checkpoints.drain()
    assert not Path(saved["path"]).exists()
    assert await runtime.files.read("alice", saved["id"]) == b"pending bytes"


async def test_corrupt_upload_does_not_evict_local_file(runtime, objects):
    def corrupt(path, bucket, key):
        objects.objects[key] = b"corrupt bytes"

    objects.upload_file = corrupt
    saved = runtime.files.save("alice", "report.txt", "text/plain", b"original bytes")
    assert not await runtime.checkpoints.drain()
    assert Path(saved["path"]).read_bytes() == b"original bytes"


async def test_on_demand_read_checks_integrity_and_reports_remote_failure(runtime, objects):
    saved = runtime.files.save("alice", "report.txt", "text/plain", b"original")
    assert await runtime.checkpoints.drain()
    key = runtime.files.get("alice", saved["id"])["object_key"]
    objects.objects[key] = b"modified"
    with pytest.raises(ValueError, match="checksum mismatch"):
        await runtime.files.read("alice", saved["id"])
    objects.objects.pop(key)
    with pytest.raises(ServiceError, match="could not be read"):
        await runtime.files.read("alice", saved["id"])
    assert not Path(saved["path"]).exists()


async def test_checkpoint_eviction_keeps_gc_references_and_workspace_recovery(runtime, objects):
    sid = runtime.db.create_session("alice", "gpt-6-luna", "none")["id"]
    payload = b"workspace result"
    source = await runtime.checkpoints.put(
        "alice",
        sid,
        "workspace_file",
        {
            "path": "/workspace/report.txt",
            "data": base64.b64encode(payload).decode(),
            "digest": hashlib.sha256(payload).hexdigest(),
        },
    )
    runtime.db.put_record(
        "alice",
        "workspace",
        sid,
        {
            "files": {
                "/workspace/report.txt": {
                    "source_id": source,
                    "digest": hashlib.sha256(payload).hexdigest(),
                    "version": 1,
                }
            }
        },
    )
    snapshot = await runtime.checkpoints.save(
        "alice", sid, [UserMessage("Report")], ContextMemory(), "test"
    )
    assert await runtime.checkpoints.drain()
    assert not list(runtime.checkpoints.directory.iterdir())
    restored = await runtime.checkpoints.get("alice", sid, source)
    assert base64.b64decode(restored["data"]) == payload
    assert not list(runtime.checkpoints.directory.iterdir())
    await runtime.checkpoints.retention.collect(force=True)
    assert runtime.db.one("SELECT id FROM context_objects WHERE id=?", (source,))
    assert runtime.db.one("SELECT id FROM context_objects WHERE id=?", (snapshot,))


async def test_image_from_r2_reaches_model_after_spool_eviction(runtime, objects):
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(image, format="PNG")
    saved = runtime.files.save("alice", "picture.png", "image/png", image.getvalue())
    assert await runtime.checkpoints.drain()
    sid = runtime.db.create_session("alice", "gpt-6-luna", "none")["id"]
    await collect(runtime.start("alice", sid, "Describe this", [saved["id"]]))
    history = runtime.db.load_history("alice", sid)
    assert not history[0].images
    assert "data:image/" not in runtime.db.session("alice", sid)["history"]
    displayed = await runtime.files.display_history("alice", sid)
    assert displayed[0]["images"][0]["url"].startswith("data:image/png;base64,")
    model = FakeModel([AssistantMessage("Still green.")])

    @asynccontextmanager
    async def factory(*args):
        yield model

    runtime.models = factory
    await collect(runtime.start("alice", sid, "What color was it?"))
    assert any(getattr(message, "images", []) for message in model.requests[0].messages)
    assert not Path(saved["path"]).exists()


async def test_remote_checkpoint_restores_image_references_without_local_payload(runtime, objects):
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(image, format="PNG")
    saved = runtime.files.save("alice", "picture.png", "image/png", image.getvalue())
    sid = runtime.db.create_session("alice", "gpt-6-luna", "none")["id"]
    message = runtime.input_message("alice", "Describe", [saved["id"]])
    await runtime.checkpoints.save("alice", sid, [message], ContextMemory(), "test")
    assert await runtime.checkpoints.drain()
    runtime.db.execute("DELETE FROM files WHERE id=?", (saved["id"],))
    runtime.db.execute("DELETE FROM context_objects WHERE session=?", (sid,))
    await runtime.checkpoints.restore("alice", sid)
    assert "data:image/" not in runtime.db.session("alice", sid)["history"]
    assert await runtime.files.read("alice", saved["id"]) == image.getvalue()
    assert not Path(saved["path"]).exists()
    history = json.loads(runtime.db.session("alice", sid)["history"])
    assert history[0]["display"]["image_files"] == [saved["id"]]


async def test_legacy_image_without_checksum_can_enter_a_remote_checkpoint(runtime, objects):
    image = io.BytesIO()
    Image.new("RGB", (2, 2)).save(image, format="PNG")
    saved = runtime.files.save("alice", "legacy.png", "image/png", image.getvalue())
    runtime.db.execute("DELETE FROM records WHERE kind='file_digest'")
    sid = runtime.db.create_session("alice", "gpt-6-luna", "none")["id"]
    message = runtime.input_message("alice", "Describe", [saved["id"]])
    snapshot = await runtime.checkpoints.save("alice", sid, [message], ContextMemory(), "test")
    assert await runtime.checkpoints.drain()
    recovered = await runtime.checkpoints.get("alice", sid, snapshot)
    assert recovered["catalog_files"][0]["sha256"] == hashlib.sha256(image.getvalue()).hexdigest()
    assert not Path(saved["path"]).exists()


async def test_missing_remote_image_does_not_hide_saved_chat_text(runtime, objects):
    image = io.BytesIO()
    Image.new("RGB", (2, 2)).save(image, format="PNG")
    saved = runtime.files.save("alice", "picture.png", "image/png", image.getvalue())
    sid = runtime.db.create_session("alice", "gpt-6-luna", "none")["id"]
    runtime.db.save_history(
        "alice", sid, [runtime.input_message("alice", "Saved text", [saved["id"]])]
    )
    assert await runtime.checkpoints.drain()
    objects.objects.clear()
    displayed = await runtime.files.display_history("alice", sid)
    assert displayed[0]["content"].startswith("Saved text")
    assert not displayed[0].get("images")
    assert not Path(saved["path"]).exists()


async def test_voice_reads_evicted_audio(runtime, objects):
    runtime.settings.transcription_url = "https://speech.invalid/v1"
    saved = runtime.files.save("alice", "voice.ogg", "audio/ogg", b"voice bytes")
    assert await runtime.checkpoints.drain()

    def endpoint(request):
        assert b"voice bytes" in request.content
        return httpx.Response(200, json={"text": "Voice transcript"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as client:
        runtime.files.voice.http = client
        assert await runtime.files.transcribe("alice", saved["id"]) == "Voice transcript"
    assert not Path(saved["path"]).exists()


async def test_browser_download_reads_r2_and_keeps_owner_isolation(runtime, objects):
    saved = runtime.files.save("alice", "report.txt", "text/plain", b"download bytes")
    assert await runtime.checkpoints.drain()
    app = create_app(runtime.settings, runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as browser:
        browser.headers["Authorization"] = "Bearer " + "a" * 32
        response = await browser.get("/api/files/" + saved["id"])
        assert response.status_code == 200 and response.content == b"download bytes"
        assert "attachment" in response.headers["content-disposition"]
        browser.headers["Authorization"] = "Bearer " + "b" * 32
        assert (await browser.get("/api/files/" + saved["id"])).status_code == 404
    assert not Path(saved["path"]).exists()


async def test_independent_backup_can_restore_after_remote_objects_disappear(
    runtime, objects, monkeypatch, tmp_path
):
    from theos.services.files import catalog

    sid = runtime.db.create_session("alice", "gpt-6-luna", "none")["id"]
    saved = runtime.files.save("alice", "report.txt", "text/plain", b"archive bytes")
    snapshot = await runtime.checkpoints.save(
        "alice", sid, [UserMessage("Saved")], ContextMemory(), "test"
    )
    extra = []
    for index in range(8):
        payload = f"workspace {index}".encode()
        extra.append(
            await runtime.checkpoints.put(
                "alice",
                sid,
                "workspace_file",
                {
                    "path": f"/workspace/report-{index}.txt",
                    "data": base64.b64encode(payload).decode(),
                    "digest": hashlib.sha256(payload).hexdigest(),
                },
            )
        )
    assert await runtime.checkpoints.drain()
    assert not Path(saved["path"]).exists()
    assert not (runtime.checkpoints.directory / snapshot).exists()
    stopped = tmp_path / "stopped-copy"
    stopped.mkdir()
    # Use SQLite's backup API for a consistent fixture, without stopping the test runtime.
    with (
        sqlite3.connect(runtime.settings.data_dir / "theos.sqlite3") as source,
        sqlite3.connect(stopped / "theos.sqlite3") as destination,
    ):
        source.backup(destination)
    monkeypatch.setattr(catalog, "storage_client", lambda config: objects)
    original_read = catalog.Files.remote_bytes
    lock = threading.Lock()
    active = peak = 0

    def delayed_read(client, bucket, key):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.02)
            return original_read(client, bucket, key)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(catalog.Files, "remote_bytes", staticmethod(delayed_read))
    archive = tmp_path / "independent.tar.gz"
    backup(stopped, archive)
    assert 2 <= peak <= 4
    objects.objects.clear()
    restored = tmp_path / "restored"
    restore(archive, restored)
    assert (restored / "files" / saved["id"]).read_bytes() == b"archive bytes"
    assert (restored / "checkpoints" / snapshot).is_file()
    assert all((restored / "checkpoints" / identity).is_file() for identity in extra)
    assert not (stopped / "files" / saved["id"]).exists()


async def test_catalog_without_r2_keeps_local_file(runtime):
    saved = runtime.files.save("alice", "local.txt", "text/plain", b"local")
    assert await runtime.checkpoints.drain()
    assert Path(saved["path"]).read_bytes() == b"local"


async def test_completed_backup_moves_to_r2_and_restores_without_retaining_archive(
    runtime, objects, monkeypatch, tmp_path
):
    from theos import settings
    from theos.services.files import catalog

    stopped = tmp_path / "stopped"
    stopped.mkdir()
    (stopped / "example.txt").write_bytes(b"independent backup")
    archive = tmp_path / "example.tar.gz"
    backup(stopped, archive)
    monkeypatch.setattr(catalog, "storage_client", lambda config: objects)
    monkeypatch.setattr(settings, "Settings", lambda **kwargs: runtime.settings)
    reference = archive_backup(archive)
    assert reference.startswith("r2:theos/backups/")
    assert not archive.exists()
    target = tmp_path / "recovered"
    restore_remote(reference[3:], target)
    assert (target / "example.txt").read_bytes() == b"independent backup"
    assert not list(tmp_path.glob("tmp*"))


async def test_backup_upload_failure_retains_local_archive(runtime, objects, monkeypatch, tmp_path):
    from theos import settings
    from theos.services.files import catalog

    archive = tmp_path / "backup.tar.gz"
    archive.write_bytes(b"backup bytes")
    objects.fail = True
    monkeypatch.setattr(catalog, "storage_client", lambda config: objects)
    monkeypatch.setattr(settings, "Settings", lambda **kwargs: runtime.settings)
    with pytest.raises(OSError, match="storage offline"):
        archive_backup(archive)
    assert archive.read_bytes() == b"backup bytes"


async def test_corrupt_backup_upload_retains_local_archive(runtime, objects, monkeypatch, tmp_path):
    from theos import settings
    from theos.services.files import catalog

    archive = tmp_path / "backup.tar.gz"
    archive.write_bytes(b"backup bytes")
    objects.upload_file = lambda path, bucket, key: objects.objects.update({key: b"corrupt"})
    monkeypatch.setattr(catalog, "storage_client", lambda config: objects)
    monkeypatch.setattr(settings, "Settings", lambda **kwargs: runtime.settings)
    with pytest.raises(ValueError, match="checksum mismatch"):
        archive_backup(archive)
    assert archive.read_bytes() == b"backup bytes"
