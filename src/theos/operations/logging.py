"""Content-free structured application logs with bounded file rotation."""

import json
import logging
import math
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

EVENT_NAMES = {
    "browser_profile_save_failed",
    "checkpoint_gc_delete_failed",
    "checkpoint_replication_failed",
    "checkpoint_retention_deferred",
    "checkpoint_retention_invalid_path",
    "delegate_incomplete",
    "final_answer_unavailable",
    "first_model_call",
    "github_event_processing_failed",
    "github_notification_delivery_uncertain",
    "github_notifications_failed",
    "integration_unavailable",
    "memory_consolidation_failed",
    "memory_consolidation_queue_full",
    "memory_consolidation_uncertain",
    "memory_enqueue_failed",
    "memory_retrieval_unavailable",
    "model_capacity_provider_fallback",
    "model_context_unknown",
    "notification_failed",
    "openrouter_reasoning_replay_rejected",
    "openui_render_issue",
    "phone_call_failed",
    "phone_call_rate_limited",
    "phone_call_uncertain",
    "phone_call_worker_failed",
    "provider_model_fallback",
    "provider_request_failed",
    "provider_stream_retry",
    "response_delivery",
    "scheduled_delivery_uncertain",
    "scheduler_failed",
    "started",
    "stopped",
    "telegram_update_failed",
    "title_generation_failed",
    "trace_export_failed",
    "turn_failed",
    "turn_incomplete",
    "turn_profile",
    "zepto_connect_failed",
    "zepto_connection_notification_failed",
    "zepto_return_failed",
}

PROFILE_SECONDS = {
    "request_accept_seconds",
    "queue_wait_seconds",
    "restore_seconds",
    "input_persist_seconds",
    "model_setup_seconds",
    "model_capacity_seconds",
    "tool_registry_seconds",
    "memory_retrieval_seconds",
    "prompt_assembly_seconds",
    "harness_seconds",
    "recovery_seconds",
    "finalize_seconds",
    "total_seconds",
    "time_to_first_model_call_seconds",
    "time_to_first_output_seconds",
    "model_seconds",
    "model_wait_seconds",
    "tool_seconds",
}
PROFILE_COUNTS = {
    "model_calls",
    "model_completed_calls",
    "model_incomplete_calls",
    "tool_completed_calls",
    "tool_incomplete_calls",
}


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
            "event": record.msg if record.msg in EVENT_NAMES else "application_event",
        }
        for key in ("error_type", "session_id"):
            if hasattr(record, key):
                value = getattr(record, key)
                if key == "error_type" and (
                    not isinstance(value, str) or len(value) > 64 or not value.isidentifier()
                ):
                    continue
                if key == "session_id" and (
                    not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9:._-]{1,128}", value)
                ):
                    continue
                if isinstance(value, str):
                    result[key] = value
        duration = getattr(record, "time_to_first_model_call_seconds", None)
        if type(duration) in {int, float} and math.isfinite(duration) and duration >= 0:
            result["time_to_first_model_call_seconds"] = round(duration, 6)
        delivery = getattr(record, "response_delivery_seconds", None)
        if type(delivery) in {int, float} and math.isfinite(delivery) and delivery >= 0:
            result["response_delivery_seconds"] = round(delivery, 6)
        delivery_state = getattr(record, "delivery_state", None)
        if (
            record.msg == "response_delivery"
            and isinstance(delivery_state, str)
            and delivery_state in {"consumed", "closed"}
        ):
            result["delivery_state"] = delivery_state
        if record.msg == "turn_profile":
            profile = getattr(record, "timing_profile", None)
            if isinstance(profile, dict):
                result["timing_profile"] = {
                    key: round(value, 6) if key in PROFILE_SECONDS else value
                    for key, value in profile.items()
                    if (
                        key in PROFILE_SECONDS
                        and type(value) in {int, float}
                        and math.isfinite(value)
                        and 0 <= value <= 86400 * 7
                    )
                    or (key in PROFILE_COUNTS and type(value) is int and 0 <= value <= 1_000_000)
                }
                tools = profile.get("tools")
                if isinstance(tools, dict):
                    result["timing_profile"]["tools"] = {
                        name: {
                            "calls": data["calls"],
                            "seconds": round(data["seconds"], 6),
                        }
                        for name, data in list(tools.items())[:64]
                        if isinstance(name, str)
                        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,79}", name)
                        and isinstance(data, dict)
                        and type(data.get("calls")) is int
                        and 0 <= data["calls"] <= 1_000_000
                        and type(data.get("seconds")) in {int, float}
                        and math.isfinite(data["seconds"])
                        and 0 <= data["seconds"] <= 86400 * 7
                    }
                attempts = profile.get("model_attempts")
                if isinstance(attempts, list):
                    result["timing_profile"]["model_attempts"] = [
                        {
                            "ordinal": item["ordinal"],
                            "scope": item["scope"],
                            "seconds": round(item["seconds"], 6),
                            "complete": item["complete"],
                            **(
                                {"first_event_seconds": round(item["first_event_seconds"], 6)}
                                if type(item.get("first_event_seconds")) in {int, float}
                                and math.isfinite(item["first_event_seconds"])
                                and 0 <= item["first_event_seconds"] <= 86400 * 7
                                else {}
                            ),
                        }
                        for item in attempts[:64]
                        if isinstance(item, dict)
                        and type(item.get("ordinal")) is int
                        and 0 < item["ordinal"] <= 1_000_000
                        and isinstance(item.get("scope"), str)
                        and item["scope"] in {"parent", "delegate"}
                        and type(item.get("seconds")) in {int, float}
                        and math.isfinite(item["seconds"])
                        and 0 <= item["seconds"] <= 86400 * 7
                        and type(item.get("complete")) is bool
                    ]
            status = getattr(record, "turn_status", None)
            if isinstance(status, str) and status in {
                "completed",
                "failed",
                "interrupted",
                "partial",
                "uncertain",
                "waiting_for_approval",
                "budget_exhausted",
            }:
                result["status"] = status
        if record.msg == "openui_render_issue":
            # The browser endpoint supplies bounded, validated diagnostic fields.
            issue = getattr(record, "openui_issue", None)
            if isinstance(issue, dict):
                result["openui"] = {
                    key: issue[key]
                    for key in (
                        "library_version",
                        "codes",
                        "component_count",
                        "unresolved_count",
                        "orphaned_count",
                    )
                    if key in issue
                }
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
