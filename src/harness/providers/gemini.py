"""Gemini adapter for the generate_content API."""

from __future__ import annotations

import base64
import copy
import json
import uuid
from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, Any

from google.genai import types as genai_types

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
    from google import genai

__all__ = ["GeminiChatModel", "accumulate_chunks"]

_FINISH_REASONS = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "refusal",
    "PROHIBITED_CONTENT": "refusal",
    "BLOCKLIST": "refusal",
    "RECITATION": "refusal",
}

_TOOL_MODES = {"auto": "AUTO", "none": "NONE", "any": "ANY"}

# Gemini accepts a smaller JSON Schema subset than pydantic produces.
_SCHEMA_KEYS = (
    {name for name in genai_types.Schema.model_fields}
    | {
        field.alias
        for field in genai_types.Schema.model_fields.values()
        if field.alias is not None
    }
) - {"additional_properties", "additionalProperties", "defs", "ref"}


def _tool_schema(schema: dict[str, Any], defs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one JSON schema rewritten into the subset `types.Schema` accepts.

    A `$ref` is replaced by the schema it names, with the sibling keys kept, so
    a tool built from a nested pydantic model still describes its own shape.
    """
    if defs is None:
        defs = schema.get("$defs") or {}
    ref = schema.get("$ref")
    if ref is not None:
        target = defs.get(ref.rsplit("/", 1)[-1])
        if target is not None:
            siblings = {key: value for key, value in schema.items() if key != "$ref"}
            schema = {**target, **siblings}
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _SCHEMA_KEYS:
            continue
        if key == "properties":
            out[key] = {name: _tool_schema(sub, defs) for name, sub in value.items()}
        elif key == "items":
            out[key] = _tool_schema(value, defs)
        elif key in ("anyOf", "any_of"):
            out[key] = [_tool_schema(sub, defs) for sub in value]
        else:
            out[key] = copy.deepcopy(value)
    return out


def _call_ids(message: AssistantMessage) -> dict[str, Any]:
    """Return the minted id to provider id mapping one assistant turn recorded."""
    data = message.provider_data.get("gemini")
    if isinstance(data, dict) and isinstance(data.get("call_ids"), dict):
        return data["call_ids"]
    return {}


class GeminiChatModel:
    """Generate chat messages with one Gemini model."""

    provider = "gemini"
    capabilities = Capabilities(json_schema_output=True, vision=True)

    def __init__(
        self,
        client: genai.Client,
        model_id: str,
        *,
        thinking_config: dict | None = None,
        stream: bool = True,
    ) -> None:
        self.client = client
        self.model_id = model_id
        self.thinking_config = thinking_config
        self.streaming = stream

    # Request encoding

    def encode_request(self, request: ModelRequest) -> dict[str, Any]:
        """Return the exact `generate_content` kwargs for this request."""
        return {
            "model": self.model_id,
            "contents": self._contents(request.messages),
            "config": self._config(request),
        }

    def _config(self, request: ModelRequest) -> genai_types.GenerateContentConfig:
        """Build the config: instructions, tools, thinking, and the two options."""
        kwargs: dict[str, Any] = {
            # The harness owns the loop, so the SDK never runs a tool itself.
            "automatic_function_calling": genai_types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        }
        system = "\n\n".join(
            m.content for m in request.messages if isinstance(m, SystemMessage)
        )
        if system:
            kwargs["system_instruction"] = system
        if request.tools:
            kwargs["tools"] = [
                genai_types.Tool(
                    function_declarations=[
                        genai_types.FunctionDeclaration(
                            name=spec.name,
                            description=spec.description,
                            parameters=_tool_schema(spec.parameters),
                        )
                        for spec in request.tools
                    ]
                )
            ]
        if self.thinking_config is not None:
            kwargs["thinking_config"] = genai_types.ThinkingConfig(**self.thinking_config)
        for key, value in request.options.items():
            if key == "tool_choice":
                kwargs["tool_config"] = self._tool_config(value)
            elif key == "json_schema":
                kwargs["response_mime_type"] = "application/json"
                kwargs["response_json_schema"] = value
            else:
                kwargs[key] = value
        return genai_types.GenerateContentConfig(**kwargs)

    @staticmethod
    def _tool_config(choice: str) -> genai_types.ToolConfig:
        """Translate the common tool choice words, or force one named tool."""
        mode = _TOOL_MODES.get(choice)
        if mode is None:
            calling = genai_types.FunctionCallingConfig(
                mode="ANY", allowed_function_names=[choice]
            )
        else:
            calling = genai_types.FunctionCallingConfig(mode=mode)
        return genai_types.ToolConfig(function_calling_config=calling)

    def _contents(self, messages: list[Message]) -> list[genai_types.Content]:
        """Build the content list, folding a run of tool results into one turn.

        The API expects every function response of one parallel round in a
        single user content, and splitting them trains the model out of parallel
        calls. A user message between two results breaks the run.
        """
        ids: dict[str, Any] = {}
        for message in messages:
            if isinstance(message, AssistantMessage):
                ids.update(_call_ids(message))
        contents: list[genai_types.Content] = []
        folding = False
        for message in messages:
            if isinstance(message, SystemMessage):
                folding = False
                continue  # System content becomes `system_instruction`.
            if isinstance(message, UserMessage):
                if message.images and not self.capabilities.vision:
                    raise ValueError("this model does not support image inputs")
                parts = [genai_types.Part(text=message.content)] if message.content else []
                for image in message.images:
                    if not image.url.startswith("data:"):
                        raise ValueError(
                            "Gemini image inputs must be Base64 data URLs; "
                            "use ImageInput.from_path() or ImageInput.from_bytes()"
                        )
                    header, _, encoded = image.url.partition(",")
                    media_type = header.removeprefix("data:").removesuffix(";base64")
                    parts.append(
                        genai_types.Part.from_bytes(
                            data=base64.b64decode(encoded), mime_type=media_type
                        )
                    )
                if not parts:
                    parts.append(genai_types.Part(text=""))
                contents.append(genai_types.Content(role="user", parts=parts))
                folding = False
            elif isinstance(message, AssistantMessage):
                parts = self._assistant_parts(message)
                if parts:
                    # A content with no parts is a request error, and an empty
                    # turn would go back on every later request.
                    contents.append(genai_types.Content(role="model", parts=parts))
                folding = False
            elif isinstance(message, ToolResultMessage):
                part = self._tool_result_part(message, ids)
                if folding:
                    contents[-1].parts.append(part)
                else:
                    contents.append(genai_types.Content(role="user", parts=[part]))
                folding = True
            else:
                raise ValueError(f"unknown message: {type(message).__name__}")
        return contents

    def _assistant_parts(self, message: AssistantMessage) -> list[genai_types.Part]:
        """Replay same-model parts, or rebuild them from common message fields."""
        data = message.provider_data.get("gemini")
        if isinstance(data, dict) and data.get("parts") and data.get("model") == self.model_id:
            return [genai_types.Part.model_validate(part) for part in data["parts"]]
        parts: list[genai_types.Part] = []
        if message.text:
            parts.append(genai_types.Part(text=message.text))
        ids = _call_ids(message)
        for call in message.tool_calls:
            parts.append(
                genai_types.Part(
                    function_call=genai_types.FunctionCall(
                        id=ids.get(call.id),
                        name=call.name,
                        args=copy.deepcopy(call.arguments),
                    )
                )
            )
        return parts

    @staticmethod
    def _tool_result_part(
        message: ToolResultMessage, ids: dict[str, Any]
    ) -> genai_types.Part:
        """Encode one result. The view stays behind, the status picks the key.

        The wire has no status field, so a result that did not complete arrives
        as `{"error": ...}` and a completed one as `{"result": ...}`.
        """
        key = "result" if message.status == "completed" else "error"
        return genai_types.Part(
            function_response=genai_types.FunctionResponse(
                id=ids.get(message.call_id),
                name=message.name,
                response={key: message.content},
            )
        )

    # Response decoding

    def decode_response(self, raw: Any) -> AssistantMessage:
        """Turn one `GenerateContentResponse` into an `AssistantMessage`."""
        parts = _response_parts(raw)
        texts: list[str] = []
        thoughts: list[str] = []
        calls: list[ToolCall] = []
        call_ids: dict[str, Any] = {}
        for part in parts:
            if part.function_call is not None:
                function_call = part.function_call
                # Most models omit the id, so the harness mints one and keeps
                # the original beside it for the function response.
                call_id = function_call.id or f"call_{uuid.uuid4().hex}"
                call_ids[call_id] = function_call.id
                calls.append(
                    ToolCall(
                        id=call_id,
                        name=function_call.name or "",
                        arguments=copy.deepcopy(function_call.args or {}),
                    )
                )
            elif part.text:
                (thoughts if part.thought else texts).append(part.text)
        finish_reason = _finish_reason(raw)
        if calls:
            stop_reason: str | None = "tool_calls"
        else:
            stop_reason = _FINISH_REASONS.get(finish_reason, finish_reason)
        return AssistantMessage(
            text="".join(texts) or None,
            reasoning="\n\n".join(thoughts) or None,
            tool_calls=calls,
            stop_reason=stop_reason,
            usage=self._usage(raw.usage_metadata),
            provider_data={
                "gemini": {
                    "model": self.model_id,
                    "response_model": raw.model_version,
                    # JSON mode so a thought signature travels base64 and
                    # survives `message_to_dict`.
                    "parts": [
                        part.model_dump(mode="json", exclude_none=True) for part in parts
                    ],
                    "finish_reason": finish_reason,
                    "call_ids": call_ids,
                }
            },
        )

    @staticmethod
    def _usage(usage: Any) -> dict[str, int]:
        """Map the reported counts, the cache count included when it is there."""
        if usage is None:
            return {}
        counts = {
            "input_tokens": usage.prompt_token_count or 0,
            "output_tokens": usage.candidates_token_count or 0,
        }
        cached = usage.cached_content_token_count
        if cached is not None:
            counts["cache_read_tokens"] = cached
        return counts

    # Model call

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        """Yield text as it arrives, followed by the complete message."""
        # 1. Translate common harness types to Gemini's wire format.
        payload = self.encode_request(request)
        endpoint = self.client.aio.models
        log_detail(
            "gemini stream start model=%s streaming=%s request=%r payload=%r",
            self.model_id,
            self.streaming,
            request,
            payload,
        )

        # 2. Yield live text and merge chunks for the final message.
        if not self.streaming:
            raw = await endpoint.generate_content(**payload)
            log_detail("gemini raw response=%r", raw)
            yield GenerationComplete(self.decode_response(raw))
            return
        stream = await endpoint.generate_content_stream(**payload)
        chunks: list[dict[str, Any]] = []
        calls_seen = 0
        async for chunk in stream:
            log_detail("gemini raw stream chunk=%r", chunk)
            data = chunk.model_dump(mode="json", exclude_none=True)
            chunks.append(data)
            for part in _chunk_parts(data):
                if part.get("text"):
                    # A thought is a summary, not assistant text.
                    kind = ReasoningDelta if part.get("thought") else TextDelta
                    yield kind(part["text"])
                elif part.get("function_call"):
                    # Gemini sends each call whole, so one delta holds all of it.
                    call = part["function_call"]
                    arguments = json.dumps(call.get("args") or {})
                    yield ToolCallDelta(calls_seen, arguments, call.get("name"))
                    calls_seen += 1
        merged = genai_types.GenerateContentResponse.model_validate(accumulate_chunks(chunks))
        log_detail("gemini merged response=%r", merged)
        yield GenerationComplete(self.decode_response(merged))

    async def generate(self, request: ModelRequest) -> AssistantMessage:
        """Consume `stream()` and return its final message."""
        return await collect_model_stream(self.stream(request))

    async def estimate_tokens(self, request: ModelRequest) -> int:
        """Use the shared character heuristic until `count_tokens` is wired."""
        return default_estimate_tokens(request)


def _response_parts(raw: Any) -> list[genai_types.Part]:
    """Return the parts of the first candidate, or none when there is no candidate."""
    candidates = raw.candidates or []
    if not candidates:
        return []
    content = candidates[0].content
    if content is None:
        return []
    return list(content.parts or [])


def _finish_reason(raw: Any) -> Any:
    """Return the finish reason of the first candidate as its raw name."""
    candidates = raw.candidates or []
    if not candidates:
        return None
    reason = candidates[0].finish_reason
    return getattr(reason, "name", reason)


def _first_candidate(chunk: dict[str, Any]) -> dict[str, Any] | None:
    """Return the candidate at index 0 of one streamed chunk dict.

    `candidate_count` asks the provider for several answers, and a chunk then
    carries one entry per answer. Only the first is decoded, the same way
    `decode_response` reads `candidates[0]`, so the streamed result and the
    non-streamed result are the same message. A missing index means the first.
    """
    for candidate in chunk.get("candidates") or []:
        if candidate.get("index", 0) == 0:
            return candidate
    return None


def _chunk_parts(chunk: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Walk the parts of the first candidate of one streamed chunk dict."""
    candidate = _first_candidate(chunk)
    if candidate is None:
        return
    content = candidate.get("content") or {}
    yield from content.get("parts") or []


def _merges_into(previous: dict[str, Any], part: dict[str, Any]) -> bool:
    """Say whether one streamed text part continues the part before it.

    Only plain text merges, and only when both fragments are of the same kind,
    so a thought summary never runs into the answer.
    """
    if "text" not in previous or "text" not in part:
        return False
    if set(previous) - {"text", "thought", "thought_signature"}:
        return False
    if set(part) - {"text", "thought", "thought_signature"}:
        return False
    return bool(previous.get("thought")) == bool(part.get("thought"))


def accumulate_chunks(chunks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Merge streamed chunks into one complete Gemini response."""
    parts: list[dict[str, Any]] = []
    finish_reason: Any = None
    usage: dict[str, Any] | None = None
    model_version = ""
    response_id = ""
    for chunk in chunks:
        usage = chunk.get("usage_metadata") or usage
        model_version = chunk.get("model_version") or model_version
        response_id = chunk.get("response_id") or response_id
        candidate = _first_candidate(chunk)
        if candidate is None:
            continue
        if candidate.get("finish_reason"):
            finish_reason = candidate["finish_reason"]
        for part in _chunk_parts(chunk):
            if parts and _merges_into(parts[-1], part):
                previous = parts[-1]
                previous["text"] += part["text"]
                if part.get("thought_signature"):
                    previous["thought_signature"] = part["thought_signature"]
            else:
                parts.append(copy.deepcopy(part))
    candidate: dict[str, Any] = {
        "index": 0,
        "content": {"role": "model", "parts": parts},
    }
    if finish_reason is not None:
        candidate["finish_reason"] = finish_reason
    merged: dict[str, Any] = {"candidates": [candidate]}
    if usage is not None:
        merged["usage_metadata"] = usage
    if model_version:
        merged["model_version"] = model_version
    if response_id:
        merged["response_id"] = response_id
    return merged
