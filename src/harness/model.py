"""The interface shared by every chat model adapter.

The harness loop depends on these methods and message types, not on a particular SDK.
Provider adapters translate this common request/event shape to each provider's API.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from harness.context import default_estimate
from harness.debug import log_detail, log_event
from harness.events import GenerationComplete, ModelEvent
from harness.types import AssistantMessage, ModelRequest

__all__ = [
    "Capabilities",
    "ChatModel",
    "Model",
    "collect_model_stream",
    "default_estimate_tokens",
]


@dataclass(frozen=True)
class Capabilities:
    """Features a model supports."""

    tools: bool = True
    parallel_tool_calls: bool = True
    forced_tool_choice: bool = (
        True  # False where the provider rejects tool_choice "any" or a named tool
    )
    json_schema_output: bool = False  # native structured output
    vision: bool = False


@runtime_checkable
class Model(Protocol):
    """The identity shared by all model types."""

    @property
    def provider(self) -> str: ...  # "openai" | "anthropic" | "gemini" | "llama"

    @property
    def model_id(self) -> str: ...


@runtime_checkable
class ChatModel(Model, Protocol):
    """A chat model that can generate an assistant message."""

    @property
    def capabilities(self) -> Capabilities: ...

    # Streaming is the main interface because transports can show progress as it arrives.
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...

    async def generate(self, request: ModelRequest) -> AssistantMessage: ...

    async def estimate_tokens(self, request: ModelRequest) -> int: ...


async def collect_model_stream(events: AsyncIterator[ModelEvent]) -> AssistantMessage:
    """Consume a model stream and return its final message."""
    # Intermediate events are useful to a live UI, but callers that need a complete
    # message must wait for exactly one GenerationComplete event.
    message: AssistantMessage | None = None
    async for event in events:
        log_event(event, phase="model-collect")
        if isinstance(event, GenerationComplete):
            if message is not None:
                raise RuntimeError("model stream produced more than one final message")
            message = event.message
    if message is None:
        raise RuntimeError("model stream ended without a final message")
    log_detail("model stream collected message=%r", message)
    return message


def default_estimate_tokens(request: ModelRequest) -> int:
    """Estimate request size using roughly four characters per token."""
    # Include tool schemas as well as conversation text; long schemas consume context too.
    total = default_estimate(request.messages)
    for spec in request.tools:
        total += max(1, len(json.dumps(spec.parameters)) // 4)
    return max(1, total)
