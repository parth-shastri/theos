"""Shared assistant punctuation rules across streamed and saved output."""

from contextlib import asynccontextmanager

import pytest

from harness import AssistantMessage, SystemMessage
from harness.events import GenerationComplete, ModelResponded, ReasoningDelta, TextDelta
from theos.runtime.text import reply_text

from .conftest import collect


@pytest.mark.parametrize("dash", ["\u2014", "&mdash;", "&#8212;", "&#x2014;", "&#X02014;"])
def test_encoded_em_dash_cannot_reappear_after_markdown_rendering(dash):
    assert reply_text("Before " + dash + " after") == "Before - after"


@pytest.mark.parametrize(
    "channel,raw", [("browser", False), ("telegram-private", False), ("terminal", True)]
)
async def test_reply_style_is_enforced_across_transports(runtime, channel, raw):
    requests = []
    provider_data = {"signed_reasoning": "opaque\u2014payload"}

    class Model:
        async def stream(self, request):
            requests.append(request)
            yield TextDelta("First")
            yield TextDelta("\u2014next")
            yield ReasoningDelta("Reason\u2014result")
            yield GenerationComplete(
                AssistantMessage(
                    "First\u2014next",
                    reasoning="Reason\u2014result",
                    provider_data=provider_data,
                )
            )

    @asynccontextmanager
    async def factory(*args):
        yield Model()

    runtime.models = factory
    session = runtime.db.create_session("alice", "test", "default", channel)
    events = await collect(runtime.start("alice", session["id"], "User\u2014input", raw_events=raw))
    if raw:
        deltas = [
            e["event"].text
            for e in events
            if e["type"] == "harness" and isinstance(e["event"], (TextDelta, ReasoningDelta))
        ]
        responses = [
            e["event"].message
            for e in events
            if e["type"] == "harness" and isinstance(e["event"], ModelResponded)
        ]
        assert responses[-1].text == "First-next"
    else:
        deltas = [e["text"] for e in events if e["type"] in {"text", "reasoning"}]
        final = next(e for e in events if e["type"] == "assistant_complete")
        assert final["text"] == "First-next" and final["reasoning"] == "Reason-result"
    assert deltas == ["First", "-next", "Reason-result"]
    history = runtime.db.load_history("alice", session["id"])
    assert history[-1].text == "First-next" and history[-1].reasoning == "Reason-result"
    assert history[-1].provider_data == provider_data
    assert history[0].content == "User\u2014input"
    instructions = "\n".join(
        m.content for m in requests[0].messages if isinstance(m, SystemMessage)
    )
    assert "Never use em dashes" in instructions
    assert ("Your reply will appear in Telegram" in instructions) == channel.startswith("telegram")


async def test_generated_title_follows_the_shared_punctuation_rule(runtime, scripted_models):
    runtime.settings.auto_titles = True
    session = runtime.db.create_session("alice", "test", "default", "browser")
    scripted_models.responses.append(
        [
            AssistantMessage("A useful answer."),
            AssistantMessage("Plan\u2014next steps"),
        ]
    )
    events = await collect(runtime.start("alice", session["id"], "Make a plan"))
    assert next(e["title"] for e in events if e["type"] == "title") == "Plan-next steps"
    assert runtime.db.session("alice", session["id"])["title"] == "Plan-next steps"


async def test_fallback_title_avoids_em_dash_without_changing_user_input(runtime):
    session = runtime.db.create_session("alice", "test", "default", "browser")
    await collect(runtime.start("alice", session["id"], "Plan\u2014next steps"))
    assert runtime.db.session("alice", session["id"])["title"] == "Plan-next steps"
    assert runtime.db.load_history("alice", session["id"])[0].content == "Plan\u2014next steps"
