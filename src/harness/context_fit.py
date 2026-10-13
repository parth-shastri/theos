"""Reduce working requests without changing journals, tasks, or tool contracts."""

import json
from copy import deepcopy
from dataclasses import replace

from harness.compression_policy import LEGACY_SUMMARY_PREFIX, ContextCompressor
from harness.context_size import request_size
from harness.types import (
    AssistantMessage,
    ModelRequest,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
    message_to_dict,
)


def smaller_request(candidate, previous):
    """Compare estimated tokens, then serialized bytes for opaque replay reductions."""
    after, before = request_size(candidate), request_size(previous)
    if after != before:
        return after < before

    def wire_bytes(request):
        return len(
            json.dumps(
                [[message_to_dict(m) for m in request.messages], [vars(t) for t in request.tools]],
                ensure_ascii=False,
                default=str,
            ).encode()
        )

    return wire_bytes(candidate) < wire_bytes(previous)


def _summary(message):
    return isinstance(message, AssistantMessage) and ContextCompressor._is_context_summary_message(
        {"role": "assistant", "content": message.text or ""}
    )


def _units(messages):
    """Keep call/result groups atomic, including steering during a parallel batch."""
    start, pending = 0, set()
    for index, message in enumerate(messages):
        if isinstance(message, AssistantMessage):
            pending.update(call.id for call in message.tool_calls)
        elif isinstance(message, ToolResultMessage):
            pending.discard(message.call_id)
        if not pending:
            yield start, index + 1, False
            start = index + 1
    if start < len(messages):
        yield start, len(messages), True


def _protected(messages):
    # All user steering since the previous finished answer belongs to the active task.
    finished = max(
        (
            i
            for i, m in enumerate(messages)
            if isinstance(m, AssistantMessage) and m.text and not m.tool_calls and not _summary(m)
        ),
        default=-1,
    )
    users = [i for i, m in enumerate(messages) if isinstance(m, UserMessage)]
    active = {i for i in users if i > finished}
    if users:
        active.add(users[-1])
    return active | {i for i, m in enumerate(messages) if isinstance(m, SystemMessage)}


def _handoff(history, tools):
    unknown = sum(isinstance(m, ToolResultMessage) and m.status == "unknown" for m in history)
    recovery = (
        "Recover omitted details with history_read or history_search before using them."
        if any(t.name in {"history_read", "history_search"} for t in tools)
        else "Omitted evidence is unavailable in this request. State missing details and do not invent them."
    )
    return (
        LEGACY_SUMMARY_PREFIX + "\n## Historical Task Snapshot\n"
        "Earlier context was shortened. The current user request remains active.\n"
        "## Critical Context\n"
        f"All {len(history)} original messages remain in the transcript. {recovery} "
        f"There are {unknown} recorded unknown action outcomes. Do not assume they succeeded or repeat them."
    )


def cut_request(request, history):
    """Return one strictly smaller candidate, or None when no safe reduction remains."""
    messages = list(request.messages)

    def candidate(changed, reason, tools=None):
        value = ModelRequest(
            changed, request.tools if tools is None else tools, dict(request.options)
        )
        return (value, reason) if smaller_request(value, request) else None

    # Page verbose results instead of breaking their tool-call pairing.
    for index in sorted(
        (i for i, m in enumerate(messages) if isinstance(m, ToolResultMessage)),
        key=lambda i: len(messages[i].content),
        reverse=True,
    ):
        message = messages[index]
        recovery = (
            f"Read history_read(call_id={message.call_id!r}) for complete evidence. "
            if any(t.name == "history_read" for t in request.tools)
            else "The original evidence is unavailable in this request. Do not invent missing details. "
        )
        text = f"[Original {message.name} result is saved. {recovery}Recorded outcome: {message.status}.]"
        if len(text) < len(message.content):
            changed = list(messages)
            changed[index] = replace(message, content=text)
            if reduced := candidate(changed, "tool_output_cut"):
                return reduced

    # Replay and reasoning stay in the original journal, not the reduced wire copy.
    for index, message in enumerate(messages):
        if isinstance(message, AssistantMessage) and (message.reasoning or message.provider_data):
            changed = list(messages)
            changed[index] = replace(message, reasoning=None, provider_data={})
            if reduced := candidate(changed, "reasoning_cut"):
                return reduced

    note = _handoff(history, request.tools)
    for index, message in enumerate(messages):
        if not _summary(message):
            continue
        body = ContextCompressor._strip_summary_prefix(message.text or "")
        # Retain an explicitly partial excerpt until the smallest handoff is needed.
        text = note
        if len(body) > 512:
            keep = len(body) // 2
            text += "\n\nPrevious summary excerpt (incomplete):\n" + body[:keep]
        unknown = sum(isinstance(m, ToolResultMessage) and m.status == "unknown" for m in history)
        minimal = LEGACY_SUMMARY_PREFIX + (
            " Earlier details remain in the original transcript. Recover missing evidence before acting. "
            f"Unknown action outcomes: {unknown}. Do not assume success or repeat uncertain actions."
        )
        for value in (text, note, minimal):
            changed = list(messages)
            changed[index] = replace(message, text=value, reasoning=None, provider_data={})
            if reduced := candidate(changed, "summary_cut"):
                return reduced
        if not unknown:
            if reduced := candidate(messages[:index] + messages[index + 1 :], "summary_cut"):
                return reduced

    protected = _protected(messages)
    dropped = set()
    units = sorted(
        _units(messages),
        key=lambda unit: any(isinstance(m, UserMessage) for m in messages[unit[0] : unit[1]]),
    )
    for start, stop, pending in units:
        indices = set(range(start, stop))
        if pending or indices & protected or any(_summary(m) for m in messages[start:stop]):
            continue
        dropped.update(indices)
        changed = [m for i, m in enumerate(messages) if i not in dropped]
        if not any(_summary(m) for m in changed):
            first_user = next(
                (i for i, m in enumerate(changed) if isinstance(m, UserMessage)), len(changed)
            )
            changed.insert(first_user, AssistantMessage(note))
        if reduced := candidate(changed, "tail_cut"):
            return reduced

    # Descriptions and examples are optional. Names and validation schemas remain intact.
    def strip_docs(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in {"description", "examples", "$comment"}:
                    continue
                if key in {
                    "properties",
                    "patternProperties",
                    "$defs",
                    "definitions",
                    "dependentSchemas",
                }:
                    result[key] = {name: strip_docs(schema) for name, schema in item.items()}
                elif key in {"allOf", "anyOf", "oneOf", "prefixItems"} and isinstance(item, list):
                    result[key] = [strip_docs(schema) for schema in item]
                elif key in {
                    "items",
                    "additionalProperties",
                    "contains",
                    "propertyNames",
                    "not",
                    "if",
                    "then",
                    "else",
                    "unevaluatedItems",
                    "unevaluatedProperties",
                }:
                    result[key] = strip_docs(item)
                else:
                    result[key] = deepcopy(item)
            return result
        return value

    tools = [
        replace(spec, description=spec.name, parameters=strip_docs(deepcopy(spec.parameters)))
        for spec in request.tools
    ]
    return candidate(messages, "tool_documentation_cut", tools)
