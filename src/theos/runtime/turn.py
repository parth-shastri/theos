"""In-memory state for delivering one active turn; SQLite stores its durable state."""

import asyncio
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4

from harness import Inbox

logger = logging.getLogger("theos")


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
    first_model_call_logged: bool = False
    request_received_at: float | None = None
    delegate_results: dict[str, dict[str, dict]] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    phase_seconds: dict[str, float] = field(default_factory=dict)
    model_started_at: dict[str | None, float] = field(default_factory=dict)
    model_active_index: dict[str | None, int] = field(default_factory=dict)
    model_attempts: list[dict[str, float | int | str | bool]] = field(default_factory=list)
    tool_started_at: dict[tuple[str | None, str], tuple[float, str]] = field(default_factory=dict)
    tool_by_name: dict[str, dict[str, float | int]] = field(default_factory=dict)
    model_calls: int = 0
    model_completed_calls: int = 0
    model_seconds: float = 0.0
    model_wait_seconds: float = 0.0
    model_wait_observed: set[str | None] = field(default_factory=set)
    tool_completed_calls: int = 0
    tool_seconds: float = 0.0
    first_model_call_seconds: float | None = None
    first_output_seconds: float | None = None
    done_queued_at: float | None = None
    delivery_logged: bool = False
    delivery_consumer_closed: bool = False
    final_status: str = "failed"
    finalization_started_at: float | None = None
    tool_activity: dict[tuple, dict] = field(default_factory=dict)
    loaded_skills: set[str] = field(default_factory=set)

    @contextmanager
    def phase(self, name):
        """Measure one fixed runtime phase independently of optional tracing."""
        started = time.monotonic()
        try:
            yield
        finally:
            self.phase_seconds[name] = self.phase_seconds.get(name, 0.0) + max(
                0.0, time.monotonic() - started
            )

    def observe_timing(self, event):
        """Count model and tool work from typed events, excluding their payloads."""
        from harness import PendingApproval, ToolFinished
        from harness.events import (
            GenerationComplete,
            ModelCalled,
            ModelResponded,
            ReasoningDelta,
            TextDelta,
            ToolCallDelta,
            ToolStarted,
        )

        now = time.monotonic()
        parent = getattr(event, "parent_call_id", None)
        if isinstance(event, ModelCalled):
            self.model_calls += 1
            self.model_started_at[parent] = now
            self.model_wait_observed.discard(parent)
            if len(self.model_attempts) < 64:
                self.model_active_index[parent] = len(self.model_attempts)
                self.model_attempts.append(
                    {
                        "ordinal": self.model_calls,
                        "scope": "delegate" if parent is not None else "parent",
                        "started_at": now,
                        "complete": False,
                    }
                )
            if self.first_model_call_seconds is None and parent is None:
                self.first_model_call_seconds = max(0.0, now - self.started_at)
        elif isinstance(event, (TextDelta, ReasoningDelta, ToolCallDelta, GenerationComplete)):
            started = self.model_started_at.get(parent)
            if started is not None and parent not in self.model_wait_observed:
                self.model_wait_observed.add(parent)
                wait = max(0.0, now - started)
                self.model_wait_seconds += wait
                if parent in self.model_active_index:
                    self.model_attempts[self.model_active_index[parent]]["first_event_seconds"] = (
                        wait
                    )
        elif isinstance(event, ModelResponded):
            started = self.model_started_at.pop(parent, None)
            if started is not None:
                if parent not in self.model_wait_observed:
                    self.model_wait_seconds += max(0.0, now - started)
                if parent in self.model_active_index:
                    attempt = self.model_attempts[self.model_active_index.pop(parent)]
                    attempt["seconds"] = max(0.0, now - started)
                    attempt["complete"] = True
                self.model_completed_calls += 1
                self.model_seconds += max(0.0, now - started)
            self.model_wait_observed.discard(parent)
        elif isinstance(event, ToolStarted):
            self.tool_started_at[(parent, event.call.id)] = (now, event.call.name)
        elif isinstance(event, ToolFinished):
            result = event.result
            call_id = result.call.id if isinstance(result, PendingApproval) else result.call_id
            active = self.tool_started_at.pop((parent, call_id), None)
            if active is not None:
                started, name = active
                duration = max(0.0, now - started)
                self.tool_completed_calls += 1
                self.tool_seconds += duration
                tool = self.tool_by_name.setdefault(name, {"calls": 0, "seconds": 0.0})
                tool["calls"] += 1
                tool["seconds"] += duration

    def timing_profile(self):
        """Return bounded numeric timings and counts for the application log."""
        now = time.monotonic()
        result = dict(self.phase_seconds)
        result.update(
            total_seconds=max(0.0, now - self.started_at),
            model_seconds=self.model_seconds
            + sum(max(0.0, now - started) for started in self.model_started_at.values()),
            model_wait_seconds=self.model_wait_seconds,
            tool_seconds=self.tool_seconds
            + sum(max(0.0, now - started) for started, _ in self.tool_started_at.values()),
            model_calls=self.model_calls,
            model_completed_calls=self.model_completed_calls,
            tool_completed_calls=self.tool_completed_calls,
            tool_incomplete_calls=len(self.tool_started_at),
            model_incomplete_calls=len(self.model_started_at),
        )
        if self.request_received_at is not None:
            result["request_accept_seconds"] = max(0.0, self.started_at - self.request_received_at)
        if "prompt_assembly_seconds" in result and "memory_retrieval_seconds" in result:
            # Memory retrieval is measured inside prompt setup; report exclusive work.
            result["prompt_assembly_seconds"] = max(
                0.0, result["prompt_assembly_seconds"] - result["memory_retrieval_seconds"]
            )
        if self.first_model_call_seconds is not None:
            result["time_to_first_model_call_seconds"] = self.first_model_call_seconds
        if self.first_output_seconds is not None:
            result["time_to_first_output_seconds"] = self.first_output_seconds
        if self.finalization_started_at is not None:
            result["finalize_seconds"] = max(0.0, now - self.finalization_started_at)
        result["model_attempts"] = [
            {
                **{key: value for key, value in attempt.items() if key != "started_at"},
                "seconds": attempt.get("seconds", max(0.0, now - attempt["started_at"])),
            }
            for attempt in self.model_attempts
        ]
        result["tools"] = self.tool_by_name
        return result

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
        now = time.monotonic()
        if self.first_output_seconds is None and value.get("type") != "done":
            self.first_output_seconds = max(0.0, now - self.started_at)
        if value.get("type") == "done":
            self.done_queued_at = now
        # A slow or closed browser must not block an external write in progress. Drop the
        # oldest display event when full; the next complete assistant event repairs the view.
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(value)
        if value.get("type") == "done" and self.delivery_consumer_closed:
            self._log_response_delivery("closed")

    def _log_response_delivery(self, state):
        """Log consumer drain once, without depending on the transport."""
        if self.delivery_logged or self.done_queued_at is None:
            return
        self.delivery_logged = True
        logger.info(
            "response_delivery",
            extra={
                "session_id": self.session_id,
                "response_delivery_seconds": max(0.0, time.monotonic() - self.done_queued_at),
                "delivery_state": state,
            },
        )

    async def events(self):
        """Yield display events until this turn ends."""
        # The done marker is the single stop signal shared by all transport readers.
        try:
            while True:
                event = await self.queue.get()
                if event["type"] == "done":
                    yield event
                    self._log_response_delivery("consumed")
                    return
                yield event
        finally:
            self.delivery_consumer_closed = True
            if not self.delivery_logged:
                self._log_response_delivery("closed")
