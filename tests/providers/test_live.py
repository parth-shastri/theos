"""One live round trip per provider, run only when its key is present.

Each test sends one tool call, answers it, and reads the final text. That is
the smallest exchange that exercises encode, decode, the call id mapping, and
the replay rule against the real API. The default test run deselects them
through the `-m "not live"` in `addopts`. Run them with:

    uv run pytest tests/providers/test_live.py -m live -q
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values

from harness.types import ModelRequest, ToolResultMessage, ToolSpec, UserMessage

ENV_FILE = Path(__file__).resolve().parents[2] / "env" / "local.env"
KEYS = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}

PROMPT = "What is the status of order 9127412? Use the tool."
ANSWER = '{"status": "shipped"}'

SPEC = ToolSpec(
    name="get_order_status",
    description="Return the shipping status of one order",
    parameters={
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "The order id"}},
        "required": ["order_id"],
    },
)


def key(name: str) -> str | None:
    """Return one key from `env/local.env`, or None when it is not there."""
    value = KEYS.get(name)
    return value or None


async def round_trip(model) -> None:
    """Ask for the tool, answer it, and check the model reads the answer back."""
    first = await model.generate(ModelRequest([UserMessage(PROMPT)], [SPEC]))
    assert len(first.tool_calls) == 1, f"expected one tool call, got {first.tool_calls}"
    call = first.tool_calls[0]
    assert call.name == "get_order_status"
    assert first.stop_reason == "tool_calls"

    history = [
        UserMessage(PROMPT),
        first,
        ToolResultMessage(call_id=call.id, name=call.name, content=ANSWER),
    ]
    second = await model.generate(ModelRequest(history, [SPEC]))
    assert second.tool_calls == []
    assert "shipped" in (second.text or "").lower()
    assert second.stop_reason == "stop"


@pytest.mark.live
@pytest.mark.skipif(not key("OPENAI_API_KEY"), reason="OPENAI_API_KEY is not in env/local.env")
async def test_openai_round_trip():
    from openai import AsyncOpenAI

    from harness.providers.openai import OpenAIChatModel

    client = AsyncOpenAI(api_key=key("OPENAI_API_KEY"))
    await round_trip(OpenAIChatModel(client, "gpt-5-nano"))


@pytest.mark.live
@pytest.mark.skipif(
    not key("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY is not in env/local.env"
)
async def test_anthropic_round_trip():
    from anthropic import AsyncAnthropic

    from harness.providers.anthropic import AnthropicChatModel

    client = AsyncAnthropic(api_key=key("ANTHROPIC_API_KEY"))
    # Haiku 4.5 is the cheapest id the Claude API reference names, and it takes
    # an explicit thinking budget rather than the adaptive default.
    await round_trip(AnthropicChatModel(client, "claude-haiku-4-5", thinking=None))


@pytest.mark.live
@pytest.mark.skipif(not key("GEMINI_API_KEY"), reason="GEMINI_API_KEY is not in env/local.env")
async def test_gemini_round_trip():
    from google import genai

    from harness.providers.gemini import GeminiChatModel

    client = genai.Client(api_key=key("GEMINI_API_KEY"))
    await round_trip(GeminiChatModel(client, "gemini-2.5-flash"))
