"""OpenAI adapter for the Responses and Chat Completions APIs."""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, Any, Literal

from openai.types.chat import ChatCompletion

from harness.debug import log_detail
from harness.events import (
    GenerationComplete,
    ModelEvent,
    ReasoningDelta,
    TextDelta,
    ToolCallDelta,
)
from harness.model import Capabilities, collect_model_stream, default_estimate_tokens
from harness.types import (
    AssistantMessage,
    Message,
    ModelRequest,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI

__all__ = ["OpenAIChatModel", "accumulate_chunks"]

_CHAT_STOP_REASONS = {
    "stop": "stop",
    "tool_calls": "tool_calls",
    "length": "length",
    "content_filter": "refusal",
}


def _decode_arguments(raw: str | None) -> tuple[dict[str, Any], str | None]:
    """Decode tool arguments and preserve invalid JSON for debugging."""
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}, raw or ""
    if not isinstance(parsed, dict):
        return {}, raw or ""
    return parsed, None


def _refuse_images_for_text_model(message: UserMessage, capabilities: Capabilities) -> None:
    if message.images and not capabilities.vision:
        raise ValueError("this model does not support image inputs")


class OpenAIChatModel:
    """Generate chat messages with one OpenAI model."""

    provider = "openai"
    capabilities = Capabilities(
        tools=True,
        parallel_tool_calls=True,
        forced_tool_choice=True,
        json_schema_output=True,
        vision=True,
    )

    def __init__(
        self,
        client: AsyncOpenAI,
        model_id: str,
        *,
        api: Literal["responses", "chat_completions"] = "responses",
        stream: bool = True,
    ) -> None:
        if api not in ("responses", "chat_completions"):
            raise ValueError(f"unknown api: {api!r}")
        self.client = client
        self.model_id = model_id
        self.api = api
        self.streaming = stream

    # Request encoding

    def encode_request(self, request: ModelRequest) -> dict[str, Any]:
        """Return the exact create kwargs for this request, minus `stream`."""
        if self.api == "responses":
            return self._encode_responses(request)
        return self._encode_chat(request)

    def _encode_responses(self, request: ModelRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_id,
            "input": self._responses_input(request.messages),
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "parallel_tool_calls": True,
        }
        instructions = "\n\n".join(
            m.content for m in request.messages if isinstance(m, SystemMessage)
        )
        if instructions:
            payload["instructions"] = instructions
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                    "strict": False,
                }
                for spec in request.tools
            ]
        for key, value in request.options.items():
            if key == "tool_choice":
                payload["tool_choice"] = self._responses_tool_choice(value)
            elif key == "json_schema":
                payload["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": "output",
                        "schema": value,
                        "strict": False,
                    }
                }
            else:
                payload[key] = value
        return payload

    def _responses_input(self, messages: list[Message]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                continue  # System content becomes `instructions`.
            if isinstance(message, UserMessage):
                if message.images:
                    _refuse_images_for_text_model(message, self.capabilities)
                    content: list[dict[str, Any]] = []
                    if message.content:
                        content.append({"type": "input_text", "text": message.content})
                    content.extend(
                        {
                            "type": "input_image",
                            "image_url": image.url,
                            "detail": image.detail,
                        }
                        for image in message.images
                    )
                    items.append({"role": "user", "content": content})
                else:
                    items.append({"role": "user", "content": message.content})
            elif isinstance(message, AssistantMessage):
                items.extend(self._responses_assistant_items(message))
            elif isinstance(message, ToolResultMessage):
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.call_id,
                        "output": message.content,
                    }
                )
            else:
                raise ValueError(f"unknown message: {type(message).__name__}")
        return items

    def _responses_assistant_items(self, message: AssistantMessage) -> list[dict[str, Any]]:
        """Replay same-model output, or rebuild it from common message fields."""
        data = message.provider_data.get("openai")
        if isinstance(data, dict) and data.get("output") and data.get("model") == self.model_id:
            return copy.deepcopy(list(data["output"]))
        items: list[dict[str, Any]] = []
        if message.text:
            items.append({"role": "assistant", "content": message.text})
        for call in message.tool_calls:
            items.append(
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                }
            )
        return items

    @staticmethod
    def _responses_tool_choice(choice: str) -> Any:
        if choice in ("auto", "none"):
            return choice
        if choice == "any":
            return "required"
        return {"type": "function", "name": choice}

    def _encode_chat(self, request: ModelRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": self._chat_messages(request.messages),
        }
        if request.tools:
            payload["tools"] = [spec.to_openai() for spec in request.tools]
        for key, value in request.options.items():
            if key == "tool_choice":
                payload["tool_choice"] = self._chat_tool_choice(value)
            elif key == "json_schema":
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "output", "schema": value},
                }
            else:
                payload[key] = value
        return payload

    def _chat_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                out.append({"role": "system", "content": message.content})
            elif isinstance(message, UserMessage):
                if message.images:
                    _refuse_images_for_text_model(message, self.capabilities)
                    content: list[dict[str, Any]] = []
                    if message.content:
                        content.append({"type": "text", "text": message.content})
                    content.extend(
                        {
                            "type": "image_url",
                            "image_url": {"url": image.url, "detail": image.detail},
                        }
                        for image in message.images
                    )
                    out.append({"role": "user", "content": content})
                else:
                    out.append({"role": "user", "content": message.content})
            elif isinstance(message, AssistantMessage):
                entry: dict[str, Any] = {"role": "assistant", "content": message.text or ""}
                if message.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in message.tool_calls
                    ]
                out.append(entry)
            elif isinstance(message, ToolResultMessage):
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.call_id,
                        "content": message.content,
                    }
                )
            else:
                raise ValueError(f"unknown message: {type(message).__name__}")
        return out

    @staticmethod
    def _chat_tool_choice(choice: str) -> Any:
        if choice in ("auto", "none", "required"):
            return choice
        if choice == "any":
            return "required"
        return {"type": "function", "function": {"name": choice}}

    # Response decoding

    def decode_response(self, raw: Any) -> AssistantMessage:
        """Turn one SDK response into an `AssistantMessage`."""
        if self.api == "responses":
            return self._decode_responses(raw)
        return self._decode_chat(raw)

    def _decode_responses(self, raw: Any) -> AssistantMessage:
        texts: list[str] = []
        summaries: list[str] = []
        calls: list[ToolCall] = []
        invalid: dict[str, str] = {}
        refused = False
        for item in raw.output:
            kind = getattr(item, "type", None)
            if kind == "message":
                for part in item.content:
                    if part.type == "output_text":
                        texts.append(part.text)
                    elif part.type == "refusal":
                        refused = True
            elif kind == "reasoning":
                summaries.extend(part.text for part in item.summary if part.text)
            elif kind == "function_call":
                arguments, bad = _decode_arguments(item.arguments)
                if bad is not None:
                    invalid[item.call_id] = bad
                calls.append(ToolCall(id=item.call_id, name=item.name, arguments=arguments))
        if calls:
            stop_reason = "tool_calls"
        elif getattr(raw.incomplete_details, "reason", None) == "max_output_tokens":
            stop_reason = "length"
        elif refused:
            stop_reason = "refusal"
        else:
            stop_reason = "stop"
        provider_data: dict[str, Any] = {
            "api": "responses",
            "model": self.model_id,
            "response_model": raw.model,
            "output": [item.model_dump(exclude_none=True) for item in raw.output],
            "status": raw.status,
        }
        if invalid:
            provider_data["invalid_arguments"] = invalid
        return AssistantMessage(
            text="".join(texts) or None,
            reasoning="\n\n".join(summaries) or None,
            tool_calls=calls,
            stop_reason=stop_reason,
            usage=self._responses_usage(raw.usage),
            provider_data={"openai": provider_data},
        )

    @staticmethod
    def _responses_usage(usage: Any) -> dict[str, int]:
        if usage is None:
            return {}
        counts = {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
        cached = getattr(usage.input_tokens_details, "cached_tokens", None)
        if cached is not None:
            counts["cache_read_tokens"] = cached
        return counts

    def _decode_chat(self, raw: ChatCompletion) -> AssistantMessage:
        choice = raw.choices[0]
        message = choice.message
        calls: list[ToolCall] = []
        invalid: dict[str, str] = {}
        for call in message.tool_calls or []:
            arguments, bad = _decode_arguments(call.function.arguments)
            if bad is not None:
                invalid[call.id] = bad
            calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))
        stop_reason = _CHAT_STOP_REASONS.get(choice.finish_reason, "stop")
        if message.refusal and stop_reason == "stop":
            stop_reason = "refusal"
        provider_data: dict[str, Any] = {
            "api": "chat_completions",
            "model": self.model_id,
            "response_model": raw.model,
            "finish_reason": choice.finish_reason,
        }
        if invalid:
            provider_data["invalid_arguments"] = invalid
        return AssistantMessage(
            text=message.content or None,
            tool_calls=calls,
            stop_reason=stop_reason,
            usage=self._chat_usage(raw.usage),
            provider_data={"openai": provider_data},
        )

    @staticmethod
    def _chat_usage(usage: Any) -> dict[str, int]:
        if usage is None:
            return {}
        counts = {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
        }
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", None)
        if cached is not None:
            counts["cache_read_tokens"] = cached
        return counts

    # Model call

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        """Yield text as it arrives, followed by the complete message."""
        # 1. Translate common harness types to the selected OpenAI API.
        payload = self.encode_request(request)
        log_detail(
            "openai stream start api=%s model=%s streaming=%s request=%r payload=%r",
            self.api,
            self.model_id,
            self.streaming,
            request,
            payload,
        )

        # 2. Convert provider chunks into the two common model events.
        if self.api == "responses":
            async for event in self._stream_responses(payload):
                yield event
        else:
            async for event in self._stream_chat(payload):
                yield event

    async def generate(self, request: ModelRequest) -> AssistantMessage:
        """Consume `stream()` and return its final message."""
        return await collect_model_stream(self.stream(request))

    async def _stream_responses(
        self, payload: dict[str, Any]
    ) -> AsyncIterator[ModelEvent]:
        if not self.streaming:
            raw = await self.client.responses.create(**payload)
            log_detail("openai responses raw response=%r", raw)
            yield GenerationComplete(self.decode_response(raw))
            return
        stream = await self.client.responses.create(**payload, stream=True)
        final = None
        async for event in stream:
            log_detail("openai responses raw stream event=%r", event)
            kind = getattr(event, "type", None)
            if kind == "response.output_text.delta":
                yield TextDelta(event.delta)
            elif kind == "response.reasoning_summary_text.delta":
                yield ReasoningDelta(event.delta)
            elif kind == "response.output_item.added" and event.item.type == "function_call":
                yield ToolCallDelta(event.output_index, name=event.item.name)
            elif kind == "response.function_call_arguments.delta":
                yield ToolCallDelta(event.output_index, event.delta)
            elif kind in ("response.completed", "response.incomplete"):
                # An incomplete response still carries its text and the reason it
                # stopped, which decodes to stop_reason "length".
                final = event.response
            elif kind == "response.failed":
                raise RuntimeError(self._failure_message(event.response))
        if final is None:
            raise RuntimeError("the responses stream ended without a final response")
        log_detail("openai responses final raw response=%r", final)
        yield GenerationComplete(self.decode_response(final))

    @staticmethod
    def _failure_message(failed: Any) -> str:
        """Describe a failed response so the caller sees the provider error."""
        error = getattr(failed, "error", None)
        if error is None:
            return "the responses stream failed without an error payload"
        return f"the responses stream failed: {error.code}: {error.message}"

    async def _stream_chat(self, payload: dict[str, Any]) -> AsyncIterator[ModelEvent]:
        if not self.streaming:
            raw = await self.client.chat.completions.create(**payload)
            log_detail("openai chat raw response=%r", raw)
            yield GenerationComplete(self.decode_response(raw))
            return
        kwargs = dict(payload)
        kwargs["stream"] = True
        kwargs.setdefault("stream_options", {"include_usage": True})
        stream = await self.client.chat.completions.create(**kwargs)
        chunks: list[dict[str, Any]] = []
        async for chunk in stream:
            log_detail("openai chat raw stream chunk=%r", chunk)
            data = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
            chunks.append(data)
            for choice in data.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    yield TextDelta(delta["content"])
                # A call streams as fragments that share an index. The first one
                # names the function, the rest carry argument text.
                for fragment in delta.get("tool_calls") or []:
                    function = fragment.get("function") or {}
                    yield ToolCallDelta(
                        fragment.get("index", 0),
                        function.get("arguments") or "",
                        function.get("name"),
                    )
        merged = ChatCompletion.model_validate(accumulate_chunks(chunks))
        log_detail("openai chat merged response=%r", merged)
        yield GenerationComplete(self.decode_response(merged))

    async def estimate_tokens(self, request: ModelRequest) -> int:
        """Use the shared character heuristic until a token count API is wired."""
        return default_estimate_tokens(request)


def accumulate_chunks(chunks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Merge streamed chat chunks into one complete response."""
    completion_id = ""
    created = 0
    model = ""
    finish_reason = "stop"
    usage: dict[str, Any] | None = None
    content: list[str] = []
    refusal: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for chunk in chunks:
        completion_id = chunk.get("id") or completion_id
        created = chunk.get("created") or created
        model = chunk.get("model") or model
        if chunk.get("usage"):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content.append(delta["content"])
            if delta.get("refusal"):
                refusal.append(delta["refusal"])
            for fragment in delta.get("tool_calls") or []:
                index = fragment.get("index", 0)
                while index >= len(tool_calls):
                    tool_calls.append(
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                    )
                current = tool_calls[index]
                if fragment.get("id"):
                    current["id"] = fragment["id"]
                function = fragment.get("function") or {}
                if function.get("name"):
                    current["function"]["name"] = function["name"]
                if function.get("arguments"):
                    current["function"]["arguments"] += function["arguments"]
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
    message: dict[str, Any] = {"role": "assistant", "content": "".join(content) or None}
    if refusal:
        message["refusal"] = "".join(refusal)
    if tool_calls:
        message["tool_calls"] = tool_calls
    merged: dict[str, Any] = {
        "id": completion_id,
        "created": created,
        "model": model,
        "object": "chat.completion",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
    }
    if usage is not None:
        merged["usage"] = usage
    return merged
