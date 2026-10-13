"""Exact transcript references for text summaries, independent of model prose."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from harness.types import AssistantMessage, Message, ToolResultMessage, UserMessage

ANCHOR_HEADING = "## Anchor Index (mechanically extracted, exact)"
USER_HEADING = "## User Messages (verbatim, newest first)"
RECOVERY_HEADING = "## Context Recovery"

PATTERNS = (
    ("url", re.compile(r'https?://[^\s<>"\']+')),
    ("path", re.compile(r"(?<![\w/])(?:[\w.~@+-]+/|/)+(?:[\w.@+-]+/)*[\w.@+-]+")),
    ("commit", re.compile(r"\b[0-9a-fA-F]{7,40}\b")),
    ("issue", re.compile(r"(?<!\w)#\d+\b")),
    (
        "error",
        re.compile(r"\b(?:[A-Z][A-Za-z]*Error|Exception|EACCES|ENOSPC|SIGKILL)\b[^\n]{0,160}"),
    ),
)
IDENTIFIER_FIELDS = {
    "id",
    "call_id",
    "record_id",
    "source_id",
    "source_ids",
    "record_ids",
    "file_ids",
    "file_id",
    "operation_id",
    "thread_id",
    "message_id",
    "run_id",
}


def _strings(value: Any, path: list) -> Iterator[tuple[list, str, bool]]:
    pending = [(path, value)]
    while pending:
        current_path, item = pending.pop()
        if isinstance(item, str):
            yield current_path, item, any(part in IDENTIFIER_FIELDS for part in current_path[-2:])
        elif isinstance(item, dict):
            pending.extend(([*current_path, key], child) for key, child in reversed(item.items()))
        elif isinstance(item, list):
            pending.extend(([*current_path, i], item[i]) for i in reversed(range(len(item))))


def anchor_fields(message: Message) -> Iterator[tuple[list, str, bool]]:
    """Exclude opaque provider replay, reasoning, images, and system instructions."""
    if isinstance(message, UserMessage):
        yield ["content"], message.content, False
    elif isinstance(message, ToolResultMessage):
        yield ["content"], message.content, False
        yield ["call_id"], message.call_id, True
        if message.content.lstrip().startswith(("{", "[")):
            try:
                value = json.loads(message.content)
            except (ValueError, RecursionError):
                return
            for path, content, identifier in _strings(value, ["content", "json"]):
                if identifier:
                    yield path, content, True
    elif isinstance(message, AssistantMessage):
        if message.text:
            yield ["text"], message.text, False
        for index, call in enumerate(message.tool_calls):
            yield ["tool_calls", index, "id"], call.id, True
            yield from _strings(call.arguments, ["tool_calls", index, "arguments"])


def extract_anchors(history: Sequence[Message], cut: int) -> list[dict]:
    """Save unique exact identifiers, pointing to their latest original occurrence."""
    found: dict[tuple[str, str], dict] = {}
    for index in range(cut):
        for path, content, identifier in anchor_fields(history[index]):
            matches = [("id", content)] if identifier and content else []
            matches += [
                (kind, match.group().rstrip(".,;:)"))
                for kind, pattern in PATTERNS
                for match in pattern.finditer(content)
            ]
            for kind, exact in matches:
                found[kind, exact] = dict(kind=kind, exact=exact, message_index=index, field=path)
    return sorted(found.values(), key=lambda anchor: anchor["message_index"])


def without_mechanical_sections(summary: str) -> str:
    """Replace model-written reference sections with original transcript data."""
    for heading in (ANCHOR_HEADING, USER_HEADING, RECOVERY_HEADING):
        summary = re.sub(rf"(?m)^{re.escape(heading)}\s*\n[\s\S]*?(?=^## |\Z)", "", summary)
    return summary.rstrip()


def reference_state(history: Sequence[Message], protected: dict, previous_ids: list) -> dict:
    """Preserve all exact references separately from the bounded request index."""
    records = protected.get("records", [])
    ids = {reference for reference in previous_ids if isinstance(reference, str) and reference}
    ids.update(
        record["id"]
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str) and record["id"]
    )
    return {
        "anchors": extract_anchors(history, len(history)),
        "record_ids": sorted(ids),
        "unknown_tools": [
            {"call_id": m.call_id, "tool": m.name, "message_index": i}
            for i, m in enumerate(history)
            if isinstance(m, ToolResultMessage) and m.status == "unknown"
        ],
    }


def render_reference_index(references: dict, max_chars: int, redact: Callable) -> str:
    """Render complete reference lines within the request allowance."""
    header = ANCHOR_HEADING + "\n"
    footer = (
        "\nThis is a bounded index. All original messages and exact references remain saved. "
        "Use history_read(message_index=...) or history_search(query=...) for details. "
        "Saved research items can be reopened with read_research(item_id=...)."
    )
    lines = []
    used = len(header) + len(footer)
    candidates = (
        [
            f"- UNKNOWN action: {item['tool']} call_id={item['call_id']} "
            f"[message_index={item['message_index']}]. Check its outcome before repeating."
            for item in reversed(references["unknown_tools"])
        ]
        + [f"- research record: {reference}" for reference in reversed(references["record_ids"])]
        + [
            f"- {anchor['kind']}: {anchor['exact']} [message_index={anchor['message_index']}]"
            for anchor in reversed(references["anchors"])
        ]
    )
    for line in candidates:
        safe = redact(line)
        if used + len(safe) + 1 <= max_chars:
            lines.append(safe)
            used += len(safe) + 1
    return header + "\n".join(lines) + footer if lines else ""
