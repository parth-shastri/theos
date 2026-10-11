"""Live delivery queues for active turns."""

import asyncio
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
    delegate_results: dict[str, dict[str, dict]] = field(default_factory=dict)

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
