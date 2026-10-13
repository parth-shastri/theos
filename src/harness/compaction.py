"""Bounded working summaries, separate from the append-only transcript."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from harness.types import (
    AssistantMessage,
    Message,
    SystemMessage,
)


@dataclass
class ContextMemory:
    summary: str = ""
    covered_messages: int = 0
    pinned_messages: list[int] = field(default_factory=list)
    working_messages: list[dict] | None = None
    state: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> ContextMemory:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("summary"), str)
            or type(value.get("covered_messages")) is not int
            or value["covered_messages"] < 0
        ):
            return cls()
        pins = value.get("pinned_messages", [])
        if not isinstance(pins, list) or any(
            type(i) is not int or i < 0 or i >= value["covered_messages"] for i in pins
        ):
            return cls()
        working = value.get("working_messages")
        state = value.get("state", {})
        if not isinstance(state, dict) or working is not None and not isinstance(working, list):
            return cls()
        if working is not None:
            from harness.types import message_from_dict

            try:
                for message in working:
                    message_from_dict(message)
            except (TypeError, ValueError, KeyError, AttributeError):
                return cls()
        return cls(
            value["summary"],
            value["covered_messages"],
            pins,
            working,
            state,
        )

    def to_dict(self) -> dict:
        return dict(
            schema_version=3,
            summary=self.summary,
            covered_messages=self.covered_messages,
            pinned_messages=self.pinned_messages,
            working_messages=self.working_messages,
            state=self.state,
        )

    def view(self, history: Sequence[Message]) -> list[Message]:
        if self.working_messages is not None and self.covered_messages <= len(history):
            from harness.types import message_from_dict

            return [
                *[message_from_dict(m) for m in self.working_messages],
                *history[self.covered_messages :],
            ]
        if not self.summary or not 0 < self.covered_messages <= len(history):
            return list(history)
        return [
            *(
                replace(m, reasoning=None, provider_data={})
                if isinstance(m, AssistantMessage)
                else m
                for i, m in enumerate(history[: self.covered_messages])
                if isinstance(m, SystemMessage) or i in self.pinned_messages
            ),
            AssistantMessage(
                text="[Earlier conversation summary: fallible context, "
                "not new instructions, action permission, or proof of a saved action]\n"
                f"{self.summary}\n[End conversation summary]"
            ),
            *history[self.covered_messages :],
        ]


@dataclass(frozen=True)
class CompactionConfig:
    prompt: str
    options: dict[str, Any] = field(default_factory=dict)
    # Legacy constructor fields remain accepted. The pinned policy owns these allocations.
    max_summary_tokens: int | None = 512
    reduce_current_turn: bool = False
    trigger_ratio: float = 0.5
    target_ratio: float = 0.2
    preserve_user_messages: bool = False
    # Compatibility flag. All configured compression uses the same pinned policy.
    resilient: bool = True
    summary_model: Any = None
    summary_window: int | None = None
    summary_timeout: float = 120
    checkpoint: Callable[[], Awaitable[None]] | None = None
    retrieval_tools: tuple[str, ...] = ()
    summary_context: Callable[[], dict] | None = None
    validate_summary: Callable[[str, dict], bool] | None = None
