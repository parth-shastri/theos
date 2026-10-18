"""Translate harness events into UI events and safe, compact SQLite traces."""

import json
import time
from dataclasses import replace

from harness import PendingApproval, TextDelta, ToolFinished, TurnFinished
from harness.events import (
    ContextCompaction,
    ModelCalled,
    ModelResponded,
    ReasoningDelta,
    ToolStarted,
)
from theos.storage.messages import display_metadata

from .text import reply_text


def publish_event(runtime, turn, event, status):
    """Publish one event and return the latest turn status."""
    # Count tool outcomes before queueing display events: a slow client may cause old
    # display updates to be dropped, but turn statistics must still include the work.
    if hasattr(turn, "observe_tool"):
        turn.observe_tool(event)
    # Apply Theos' shared text rule to every generated stream chunk before it is displayed.
    if isinstance(event, (TextDelta, ReasoningDelta)):
        event = replace(event, text=reply_text(event.text))
    # Terminal raw mode needs the original typed harness event for its adapter. Browser
    # and Telegram receive a smaller transport-neutral dictionary below.
    if turn.raw_events:
        turn.emit({"type": "harness", "event": event})
    if isinstance(event, ContextCompaction) and not turn.raw_events:
        turn.emit(
            {
                "type": "compaction",
                "status": event.status,
                "before_tokens": event.before_tokens,
                "after_tokens": event.after_tokens,
                "reason": event.reason,
                "parent_call_id": event.parent_call_id,
                "compaction_id": event.compaction_id,
            }
        )
    # Delegate events are scoped by parent_call_id. Show child tool progress where supported,
    # but never let a child's answer mark the parent conversation as complete.
    if getattr(event, "parent_call_id", None) is not None:
        if not turn.raw_events and getattr(turn, "include_delegate_tool_progress", False):
            if isinstance(event, ToolStarted):
                turn.emit(
                    {
                        "type": "tool",
                        "name": event.call.name,
                        "call_id": event.call.id,
                        "arguments": event.call.arguments,
                        "parent_call_id": event.parent_call_id,
                        "status": "running",
                    }
                )
            elif isinstance(event, ToolFinished):
                result = event.result
                if isinstance(result, PendingApproval):
                    call = result.call
                    turn.emit(
                        {
                            "type": "tool",
                            "name": call.name,
                            "call_id": call.id,
                            "parent_call_id": event.parent_call_id,
                            "status": "waiting_for_approval",
                        }
                    )
                else:
                    turn.emit(
                        {
                            "type": "tool",
                            "name": result.name,
                            "call_id": result.call_id,
                            "parent_call_id": event.parent_call_id,
                            "status": result.status,
                        }
                    )
        return status
    # The remaining branch handles parent-turn events and records their safe summary.
    runtime.tracing.turn_event(event)
    if isinstance(event, ModelCalled):
        if not turn.raw_events:
            turn.emit({"type": "thinking", "display": {"created_at": time.time()}})
    elif isinstance(event, TextDelta):
        if not turn.raw_events:
            turn.emit({"type": "text", "text": event.text})
    elif isinstance(event, ReasoningDelta):
        if not turn.raw_events:
            payload = {"type": "reasoning", "text": event.text}
            if event.display_summary:
                payload["display_summary"] = True
            turn.emit(payload)
    elif isinstance(event, ModelResponded):
        # Completion replaces streamed partial text and carries usage for statistics.
        # Transports decide which display-safe fields they need from this event.
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
        # Keep arguments for the temporary tool-progress display; durable approvals and
        # checkpoint records are handled by hooks, not by this event translation.
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
        # A pending approval is different from a finished tool result: show the saved
        # approval list, and emit ordinary results only after the hook has persisted them.
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
        # Remember the final outcome so the done event and the durable trace agree.
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
