"""Display-only events for authenticated terminal clients."""

import json
from dataclasses import asdict, replace

from harness import PendingApproval, ToolFinished, TurnFinished
from renderer import events as display
from renderer.adapters import HarnessAdapter, events

EVENT_TYPES = {
    cls.__name__: cls
    for cls in (
        display.ModelStarted,
        display.ModelFinished,
        display.TextDelta,
        display.ReasoningDelta,
        display.ToolCallDelta,
        display.ToolStarted,
        display.ToolProgress,
        display.ToolFinished,
        display.ApprovalRequested,
        display.Notice,
        display.RunFinished,
    )
}


def approval_events(rows):
    return tuple(
        display.ApprovalRequested(
            row["id"],
            row["tool"],
            json.loads(row["arguments"]),
            "Review this saved action.\n" + json.dumps(json.loads(row["preview"]), indent=2),
        )
        for row in rows
    )


def encode_event(event):
    # Run results contain harness state. Only display values cross this boundary.
    if isinstance(event, display.RunFinished):
        event = replace(event, result=None)
    return {"event": type(event).__name__, "data": asdict(event)}


def decode_event(value):
    cls = EVENT_TYPES.get(value.get("event"))
    if cls is None:
        raise ValueError("The deployment sent an unsupported terminal event.")
    data = dict(value["data"])
    if cls is display.ModelFinished:
        data["requested_tools"] = tuple(data.get("requested_tools", ()))
    return cls(**data)


async def display_events(runtime, turn):
    """Keep server execution alive when the client closes its event stream."""
    adapter = HarnessAdapter()
    async for item in turn.events():
        if item["type"] == "harness":
            event = item["event"]
            if isinstance(event, TurnFinished) and event.parent_call_id is None:
                continue
            if isinstance(event, ToolFinished) and isinstance(event.result, PendingApproval):
                continue
            for normalized in events(adapter(event)):
                yield normalized
        elif item["type"] == "error":
            yield display.Notice(item["message"], "error")
        elif item["type"] == "file":
            yield display.Notice(
                f"File: {item['file_id']} · Download through the browser workspace."
            )
        elif item["type"] == "done":
            pending = approval_events(runtime.pending(turn.owner, turn.session_id))
            for request in pending:
                yield request
            yield display.RunFinished(item["status"], pending_count=len(pending))
