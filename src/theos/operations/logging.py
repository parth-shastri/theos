"""Content-free structured application logs with bounded file rotation."""

import json
import logging
from logging.handlers import RotatingFileHandler


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
                "integration_unavailable",
                "scheduler_failed",
                "notification_failed",
                "telegram_update_failed",
                "trace_export_failed",
                "started",
                "stopped",
            }
            else "application_event",
        }
        for key in ("error_type", "session_id"):
            if hasattr(record, key):
                result[key] = getattr(record, key)
        return json.dumps(result)


def configure_logging(directory):
    """Disable verbose SDK and harness logs that can contain prompts or tokens."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = RotatingFileHandler(directory / "theos.log", maxBytes=2_000_000, backupCount=3)
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
