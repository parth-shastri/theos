"""Anthropic adapter for the Messages API."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from harness.debug import log_detail
from harness.events import (
    GenerationComplete,
    ModelDelta,
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
    from anthropic import AsyncAnthropic

__all__ = ["AnthropicChatModel"]

_STOP_REASONS = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "refusal": "refusal",
}

# What a tool result says when the tool returned nothing. An empty content block
# is a request error on the Messages API.
_EMPTY_RESULT = "(empty result)"

# Models that reject a forced tool choice, so the application asks nicely instead.
_NO_FORCED_TOOL_CHOICE = ("claude-fable-5-1", "claude-mythos-5-1")

# The beta flag each `fallbacks` form needs. The scalar form routes by refusal
# category, the list form names the models to try.
_FALLBACK_BETAS = {
    "scalar": "server-side-fallback-2026-07-01",
    "list": "server-side-fallback-2026-06-01",
}


def _content_blocks(content: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one turn's content as blocks. A plain string becomes a text block."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return list(content)


def _merge_same_role_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge every run of adjacent same-role turns into one turn of blocks.

    A turn that needs no merge keeps the content it had, so an alternating
    conversation still sends plain strings.
    """
    merged: list[dict[str, Any]] = []
    for turn in turns:
        if merged and merged[-1]["role"] == turn["role"]:
            previous = merged[-1]
            merged[-1] = {
                "role": turn["role"],
                "content": _content_blocks(previous["content"])
                + _content_blocks(turn["content"]),
            }
        else:
            merged.append(turn)
    return merged


def _delta(event: Any) -> ModelDelta | None:
    """Translate one SDK stream event into a harness delta, or nothing.

    The SDK yields its own `text` and `thinking` events beside the raw wire
    events. Tool arguments only exist on the wire, as a `tool_use` block start
    followed by `input_json_delta` fragments.
    """
    kind = getattr(event, "type", None)
    if kind == "text":
        return TextDelta(event.text)
    if kind == "thinking" and event.thinking:
        return ReasoningDelta(event.thinking)
    if kind == "content_block_start" and event.content_block.type == "tool_use":
        return ToolCallDelta(event.index, name=event.content_block.name)
    if kind == "content_block_delta" and event.delta.type == "input_json_delta":
        return ToolCallDelta(event.index, event.delta.partial_json)
    return None


class AnthropicChatModel:
    """Generate chat messages with one Anthropic model."""

    provider = "anthropic"
    capabilities = Capabilities(json_schema_output=True, vision=True)

    def __init__(
        self,
        client: AsyncAnthropic,
        model_id: str = "claude-opus-5",
        *,
        max_tokens: int = 16000,
        thinking: dict | None = {"type": "adaptive"},  # noqa: B006 - read, never mutated
        stream: bool = True,
        fallbacks: list[dict] | str | None = None,
        cache: bool = True,
    ) -> None:
        self.client = client
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.thinking = thinking
        self.streaming = stream
        self.fallbacks = fallbacks
        self.cache = cache
        if model_id.startswith(_NO_FORCED_TOOL_CHOICE):
            self.capabilities = replace(type(self).capabilities, forced_tool_choice=False)

    # Request encoding

    def encode_request(self, request: ModelRequest) -> dict[str, Any]:
        """Return the exact create kwargs for this request, minus `stream`."""
        payload: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "messages": self._messages(request.messages),
        }
        system = "\n\n".join(
            m.content for m in request.messages if isinstance(m, SystemMessage)
        )
        if system:
            payload["system"] = system
        if self.thinking is not None:
            payload["thinking"] = dict(self.thinking)
        if request.tools:
            payload["tools"] = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.parameters,
                }
                for spec in request.tools
            ]
        if self.fallbacks is not None:
            payload["fallbacks"] = self.fallbacks
            payload["betas"] = [self._fallback_beta()]
        if self.cache:
            # The prefix is tools, then system, then messages. One top-level
            # breakpoint caches everything up to the newest message, so the
            # next call in a loop reads the whole previous request from cache.
            payload["cache_control"] = {"type": "ephemeral"}
        self._apply_options(payload, request.options)
        return payload

    def _fallback_beta(self) -> str:
        """Name the beta flag the configured `fallbacks` form requires."""
        form = "scalar" if isinstance(self.fallbacks, str) else "list"
        return _FALLBACK_BETAS[form]

    def _apply_options(self, payload: dict[str, Any], options: dict[str, Any]) -> None:
        """Translate the two common options and pass every other key through.

        A caller `output_config` keeps its own keys, such as `effort`, and the
        translated `json_schema` becomes its `format`.
        """
        for key, value in options.items():
            if key == "tool_choice":
                payload["tool_choice"] = self._tool_choice(value)
            elif key == "json_schema":
                config = dict(payload.get("output_config") or {})
                config["format"] = {"type": "json_schema", "schema": value}
                payload["output_config"] = config
            elif key == "output_config":
                config = dict(value)
                current = payload.get("output_config") or {}
                if "format" in current:
                    config["format"] = current["format"]
                payload["output_config"] = config
            else:
                payload[key] = value

    @staticmethod
    def _tool_choice(choice: str) -> dict[str, Any]:
        if choice in ("auto", "none", "any"):
            return {"type": choice}
        return {"type": "tool", "name": choice}

    def _messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Build the message list, merging every run of same-role turns into one.

        Roles have to alternate on the wire, and history produces runs that do
        not: parallel tool results are one message each, a steering message
        follows those results, and a turn that carries nothing is dropped, which
        leaves its neighbors adjacent. Merging here means the encoder never
        depends on the API combining anything. Results split across several user
        messages also train the model out of parallel calls, so a run of them
        becomes one turn holding every `tool_result` block in order.
        """
        turns: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                continue  # System content becomes the top-level `system`.
            if isinstance(message, UserMessage):
                if message.images:
                    if not self.capabilities.vision:
                        raise ValueError("this model does not support image inputs")
                    content: list[dict[str, Any]] = []
                    for image in message.images:
                        if image.url.startswith("data:"):
                            header, _, encoded = image.url.partition(",")
                            media_type = header.removeprefix("data:").removesuffix(";base64")
                            source = {
                                "type": "base64",
                                "media_type": media_type,
                                "data": encoded,
                            }
                        else:
                            source = {"type": "url", "url": image.url}
                        content.append({"type": "image", "source": source})
                    if message.content:
                        content.append({"type": "text", "text": message.content})
                    turns.append({"role": "user", "content": content})
                else:
                    turns.append({"role": "user", "content": message.content})
            elif isinstance(message, ToolResultMessage):
                turns.append({"role": "user", "content": [self._tool_result_block(message)]})
            elif isinstance(message, AssistantMessage):
                content = self._assistant_content(message)
                if content:
                    # A refusal before any output leaves nothing to replay, and an
                    # empty assistant turn would go back on every later request.
                    turns.append({"role": "assistant", "content": content})
            else:
                raise ValueError(f"unknown message: {type(message).__name__}")
        return _merge_same_role_turns(turns)

    @staticmethod
    def _tool_result_block(message: ToolResultMessage) -> dict[str, Any]:
        """Encode one result. The view stays behind, the status becomes `is_error`.

        A tool that returns nothing gets a placeholder, because the Messages API
        rejects an empty content block.
        """
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": message.call_id,
            "content": message.content if message.content.strip() else _EMPTY_RESULT,
        }
        if message.status != "completed":
            block["is_error"] = True
        return block

    def _assistant_content(self, message: AssistantMessage) -> list[dict[str, Any]]:
        """Replay same-model content, or rebuild it from common message fields."""
        data = message.provider_data.get("anthropic")
        if isinstance(data, dict) and data.get("content") and data.get("model") == self.model_id:
            return copy.deepcopy(list(data["content"]))
        blocks: list[dict[str, Any]] = []
        if message.text:
            blocks.append({"type": "text", "text": message.text})
        for call in message.tool_calls:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": copy.deepcopy(call.arguments),
                }
            )
        return blocks

    # Response decoding

    def decode_response(self, raw: Any) -> AssistantMessage:
        """Turn one SDK `Message` into an `AssistantMessage`."""
        texts: list[str] = []
        thoughts: list[str] = []
        calls: list[ToolCall] = []
        for block in raw.content:
            kind = getattr(block, "type", None)
            if kind == "text":
                texts.append(block.text)
            elif kind == "thinking":
                if block.thinking:
                    thoughts.append(block.thinking)
            elif kind == "tool_use":
                # The wire carries a JSON object, so arguments arrive decoded.
                # There is no invalid argument string to record here.
                calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=copy.deepcopy(block.input))
                )
        provider_data: dict[str, Any] = {
            "model": self.model_id,
            "response_model": raw.model,
            "content": [block.model_dump(exclude_none=True) for block in raw.content],
            "stop_reason": raw.stop_reason,
        }
        details = getattr(raw, "stop_details", None)
        if raw.stop_reason == "refusal" and details is not None:
            provider_data["stop_details"] = details.model_dump(exclude_none=True)
        return AssistantMessage(
            text="".join(texts) or None,
            reasoning="\n\n".join(thoughts) or None,
            tool_calls=calls,
            stop_reason=_STOP_REASONS.get(raw.stop_reason, raw.stop_reason),
            usage=self._usage(raw.usage),
            provider_data={"anthropic": provider_data},
        )

    @staticmethod
    def _usage(usage: Any) -> dict[str, int]:
        """Map the reported counts, cache fields included when the provider sent them."""
        if usage is None:
            return {}
        counts = {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
        read = getattr(usage, "cache_read_input_tokens", None)
        if read is not None:
            counts["cache_read_tokens"] = read
        written = getattr(usage, "cache_creation_input_tokens", None)
        if written is not None:
            counts["cache_write_tokens"] = written
        return counts

    # Model call

    def _endpoint(self) -> Any:
        """Pick the endpoint. `fallbacks` lives on the beta messages endpoint."""
        if self.fallbacks is not None:
            return self.client.beta.messages
        return self.client.messages

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        """Yield text as it arrives, followed by the complete message."""
        # 1. Translate common harness types to Anthropic's wire format.
        payload = self.encode_request(request)
        endpoint = self._endpoint()
        log_detail(
            "anthropic stream start model=%s streaming=%s request=%r payload=%r",
            self.model_id,
            self.streaming,
            request,
            payload,
        )

        # 2. Yield live text and finish with the accumulated SDK message.
        if not self.streaming:
            raw = await endpoint.create(**payload)
            log_detail("anthropic raw response=%r", raw)
            yield GenerationComplete(self.decode_response(raw))
            return
        async with endpoint.stream(**payload) as stream:
            async for event in stream:
                log_detail("anthropic raw stream event=%r", event)
                delta = _delta(event)
                if delta is not None:
                    yield delta
            final = await stream.get_final_message()
        if final is None:
            raise RuntimeError("the messages stream ended without a final message")
        log_detail("anthropic final raw response=%r", final)
        yield GenerationComplete(self.decode_response(final))

    async def generate(self, request: ModelRequest) -> AssistantMessage:
        """Consume `stream()` and return its final message."""
        return await collect_model_stream(self.stream(request))

    async def estimate_tokens(self, request: ModelRequest) -> int:
        """Use the shared character heuristic until the token count API is wired."""
        return default_estimate_tokens(request)
