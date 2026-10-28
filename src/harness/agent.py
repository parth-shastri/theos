"""Configure one generic model-and-tools agent run.

Agent is not the conversation database. The caller supplies and retains history so the
same harness can work with Theos, tests, or another application.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

from harness.compaction import CompactionConfig, ContextMemory
from harness.context import default_estimate
from harness.hooks import Hooks
from harness.inbox import Inbox
from harness.limits import DEFAULT_EXECUTION_LIMITS, ExecutionLimits
from harness.loop import (
    EstimateTokens,
    Instructions,
    RunEvent,
    TurnResult,
    collect_run_stream,
    run_turn_stream,
)
from harness.model import ChatModel
from harness.output import DEFAULT_OUTPUT_RESERVATION
from harness.tools import Tool
from harness.types import Budget, Message

__all__ = ["Agent"]


@dataclass
class Agent:
    """Reusable agent configuration. Conversation state stays with the caller."""

    # The model follows the ChatModel protocol; a provider adapter supplies the actual API.
    model: ChatModel
    # These are the only actions the model can request on this run.
    tools: Sequence[Tool] = ()
    # Instructions guide the model but are not inserted into the caller's saved transcript.
    instructions: Instructions | None = None
    # Hooks let the application run policy and persistence around model/tool boundaries.
    hooks: Hooks = field(default_factory=Hooks)
    # Context and output settings constrain the request and reserve room for the answer.
    max_context_tokens: int | None = None
    estimate_tokens: EstimateTokens = default_estimate  # used to trim history
    context_window: int | None = None
    reserved_output_tokens: int = DEFAULT_OUTPUT_RESERVATION
    limits: ExecutionLimits = DEFAULT_EXECUTION_LIMITS
    compaction: CompactionConfig | None = None

    async def run(
        self,
        history: list[Message],
        *,
        deps: Any = None,
        inbox: Inbox | None = None,
        budget: Budget | None = None,
        compaction_budget: Budget | None = None,
        memory: ContextMemory | None = None,
    ) -> TurnResult:
        """Consume the event stream when a caller needs only the final result."""
        # Keep one implementation of turn logic: run() is the non-streaming convenience
        # wrapper around run_stream(), not a second model/tool loop.
        return await collect_run_stream(
            self.run_stream(
                history,
                deps=deps,
                inbox=inbox,
                budget=budget,
                compaction_budget=compaction_budget,
                memory=memory,
            )
        )

    async def run_stream(
        self,
        history: list[Message],
        *,
        deps: Any = None,
        inbox: Inbox | None = None,
        budget: Budget | None = None,
        compaction_budget: Budget | None = None,
        memory: ContextMemory | None = None,
    ) -> AsyncIterator[RunEvent]:
        """Yield every event produced while this agent runs one turn."""
        # Pass configuration into the harness loop. History is mutated in place so the
        # caller can save the completed assistant and tool messages afterward.
        events = run_turn_stream(
            self.model,
            self.tools,
            history,
            deps=deps,
            hooks=self.hooks,
            instructions=self.instructions,
            inbox=inbox,
            budget=budget,
            compaction_budget=compaction_budget,
            max_context_tokens=self.max_context_tokens,
            estimate_tokens=self.estimate_tokens,
            context_window=self.context_window,
            reserved_output_tokens=self.reserved_output_tokens,
            limits=self.limits,
            compaction=self.compaction,
            memory=memory,
        )
        # Closing the consumer also closes provider streams and any active tool batch.
        async with aclosing(events):
            async for event in events:
                yield event
