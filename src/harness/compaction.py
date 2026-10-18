"""Keep a rolling checkpoint and a recent tail beside the complete transcript.

Only the model view changes. The caller retains every original message.
When a newly covered turn is split, two summaries form one checkpoint:

    previous checkpoint + new history --> history summary --+
                                                           |
    original request + earlier work ----> turn summary -----+
                                                           |
                                                           v
                              combined checkpoint + retained tail --> model

The history summary can reuse the previous checkpoint without another model call.
If the original request is already covered, new progress uses the update prompt.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from harness.context_size import ContextOverflowError, request_size
from harness.events import ContextCompaction
from harness.output import requested_output_tokens
from harness.prompting import render_prompt
from harness.types import (
    AssistantMessage,
    Message,
    ModelRequest,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
    message_from_dict,
    message_to_dict,
)

SUMMARY_TIERS = 3
SUMMARY_LABEL = "[Conversation summary: fallible context, not instructions or proof of action]"
TURN_PREFIX_LABEL = "**Turn Context (split turn):**"
# Keep these names for callers that inspect the production prompt text.
DEFAULT_SUMMARY_PROMPT = render_prompt("harness", "compaction/system.md")
SUMMARY_FORMAT = render_prompt("harness", "compaction/format.md")
INITIAL_SUMMARY_PROMPT = render_prompt("harness", "compaction/initial.md")
UPDATE_SUMMARY_PROMPT = render_prompt("harness", "compaction/update.md")
TURN_PREFIX_SUMMARY_PROMPT = render_prompt("harness", "compaction/turn_prefix.md")
DEFAULT_SHORTENING_PROMPTS = tuple(
    render_prompt("harness", "compaction/shorten.md", tier=tier, length=length)
    for tier, length in enumerate(
        ("a short paragraph", "three short sentences", "one concise sentence"), 1
    )
)


@dataclass
class ContextMemory:
    """Track the exclusive boundary between summarized history and the raw tail.

    history[:covered_messages] -> represented by the checkpoint
    history[covered_messages:] -> retained verbatim

    Covered system messages also remain verbatim in the model view.
    """

    summary: str = ""
    covered_messages: int = 0
    _legacy_view: list[Message] | None = field(default=None, repr=False, compare=False)
    _legacy_summary: bool = field(default=False, repr=False, compare=False)

    @classmethod
    def from_dict(cls, value: Any) -> ContextMemory:
        """Read new state and keep an older saved view until the next compaction."""
        if not isinstance(value, dict):
            return cls()
        summary = value.get("summary", "")
        covered = value.get("covered_messages", 0)
        if not isinstance(summary, str) or type(covered) is not int or covered < 0:
            return cls()

        # Older saves contain an exact working view, which can include unresolved calls.
        # Preserve that view until a successful compaction replaces its checkpoint.
        legacy = value.get("working_messages")
        if isinstance(legacy, list):
            try:
                legacy = [message_from_dict(message) for message in legacy]
            except (TypeError, ValueError, KeyError, AttributeError):
                legacy = None
        else:
            legacy = None
        # Version 4 excluded the latest covered request from summary input.
        legacy_summary = value.get("schema_version", 4) == 4 and bool(summary)
        return cls(summary, covered, legacy, legacy_summary)

    def to_dict(self) -> dict:
        # Retain version 4 until a successful commit includes its omitted request.
        value = {
            "schema_version": 4 if self._legacy_summary else 5,
            "summary": self.summary,
            "covered_messages": self.covered_messages,
        }
        if self._legacy_view is not None:
            value["working_messages"] = [message_to_dict(message) for message in self._legacy_view]
        return value

    def checkpoint(self, history: Sequence[Message]) -> str:
        """Include a request omitted by the previous summary policy in its checkpoint."""
        if self._legacy_summary:
            # Put recovered input inside the checkpoint so it cannot appear as a fresh request.
            request = next(
                (
                    message
                    for message in reversed(history[: self.covered_messages])
                    if isinstance(message, UserMessage)
                ),
                None,
            )
            if request is not None:
                return render_prompt(
                    "harness",
                    "compaction/legacy_checkpoint.md",
                    request=request.content,
                    summary=self.summary,
                )
        return self.summary

    def view(
        self,
        history: Sequence[Message],
        *,
        summary: str | None = None,
        covered_messages: int | None = None,
    ) -> list[Message]:
        """Build a model view without changing or deleting any saved messages.

        A split turn has this order:

            saved: [older history] [request] [work A, B] | [work C]
            view:  [systems] [checkpoint: history + request + A, B] [work C]

        The bar marks covered_messages. The checkpoint replaces its left side.
        """
        if summary is None and covered_messages is None and self._legacy_view is not None:
            if self.covered_messages <= len(history):
                return [*self._legacy_view, *history[self.covered_messages :]]

        summary = self.checkpoint(history) if summary is None else summary
        covered = self.covered_messages if covered_messages is None else covered_messages
        if not 0 < covered <= len(history):
            return list(history)

        # Keep instruction priority while the checkpoint carries covered conversation messages.
        earlier_system = [
            message for message in history[:covered] if isinstance(message, SystemMessage)
        ]
        middle = (
            [
                UserMessage(
                    render_prompt(
                        "harness", "compaction/checkpoint.md", label=SUMMARY_LABEL, summary=summary
                    )
                )
            ]
            if summary
            else []
        )
        # A covered request belongs inside the checkpoint. Append only the untouched tail.
        return [*earlier_system, *middle, *history[covered:]]


@dataclass(frozen=True)
class CompactionConfig:
    """Small set of runtime choices for rolling summaries."""

    prompt: str = DEFAULT_SUMMARY_PROMPT
    options: dict[str, Any] = field(default_factory=dict)
    summary_timeout: float = 120
    on_commit: Callable[[ContextMemory, Sequence[Message]], Awaitable[None]] | None = None
    on_summary: Callable[[AssistantMessage], Awaitable[None]] | None = None
    trigger_ratio: float = 0.5
    tail_ratio: float = 0.025
    summary_model: Any = None
    summary_window: int | None = None
    additional_instructions: str = ""
    # Each supplied field replaces one operation. Omitted fields use production defaults.
    initial_prompt: str = INITIAL_SUMMARY_PROMPT
    update_prompt: str = UPDATE_SUMMARY_PROMPT
    turn_prefix_prompt: str = TURN_PREFIX_SUMMARY_PROMPT
    shortening_prompts: tuple[str, str, str] = DEFAULT_SHORTENING_PROMPTS

    def __post_init__(self):
        if (
            not isinstance(self.shortening_prompts, tuple)
            or len(self.shortening_prompts) != SUMMARY_TIERS
            or any(
                not isinstance(prompt, str) or not prompt.strip()
                for prompt in self.shortening_prompts
            )
        ):
            raise ValueError("shortening_prompts must contain three nonempty prompts")
        for name in ("prompt", "initial_prompt", "update_prompt", "turn_prefix_prompt"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty prompt")
        if not 0 < self.trigger_ratio <= 1:
            raise ValueError("trigger_ratio must be greater than 0 and at most 1")
        if not 0 < self.tail_ratio <= 0.5:
            raise ValueError("tail_ratio must be greater than 0 and at most 0.5")
        if self.summary_window is not None and self.summary_window < 1:
            raise ValueError("summary_window must be positive")


class CompactingModel:
    """Compact before a request and retry overflow using shorter summary tiers."""

    def __init__(self, model, window, config, memory, history, summary_budget):
        self.model = model
        self.window = window
        self.config = config
        self.memory = memory
        self.history = history
        self.summary_budget = summary_budget
        self._rebuild: Callable[[Sequence[Message]], Awaitable[ModelRequest]] | None = None

    def __getattr__(self, name):
        return getattr(self.model, name)

    async def estimate_tokens(self, request):
        return request_size(request)

    async def prepare(self, request, *, rebuild=None, force=False):
        """Return the original request or a smaller complete request."""
        if rebuild is not None:
            self._rebuild = rebuild
        # 1. Measure the full request, including tool schemas and reserved output.
        before = await self.estimate_tokens(request)
        output = requested_output_tokens(request)
        window = self.window
        if (
            not force
            and before < int(window * self.config.trigger_ratio)
            and before + output <= window
        ):
            yield request
            return

        if self._rebuild is None:
            raise RuntimeError("Compaction needs the harness request builder.")

        compaction_id = uuid4().hex
        yield ContextCompaction("started", before_tokens=before, compaction_id=compaction_id)
        # 2. Select coverage while retaining unanswered input and unfinished tool calls.
        old_summary = self.memory.checkpoint(self.history)
        old_covered = self.memory.covered_messages
        tail_start = self._tail_start(self.history, window)

        # Cover completed progress on overflow, but retain a new unanswered user message.
        covered = len(self.history) if force else max(old_covered, tail_start)
        if self.history and isinstance(self.history[-1], UserMessage):
            covered = min(covered, len(self.history) - 1)
        # Pending tool calls must remain exact, including during forced recovery.
        answered = {
            message.call_id for message in self.history if isinstance(message, ToolResultMessage)
        }
        for index, message in enumerate(self.history):
            if isinstance(message, AssistantMessage) and any(
                call.id not in answered for call in message.tool_calls
            ):
                covered = min(covered, index)
                break

        if covered <= old_covered and not force and before + output <= window:
            yield request
            return

        # 3. Check fixed instructions and retained messages before spending summary calls.
        # Even an empty checkpoint cannot help if that content and output do not fit.
        minimal = await self._rebuild(
            self.memory.view(self.history, summary="", covered_messages=covered)
        )
        minimal_size = await self.estimate_tokens(minimal)
        if minimal_size + output > window or (force and minimal_size >= before):
            raise ContextOverflowError(
                "The current task, instructions, and tool schemas do not fit the available context."
            )

        # 4. Build the complete checkpoint before changing active or saved memory.
        mandatory = force or before + output > window
        try:
            summary = await self._checkpoint_summary(old_summary, old_covered, covered)
        except Exception:
            summary = ""
        if not summary:
            # Never remove older messages unless the model gave us a summary for them.
            if not mandatory:
                yield ContextCompaction(
                    "failed",
                    before_tokens=before,
                    reason="summary_unavailable",
                    compaction_id=compaction_id,
                )
                yield request
                return
            raise ContextOverflowError(
                "The request overflowed and the conversation could not be summarized safely."
            )

        # 5. Rebuild and measure each candidate. Commit only a complete checkpoint that fits.
        # Shortening affects the combined checkpoint, including both parts of a split turn.
        tier = 1
        while True:
            candidate = await self._rebuild(
                self.memory.view(self.history, summary=summary, covered_messages=covered)
            )
            size = await self.estimate_tokens(candidate)
            if size + output <= window and (not force or size < before):
                await self._commit(summary, covered)
                yield ContextCompaction(
                    "completed",
                    before_tokens=before,
                    after_tokens=size,
                    covered_messages=covered,
                    reason="rolling_summary",
                    compaction_id=compaction_id,
                )
                yield candidate
                return

            if tier > SUMMARY_TIERS:
                break
            try:
                shorter = await self._summarize(summary, tier=tier)
            except Exception:
                shorter = ""
            tier += 1
            # Keep the last useful summary if a retry is empty or fails to shorten it.
            if shorter and len(shorter) < len(summary):
                summary = shorter
            yield ContextCompaction(
                "progress",
                before_tokens=before,
                after_tokens=size,
                covered_messages=covered,
                reason="shorter_summary",
                compaction_id=compaction_id,
            )

        # The fixed prompt, tools, and current user turn are the irreducible request.
        raise ContextOverflowError(
            "The current task, instructions, and tool schemas do not fit the available context."
        )

    async def _checkpoint_summary(self, previous, start, covered):
        """Summarize history and a split turn separately before combining them.

        With a newly covered user request at split:

            previous + history[start:split] -> history summary --+
                                                                +-> checkpoint
            history[split:covered] ---------> turn summary -----+
            history[covered:] --------------> retained verbatim

        Both summary parts must succeed. Neither part commits memory on its own.
        """
        # 1. Locate the request that starts the split turn.
        # A retained user message starts a whole unsummarized turn.
        # If its request was covered earlier, the update path retains that checkpoint's context.
        split = None
        if covered == len(self.history) or not isinstance(self.history[covered], UserMessage):
            split = next(
                (
                    index
                    for index in range(covered - 1, start - 1, -1)
                    if isinstance(self.history[index], UserMessage)
                ),
                None,
            )
        history_end = covered if split is None else split
        # 2. Summarize new history, or reuse the previous checkpoint when history is unchanged.
        messages = list(enumerate(self.history[start:history_end], start))
        history_summary = previous
        if messages or split is None:
            source = self._summary_source(
                previous, messages, self.window, self.config.trigger_ratio
            )
            history_summary = await self._summarize(source, tier=0, update=bool(previous))
            if not history_summary:
                return ""
        if split is None:
            return history_summary

        # 3. Summarize the original request and covered progress in their own model call.
        prefix = list(enumerate(self.history[split:covered], split))
        source = self._summary_source(
            "", prefix, self.window, self.config.trigger_ratio, preserve_user=True
        )
        turn_summary = await self._summarize(source, tier=0, turn_prefix=True)
        if not turn_summary:
            return ""
        # 4. Combine successful parts. prepare() still has to measure and persist the result.
        turn_context = f"{TURN_PREFIX_LABEL}\n\n{turn_summary}"
        return f"{history_summary}\n\n---\n\n{turn_context}" if history_summary else turn_context

    async def _summarize(self, source, *, tier, update=False, turn_prefix=False):
        from harness.model import collect_model_stream

        if not source or self.summary_budget is not None and not self.summary_budget.spend():
            return ""
        # Select one operation format. Shortening must not also require structured headings.
        #
        # tier > 0  -> shortening
        # turn_prefix -> original request + progress
        # update    -> previous checkpoint + new messages
        # otherwise -> initial history summary
        if tier:
            operation = self.config.shortening_prompts[tier - 1]
        elif turn_prefix:
            operation = self.config.turn_prefix_prompt
        else:
            operation = self.config.update_prompt if update else self.config.initial_prompt
        instructions = render_prompt(
            "harness",
            "compaction/instructions.md",
            shared=self.config.prompt,
            operation=operation,
            separator="\n" if tier else "\n\n",
            additional_instructions=self.config.additional_instructions,
        )
        options = dict(self.config.options)
        summary_model = self.config.summary_model or self.model
        summary_window = self.config.summary_window or self.window
        output_limit = max(1, int(summary_window * self.config.tail_ratio))
        for key in ("max_output_tokens", "max_tokens", "max_completion_tokens"):
            value = options.get(key)
            if type(value) is int and value > output_limit:
                options[key] = output_limit
        request = ModelRequest([SystemMessage(instructions), UserMessage(source)], options=options)
        async with asyncio.timeout(self.config.summary_timeout):
            result = await collect_model_stream(summary_model.stream(request))
        # Account for provider usage even when the response fails completeness checks below.
        if self.config.on_summary:
            await self.config.on_summary(result)
        text = (result.text or "").strip()
        if result.tool_calls or result.stop_reason in {"length", "max_tokens", "cut_off"}:
            raise ValueError("The summary was incomplete.")
        if not text:
            raise ValueError("The model returned an empty summary.")
        return text

    @staticmethod
    def _summary_source(previous, messages, window, trigger_ratio, *, preserve_user=False):
        """Serialize evidence and point oversized messages to their saved history indexes."""
        rows = []
        if previous:
            rows.append({"kind": "previous_summary", "content": previous})
        for index, message in messages:
            # A split-turn summary needs the original request, rather than an index-only marker.
            if not (preserve_user and isinstance(message, UserMessage)) and request_size(
                ModelRequest([message])
            ) > int(window * trigger_ratio):
                row = {
                    "kind": "large_message_available_in_history",
                    "message_index": index,
                    "note": "The full message is saved. Use history_read or history_search for exact content.",
                }
                if isinstance(message, UserMessage):
                    row["role"] = "user"
                elif isinstance(message, AssistantMessage):
                    row["role"] = "assistant"
                    row["tool_calls"] = [
                        {"id": call.id, "name": call.name} for call in message.tool_calls
                    ]
                elif isinstance(message, ToolResultMessage):
                    row.update(
                        role="tool",
                        tool=message.name,
                        call_id=message.call_id,
                        status=message.status,
                    )
                rows.append(row)
                continue
            if isinstance(message, SystemMessage):
                continue
            if isinstance(message, UserMessage):
                row = {"role": "user", "content": message.content}
                if message.images:
                    row["images"] = [image.filename or "attached image" for image in message.images]
            elif isinstance(message, AssistantMessage):
                row = {
                    "role": "assistant",
                    "content": message.text or "",
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "arguments": call.arguments}
                        for call in message.tool_calls
                    ],
                }
            elif isinstance(message, ToolResultMessage):
                row = {
                    "role": "tool",
                    "tool": message.name,
                    "status": message.status,
                    "content": message.content,
                }
            else:
                row = message_to_dict(message)
            rows.append(row)
        return json.dumps(rows, ensure_ascii=False)

    def _tail_start(self, history, window):
        """Keep a 2.5% tail without splitting a completed tool batch."""
        budget = int(window * self.config.tail_ratio)
        used = 0
        start = len(history)
        for index in range(len(history) - 1, -1, -1):
            cost = request_size(ModelRequest([history[index]]))
            if used + cost > budget:
                break
            used += cost
            start = index
        results = {}
        for index, message in enumerate(history):
            if isinstance(message, ToolResultMessage):
                results.setdefault(message.call_id, []).append(index)

        # The bar separates summarized messages from the retained tail:
        #
        # complete: [call] | [results, tail] -> [call, results] | [tail]
        # pending:  [call] | [some results]  -> | [call, some results]
        #
        # A completed batch can move wholly into the summary. An unfinished batch stays raw.
        for owner, message in enumerate(history):
            if not isinstance(message, AssistantMessage) or not message.tool_calls:
                continue
            call_ids = [call.id for call in message.tool_calls]
            result_indexes = [index for call_id in call_ids for index in results.get(call_id, [])]
            if owner < start and result_indexes and max(result_indexes) >= start:
                if all(results.get(call_id) for call_id in call_ids):
                    # A finished batch is summarized as a whole instead of widening the tail.
                    start = max(result_indexes) + 1
                else:
                    # An unfinished batch stays intact so the harness can safely resume it.
                    start = owner
        return start

    async def _commit(self, summary, covered):
        """Persist one complete checkpoint and restore all memory fields if saving fails."""
        # The schema marker, boundary, and checkpoint belong to the same rollback unit.
        previous = self.memory.to_dict()
        self.memory.summary = summary
        self.memory.covered_messages = covered
        self.memory._legacy_view = None
        self.memory._legacy_summary = False
        try:
            if self.config.on_commit:
                await self.config.on_commit(self.memory, self.history)
        except BaseException:
            restored = ContextMemory.from_dict(previous)
            self.memory.summary = restored.summary
            self.memory.covered_messages = restored.covered_messages
            self.memory._legacy_view = restored._legacy_view
            self.memory._legacy_summary = restored._legacy_summary
            raise

    async def stream(self, request):
        """Call the model; if context is rejected, rebuild from a shorter summary tier."""
        current = request
        while True:
            try:
                async with aclosing(self.model.stream(current)) as events:
                    async for event in events:
                        yield event
                return
            except ContextOverflowError:
                # Retry generation only. The caller still owns tool execution and its journal.
                smaller = None
                async for event in self.prepare(current, force=True):
                    if isinstance(event, ModelRequest):
                        smaller = event
                    else:
                        yield event
                if smaller is None or request_size(smaller) >= request_size(current):
                    raise
                current = smaller
