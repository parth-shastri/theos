"""Async harness adapter for the pinned middle-turn compression policy."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import aclosing, asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

from harness.compaction import ContextMemory
from harness.compression_policy import (
    ContextCompressor,
    _is_summary_refusal,
    _redact_compaction_text,
)
from harness.compression_support import parse_context_limit_from_error
from harness.context_fit import _protected, cut_request, smaller_request
from harness.context_size import ContextOverflowError, request_size
from harness.events import ContextCompaction, GenerationComplete
from harness.model import collect_model_stream
from harness.output import requested_output_tokens
from harness.summary_references import (
    ANCHOR_HEADING,
    reference_state,
    render_reference_index,
    without_mechanical_sections,
)
from harness.types import (
    AssistantMessage,
    ModelRequest,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
    message_from_dict,
    message_to_dict,
)


def wire_messages(messages):
    rows = []
    for message in messages:
        saved = message_to_dict(message)
        if isinstance(message, AssistantMessage):
            row = {"role": "assistant", "content": message.text or ""}
            if message.reasoning:
                row["reasoning_content"] = message.reasoning
            if message.tool_calls:
                row["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": json.dumps(c.arguments, ensure_ascii=False),
                        },
                    }
                    for c in message.tool_calls
                ]
        elif isinstance(message, ToolResultMessage):
            row = {
                "role": "tool",
                "content": message.content,
                "tool_call_id": message.call_id,
                "tool_name": message.name,
            }
        elif isinstance(message, UserMessage):
            content = message.content
            if message.images:
                content = [
                    {"type": "text", "text": content},
                    *[
                        {"type": "image_url", "image_url": {"url": "saved image"}}
                        for _ in message.images
                    ],
                ]
            row = {"role": "user", "content": content}
        else:
            row = {"role": "system", "content": message.content}
        row["_saved"] = saved
        rows.append(row)
    return rows


def restore_rows(rows):
    messages = []
    for row in rows:
        if "_saved" not in row:
            messages.append(AssistantMessage(row.get("content", "")))
            continue
        message = message_from_dict(row["_saved"])
        if isinstance(message, ToolResultMessage):
            content = row.get("content", "")
            if content != message.content:
                content += (
                    f"\nOriginal result: history_read(call_id={message.call_id!r}, view='text')."
                )
            message = replace(message, content=content)
        elif isinstance(message, AssistantMessage) and row.get("content", "") != (
            message.text or ""
        ):
            # A changed body cannot reuse signed provider content. Unchanged protected
            # messages retain their replay blocks, including a pending tool round.
            message = replace(message, text=row.get("content"), reasoning=None, provider_data={})
        messages.append(message)
    return messages


def fingerprint(request):
    def digest(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()

    return [digest(message_to_dict(m)) for m in request.messages], digest(
        [vars(t) for t in request.tools]
    )


def failure_kind(error):
    cause = error
    chain = [cause]
    while getattr(cause, "__cause__", None):
        cause = cause.__cause__
        chain.append(cause)
    status = getattr(cause, "status_code", None) or getattr(
        getattr(cause, "response", None), "status_code", None
    )
    if status in {401, 402, 403}:
        return "access"
    if status in {429, 503, 529}:
        return "overload"
    if any(
        isinstance(item, TimeoutError)
        or type(item).__name__
        in {
            "APITimeoutError",
            "TimeoutException",
            "ReadTimeout",
            "ConnectTimeout",
            "WriteTimeout",
            "PoolTimeout",
        }
        for item in chain
    ):
        return "timeout"
    if isinstance(error, InvalidSummary):
        return "truncated" if str(error) == "length" else "empty"
    return "network"


class InvalidSummary(ValueError):
    pass


class LeanModel:
    def __init__(self, model, window, config, memory, history, summary_budget):
        self.model, self.window, self.config = model, window, config
        self.memory, self.history, self.summary_budget = memory, history, summary_budget
        route = f"{getattr(model, 'provider', '')}/{getattr(model, 'model_id', '')}"
        if memory.state.get("route") != route:
            references = memory.state.get("references")
            memory.state.clear()
            if isinstance(references, dict):
                memory.state["references"] = references
            memory.state["route"] = route
        self.state = memory.state

    def __getattr__(self, name):
        return getattr(self.model, name)

    async def estimate_tokens(self, request):
        local = request_size(request)
        anchor = self.state.get("usage_anchor")
        if anchor:
            hashes, schemas = fingerprint(request)
            if (
                schemas == anchor["schemas"]
                and hashes[: len(anchor["messages"])] == anchor["messages"]
            ):
                return anchor["tokens"] + max(0, local - anchor["estimate"])
        return local

    @asynccontextmanager
    async def summary_client(self):
        factory = self.config.summary_model
        if factory:
            async with factory() as model:
                yield model
        else:
            yield self.model

    async def checkpoint(self):
        if self.config.on_commit:
            await self.config.on_commit(self.memory, self.history)
        if self.config.checkpoint:
            await self.config.checkpoint()

    async def publish(self, rows, summary=None, references=None, compaction=None):
        previous = deepcopy(self.memory.to_dict())
        try:
            self.commit(rows, summary)
            if references is not None:
                self.state["references"] = references
            if compaction is not None:
                self.state["ineffective"] = 0
                self.state.pop("ineffective_probe_at", None)
                self.state["last_compaction"] = compaction
            await self.checkpoint()
        except BaseException:
            restored = ContextMemory.from_dict(previous)
            self.memory.__dict__.update(restored.__dict__)
            self.state = self.memory.state
            raise

    def commit(self, rows, summary=None):
        # Rebuilt instruction hooks stay out of storage. System messages in the original
        # journal remain authoritative across later turns and process restarts.
        persistent_system = [m for m in self.history if isinstance(m, SystemMessage)]
        self.memory.working_messages = [
            message_to_dict(m)
            for m in [
                *persistent_system,
                *[m for m in restore_rows(rows) if not isinstance(m, SystemMessage)],
            ]
        ]
        self.memory.covered_messages = len(self.history)
        self.memory.pinned_messages = []
        if summary is not None:
            self.memory.summary = summary
            self.state["compression_count"] = self.state.get("compression_count", 0) + 1
        self.state.pop("usage_anchor", None)

    async def prepare(self, request, *, force=False):
        """Publish and send only a complete request that fits, with progress-based reductions."""
        before = await self.estimate_tokens(request)
        window = min(self.window, self.state.get("learned_window", self.window))
        output = requested_output_tokens(request)
        threshold = ContextCompressor(window, output, self.config.trigger_ratio).threshold_tokens
        if not force and before < threshold and before + output <= window:
            yield request
            return
        compaction_id = uuid4().hex
        yield ContextCompaction("started", before_tokens=before, compaction_id=compaction_id)
        active_memory, active_state, active_config = self.memory, self.state, self.config
        candidate_memory = ContextMemory.from_dict(deepcopy(active_memory.to_dict()))
        self.memory, self.state = candidate_memory, candidate_memory.state
        self.config = replace(active_config, on_commit=None, checkpoint=None)
        selected = request
        try:
            async for event in self._compress_once(request, force=force):
                if isinstance(event, ModelRequest):
                    selected = event
                elif event.status != "started":
                    yield replace(event, status="progress", compaction_id=compaction_id)
            target = window - output
            if force:
                target = min(target, max(0, int(request_size(request) * 0.80)))
            while await self.estimate_tokens(selected) > target:
                reduced = cut_request(selected, self.history)
                if reduced is None:
                    if await self.estimate_tokens(selected) + output <= window and smaller_request(
                        selected, request
                    ):
                        break  # The retry goal is soft. Any smaller fitting request can proceed.
                    raise ContextOverflowError(
                        "The required instructions, current task, pending calls, and tool schemas "
                        "cannot fit with the requested output. No safe context reduction remains."
                    )
                selected, reason = reduced
                yield ContextCompaction(
                    "progress",
                    before_tokens=before,
                    after_tokens=request_size(selected),
                    reason=reason,
                    compaction_id=compaction_id,
                )
            # A forced retry must change the rejected request, even when its estimate fits.
            if force and not smaller_request(selected, request):
                raise ContextOverflowError("No smaller safe request remains for context recovery.")
            self.commit(wire_messages(selected.messages))
            summaries = [
                m.text
                for m in selected.messages
                if isinstance(m, AssistantMessage)
                and ContextCompressor._is_context_summary_message(
                    {"role": "assistant", "content": m.text or ""}
                )
            ]
            if summaries:
                candidate_memory.summary = summaries[-1]
            candidate_memory.state["references"] = reference_state(
                self.history,
                active_config.summary_context() if active_config.summary_context else {},
                candidate_memory.state.get("references", {}).get("record_ids", []),
            )
            self.memory, self.state, self.config = active_memory, active_state, active_config
            previous = deepcopy(active_memory.to_dict())
            try:
                active_memory.__dict__.update(candidate_memory.__dict__)
                self.state = active_memory.state
                await self.checkpoint()
            except BaseException:
                active_memory.__dict__.update(ContextMemory.from_dict(previous).__dict__)
                self.state = active_memory.state
                raise
            yield ContextCompaction(
                "completed",
                before_tokens=before,
                after_tokens=request_size(selected),
                reason="request_fitted",
                compaction_id=compaction_id,
            )
            yield selected
        except Exception as error:
            yield ContextCompaction(
                "failed",
                before_tokens=before,
                reason="no_safe_fit"
                if isinstance(error, ContextOverflowError)
                else "preparation_failed",
                compaction_id=compaction_id,
            )
            raise
        finally:
            self.memory, self.config = active_memory, active_config
            self.state = active_memory.state

    async def _compress_once(self, request, *, force=False):
        before = await self.estimate_tokens(request)
        window = min(self.window, self.state.get("learned_window", self.window))
        output = requested_output_tokens(request)
        policy = ContextCompressor(
            window,
            output,
            self.config.trigger_ratio,
            self.memory.summary,
            self.state.get("compression_count", 0),
        )
        policy._session_id = "current"
        policy.tail_mode = self.config.tail_mode
        policy.min_tail_user_messages = self.config.min_tail_user_messages
        if policy.tail_mode == "current":
            policy.tail_token_budget = max(
                1, min(int(window * 0.20), int(policy.threshold_tokens * self.config.target_ratio))
            )
        if not force and before < policy.threshold_tokens and before + output <= window:
            yield request
            return
        rows = wire_messages(request.messages)
        pruned, changed = policy._prune_old_tool_results(
            rows, policy.protect_last_n, policy.tail_token_budget
        )
        projected = ModelRequest(restore_rows(pruned), request.tools, request.options)
        if changed and request_size(projected) < before:
            await self.publish(pruned)
            yield ContextCompaction(
                "completed",
                before_tokens=before,
                after_tokens=request_size(projected),
                reason="tool_output_pruning",
            )
        current = request_size(projected) if changed else before
        if not force and current < policy.threshold_tokens and current + output <= window:
            yield projected if changed else request
            return
        start, end = policy._compress_window(pruned)
        active_users = [
            i for i in _protected(request.messages) if isinstance(request.messages[i], UserMessage)
        ]
        if active_users:
            end = min(end, min(active_users))
        # The upstream structural guard protects a small conversation instead of deleting its head.
        if len(pruned) <= policy._protect_head_size(pruned) + 4 or start >= end:
            yield projected if changed else request
            return
        if not force and self.state.get("cooldown_until", 0) > time.time():
            yield projected if changed else request
            return
        if not force and self.state.get("ineffective", 0) >= 2:
            now = time.time()
            deadline = self.state.setdefault("ineffective_probe_at", now + 300)
            if deadline > now:
                yield projected if changed else request
                return
            self.state["ineffective"] = 1
            self.state.pop("ineffective_probe_at", None)
        yield ContextCompaction("started", before_tokens=current)
        middle = [r for r in pruned[start:end] if not policy._is_context_summary_message(r)]
        if not middle:
            yield projected
            return
        pruned = policy._demote_stale_tail_tools(pruned, end)
        records = policy._serialize_records_for_summary(middle)
        content, coverage = policy._sample_summary_records(records)
        protected = self.config.summary_context() if self.config.summary_context else {}
        target = policy._compute_summary_budget(middle)
        retained = ModelRequest(
            restore_rows([*pruned[:start], *pruned[end:]]), request.tools, request.options
        )
        summary_room = max(128, window - output - request_size(retained) - 256)

        def build_prompt(sample):
            value = policy._build_summary_prompt(
                sample,
                target,
                None,
                json.dumps(protected) if protected else "",
                any(r["role"] == "user" for r in rows),
            )
            log = 4000 if self.config.tail_mode == "lean" else 0
            total = min(target + log, summary_room)
            value = value.replace(f"Target ~{target + log} tokens", f"Target ~{total} tokens")
            return value.replace(
                "Spend up to ~4000 tokens here", f"Spend up to ~{min(log, total // 2)} tokens here"
            )

        prompt = build_prompt(content)
        # Use the auxiliary model's own capacity. Sampling never starts a chain of summary calls.
        summary_window = self.config.summary_window or window
        options = {
            k: v
            for k, v in self.config.options.items()
            if k
            not in {
                "max_tokens",
                "max_output_tokens",
                "max_completion_tokens",
                "tool_choice",
                "parallel_tool_calls",
            }
        }
        summary_request = ModelRequest([SystemMessage(prompt)], options=options)
        allowance = summary_window - min(summary_window // 4, max(8192, target + 4000))
        while request_size(summary_request) > allowance and len(content) > 256:
            cap = max(256, int(len(content) * 0.75))
            sample_policy = type(
                "AuxiliarySample", (ContextCompressor,), {"_SUMMARY_INPUT_MAX_CHARS": cap}
            )
            content, coverage = sample_policy._sample_summary_records(records)
            summary_request.messages = [SystemMessage(build_prompt(content))]
        summary = None
        reason = "llm_summary"
        usage = {}
        calls = 0
        revision = len(self.history)
        try:
            if request_size(summary_request) > allowance:
                raise InvalidSummary("summary fixed content exceeds auxiliary window")
            if not self.summary_budget.spend():
                raise InvalidSummary("summary call budget exhausted")
            calls = 1

            async def summarize(client):
                async with asyncio.timeout(self.config.summary_timeout):
                    result = await collect_model_stream(client.stream(summary_request))
                text = (result.text or "").strip()
                if result.stop_reason in {"length", "max_tokens", "cut_off"}:
                    raise InvalidSummary("length")
                if not text or result.tool_calls or _is_summary_refusal(text):
                    raise InvalidSummary("empty")
                if self.config.validate_summary and not self.config.validate_summary(
                    text, protected
                ):
                    raise InvalidSummary("invalid protected context")
                return result, text

            async with self.summary_client() as auxiliary:
                try:
                    result, text = await summarize(auxiliary)
                except Exception:
                    auxiliary_route = getattr(auxiliary, "model_id", None)
                    main_route = getattr(self.model, "model_id", None)
                    if not auxiliary_route or auxiliary_route == main_route:
                        raise
                    if request_size(summary_request) > window - min(
                        window // 4, max(8192, target + 4000)
                    ):
                        raise
                    if not self.summary_budget.spend():
                        raise
                    calls += 1
                    result, text = await summarize(self.model)
            usage = result.usage
            summary = policy._with_summary_prefix(without_mechanical_sections(text))
            self.state.pop("cooldown_until", None)
            self.state["failures"] = {}
        except Exception as error:
            kind = failure_kind(error)
            failures = self.state.setdefault("failures", {})
            failures[kind] = failures.get(kind, 0) + 1
            delay = (
                (60, 300, 900)[min(failures[kind], 3) - 1]
                if kind in {"timeout", "truncated"}
                else 30
                if kind == "empty"
                else 60
            )
            self.state["cooldown_until"] = time.time() + max(
                delay, self.config.summary_timeout if kind == "timeout" else 0
            )
            # Preserve the transcript on access/network/empty failures. A repeated stall or sustained
            # overload takes the upstream deterministic rung, rather than looping forever.
            degrade = (
                kind == "timeout"
                and failures[kind] >= 2
                or kind == "overload"
                and failures[kind] >= 3
            )
            if degrade:
                summary = policy._build_static_fallback_summary(middle, kind)
                reason = "deterministic_fallback"
            else:
                reason = "summary_" + kind
        yield ContextCompaction(
            "progress", before_tokens=current, model_calls=calls, usage=usage, reason=reason
        )
        if len(self.history) != revision:
            raise RuntimeError("Conversation changed during compaction.")
        if summary:
            references = reference_state(
                self.history,
                protected,
                self.state.get("references", {}).get("record_ids", []),
            )
            summary = without_mechanical_sections(summary)
            reference_index = render_reference_index(
                references,
                min(7000, max(0, (window - output) // 5)),
                _redact_compaction_text,
            )
            # Keep the policy from replacing an empty bounded index with its larger index.
            summary += "\n\n" + (reference_index or ANCHOR_HEADING)
            summary = policy._augment_summary_lean(summary, wire_messages(self.history))
            # Protected head decays after the first compression; the system prefix is rebuilt each call.
            head = [r for r in pruned[:start] if not policy._is_context_summary_message(r)]
            tail = pruned[end:]
            latest = next(
                (i for i in range(len(rows) - 1, -1, -1) if policy._is_real_user_turn(rows[i])), -1
            )
            if 0 <= latest < end:
                # Restore the active request verbatim after the handoff when a long live turn is split.
                tail = [rows[latest], *tail]
            working = [*head, {"role": "assistant", "content": summary}, *tail]
            candidate = ModelRequest(restore_rows(working), request.tools, request.options)
            if request_size(candidate) < current:
                committed = {
                    "before": current,
                    "after": request_size(candidate),
                    "method": reason,
                    **coverage,
                }
                await self.publish(working, summary, references, committed)
                yield ContextCompaction(
                    "completed",
                    before_tokens=current,
                    after_tokens=request_size(candidate),
                    reason=reason,
                )
                yield candidate
                return
            self.state["ineffective"] = self.state.get("ineffective", 0) + 1
        await self.checkpoint()
        yield ContextCompaction("failed", before_tokens=current, reason=reason)
        yield projected

    async def stream(self, request):
        current = request
        while True:
            try:
                async with aclosing(self.model.stream(current)) as events:
                    async for event in events:
                        if isinstance(event, GenerationComplete):
                            tokens = event.message.usage.get("input_tokens")
                            if tokens:
                                hashes, schemas = fingerprint(current)
                                self.state["usage_anchor"] = {
                                    "messages": hashes,
                                    "schemas": schemas,
                                    "tokens": tokens,
                                    "estimate": request_size(current),
                                }
                        yield event
                return
            except ContextOverflowError as error:
                self.state.pop("usage_anchor", None)
                cause = error
                while cause.__cause__ is not None:
                    cause = cause.__cause__
                reported = parse_context_limit_from_error(str(cause))
                if reported is not None and reported < min(
                    self.window, self.state.get("learned_window", self.window)
                ):
                    self.state["learned_window"] = reported
                next_request = None
                async for event in self.prepare(current, force=True):
                    if isinstance(event, ModelRequest):
                        next_request = event
                    else:
                        yield event
                if next_request is None or not smaller_request(next_request, current):
                    raise
                current = next_request
