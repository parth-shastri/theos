"""Bound model input without changing the complete, saved transcript."""

from __future__ import annotations

import json

from harness.compression_support import estimate_tokens_rough as text_tokens
from harness.types import (
    AssistantMessage,
    UserMessage,
)


class ContextOverflowError(ValueError):
    """The provider rejected the input because its context window is full."""


def request_size(request):
    """Count text, tool schemas, provider state, framing, and estimated image space.

    Provider usage anchors take precedence. This is the pinned UTF-8-aware rough estimate.
    """
    total = 128
    for message in request.messages:
        if isinstance(message, AssistantMessage):
            text = json.dumps(
                [
                    message.text,
                    message.reasoning,
                    {},  # Opaque provider state is priced only by provider usage.
                    [(c.id, c.name, c.arguments) for c in message.tool_calls],
                ],
                ensure_ascii=False,
            )
        else:
            text = message.content
        total += text_tokens(text) + 16
        if isinstance(message, UserMessage):
            total += 4096 * len(message.images)
    for spec in request.tools:
        total += (
            text_tokens(
                json.dumps([spec.name, spec.description, spec.parameters], ensure_ascii=False)
            )
            + 16
        )
    return total
