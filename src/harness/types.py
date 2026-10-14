"""Data types shared by the harness, tools, and provider adapters."""

from __future__ import annotations

import base64
import binascii
import copy
import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel


@dataclass
class SystemMessage:
    """Instructions that stay at the front of the request."""

    content: str


@dataclass
class UserMessage:
    """One turn of user input."""

    content: str
    images: list[ImageInput] = field(default_factory=list)


ImageDetail = Literal["auto", "low", "high", "original"]
SUPPORTED_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024


def _detected_image_media_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(frozen=True)
class ImageInput:
    """One replayable HTTP or Base64 image input.

    Local files become data URLs at the input boundary, so stored conversations
    remain replayable when the source file moves or is deleted.
    """

    url: str
    detail: ImageDetail = "auto"
    filename: str | None = None

    def __post_init__(self) -> None:
        if self.detail not in {"auto", "low", "high", "original"}:
            raise ValueError(f"unsupported image detail: {self.detail!r}")
        if self.url.startswith(("https://", "http://")):
            if not urlparse(self.url).netloc:
                raise ValueError("image URL must include a host")
            return
        if not self.url.startswith("data:image/"):
            raise ValueError("image URL must be HTTP(S) or a Base64 data:image URL")
        header, separator, encoded = self.url.partition(",")
        if not separator or not header.endswith(";base64"):
            raise ValueError("image data URL must contain Base64 data")
        media_type = header.removeprefix("data:").removesuffix(";base64")
        if media_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
            raise ValueError(f"unsupported image type {media_type!r}")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("image data URL contains invalid Base64") from error
        detected = _detected_image_media_type(data)
        if detected != media_type:
            raise ValueError(
                f"image bytes are {detected or 'not a supported image'}, not {media_type}"
            )

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        media_type: str,
        filename: str | None = None,
        detail: ImageDetail = "auto",
        max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    ) -> ImageInput:
        """Build a self-contained image after checking its type and size."""
        canonical = "image/jpeg" if media_type == "image/jpg" else media_type
        if canonical not in SUPPORTED_IMAGE_MEDIA_TYPES:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_MEDIA_TYPES))
            raise ValueError(f"unsupported image type {media_type!r}; expected {supported}")
        if not data:
            raise ValueError("image must not be empty")
        if len(data) > max_bytes:
            raise ValueError(f"image is {len(data):,} bytes; local limit is {max_bytes:,} bytes")
        detected = _detected_image_media_type(data)
        if detected != canonical:
            raise ValueError(
                f"image bytes are {detected or 'not a supported image'}, not {canonical}"
            )
        encoded = base64.b64encode(data).decode("ascii")
        return cls(f"data:{canonical};base64,{encoded}", detail, filename)

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        detail: ImageDetail = "auto",
        max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    ) -> ImageInput:
        """Read one supported local image into a self-contained data URL."""
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise ValueError(f"image does not exist: {resolved}")
        media_type, _ = mimetypes.guess_type(resolved.name)
        if media_type is None:
            raise ValueError(f"could not determine image type: {resolved.name}")
        if resolved.stat().st_size > max_bytes:
            raise ValueError(
                f"image is {resolved.stat().st_size:,} bytes; local limit is {max_bytes:,} bytes"
            )
        return cls.from_bytes(
            resolved.read_bytes(),
            media_type=media_type,
            filename=resolved.name,
            detail=detail,
            max_bytes=max_bytes,
        )


TOKEN_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)


def normalize_token_usage(usage: Mapping[str, Any] | None = None) -> dict[str, int]:
    """Normalize provider usage into stable counters for storage and display."""
    aliases = {
        "prompt_tokens": "input_tokens",
        "completion_tokens": "output_tokens",
        "cached_tokens": "cache_read_tokens",
        "cache_tokens": "cache_read_tokens",
        "cache_creation_input_tokens": "cache_write_tokens",
    }
    counts: dict[str, int] = {}
    for key, value in (usage or {}).items():
        canonical = aliases.get(str(key), str(key))
        if isinstance(value, int) and not isinstance(value, bool):
            counts[canonical] = max(0, value)
    for key in TOKEN_USAGE_KEYS:
        counts.setdefault(key, 0)
    raw_total = (usage or {}).get("total_tokens")
    if not isinstance(raw_total, int) or isinstance(raw_total, bool):
        counts["total_tokens"] = counts["input_tokens"] + counts["output_tokens"]
    return counts


@dataclass(frozen=True)
class ToolCall:
    """A model request to run one tool with decoded arguments."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantMessage:
    """Text and tool calls generated by a model."""

    text: str | None = None
    reasoning: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    provider_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.usage = normalize_token_usage(self.usage)


@dataclass(frozen=True)
class View:
    """A frontend renderer name and its JSON props."""

    name: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolOutput:
    """A tool return value that carries model-visible content and a UI view."""

    content: Any
    view: View | None = None


@dataclass
class ToolResultMessage:
    """The result of one tool call."""

    call_id: str
    name: str
    content: str
    status: Literal["completed", "denied", "not_started", "failed", "unknown"] = "completed"
    view: View | None = None


Message = SystemMessage | UserMessage | AssistantMessage | ToolResultMessage


@dataclass(frozen=True)
class PendingApproval:
    """A validated tool call waiting for human approval."""

    call: ToolCall
    args: BaseModel
    reason: str
    view: View | None = None


@dataclass(frozen=True)
class ToolSpec:
    """The wire description of one tool: name, description, and JSON schema."""

    name: str
    description: str
    parameters: dict[str, Any]

    @classmethod
    def from_model(cls, name: str, description: str, model: type[BaseModel]) -> ToolSpec:
        """Build a spec from a pydantic input model."""
        return cls(name=name, description=description, parameters=model.model_json_schema())

    def to_openai(self) -> dict[str, Any]:
        """Return the chat completions function shape."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ModelRequest:
    """Everything one model call needs: messages, tools, and options."""

    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class Budget:
    """A shared limit on model calls."""

    max_model_calls: int
    used: int = 0

    def spend(self) -> bool:
        """Charge one model call. Return False when the budget is exhausted."""
        if self.used >= self.max_model_calls:
            return False
        self.used += 1
        return True


def _view_to_dict(view: View | None) -> dict[str, Any] | None:
    if view is None:
        return None
    return {"name": view.name, "props": copy.deepcopy(view.props)}


def _view_from_dict(payload: dict[str, Any] | None) -> View | None:
    if payload is None:
        return None
    return View(name=payload["name"], props=copy.deepcopy(payload.get("props", {})))


def message_to_dict(m: Message) -> dict[str, Any]:
    """Convert one message to a JSON-ready dictionary."""
    if isinstance(m, SystemMessage):
        return {"type": "system", "content": m.content}
    if isinstance(m, UserMessage):
        payload: dict[str, Any] = {"type": "user", "content": m.content}
        if m.images:
            payload["images"] = [
                {"url": image.url, "detail": image.detail, "filename": image.filename}
                for image in m.images
            ]
        return payload
    if isinstance(m, AssistantMessage):
        return {
            "type": "assistant",
            "text": m.text,
            "reasoning": m.reasoning,
            "tool_calls": [
                {"id": c.id, "name": c.name, "arguments": copy.deepcopy(c.arguments)}
                for c in m.tool_calls
            ],
            "stop_reason": m.stop_reason,
            "usage": copy.deepcopy(m.usage),
            "provider_data": copy.deepcopy(m.provider_data),
        }
    if isinstance(m, ToolResultMessage):
        return {
            "type": "tool_result",
            "call_id": m.call_id,
            "name": m.name,
            "content": m.content,
            "status": m.status,
            "view": _view_to_dict(m.view),
        }
    raise ValueError(f"unknown message: {type(m).__name__}")


def message_from_dict(d: dict[str, Any]) -> Message:
    """Read back a dict written by `message_to_dict`."""
    kind = d.get("type")
    if kind == "system":
        return SystemMessage(content=d["content"])
    if kind == "user":
        return UserMessage(
            content=d["content"],
            images=[
                ImageInput(
                    url=image["url"],
                    detail=image.get("detail", "auto"),
                    filename=image.get("filename"),
                )
                for image in d.get("images", [])
            ],
        )
    if kind == "assistant":
        return AssistantMessage(
            text=d.get("text"),
            reasoning=d.get("reasoning"),
            tool_calls=[
                ToolCall(
                    id=c["id"],
                    name=c["name"],
                    arguments=copy.deepcopy(c.get("arguments", {})),
                )
                for c in d.get("tool_calls", [])
            ],
            stop_reason=d.get("stop_reason"),
            usage=copy.deepcopy(d.get("usage", {})),
            provider_data=copy.deepcopy(d.get("provider_data", {})),
        )
    if kind == "tool_result":
        return ToolResultMessage(
            call_id=d["call_id"],
            name=d["name"],
            content=d["content"],
            status=d.get("status", "completed"),
            view=_view_from_dict(d.get("view")),
        )
    raise ValueError(f"unknown message type: {kind!r}")
