"""Return useful partial answers without repeating tools or changing instructions."""

import asyncio
import json
import logging
import time
from dataclasses import replace

from harness import (
    AssistantMessage,
    ContextLimitError,
    HarnessError,
    HarnessErrorCode,
    ModelCalled,
    ModelRequest,
    ModelResponded,
    SystemMessage,
    TextDelta,
    ToolResultMessage,
    UserMessage,
    collect_model_stream,
    message_from_dict,
    message_to_dict,
    unanswered_calls,
    validate_assistant_message,
)
from theos.storage.messages import stamp_message

from .events import publish_event
from .models import session_options
from .text import reply_text

logger = logging.getLogger("theos")
FINAL_SECONDS = 15
REASONS = {
    "budget_limit": "The research reached its model-call limit.",
    "timeout": "The research reached its time limit.",
    "context_limit": "The collected material exceeded the available model context.",
    "output_limit": "The answer reached its output limit.",
    "provider_error": "The model or an integration could not complete the request.",
    "delegate_partial": "Some delegated research could not finish.",
}


def failure_reason(error):
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ContextLimitError) or (
        isinstance(error, HarnessError) and error.code == HarnessErrorCode.CONTEXT_LIMIT_EXCEEDED
    ):
        return "context_limit"
    return "provider_error"


def clip(text, size):
    """Bound model-visible copies. Keep the original durable results unchanged."""
    if len(text) <= size:
        return text
    marker = "\n[Result shortened.]"
    return text[: max(0, size - len(marker))] + marker[:size]


def bound_tool_results(request, total_chars):
    """Bound tool data sent to a model while preserving complete durable results."""
    count = sum(isinstance(m, ToolResultMessage) for m in request.messages)
    allowance = min(8000, max(1, total_chars // max(1, count)))
    request.messages = [
        replace(m, content=clip(m.content, allowance)) if isinstance(m, ToolResultMessage) else m
        for m in request.messages
    ]


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
                "unknown" if row else "failed",
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


def bounded_history(history, offset, size=6000):
    """Keep a question and complete tool exchanges in a small recovery request."""
    question = next((m for m in reversed(history) if isinstance(m, UserMessage)), None)
    selected = [UserMessage(clip(question.content, size // 3))] if question else []
    results = {m.call_id: m for m in history[offset:] if isinstance(m, ToolResultMessage)}
    # Prefer recent exchanges. Never separate a tool result from its call.
    exchanges = []
    remaining = size * 2 // 3
    for message in reversed(history[offset:]):
        if not isinstance(message, AssistantMessage):
            continue
        if message.tool_calls:
            calls = [c for c in message.tool_calls if c.id in results]
            if not calls or remaining <= 0:
                continue
            allowance = max(1, remaining // len(calls))
            batch = [AssistantMessage(tool_calls=[replace(c, arguments={}) for c in calls])]
            for call in calls:
                result = results[call.id]
                content = clip(result.content, allowance)
                batch.append(replace(result, content=content))
                remaining -= len(content)
            exchanges.append(batch)
        elif message.text and remaining > 0:
            text = clip(message.text, remaining)
            exchanges.append([AssistantMessage(text)])
            remaining -= len(text)
    for exchange in reversed(exchanges):
        selected.extend(exchange)
    return selected


def findings(history, offset):
    """Share fallback space across delegates and recent results without inventing facts."""
    delegate_sections = []
    sections = []
    for message in history[offset:]:
        if isinstance(message, AssistantMessage) and message.text and not message.tool_calls:
            sections.append(clip(message.text, 4000))
        elif isinstance(message, ToolResultMessage):
            if message.name == "delegate_tasks":
                try:
                    delegates = json.loads(message.content)
                    for delegate in delegates:
                        if not delegate.get("answer"):
                            continue
                        delegate_sections.append(
                            clip(
                                f"{delegate['name']} ({delegate['status']}):\n{delegate['answer']}",
                                4000,
                            )
                        )
                    continue
                except (ValueError, TypeError, KeyError):
                    pass
            sections.append(clip(f"{message.name} ({message.status}):\n{message.content}", 4000))
    selected = [*delegate_sections[-3:], *sections[-9:]]
    if not selected:
        return ""
    allowance = 8000 // len(selected)
    return "\n\n".join(clip(section, allowance) for section in selected)


async def finish(
    runtime, turn, session, history, memory, offset, budget, instructions, reason, deadline
):
    """Try bounded answers with no tools, then use a deterministic partial answer."""
    settle_calls(runtime, turn, history)
    answer = (
        history[-1]
        if reason == "delegate_partial" and isinstance(history[-1], AssistantMessage)
        else None
    )
    mode = "existing_answer" if answer else "saved_findings"
    duration_ms = None
    with runtime.tracing.span("finalize answer", {"theos.recovery.reason": reason}) as span:
        final_deadline = min(deadline, time.monotonic() + FINAL_SECONDS)
        while (
            answer is None
            and reason != "provider_error"
            and instructions
            and time.monotonic() < final_deadline
            and budget.used < budget.max_model_calls
        ):
            used_before = budget.used
            try:
                async with asyncio.timeout(max(0, final_deadline - time.monotonic())):
                    async with runtime.models(
                        runtime.settings, session["model"], session["reasoning"]
                    ) as model:
                        options = session_options(runtime.settings, session)
                        options["max_tokens"] = min(
                            options.get("max_tokens", options.get("max_completion_tokens", 2048)),
                            max(256, runtime.settings.context_tokens // 4),
                        )
                        options.pop("max_completion_tokens", None)
                        # Sizing does not consume a model call or modify saved history.
                        for size in (6000, 3000, 1000):
                            request = ModelRequest(
                                [
                                    SystemMessage(instructions),
                                    *bounded_history(history, offset, size),
                                ],
                                options=options,
                            )
                            if (
                                await model.estimate_tokens(request) + options["max_tokens"]
                                <= runtime.settings.context_tokens
                            ):
                                break
                        else:
                            raise ContextLimitError("The recovery request does not fit.")
                        if budget.spend():
                            publish_event(runtime, turn, ModelCalled(request), "partial")
                            started = time.monotonic()
                            answer = await collect_model_stream(model.stream(request))
                            duration_ms = (time.monotonic() - started) * 1000
                            runtime.record_usage(session, answer.usage)
                            validate_assistant_message(answer)
                            if answer.tool_calls or not answer.text:
                                answer = None
                            else:
                                mode = "model"
            except Exception as error:
                logger.warning(
                    "final_answer_unavailable", extra={"error_type": type(error).__name__}
                )
                answer = None
                if budget.used == used_before:
                    break
        text = answer.text if answer else findings(history, offset)
        caveat = (
            "Some action outcomes are unknown. Check the external service before repeating them."
            if any(
                isinstance(m, ToolResultMessage) and m.status == "unknown" for m in history[offset:]
            )
            else "Some details remain incomplete or unverified."
        )
        status = "partial" if text else "failed"
        if status == "failed":
            mode = "failure"
        reply = (
            f"Partial answer: {REASONS[reason]}\n\n{text}\n\n{caveat}"
            if text
            else f"Request failed: {REASONS[reason]} No answer was generated. Please try again."
        )
        message = stamp_message(
            AssistantMessage(
                reply_text(reply),
                usage=answer.usage if answer else {},
                stop_reason=answer.stop_reason if answer else None,
            ),
            duration_ms=duration_ms,
        )
        history.append(message)
        runtime.db.save_history(turn.owner, turn.session_id, history, memory.to_dict(), status)
        publish_event(runtime, turn, TextDelta(message.text), status)
        publish_event(runtime, turn, ModelResponded(message), status)
        if span is not None:
            span.set_attribute("theos.recovery.mode", mode)
            span.set_attribute("theos.agent.status", status)
            if status == "failed":
                runtime.tracing.failed(span, "no_answer")
    return status
