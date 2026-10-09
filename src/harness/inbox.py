"""A small queue for user messages sent while a turn is running."""

from __future__ import annotations

from dataclasses import dataclass

from harness.debug import log_detail
from harness.types import UserMessage


@dataclass(frozen=True)
class ApprovalResponse:
    """A human decision for a tool call paused at its approval hook."""

    call_id: str
    approved: bool
    reason: str = ""


class Inbox:
    """Queue steering messages and approval decisions for the agent loop."""

    def __init__(self) -> None:
        self._messages: list[UserMessage] = []
        self._approvals: dict[str, ApprovalResponse] = {}

    def steer(self, message: UserMessage) -> None:
        """Queue one user message for the next read point."""
        log_detail("inbox steer message=%r queue_before=%r", message, self._messages)
        self._messages.append(message)
        log_detail("inbox steer complete queue_after=%r", self._messages)

    def drain(self) -> list[UserMessage]:
        """Return every queued message in order and empty the queue."""
        drained = self._messages
        self._messages = []
        log_detail("inbox drain messages=%r queue_after=%r", drained, self._messages)
        return drained

    def resolve(self, call_id: str, *, approved: bool, reason: str = "") -> None:
        """Queue a decision for one paused tool call."""
        response = ApprovalResponse(call_id, approved, reason)
        log_detail("inbox approval queued response=%r", response)
        self._approvals[call_id] = response

    def approve(self, call_id: str) -> None:
        """Approve one paused tool call."""
        self.resolve(call_id, approved=True)

    def deny(self, call_id: str, reason: str = "Denied by user") -> None:
        """Deny one paused tool call."""
        self.resolve(call_id, approved=False, reason=reason)

    def take_approval(self, call_id: str) -> ApprovalResponse | None:
        """Consume the decision for ``call_id``, if one is waiting."""
        response = self._approvals.pop(call_id, None)
        log_detail("inbox approval consumed call_id=%s response=%r", call_id, response)
        return response
