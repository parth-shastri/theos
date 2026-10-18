"""Finish bounded research without exposing raw tool results as answers."""

import json
import logging
import time
from contextlib import asynccontextmanager

from harness import (
    AssistantMessage,
    ContextLimitError,
    HarnessError,
    HarnessErrorCode,
    ToolResultMessage,
    message_from_dict,
    message_to_dict,
    unanswered_calls,
)
from theos.prompts import render
from theos.storage.messages import stamp_message

from .errors import CheckedModel, ProviderFailure, failure_message
from .text import reply_text
from .usage import message_model

logger = logging.getLogger("theos")
REASONS = {
    "budget_limit": "The research reached its model-call limit.",
    "timeout": "The research reached its time limit.",
    "context_limit": "The collected material exceeded the available model context.",
    "output_limit": "The answer reached its output limit.",
    "provider_error": "The model or an integration could not complete the request.",
    "delegate_partial": "Some delegated research could not finish.",
}


def failure_reason(error):
    from harness.context_size import ContextOverflowError

    if isinstance(error, ContextOverflowError):
        return "context_limit"
    if isinstance(error, ProviderFailure):
        return "provider_error"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ContextLimitError) or (
        isinstance(error, HarnessError) and error.code == HarnessErrorCode.CONTEXT_LIMIT_EXCEEDED
    ):
        return "context_limit"
    return "provider_error"


def settle_calls(runtime, turn, history):
    """Restore finished checkpoints and record unfinished actions without executing them."""
    calls = unanswered_calls(history)
    # Cancellation can append an unknown group result before the parent regains control.
    for message in history:
        if isinstance(message, AssistantMessage):
            calls.extend(
                c
                for c in message.tool_calls
                if c.id in turn.delegate_results
                and any(
                    isinstance(m, ToolResultMessage) and m.call_id == c.id and m.status == "unknown"
                    for m in history
                )
            )
    for call in calls:
        row = runtime.db.one(
            "SELECT * FROM tool_runs WHERE session=? AND call_id=?", (turn.session_id, call.id)
        )
        if call.id in turn.delegate_results:
            result = ToolResultMessage(
                call.id, call.name, json.dumps(list(turn.delegate_results[call.id].values()))
            )
        elif row and row["result"]:
            result = message_from_dict(json.loads(row["result"]))
        else:
            result = ToolResultMessage(
                call.id,
                call.name,
                "The action outcome is unknown. Check the external service before repeating it."
                if row
                else "The turn stopped before this tool started.",
                "unknown" if row else "not_started",
            )
        previous = next(
            (
                i
                for i, m in enumerate(history)
                if isinstance(m, ToolResultMessage) and m.call_id == call.id
            ),
            None,
        )
        if previous is None:
            history.append(result)
        else:
            history[previous] = result
        runtime.db.execute(
            "INSERT INTO tool_runs VALUES (?,?,?,?,?) ON CONFLICT(session,call_id) DO UPDATE SET "
            "status=excluded.status,result=excluded.result",
            (
                turn.session_id,
                call.id,
                call.name,
                result.status,
                json.dumps(message_to_dict(result)),
            ),
        )
    for message in history:
        if isinstance(message, ToolResultMessage) and message.status == "unknown":
            runtime.db.execute(
                "UPDATE tool_runs SET status='unknown',result=? WHERE session=? AND call_id=?",
                (json.dumps(message_to_dict(message)), turn.session_id, message.call_id),
            )


async def response_call(
    runtime,
    session,
    history,
    memory,
    budget,
    instructions,
    reason,
    *,
    compact_budget=None,
    model=None,
    research_id=None,
    persist_session=True,
):
    """Use one tool-free response call with the same task and complete working context."""
    from harness import Agent, ContextCompaction, Hooks, collect_run_stream

    from . import context

    limits = await context.capacity(runtime, session)
    existing_model = model

    @asynccontextmanager
    async def connection():
        if existing_model is not None:
            yield existing_model
        else:
            async with runtime.models(
                runtime.settings, session["model"], session["reasoning"]
            ) as connected:
                yield connected

    async with connection() as connected:
        model = CheckedModel(connected, runtime.settings.provider)

        async def prepare(request, ctx):
            request.options.update(context.options(runtime, session, limits))
            if research_id:
                runtime.research.attach(request, session["owner"], session["id"], research_id)
            return request

        async def record(message, ctx):
            runtime.record_usage(session, message.usage, model_id=message_model(message))
            return message

        agent = Agent(
            model,
            instructions=render(
                "recovery/final_answer.md", instructions=instructions, reason=REASONS[reason]
            ),
            hooks=Hooks(before_model=prepare, after_model=record),
            context_window=limits.context,
            compaction=context.compaction(
                runtime, session, limits, research_id, persist_session=persist_session
            ),
        )
        # Use a copy so a failed final call cannot replace the durable transcript.
        working = list(history)

        async def final_events():
            from contextlib import aclosing

            async with aclosing(
                agent.run_stream(
                    working, budget=budget, compaction_budget=compact_budget, memory=memory
                )
            ) as stream:
                async for event in stream:
                    if (
                        isinstance(event, ContextCompaction)
                        and event.status == "progress"
                        and event.model_calls
                    ):
                        runtime.record_usage(session, event.usage)
                    yield event

        result = await collect_run_stream(final_events())
        answer = result.message
        if answer is None or answer.tool_calls or not answer.text:
            return None
        return answer


async def finish(
    runtime, turn, session, history, memory, offset, budget, instructions, reason, error=None
):
    """Finish once without a generation deadline or repeated research."""
    settle_calls(runtime, turn, history)
    last = history[-1] if history and isinstance(history[-1], AssistantMessage) else None
    answer = last if reason in {"delegate_partial", "output_limit"} and last and last.text else None
    mode = "existing_answer" if answer else "failure"
    duration_ms = None
    with runtime.tracing.span("finalize answer", {"theos.recovery.reason": reason}) as span:
        if (
            answer is None
            and reason not in {"provider_error", "context_limit"}
            and instructions
            and budget.used < budget.max_model_calls
        ):
            started = time.monotonic()
            try:
                answer = await response_call(
                    runtime,
                    session,
                    history,
                    memory,
                    budget,
                    instructions,
                    reason,
                    compact_budget=turn.budgets.final_compaction,
                    research_id=turn.research_id,
                )
                duration_ms = (time.monotonic() - started) * 1000
                if answer:
                    mode = "model"
            except Exception as failure:
                error = failure
                reason = failure_reason(failure)
                logger.warning(
                    "final_answer_unavailable", extra={"error_type": type(failure).__name__}
                )
        text = answer.text if answer else ""
        caveat = (
            "Some action outcomes are unknown. Check the external service before repeating them."
            if any(
                isinstance(m, ToolResultMessage) and m.status == "unknown" for m in history[offset:]
            )
            else "Some details remain incomplete or unverified."
        )
        if answer and answer.stop_reason in {"length", "max_tokens", "cut_off"}:
            caveat = "The provider stopped generation at its output limit. The returned text is incomplete."
        status = "partial" if text else "failed"
        if status == "failed":
            mode = "failure"
        reply = f"{text}\n\n{REASONS[reason]} {caveat}" if text else failure_message(reason, error)
        message = stamp_message(
            AssistantMessage(
                reply_text(reply),
                usage=answer.usage if answer else {},
                stop_reason=answer.stop_reason if answer else None,
            ),
            duration_ms=duration_ms,
        )
        # Retain drafts for diagnostics but hide replaced answers in conversation views.
        for previous in history[offset:]:
            if isinstance(previous, AssistantMessage) and previous.text and not previous.tool_calls:
                previous._theos_display = {
                    **getattr(previous, "_theos_display", {}),
                    "superseded": True,
                }
        history.append(message)
        runtime.db.save_history(turn.owner, turn.session_id, history, memory.to_dict(), status)
        from theos.storage.messages import display_metadata

        turn.emit(
            {
                "type": "answer_replace",
                "text": message.text,
                "reasoning": message.reasoning,
                "stop_reason": message.stop_reason,
                "usage": message.usage,
                "already_counted": mode == "existing_answer",
                "display": display_metadata(message),
            }
        )
        if span is not None:
            span.set_attribute("theos.recovery.mode", mode)
            span.set_attribute("theos.agent.status", status)
            if status == "failed":
                runtime.tracing.failed(span, "no_answer")
    return status
