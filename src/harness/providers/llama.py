"""Adapter for local models served by ``llama-server --jinja``.

The OpenAI-compatible API handles generation. This adapter adds llama-server
options and uses its template and tokenizer endpoints for request sizing.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import httpx

from harness.context import default_estimate
from harness.debug import log_detail
from harness.model import Capabilities, default_estimate_tokens
from harness.providers.openai import OpenAIChatModel
from harness.types import (
    AssistantMessage,
    Message,
    ModelRequest,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI

__all__ = ["LlamaServerModel"]

# Keyword arguments the OpenAI SDK accepts for chat completions. Anything else
# travels in `extra_body`, which the SDK merges into the JSON body unchanged.
_SDK_OPTIONS = frozenset(
    {
        "frequency_penalty",
        "logit_bias",
        "logprobs",
        "max_completion_tokens",
        "max_tokens",
        "metadata",
        "n",
        "parallel_tool_calls",
        "presence_penalty",
        "reasoning_effort",
        "response_format",
        "seed",
        "stop",
        "stream_options",
        "temperature",
        "tool_choice",
        "top_logprobs",
        "top_p",
        "user",
        "extra_headers",
        "extra_query",
        "timeout",
    }
)

# Encoded by the base adapter itself.
_ADAPTER_OPTIONS = frozenset({"tool_choice", "json_schema"})

def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


class LlamaServerModel(OpenAIChatModel):
    """Chat with a model served by `llama-server --jinja`."""

    def __init__(
        self,
        client: AsyncOpenAI,
        model_id: str,
        *,
        capabilities: Capabilities,
        stream: bool = True,
        default_options: dict[str, Any] | None = None,
        tokenize_timeout_s: float = 10.0,
    ) -> None:
        super().__init__(client, model_id, api="chat_completions", stream=stream)
        self.provider = "llama"
        self.capabilities = capabilities
        self.default_options = copy.deepcopy(default_options or {})
        self.tokenize_timeout_s = tokenize_timeout_s

    # Request encoding

    def encode_request(self, request: ModelRequest) -> dict[str, Any]:
        """Encode options for llama-server's OpenAI-compatible endpoint."""
        options = copy.deepcopy(self.default_options)
        options.update(copy.deepcopy(request.options))
        extra = copy.deepcopy(options.pop("extra_body", None) or {})
        # Thinking stays enabled unless a request turns it off.
        enable_thinking = options.pop("enable_thinking", True) is not False
        template = dict(options.pop("chat_template_kwargs", None) or {})
        extra["cache_prompt"] = True
        extra["reasoning_format"] = options.pop("reasoning_format", "auto")
        for key in list(options):
            if key not in _SDK_OPTIONS and key not in _ADAPTER_OPTIONS:
                extra[key] = options.pop(key)
        extra["chat_template_kwargs"] = {**template, "enable_thinking": enable_thinking}
        options["extra_body"] = extra
        encoded = ModelRequest(request.messages, request.tools, options)
        return self._encode_chat(encoded)

    def _chat_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        return [self._wire(message) for message in messages]

    def _wire(self, message: Message) -> dict[str, Any]:
        """Encode a common harness message for the chat completions API."""
        if isinstance(message, SystemMessage):
            return {"role": "system", "content": message.content}
        if isinstance(message, UserMessage):
            # Reject unsupported image inputs before encoding the request.
            if message.images and not self.capabilities.vision:
                raise ValueError("this model does not support image inputs")
            if not message.images:
                return {"role": "user", "content": message.content}
            return {
                "role": "user",
                "content": [
                    {"type": "text", "text": message.content},
                    *(
                        {"type": "image_url", "image_url": {"url": image.url}}
                        for image in message.images
                    ),
                ],
            }
        if isinstance(message, AssistantMessage):
            entry: dict[str, Any] = {"role": "assistant", "content": message.text}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": _compact(call.arguments)},
                    }
                    for call in message.tool_calls
                ]
            return entry
        if isinstance(message, ToolResultMessage):
            return {
                "role": "tool",
                "tool_call_id": message.call_id,
                "name": message.name,
                "content": message.content,
            }
        raise ValueError(f"unknown message: {type(message).__name__}")

    # Token counting

    def _server_root(self) -> str:
        base = str(self.client.base_url).rstrip("/")
        return base[: -len("/v1")] if base.endswith("/v1") else base

    async def count_tokens(self, messages: Sequence[Message]) -> int:
        """Count with the server's tokenizer; estimate when it cannot answer.

        llama-server serves `/tokenize` at its root, not under `/v1`.
        """
        try:
            content = "\n".join(_compact(self._wire(m)) for m in messages)
        except ValueError:
            return default_estimate(messages)
        try:
            async with httpx.AsyncClient(timeout=self.tokenize_timeout_s) as http:
                response = await http.post(
                    f"{self._server_root()}/tokenize",
                    json={"content": content, "add_special": True},
                )
            if response.status_code != 200:
                return default_estimate(messages)
            tokens = response.json().get("tokens")
        except (httpx.HTTPError, ValueError) as error:
            log_detail("llama tokenize failed error=%r; using the estimate", error)
            return default_estimate(messages)
        return len(tokens) if isinstance(tokens, list) else default_estimate(messages)

    async def _template_tokens(
        self,
        messages: Sequence[Message],
        tools: Sequence[Any] = (),
        *,
        enable_thinking: bool = True,
    ) -> int | None:
        """Tokens of the exact prompt the server renders: chat template, tool
        specs, and thinking switch included. None when the server cannot say."""
        try:
            body: dict[str, Any] = {
                "messages": [self._wire(m) for m in messages],
                "chat_template_kwargs": {"enable_thinking": enable_thinking},
            }
            if tools:
                body["tools"] = [t.to_openai() if hasattr(t, "to_openai") else t for t in tools]
            async with httpx.AsyncClient(timeout=self.tokenize_timeout_s) as http:
                rendered = await http.post(f"{self._server_root()}/apply-template", json=body)
                prompt = rendered.json().get("prompt") if rendered.status_code == 200 else None
                if not isinstance(prompt, str):
                    return None
                response = await http.post(
                    f"{self._server_root()}/tokenize",
                    json={"content": prompt, "add_special": True, "parse_special": True},
                )
            tokens = response.json().get("tokens") if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as error:
            log_detail("llama apply-template failed error=%r; using the estimate", error)
            return None
        return len(tokens) if isinstance(tokens, list) else None

    async def count_request_tokens(self, request: ModelRequest) -> int:
        """Count the exact prompt the server renders for ``request``."""
        exact = await self._template_tokens(
            request.messages,
            request.tools,
            enable_thinking=request.options.get("enable_thinking") is not False,
        )
        if exact is not None:
            return exact
        return default_estimate_tokens(request)

    async def estimate_tokens(self, request: ModelRequest) -> int:
        return await self.count_request_tokens(request)
