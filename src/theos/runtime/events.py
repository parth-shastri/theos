"""Translate harness events into transport events and content-free traces."""

import json
import time
from dataclasses import replace

from harness import PendingApproval, TextDelta, ToolFinished, TurnFinished
from harness.events import ModelCalled, ModelResponded, ReasoningDelta, ToolStarted
from theos.storage.messages import display_metadata

from .text import reply_text


def publish_event(runtime, turn, event, status):
    """Publish one event and return the latest turn status."""
    if isinstance(event, (TextDelta, ReasoningDelta)):
        event = replace(event, text=reply_text(event.text))
    if turn.raw_events:
        turn.emit({"type": "harness", "event": event})
    # Child progress belongs to its tool. It cannot finish or supply the parent answer.
    if getattr(event, "parent_call_id", None) is not None:
        return status
    if isinstance(event, ModelCalled):
        if not turn.raw_events:
            turn.emit({"type": "thinking", "display": {"created_at": time.time()}})
    elif isinstance(event, TextDelta):
        if not turn.raw_events:
            turn.emit({"type": "text", "text": event.text})
    elif isinstance(event, ReasoningDelta):
        if not turn.raw_events:
            turn.emit({"type": "reasoning", "text": event.text})
    elif isinstance(event, ModelResponded):
        if not turn.raw_events:
            turn.emit(
                {
                    "type": "assistant_complete",
                    "text": event.message.text,
                    "reasoning": event.message.reasoning,
                    "usage": event.message.usage,
                    "requested_tools": [call.name for call in event.message.tool_calls],
                    "display": display_metadata(event.message),
                }
            )
    elif isinstance(event, ToolStarted):
        if not turn.raw_events:
            turn.emit(
                {
                    "type": "tool",
                    "name": event.call.name,
                    "call_id": event.call.id,
                    "arguments": event.call.arguments,
                    "status": "running",
                }
            )
    elif isinstance(event, ToolFinished):
        if isinstance(event.result, PendingApproval) and not turn.raw_events:
            turn.emit(
                {
                    "type": "approvals",
                    "items": runtime.pending(turn.owner, turn.session_id),
                }
            )
        elif not isinstance(event.result, PendingApproval):
            if not turn.raw_events:
                turn.emit(
                    {
                        "type": "tool",
                        "name": event.result.name,
                        "call_id": event.result.call_id,
                        "content": event.result.content,
                        "status": event.result.status,
                    }
                )
            if event.result.status == "completed":
                try:
                    value = json.loads(event.result.content)
                    if isinstance(value, dict) and value.get("file_id"):
                        runtime.files.get(turn.owner, value["file_id"])
                        turn.emit({"type": "file", **value})
                except (ValueError, LookupError):
                    pass
    elif isinstance(event, TurnFinished):
        status = event.result.status
    if not isinstance(event, (TextDelta, ReasoningDelta)):
        runtime.db.execute(
            "INSERT INTO traces(owner,session,event,tool,status,created) VALUES (?,?,?,?,?,?)",
            (
                turn.owner,
                turn.session_id,
                type(event).__name__,
                event.call.name if isinstance(event, ToolStarted) else None,
                status if isinstance(event, TurnFinished) else None,
                time.time(),
            ),
        )
    return status
