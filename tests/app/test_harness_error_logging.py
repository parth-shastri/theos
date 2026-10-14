"""Keep fixed harness error codes without logging private exception contents."""

import json
import logging

import pytest

from theos.operations.logging import SafeFormatter


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
