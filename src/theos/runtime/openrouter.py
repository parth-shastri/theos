"""OpenRouter response fields that the generic OpenAI adapter does not retain."""

import asyncio
import copy
import logging
from decimal import Decimal, InvalidOperation
from time import monotonic

from openai import BadRequestError, NotFoundError
from openai.types.chat import ChatCompletion

from harness import AssistantMessage
from harness.events import GenerationComplete, ReasoningDelta, TextDelta, ToolCallDelta
from harness.providers.openai import OpenAIChatModel, accumulate_chunks
from theos.operations.provider_diagnostics import annotate, chunk, diagnostics, failure

OPENAI_REASONING_FORMATS = {
    "openai-responses-v1",
    "azure-openai-responses-v1",
    "bedrock-openai-responses-v1",
}


def encrypted_formats(wire):
    return {
        block["format"]
        for block in wire.get("reasoning_details", [])
        if block.get("type") == "reasoning.encrypted"
        and block.get("format") in OPENAI_REASONING_FORMATS
    }


def omit_reasoning(wire):
    """Omit a whole sequence without modifying any signed block or visible message."""
    wire.pop("reasoning_details", None)
    wire.pop("reasoning", None)


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
        if self.model_id.startswith("openai/"):
            formats = [encrypted_formats(wire) for wire in payload["messages"]]
            latest = next((group for group in reversed(formats) if len(group) == 1), set())
            for wire, group in zip(payload["messages"], formats, strict=True):
                if group and group != latest:
                    omit_reasoning(wire)
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
        from .errors import ProviderFailure

        retry = payload
        route_retried = False
        transient_retries = 0
        started = monotonic()
        while True:
            emitted = False
            try:
                async for event in self._stream_chat_once(retry):
                    emitted = True
                    yield event
                return
            except (NotFoundError, BadRequestError) as error:
                body = error.body if isinstance(error.body, dict) else {}
                message = body.get("message", "")
                if isinstance(body.get("error"), dict):
                    message = body["error"].get("message", message)
                rejected_state = isinstance(message, str) and (
                    isinstance(error, NotFoundError)
                    and "No endpoints found matching your data policy (Zero data retention)"
                    in message
                    or isinstance(error, BadRequestError)
                    and "encrypted reasoning or compaction content from multiple providers"
                    in message
                )
                if (
                    emitted
                    or route_retried
                    or not self.model_id.startswith("openai/")
                    or not rejected_state
                ):
                    raise
                candidate = copy.deepcopy(retry)
                changed = False
                for wire in candidate["messages"]:
                    if encrypted_formats(wire):
                        omit_reasoning(wire)
                        changed = True
                if not changed:
                    raise
                retry = candidate
                route_retried = True
                logging.getLogger("theos").warning("openrouter_reasoning_replay_rejected")
            except ProviderFailure as error:
                if (
                    emitted
                    or transient_retries >= 2
                    or monotonic() - started >= 30
                    or error.diagnostics.get("http_status") != 200
                    or error.diagnostics.get("status_code") not in {500, 502, 503, 504, 529}
                    or error.context_overflow
                    or error.diagnostics.get("provider_error_type")
                    in {
                        "authentication",
                        "content_policy_violation",
                        "invalid_request",
                        "refusal",
                        "rate_limit_exceeded",
                    }
                ):
                    raise
                # Retry only this unfinished model request. No tool has executed from it.
                transient_retries += 1
                logging.getLogger("theos").warning(
                    "provider_stream_retry",
                    extra={**error.diagnostics, "attempt": transient_retries + 1},
                )
                await asyncio.sleep(0.5 * transient_retries)

    async def _stream_chat_once(self, payload):
        if not self.streaming:
            raw = await self.client.chat.completions.create(**payload)
            yield GenerationComplete(self.decode_response(raw))
            return
        stream = await self.client.chat.completions.create(**payload, stream=True)
        chunks, summaries, blocks = [], [], {}
        response = getattr(stream, "response", None)
        stream_info = {
            "provider_stage": "stream",
            "http_status": getattr(response, "status_code", None),
            "generation_id": response.headers.get("x-generation-id")
            if response is not None
            else None,
        }
        annotate(stream_info)
        try:
            async with stream:
                async for item in stream:
                    data = item.model_dump() if hasattr(item, "model_dump") else item
                    chunk(data)
                    if data.get("error") or any(
                        choice.get("finish_reason") == "error"
                        for choice in data.get("choices") or []
                    ):
                        from .errors import ProviderFailure

                        raise ProviderFailure("openrouter", data.get("error") or {})
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
        except Exception as error:
            from .errors import ProviderFailure

            problem = (
                error
                if isinstance(error, ProviderFailure)
                else ProviderFailure("openrouter", error)
            )
            problem.diagnostics.update(
                diagnostics(error, **{k: v for k, v in stream_info.items() if v is not None})
            )
            failure(problem)
            if problem is error:
                raise
            raise problem from error
        merged = accumulate_chunks(chunks)
        response = merged["choices"][0]["message"]
        response["reasoning"] = "".join(summaries) or None
        if blocks:
            response["reasoning_details"] = list(blocks.values())
        yield GenerationComplete(self.decode_response(ChatCompletion.model_validate(merged)))
