"""Adapters from common agent streams to renderer events.

No supported agent framework is imported here.  Adapters use public stream
shapes and light duck typing, which keeps every integration optional.
"""

from __future__ import annotations

import json
from dataclasses import replace
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from renderer.events import (
    ApprovalRequested,
    ModelFinished,
    ModelStarted,
    Notice,
    QuestionRequested,
    ReasoningDelta,
    RenderEvent,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallDelta,
    ToolFinished,
    ToolProgress,
    ToolStarted,
    is_render_event,
)

type Adapted = RenderEvent | Iterable[RenderEvent] | None
type Adapter = Callable[[Any], Adapted]


class EventAdapter(Protocol):
    """The complete interface needed to support another agent framework."""

    def __call__(self, event: Any) -> Adapted: ...


def events(value: Adapted) -> tuple[RenderEvent, ...]:
    """Turn one adapter return value into a predictable tuple."""
    if value is None:
        return ()
    if is_render_event(value):
        return (value,)
    normalized = tuple(value)
    invalid = next((event for event in normalized if not is_render_event(event)), None)
    if invalid is not None:
        raise TypeError(
            "adapter returned an unsupported value: "
            f"{type(invalid).__name__}; return renderer event objects"
        )
    return normalized


class HarnessAdapter:
    """Normalize events from this repository's harness."""

    def __call__(self, event: Any) -> Adapted:
        adapted = self._adapt(event)
        if adapted is None:
            return None
        parent = getattr(event, "parent_call_id", None)
        if is_render_event(adapted):
            return replace(adapted, parent_call_id=parent)
        return tuple(replace(item, parent_call_id=parent) for item in events(adapted))

    def _adapt(self, event: Any) -> Adapted:
        # Import on first use so the renderer can run without the harness package.
        import harness

        if isinstance(event, harness.ContextCompaction):
            if event.status == 'started':
                return ModelStarted(label='Summarizing earlier conversation')
            if event.status == 'progress':
                # The active compaction indicator already shows progress.
                return None
            if event.status == 'completed':
                size = (f" ({event.before_tokens:,} → {event.after_tokens:,} tokens)"
                        if event.after_tokens is not None else "")
                notice = Notice(f"Earlier conversation summarized{size}.")
            else:
                reason = f" ({event.reason.replace('_', ' ')})" if event.reason else ""
                notice = Notice(f"Could not summarize earlier conversation{reason}.", level='warning')
            return (ModelFinished(usage=event.usage), notice)
        if isinstance(event, harness.ModelCalled):
            return ModelStarted(
                message_count=len(event.request.messages),
                tool_count=len(event.request.tools),
            )
        if isinstance(event, harness.TextDelta):
            return TextDelta(event.text)
        if isinstance(event, harness.ReasoningDelta):
            return ReasoningDelta(event.text)
        if isinstance(event, harness.ToolCallDelta):
            return ToolCallDelta(event.index, event.text, event.name)
        if isinstance(event, harness.ModelResponded):
            message = event.message
            return ModelFinished(
                text=message.text,
                reasoning=message.reasoning,
                stop_reason=message.stop_reason,
                usage=message.usage,
                requested_tools=tuple(call.name for call in message.tool_calls),
            )
        if isinstance(event, harness.ToolStarted):
            return ToolStarted(event.call.id, event.call.name, event.call.arguments)
        if isinstance(event, harness.ToolFinished):
            result = event.result
            if isinstance(result, harness.PendingApproval):
                return ApprovalRequested(
                    result.call.id,
                    result.call.name,
                    result.call.arguments,
                    result.reason,
                )
            return ToolFinished(
                result.call_id,
                result.name,
                result.content,
                result.status,
            )
        if isinstance(event, harness.TurnFinished):
            return RunFinished(
                event.result.status,
                result=event.result,
                pending_count=len(event.result.pending),
            )
        return None


class LangGraphAdapter:
    """Normalize LangGraph ``astream`` and ``astream_events`` output."""

    def __call__(self, event: Any) -> Adapted:
        # ``stream_mode="messages"`` yields ``(message_chunk, metadata)``.
        if isinstance(event, tuple) and len(event) == 2:
            mode, chunk = event
            if mode == "messages":
                return self._message_chunk(chunk)
            if isinstance(mode, str) and mode in {"tools", "custom", "updates"}:
                return self._dictionary(chunk)
            if isinstance(chunk, dict):
                normalized = self._message_chunk(mode)
                return normalized or Notice(f"Graph update: {_stringify(chunk)}", "debug")

        if isinstance(event, dict):
            return self._dictionary(event)
        return self._message_chunk(event)

    def _dictionary(self, event: dict[str, Any]) -> Adapted:
        kind = str(event.get("event") or event.get("type") or "")
        data = event.get("data") or {}
        payload = data if isinstance(data, dict) else {}
        name = str(event.get("name") or payload.get("name") or "tool")
        call_id = str(
            event.get("run_id") or event.get("toolCallId") or payload.get("toolCallId") or name
        )

        # Portable JSON form of the renderer protocol. This is convenient for
        # SSE/WebSocket clients and frameworks that already emit dictionaries.
        if kind == "run_started":
            return RunStarted(
                str(payload.get("title", event.get("title", "Agent"))),
                payload.get("prompt", event.get("prompt")),
            )
        if kind == "model_started":
            return ModelStarted(
                label=str(payload.get("label", "Thinking")),
                model=payload.get("model"),
            )
        if kind in {"text_delta", "token", "message_delta"}:
            return TextDelta(str(payload.get("text", event.get("text", event.get("token", "")))))
        if kind == "model_finished":
            return ModelFinished(
                text=payload.get("text"),
                reasoning=payload.get("reasoning"),
                stop_reason=payload.get("stop_reason"),
                usage=_usage(payload.get("usage")),
                requested_tools=tuple(payload.get("requested_tools", ())),
            )
        if kind == "tool_started":
            return ToolStarted(
                call_id,
                name,
                _mapping(payload.get("arguments", event.get("arguments", {}))),
            )
        if kind == "tool_progress":
            return ToolProgress(
                call_id,
                str(payload.get("message", "")),
                payload.get("progress"),
            )
        if kind == "tool_finished":
            return ToolFinished(
                call_id,
                name,
                _stringify(payload.get("output", event.get("output", ""))),
                payload.get("status", "completed"),
            )
        if kind == "approval_requested":
            return ApprovalRequested(
                call_id,
                name,
                _mapping(payload.get("arguments", {})),
                str(payload.get("reason", "")),
            )
        if kind in {"question_requested", "input_requested"}:
            choices = payload.get("choices", event.get("choices", ()))
            return QuestionRequested(
                str(
                    payload.get("request_id")
                    or event.get("request_id")
                    or event.get("run_id")
                    or "question"
                ),
                str(payload.get("question", event.get("question", ""))),
                tuple(str(choice) for choice in choices or ()),
                bool(payload.get("allow_free_text", True)),
            )
        if kind == "notice":
            return Notice(
                str(payload.get("message", "")),
                payload.get("level", "info"),
            )
        if kind == "run_finished":
            return RunFinished(
                str(payload.get("status", "completed")),
                payload.get("result"),
                int(payload.get("pending_count", 0)),
            )

        if kind in {"on_chat_model_start", "on_llm_start"}:
            return ModelStarted(model=name)
        if kind in {"on_chat_model_stream", "on_llm_stream"}:
            return self._message_chunk(payload.get("chunk"))
        if kind in {"on_chat_model_end", "on_llm_end"}:
            output = payload.get("output")
            return ModelFinished(
                text=_content(output),
                usage=_usage(output),
            )
        if kind == "on_tool_start":
            arguments = payload.get("input", event.get("input", {}))
            return ToolStarted(call_id, name, _mapping(arguments))
        if kind == "on_tool_event":
            return ToolProgress(call_id, _stringify(payload.get("data", data)))
        if kind == "on_tool_end":
            return ToolFinished(call_id, name, _stringify(payload.get("output", "")))
        if kind == "on_tool_error":
            return ToolFinished(
                call_id,
                name,
                _stringify(payload.get("error", "Tool failed")),
                "failed",
            )
        if kind in {"interrupt", "on_interrupt"}:
            question = payload.get("question") or event.get("question")
            if question:
                return QuestionRequested(
                    call_id,
                    str(question),
                    tuple(str(choice) for choice in payload.get("choices", ())),
                    bool(payload.get("allow_free_text", True)),
                )
            return ApprovalRequested(call_id, name, reason=_stringify(data))
        if kind:
            return Notice(f"{kind}: {_stringify(data)}", "debug")

        # A message-mode chunk may arrive without an event envelope.
        message = event.get("message") or event.get("chunk")
        if message is not None:
            return self._message_chunk(message)
        return Notice(f"Graph update: {_stringify(event)}", "debug")

    @staticmethod
    def _message_chunk(chunk: Any) -> Adapted:
        text = _content(chunk)
        return TextDelta(text) if text else None


class SmolAgentsAdapter:
    """Normalize the generator returned by ``agent.run(..., stream=True)``."""

    def __init__(self) -> None:
        self._model_active = False
        self._final_answer: Any = None

    def __call__(self, event: Any) -> Adapted:
        kind = type(event).__name__
        if kind == "ChatMessageStreamDelta":
            prefix: list[RenderEvent] = []
            if not self._model_active:
                prefix.append(ModelStarted())
                self._model_active = True
            content = _content(event)
            if content:
                prefix.append(TextDelta(content))
            return prefix
        if kind in {"ToolCall", "ChatMessageToolCall"}:
            function = getattr(event, "function", event)
            name = str(getattr(function, "name", "tool"))
            arguments = getattr(function, "arguments", {})
            call_id = str(getattr(event, "id", name))
            return ToolStarted(call_id, name, _mapping(arguments))
        if kind == "ToolOutput":
            call = getattr(event, "tool_call", None)
            name = str(getattr(call, "name", "tool"))
            call_id = str(getattr(event, "id", getattr(call, "id", name)))
            return ToolFinished(call_id, name, _stringify(getattr(event, "output", event)))
        if kind == "PlanningStep":
            plan = getattr(event, "plan", None) or getattr(event, "model_output", None)
            return Notice(f"Plan: {_stringify(plan)}", "info") if plan else None
        if kind == "ActionStep":
            was_streaming = self._model_active
            self._model_active = False
            output: list[RenderEvent] = []
            error = getattr(event, "error", None)
            if error:
                output.append(Notice(_stringify(error), "error"))
            observation = getattr(event, "observations", None)
            if observation:
                output.append(Notice(_stringify(observation), "info"))
            usage = _usage(getattr(event, "token_usage", None))
            model_output = getattr(event, "model_output", None)
            if model_output and not was_streaming:
                output.extend(
                    [
                        ModelStarted(),
                        ModelFinished(reasoning=_stringify(model_output), usage=usage),
                    ]
                )
            else:
                output.append(ModelFinished(usage=usage))
            return output
        if kind == "FinalAnswerStep":
            answer = getattr(event, "output", None)
            if answer is None:
                answer = self._final_answer if self._final_answer is not None else event
            text = _stringify(answer)
            return [ModelFinished(text=text), RunFinished("completed", answer)]
        if kind == "ActionOutput" and getattr(event, "is_final_answer", False):
            self._final_answer = getattr(event, "output", event)
            return None
        return Notice(f"{kind}: {_stringify(event)}", "debug")


class AutoAdapter:
    """Choose a built-in adapter from the first event and then reuse it."""

    def __init__(self) -> None:
        self._selected: EventAdapter | None = None

    def __call__(self, event: Any) -> Adapted:
        if is_render_event(event):
            return event
        if self._selected is None:
            module = type(event).__module__
            if module == "harness" or module.startswith("harness."):
                self._selected = HarnessAdapter()
            elif module.startswith(("langchain", "langgraph")) or isinstance(event, (dict, tuple)):
                self._selected = LangGraphAdapter()
            elif module.startswith("smolagents"):
                self._selected = SmolAgentsAdapter()
            elif isinstance(event, str):
                self._selected = lambda value: TextDelta(str(value))
            else:
                self._selected = GenericAdapter()
        return self._selected(event)


class GenericAdapter:
    """Useful fallback for simple chunk objects and arbitrary streams."""

    def __call__(self, event: Any) -> Adapted:
        if is_render_event(event):
            return event
        if isinstance(event, str):
            return TextDelta(event)
        text = _content(event)
        if text:
            return TextDelta(text)
        return Notice(_stringify(event), "info")


def _content(value: Any) -> str:
    if value is None:
        return ""
    content = getattr(value, "content", None)
    if content is None and isinstance(value, dict):
        content = value.get("content") or value.get("text")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") in {"text", "output_text"}:
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return str(content)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {"input": value}
        except json.JSONDecodeError:
            return {"input": value}
    return {"input": value}


def _usage(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    usage = getattr(value, "usage_metadata", None) or getattr(
        value, "token_usage", None
    )
    if usage is None and isinstance(value, dict):
        usage = (
            value.get("usage_metadata")
            or value.get("token_usage")
            or value.get("usage")
        )
    if usage is None:
        usage = value
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    if not isinstance(usage, dict):
        usage = vars(usage) if hasattr(usage, "__dict__") else {}
    aliases = {
        "prompt_tokens": "input_tokens",
        "completion_tokens": "output_tokens",
        "cached_tokens": "cache_read_tokens",
        "cache_read_input_tokens": "cache_read_tokens",
        "cached_content_token_count": "cache_read_tokens",
        "cache_creation_input_tokens": "cache_write_tokens",
    }
    counts = {
        aliases.get(str(key), str(key)): int(number)
        for key, number in usage.items()
        if isinstance(number, int) and not isinstance(number, bool)
    }

    detail_aliases = {
        "cached_tokens": "cache_read_tokens",
        "cache_read": "cache_read_tokens",
        "cache_read_input_tokens": "cache_read_tokens",
        "cache_creation": "cache_write_tokens",
        "cache_write": "cache_write_tokens",
        "cache_creation_input_tokens": "cache_write_tokens",
    }
    for details_key in (
        "input_token_details",
        "input_tokens_details",
        "prompt_tokens_details",
    ):
        details = usage.get(details_key)
        if hasattr(details, "model_dump"):
            details = details.model_dump()
        elif details is not None and not isinstance(details, dict):
            details = vars(details) if hasattr(details, "__dict__") else {}
        if not isinstance(details, dict):
            continue
        for key, number in details.items():
            canonical = detail_aliases.get(str(key))
            if (
                canonical is not None
                and isinstance(number, int)
                and not isinstance(number, bool)
            ):
                counts.setdefault(canonical, int(number))

    return counts


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "to_string"):
        return str(value.to_string())
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)
