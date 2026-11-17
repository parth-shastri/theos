"""Keep fixed harness error codes without logging private exception contents."""

import json
import logging
import time

import pytest

from harness.events import ModelCalled
from theos.operations.logging import SafeFormatter
from theos.runtime import events
from theos.runtime.turn import Turn


@pytest.mark.parametrize(
    "code", ["duplicate_tool_call_id", "private-credential", {"private": "credential"}]
)
def test_only_known_harness_codes_enter_logs(code):
    record = logging.LogRecord("theos", logging.WARNING, "", 0, "turn_incomplete", (), None)
    record.error_type = "HarnessError"
    record.error_code = code
    result = json.loads(SafeFormatter().format(record))
    if code == "duplicate_tool_call_id":
        assert result["error_code"] == code
    else:
        assert "error_code" not in result
    assert "private" not in json.dumps(result)


async def test_first_model_call_timing_is_logged_once_with_tracing_disabled(runtime, monkeypatch):
    row = runtime.db.create_session("alice", "test-model", "default")
    turn = Turn("alice", row["id"], raw_events=True, started_at=time.monotonic() - 2)
    records = []
    monkeypatch.setattr(
        events.logger, "info", lambda message, **kwargs: records.append((message, kwargs))
    )

    assert runtime.tracing.tracer is None
    event = ModelCalled(None)
    events.publish_event(runtime, turn, event, "running")
    events.publish_event(runtime, turn, event, "running")

    assert len(records) == 1
    message, kwargs = records[0]
    assert message == "first_model_call"
    assert kwargs["extra"]["session_id"] == row["id"]
    duration = kwargs["extra"]["time_to_first_model_call_seconds"]
    assert 2 <= duration < 3
    record = logging.LogRecord("theos", logging.INFO, "", 0, message, (), None)
    record.__dict__.update(kwargs["extra"])
    formatted = json.loads(SafeFormatter().format(record))
    assert formatted["time_to_first_model_call_seconds"] == round(duration, 6)
    assert "prompt" not in json.dumps(formatted)
