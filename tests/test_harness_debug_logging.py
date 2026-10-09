"""Debug logging coverage for the harness lifecycle."""

from __future__ import annotations

import logging

from harness import Agent, UserMessage
from harness.testing import FakeModel
from harness.types import AssistantMessage


async def test_debug_logging_includes_model_lifecycle_and_full_payload(caplog):
    caplog.set_level(logging.DEBUG, logger="harness")
    agent = Agent(model=FakeModel([AssistantMessage(text="done")]))

    await agent.run([UserMessage("hello")])

    output = caplog.text
    assert "type=ModelCalled" in output
    assert "type=TextDelta" in output
    assert "type=GenerationComplete" in output
    assert "type=ModelResponded" in output
    assert "type=TurnFinished" in output
    assert "content='hello'" in output
    assert "text='done'" in output
