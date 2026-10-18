"""Long conversations with a compressible middle and explicit protected endpoints."""

from harness import AssistantMessage, UserMessage


def long_history():
    return [UserMessage("Preserve dates and exact values.")] + [
        message
        for i in range(18)
        for message in (
            UserMessage(f"Question {i}"),
            AssistantMessage(f"Finding {i}: " + "Evidence text. " * 1000),
        )
    ]
