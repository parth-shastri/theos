"""Bound JSON trace content without changing model requests or tool values."""

import json
from itertools import islice

from pydantic import BaseModel

from harness import AssistantMessage, SystemMessage, ToolResultMessage, UserMessage


def message_content(message):
    """Use the OTel GenAI role and parts schema. Omit binary and provider state."""
    if isinstance(message, (SystemMessage, UserMessage)):
        return {
            "role": "system" if isinstance(message, SystemMessage) else "user",
            "parts": [{"type": "text", "content": message.content}],
        }
    if isinstance(message, ToolResultMessage):
        return {
            "role": "tool",
            "parts": [
                {
                    "type": "tool_call_response",
                    "id": message.call_id,
                    "response": message.content
                    if message.status == "completed"
                    else message.status,
                }
            ],
        }
    if isinstance(message, AssistantMessage):
        parts = []
        if message.text:
            parts.append({"type": "text", "content": message.text})
        parts.extend(
            {"type": "tool_call", "id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls[:16]
        )
        return {"role": "assistant", "parts": parts}
    return {"role": "user", "parts": [{"type": "text", "content": "[unsupported message]"}]}


def bounded_json(value, limit):
    """Keep valid JSON within a UTF-8 byte limit, with bounded traversal and depth."""
    truncated = False

    def build(text_limit, item_limit):
        remaining = limit
        nodes = 0

        def walk(item, depth=0):
            nonlocal remaining, nodes, truncated
            nodes += 1
            if depth > 10 or nodes > 1024 or remaining <= 0:
                truncated = True
                return "[truncated]"
            if isinstance(item, str):
                # Slice before encoding so a large string cannot allocate a large copy.
                size = min(remaining, text_limit)
                encoded = item[:size].encode("utf-8")
                text = encoded[:size].decode("utf-8", errors="ignore")
                remaining -= len(text.encode("utf-8"))
                if len(text) < len(item):
                    truncated = True
                    return text + "[truncated]"
                return text
            if isinstance(item, BaseModel):
                pairs = ((key, getattr(item, key)) for key in type(item).model_fields)
            elif isinstance(item, dict):
                pairs = item.items()
            else:
                pairs = None
            if pairs is not None:
                result = {}
                for key, child in islice(pairs, item_limit):
                    if nodes >= 1024 or remaining <= 0:
                        truncated = True
                        break
                    safe_key = str(key)[:128]
                    if any(
                        word in safe_key.lower()
                        for word in (
                            "password",
                            "secret",
                            "authorization",
                            "api_key",
                            "access_token",
                            "refresh_token",
                            "cookie",
                        )
                    ):
                        result[safe_key] = "[redacted]"
                    else:
                        result[safe_key] = walk(child, depth + 1)
                if (
                    len(type(item).model_fields if isinstance(item, BaseModel) else item)
                    > item_limit
                ):
                    truncated = True
                return result
            if isinstance(item, (list, tuple)):
                if len(item) > item_limit:
                    truncated = True
                result = []
                for child in item[:item_limit]:
                    if nodes >= 1024 or remaining <= 0:
                        truncated = True
                        break
                    result.append(walk(child, depth + 1))
                return result
            if item is None or isinstance(item, (bool, int, float)):
                return item
            return "[unsupported content]"

        return walk(value)

    for text_limit, item_limit in ((limit, 64), (limit // 4, 32), (256, 8), (64, 2)):
        encoded = json.dumps(
            build(text_limit, item_limit),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) <= limit:
            return encoded, truncated
        truncated = True
    return "[]" if isinstance(value, list) else "{}", True
