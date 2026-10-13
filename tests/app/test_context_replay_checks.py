"""Replay evidence checks accept exact history selectors without false positives."""

import pytest

from scripts.replay_context_failure import source_was_read


@pytest.mark.parametrize(
    "arguments,resolved,status,name,expected",
    [
        ({"message_index": 1}, None, "completed", "history_read", True),
        ({"call_id": "receipt"}, None, "completed", "history_read", True),
        ({"call_id": "receipt"}, 1, "completed", "history_read", True),
        ({"message_index": 0}, None, "completed", "history_read", False),
        ({"call_id": "other"}, None, "completed", "history_read", False),
        ({"message_index": 1}, None, "failed", "history_read", False),
        ({"message_index": 1}, None, "completed", "history_search", False),
    ],
)
def test_source_read_validation(arguments, resolved, status, name, expected):
    original = [{"type": "user"}, {"type": "tool_result", "call_id": "receipt"}]
    reads = [{"name": name, "arguments": arguments, "message_index": resolved, "status": status}]
    assert source_was_read(reads, original, 1) == expected
