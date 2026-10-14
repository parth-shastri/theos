"""Live delivery queues for active turns."""

import asyncio
import time
from dataclasses import dataclass, field

from harness import Inbox


@dataclass
class Turn:
    """Live delivery state. SQLite owns the durable conversation state."""

    owner: str
    session_id: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=512))
    task: asyncio.Task | None = None
    raw_events: bool = False
    research_task: str | None = None
    research_id: str | None = None
    inbox: Inbox = field(default_factory=Inbox)
    provider_failure: Exception | None = None
    delegate_results: dict[str, dict[str, dict]] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    tool_activity: dict[tuple, dict] = field(default_factory=dict)

    def observe_tool(self, event):
        """Count parent and delegate calls before display queues can drop events."""
        from harness import PendingApproval, ToolFinished
        from harness.events import ToolStarted

        if isinstance(event, ToolStarted):
            key = (event.parent_call_id, event.call.id)
            self.tool_activity[key] = {
                "status": "running",
                "skill": event.call.arguments.get("name")
                if event.call.name == "load_skill"
                else None,
            }
        elif isinstance(event, ToolFinished):
            result = event.result
            key = (
                event.parent_call_id,
                result.call.id if isinstance(result, PendingApproval) else result.call_id,
            )
            item = self.tool_activity.setdefault(key, {"skill": None})
            item["status"] = (
                "waiting_for_approval" if isinstance(result, PendingApproval) else result.status
            )

    def stats(self):
        """Return measured activity, without arguments or private tool results."""
        from collections import Counter

        outcomes = Counter(item["status"] for item in self.tool_activity.values())
        skills = sorted(
            {
                " ".join(item["skill"].split())[:128]
                for item in self.tool_activity.values()
                if item["status"] == "completed" and isinstance(item["skill"], str)
            }
        )
        return {
            "elapsed_seconds": max(0, time.monotonic() - self.started_at),
            "tool_calls": len(self.tool_activity),
            "tool_outcomes": dict(outcomes),
            "skills": skills,
        }

    def emit(self, value):
        """Queue display progress without blocking the active tool."""
        # A slow or closed browser must not block an external write in progress.
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(value)

    async def events(self):
        """Yield display events until this turn ends."""
        while True:
            event = await self.queue.get()
            yield event
            if event["type"] == "done":
                return
