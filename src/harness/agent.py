"""An agent bundles a model, tools, instructions, and hooks."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from contextlib import aclosing

from harness.compaction import CompactionConfig, ContextMemory
from typing import Any

from harness.hooks import Hooks
from harness.inbox import Inbox
from harness.context import default_estimate
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
from harness.tools import Tool
from harness.types import Budget, Message

__all__ = ["Agent"]


@dataclass
class Agent:
    """Reusable agent configuration. Conversation state stays with the caller."""

    model: ChatModel
    tools: Sequence[Tool] = ()
    instructions: Instructions | None = None
    hooks: Hooks = field(default_factory=Hooks)
    max_context_tokens: int | None = None
    estimate_tokens: EstimateTokens = default_estimate  # used to trim history
    context_window: int | None = None
    reserved_output_tokens: int = 1024
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
        """Consume `run_stream()` and return its final result."""
        return await collect_run_stream(
            self.run_stream(history, deps=deps, inbox=inbox, budget=budget,
                            compaction_budget=compaction_budget, memory=memory)
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
        async with aclosing(events):
            async for event in events:
                yield event
