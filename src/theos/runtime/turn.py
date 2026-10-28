"""In-memory state for delivering one active turn; SQLite stores its durable state."""

import asyncio
import time
from dataclasses import dataclass, field
from uuid import uuid4

from harness import Inbox


@dataclass
class Turn:
    """Live delivery state. SQLite owns the durable conversation state."""

    # These identify which owner's conversation is producing the events.
    owner: str
    session_id: str
    # This bounded queue connects the background runtime task to a live transport reader.
    # It is intentionally not a durable event log; messages and tool results are saved in DB.
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=512))
    # The task performs the model/tool work while Telegram or a browser consumes queue events.
    task: asyncio.Task | None = None
    # Some clients need original typed harness events; most receive display-ready events.
    raw_events: bool = False
    include_delegate_tool_progress: bool = False
    browser_ui: bool = False
    tools_disabled: bool = False
    text_recovery: bool = False
    library_version: str | None = None
    output_message_id: str | None = None
    # Explicit research and provider failures are kept here so application code can resume
    # or report the right status without encoding that state in the UI queue.
    research_task: str | None = None
    research_id: str | None = None
    inbox: Inbox = field(default_factory=Inbox)
    provider_failure: Exception | None = None
    delegate_results: dict[str, dict[str, dict]] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    tool_activity: dict[tuple, dict] = field(default_factory=dict)
    loaded_skills: set[str] = field(default_factory=set)

    def prepare_output(self, *, new=False):
        """Assign an ID before a browser response streams or saves form state."""
        if self.browser_ui and (new or not self.output_message_id):
            self.output_message_id = uuid4().hex
        return self.output_message_id

    def observe_tool(self, event):
        """Count parent and delegate calls before display queues can drop events."""
        from harness import PendingApproval, ToolFinished
        from harness.events import ToolStarted

        # Tool identity includes the delegate parent because child agents can reuse call IDs.
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
            self.loaded_skills
            | {
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
        # A slow or closed browser must not block an external write in progress. Drop the
        # oldest display event when full; the next complete assistant event repairs the view.
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(value)

    async def events(self):
        """Yield display events until this turn ends."""
        # The done marker is the single stop signal shared by all transport readers.
        while True:
            event = await self.queue.get()
            yield event
            if event["type"] == "done":
                return
