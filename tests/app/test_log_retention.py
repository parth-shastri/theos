"""Check bounded application logs without deleting durable database records."""

import json
import logging
import os
import time

from theos.operations.logging import RetentionFileHandler, SafeFormatter


def record():
    return logging.LogRecord("theos", logging.INFO, __file__, 1, "started", (), None)


def test_rotation_keeps_only_three_backups(tmp_path):
    handler = RetentionFileHandler(tmp_path / "theos.log")
    handler.setFormatter(SafeFormatter())
    handler.maxBytes = 200
    try:
        for _ in range(30):
            handler.handle(record())
        files = list(tmp_path.iterdir())
        assert {path.name for path in files} == {
            "theos.log",
            "theos.log.1",
            "theos.log.2",
            "theos.log.3",
        }
        assert all(path.stat().st_size <= 200 for path in files)
    finally:
        handler.close()


def test_startup_expires_old_backups_only(tmp_path):
    old = time.time() - 8 * 86400
    expired = tmp_path / "theos.log.2"
    expired.write_text("old diagnostic event")
    os.utime(expired, (old, old))
    recent = tmp_path / "theos.log.1"
    recent.write_text("recent diagnostic event")
    unrelated = tmp_path / "other.log"
    unrelated.write_text("unrelated data")
    os.utime(unrelated, (old, old))
    handler = RetentionFileHandler(tmp_path / "theos.log")
    try:
        assert not expired.exists()
        assert recent.exists() and unrelated.exists()
    finally:
        handler.close()


def test_quiet_old_current_log_rotates_and_expires_on_next_event(tmp_path):
    old = time.time() - 8 * 86400
    path = tmp_path / "theos.log"
    path.write_text(json.dumps({"time": old, "event": "old_event"}) + "\n")
    os.utime(path, (old, old))
    handler = RetentionFileHandler(path)
    handler.setFormatter(SafeFormatter())
    try:
        handler.handle(record())
        assert json.loads(path.read_text())["event"] == "started"
        assert not (tmp_path / "theos.log.1").exists()
    finally:
        handler.close()


def test_age_rotation_is_independent_of_frequent_writes(tmp_path, monkeypatch):
    from theos.operations import logging as app_logging

    clock = time.time()
    monkeypatch.setattr(app_logging.time, "time", lambda: clock)
    handler = RetentionFileHandler(tmp_path / "theos.log")
    handler.setFormatter(SafeFormatter())
    try:
        handler.handle(record())
        clock += 6 * 86400
        handler.handle(record())
        os.utime(tmp_path / "theos.log", (clock, clock))
        clock += 2 * 86400
        handler.handle(record())
        assert len((tmp_path / "theos.log").read_text().splitlines()) == 1
        assert len((tmp_path / "theos.log.1").read_text().splitlines()) == 2
    finally:
        handler.close()


def test_cleanup_failure_does_not_interrupt_logging(tmp_path, monkeypatch):
    from pathlib import Path

    handler = RetentionFileHandler(tmp_path / "theos.log")
    handler.setFormatter(SafeFormatter())
    expired = tmp_path / "theos.log.1"
    expired.write_text("old event")
    old = time.time() - 8 * 86400
    os.utime(expired, (old, old))
    handler.next_cleanup = 0

    def blocked_unlink(path):
        raise PermissionError("cleanup unavailable")

    monkeypatch.setattr(Path, "unlink", blocked_unlink)
    try:
        handler.handle(record())
        assert json.loads((tmp_path / "theos.log").read_text())["event"] == "started"
    finally:
        handler.close()
