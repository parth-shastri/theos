"""Content-free structured application logs with bounded file rotation."""

import json
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


class RetentionFileHandler(RotatingFileHandler):
    """Keep four bounded files and expire old files after seven days."""

    retention_seconds = 7 * 86400

    def __init__(self, path):
        super().__init__(path, maxBytes=2_000_000, backupCount=3)
        self.first_record = time.time()
        with Path(self.baseFilename).open() as source:
            first = source.readline()
        if first:
            try:
                self.first_record = float(json.loads(first)["time"])
            except (ValueError, KeyError, TypeError):
                self.first_record = Path(self.baseFilename).stat().st_mtime
        self.next_cleanup = 0.0
        self.expire()

    def expire(self):
        """Inspect only this handler's backup files, never unrelated files."""
        now = time.time()
        if now < self.next_cleanup:
            return
        for index in range(1, self.backupCount + 1):
            path = Path(f"{self.baseFilename}.{index}")
            if path.exists() and path.stat().st_mtime < now - self.retention_seconds:
                path.unlink()
        self.next_cleanup = now + 3600

    def shouldRollover(self, record):
        return time.time() - self.first_record >= self.retention_seconds or super().shouldRollover(
            record
        )

    def doRollover(self):
        super().doRollover()
        self.first_record = time.time()
        self.next_cleanup = 0.0
        self.expire()

    def emit(self, record):
        try:
            self.expire()
        except OSError:
            # Cleanup failures must not interrupt a turn or remote exporter.
            pass
        super().emit(record)


class SafeFormatter(logging.Formatter):
    """Allow fixed event names and approved metadata, never exception payloads."""

    def format(self, record):
        """Include only approved metadata fields in structured logs."""
        result = {
            "time": record.created,
            "level": record.levelname,
            "event": record.msg
            if record.msg
            in {
                "turn_failed",
                "turn_incomplete",
                "openrouter_reasoning_replay_rejected",
                "integration_unavailable",
                "scheduler_failed",
                "notification_failed",
                "telegram_update_failed",
                "trace_export_failed",
                "started",
                "stopped",
                "provider_request_failed",
                "provider_stream_retry",
                "checkpoint_replication_failed",
            }
            else "application_event",
        }
        for key in ("error_type", "session_id"):
            if hasattr(record, key):
                value = getattr(record, key)
                if key != "error_type" or (
                    isinstance(value, str) and len(value) <= 64 and value.isidentifier()
                ):
                    result[key] = value
        from .provider_diagnostics import clean

        result.update(clean(record.__dict__))
        from harness.limits import HarnessErrorCode

        code = getattr(record, "error_code", None)
        if isinstance(code, str) and code in {item.value for item in HarnessErrorCode}:
            result["error_code"] = code
        return json.dumps(result)


def configure_logging(directory):
    """Disable verbose SDK and harness logs that can contain prompts or tokens."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = RetentionFileHandler(directory / "theos.log")
    handler.setFormatter(SafeFormatter())
    logger = logging.getLogger("theos")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for name in (
        "harness",
        "httpx",
        "httpcore",
        "openai",
        "anthropic",
        "google",
        "mcp",
        "opensandbox",
        "opentelemetry",
        "urllib3",
    ):
        remote = logging.getLogger(name)
        remote.handlers = [logging.NullHandler()]
        remote.propagate = False
        remote.setLevel(logging.CRITICAL)
    return handler
