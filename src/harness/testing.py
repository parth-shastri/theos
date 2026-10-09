"""A scripted model for tests and offline examples."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from harness.debug import log_detail, log_event
from harness.events import GenerationComplete, ModelEvent, TextDelta
from harness.model import Capabilities, collect_model_stream, default_estimate_tokens
from harness.types import AssistantMessage, ModelRequest

__all__ = ["FakeModel"]


class FakeModel:
    """Return the next scripted message for each request."""

    def __init__(
        self,
        script: Sequence[AssistantMessage | Exception],
        *,
        provider: str = "fake",
        model_id: str = "fake-1",
        capabilities: Capabilities = Capabilities(),
    ) -> None:
        self.script: list[AssistantMessage | Exception] = list(script)
        self.provider = provider
        self.model_id = model_id
        self.capabilities = capabilities
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        """Yield the next scripted response as a model event stream."""
        # Keep requests visible so tutorials and tests can inspect model input.
        log_detail("fake model request=%r script_remaining=%r", request, self.script)
        self.requests.append(request)
        if not self.script:
            raise RuntimeError("FakeModel script exhausted")

        # Exceptions let tests demonstrate failed streams.
        item = self.script.pop(0)
        if isinstance(item, Exception):
            event = TextDelta('{"tool_call": "partial"}')
            log_event(event, phase="fake-model")
            yield event
            raise item
        if item.text:
            event = TextDelta(item.text)
            log_event(event, phase="fake-model")
            yield event
        event = GenerationComplete(item)
        log_event(event, phase="fake-model")
        yield event

    async def generate(self, request: ModelRequest) -> AssistantMessage:
        """Consume `stream()` and return the final scripted message."""
        return await collect_model_stream(self.stream(request))

    async def estimate_tokens(self, request: ModelRequest) -> int:
        """Use the shared character heuristic."""
        return default_estimate_tokens(request)
