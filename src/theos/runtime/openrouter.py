"""OpenRouter response fields that the generic OpenAI adapter does not retain."""

import copy
import logging
from decimal import Decimal, InvalidOperation

from openai import NotFoundError
from openai.types.chat import ChatCompletion

from harness import AssistantMessage
from harness.events import GenerationComplete, ReasoningDelta, TextDelta, ToolCallDelta
from harness.providers.openai import OpenAIChatModel, accumulate_chunks


def reasoning_text(value):
    """Expose readable summaries only. Keep encrypted blocks in provider state."""
    text = value.get("reasoning") or value.get("reasoning_content")
    if isinstance(text, str):
        return text
    parts = []
    for detail in value.get("reasoning_details") or []:
        if detail.get("type") == "reasoning.summary":
            parts.append(detail.get("summary") or "")
        elif detail.get("type") == "reasoning.text":
            parts.append(detail.get("text") or "")
    return "".join(parts)


def merge_reasoning(blocks, fragments):
    """Join streamed blocks by index without changing their order or signatures."""
    for fragment in fragments:
        index = fragment.get("index", 0)
        current = blocks.setdefault(index, {})
        for key, value in fragment.items():
            if key in {"text", "summary", "data"} and isinstance(value, str):
                current[key] = current.get(key, "") + value
            else:
                current[key] = copy.deepcopy(value)


class OpenRouterChatModel(OpenAIChatModel):
    """Enforce ZDR and retain reasoning and reported costs on the OpenAI protocol."""

    provider = "openrouter"

    def _encode_chat(self, request):
        payload = super()._encode_chat(request)
        # Apply the retention policy after request options, including internal calls.
        extra = dict(payload.get("extra_body") or {})
        extra["provider"] = {**(extra.get("provider") or {}), "zdr": True}
        payload["extra_body"] = extra
        for message, wire in zip(request.messages, payload["messages"], strict=True):
            if not isinstance(message, AssistantMessage):
                continue
            saved = message.provider_data.get("openrouter", {})
            if saved.get("model") == self.model_id:
                if saved.get("reasoning_details"):
                    wire["reasoning_details"] = copy.deepcopy(saved["reasoning_details"])
                elif message.reasoning:
                    wire["reasoning"] = message.reasoning
        return payload

    def decode_response(self, raw):
        message = super().decode_response(raw)
        value = raw.choices[0].message.model_dump()
        message.reasoning = reasoning_text(value) or None
        if message.reasoning or value.get("reasoning_details"):
            message.provider_data["openrouter"] = {
                "model": self.model_id,
                "reasoning_details": copy.deepcopy(value.get("reasoning_details") or []),
            }
        cost = getattr(raw.usage, "cost", None)
        if cost is not None and not isinstance(cost, bool):
            try:
                amount = Decimal(str(cost))
                if amount.is_finite() and amount >= 0:
                    # Usage counters remain integers. SQLite stores USD at the app boundary.
                    message.usage["cost_nanousd"] = int(
                        (amount * 1_000_000_000).to_integral_value()
                    )
            except (InvalidOperation, ValueError):
                pass
        return message

    async def _stream_chat(self, payload):
        emitted = False
        try:
            async for event in self._stream_chat_once(payload):
                emitted = True
                yield event
            return
        except NotFoundError as error:
            body = error.body if isinstance(error.body, dict) else {}
            message = body.get("message", "")
            if isinstance(body.get("error"), dict):
                message = body["error"].get("message", message)
            if (
                emitted
                or not self.model_id.startswith("openai/")
                or not isinstance(message, str)
                or "No endpoints found matching your data policy (Zero data retention)"
                not in message
            ):
                raise
            retry = copy.deepcopy(payload)
            changed = False
            for wire in retry["messages"]:
                if any(
                    block.get("type") == "reasoning.encrypted"
                    and block.get("format")
                    in {
                        "openai-responses-v1",
                        "azure-openai-responses-v1",
                        "bedrock-openai-responses-v1",
                    }
                    for block in wire.get("reasoning_details", [])
                ):
                    # Omit the whole sequence. Never alter signed reasoning blocks.
                    wire.pop("reasoning_details", None)
                    wire.pop("reasoning", None)
                    changed = True
            if not changed:
                raise
            logging.getLogger("theos").warning("openrouter_reasoning_replay_rejected")
        # Routing rejected the first request before generation. Keep ZDR and tools unchanged.
        async for event in self._stream_chat_once(retry):
            yield event

    async def _stream_chat_once(self, payload):
        if not self.streaming:
            raw = await self.client.chat.completions.create(**payload)
            yield GenerationComplete(self.decode_response(raw))
            return
        stream = await self.client.chat.completions.create(**payload, stream=True)
        chunks, summaries, blocks = [], [], {}
        async with stream:
            async for chunk in stream:
                data = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
                chunks.append(data)
                for choice in data.get("choices") or []:
                    delta = choice.get("delta") or {}
                    summary = reasoning_text(delta)
                    if summary:
                        summaries.append(summary)
                        yield ReasoningDelta(summary)
                    merge_reasoning(blocks, delta.get("reasoning_details") or [])
                    if delta.get("content"):
                        yield TextDelta(delta["content"])
                    for fragment in delta.get("tool_calls") or []:
                        function = fragment.get("function") or {}
                        yield ToolCallDelta(
                            fragment.get("index", 0),
                            function.get("arguments") or "",
                            function.get("name"),
                        )
        merged = accumulate_chunks(chunks)
        response = merged["choices"][0]["message"]
        response["reasoning"] = "".join(summaries) or None
        if blocks:
            response["reasoning_details"] = list(blocks.values())
        yield GenerationComplete(self.decode_response(ChatCompletion.model_validate(merged)))
