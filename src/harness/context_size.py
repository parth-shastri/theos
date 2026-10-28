"""Small, conservative request-size estimates for compaction preflight."""

from __future__ import annotations

import json

from harness.types import AssistantMessage, ModelRequest, UserMessage


class ContextOverflowError(ValueError):
    """The provider rejected the input because its context window is full."""


def _text_tokens(text):
    """Estimate four bytes per token; count dense CJK characters as one each."""
    if not text:
        return 0
    text = str(text)
    if text.isascii():
        return (len(text) + 3) // 4
    dense = sum("\u1100" <= char <= "\uffef" for char in text)
    return dense + (len(text.encode("utf-8", "replace")) + 3) // 4


def request_size(request: ModelRequest) -> int:
    """Count visible messages, tool schemas, framing, and a safe image allowance."""
    total = 128
    for message in request.messages:
        if isinstance(message, AssistantMessage):
            text = json.dumps(
                [
                    message.text,
                    message.reasoning,
                    [(c.id, c.name, c.arguments) for c in message.tool_calls],
                ],
                ensure_ascii=False,
            )
        else:
            text = message.content
        total += _text_tokens(text) + 16
        if isinstance(message, UserMessage):
            total += 4096 * len(message.images)
    for tool in request.tools:
        total += (
            _text_tokens(
                json.dumps([tool.name, tool.description, tool.parameters], ensure_ascii=False)
            )
            + 16
        )
    return total
