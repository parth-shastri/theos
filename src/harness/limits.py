"""Generic bounds for model responses before they reach tool execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from harness.types import AssistantMessage, ToolCall

__all__ = [
    "DEFAULT_EXECUTION_LIMITS",
    "ExecutionLimits",
    "HarnessError",
    "HarnessErrorCode",
    "validate_assistant_message",
    "validate_tool_arguments",
]


class HarnessErrorCode(StrEnum):
    CONTEXT_LIMIT_EXCEEDED = "context_limit_exceeded"
    MALFORMED_MODEL_OUTPUT = "malformed_model_output"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    DUPLICATE_TOOL_CALL_ID = "duplicate_tool_call_id"
    TOO_MANY_TOOL_CALLS = "too_many_tool_calls"
    TOOL_ARGUMENTS_TOO_LARGE = "tool_arguments_too_large"
    TOOL_ARGUMENTS_TOO_DEEP = "tool_arguments_too_deep"
    BATCH_SIZE_EXCEEDED = "batch_size_exceeded"


class HarnessError(ValueError):
    """A generated response exceeded a configured harness limit."""

    def __init__(self, code: HarnessErrorCode, message: str | None = None) -> None:
        super().__init__(message or code.value)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ExecutionLimits:
    """Argument bounds and the size of each tool execution batch."""

    max_output_bytes: int | None = None
    max_argument_bytes: int = 64 * 1024
    max_nesting_depth: int = 32
    tool_batch_size: int = 16
    max_batch_size: int = 64

    def __post_init__(self) -> None:
        if (
            min(
                self.max_output_bytes if self.max_output_bytes is not None else 0,
                self.max_argument_bytes,
                self.max_nesting_depth,
                self.max_batch_size,
            )
            < 0
        ):
            raise ValueError("execution limits cannot be negative")
        if self.tool_batch_size < 1:
            raise ValueError("tool_batch_size must be positive")


DEFAULT_EXECUTION_LIMITS = ExecutionLimits()


def _shape(value: Any) -> tuple[int, int]:
    """Return maximum JSON nesting depth and list size without recursion."""
    maximum_depth = 0
    maximum_list = 0
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if isinstance(current, dict):
            child_depth = depth + 1
            maximum_depth = max(maximum_depth, child_depth)
            pending.extend((child, child_depth) for child in current.values())
        elif isinstance(current, list):
            child_depth = depth + 1
            maximum_depth = max(maximum_depth, child_depth)
            maximum_list = max(maximum_list, len(current))
            pending.extend((child, child_depth) for child in current)
    return maximum_depth, maximum_list


def validate_assistant_message(
    message: AssistantMessage,
    limits: ExecutionLimits = DEFAULT_EXECUTION_LIMITS,
    *,
    validate_arguments: bool = True,
) -> None:
    """Check response identity. Executors can answer argument errors per call."""
    if (message.text is not None and not isinstance(message.text, str)) or (
        message.reasoning is not None and not isinstance(message.reasoning, str)
    ):
        raise HarnessError(HarnessErrorCode.MALFORMED_MODEL_OUTPUT)
    if message.tool_calls and message.stop_reason == "length":
        raise HarnessError(HarnessErrorCode.MALFORMED_MODEL_OUTPUT)
    output_bytes = len((message.text or "").encode("utf-8"))
    output_bytes += len((message.reasoning or "").encode("utf-8"))
    if limits.max_output_bytes is not None and output_bytes > limits.max_output_bytes:
        raise HarnessError(HarnessErrorCode.OUTPUT_LIMIT_EXCEEDED)

    ids: set[str] = set()
    for call in message.tool_calls:
        if (
            not isinstance(call.id, str)
            or not call.id.strip()
            or not isinstance(call.name, str)
            or not call.name.strip()
            or not isinstance(call.arguments, dict)
        ):
            raise HarnessError(HarnessErrorCode.MALFORMED_MODEL_OUTPUT)
        if call.id in ids:
            raise HarnessError(HarnessErrorCode.DUPLICATE_TOOL_CALL_ID)
        ids.add(call.id)
        if validate_arguments:
            validate_tool_arguments(call, limits)


def validate_tool_arguments(call: ToolCall, limits: ExecutionLimits) -> None:
    """Bound one call before schema validation, approval, or execution."""
    try:
        argument_bytes = len(
            json.dumps(
                call.arguments,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise HarnessError(
            HarnessErrorCode.MALFORMED_MODEL_OUTPUT,
            "Tool arguments must contain valid JSON values.",
        ) from error
    if argument_bytes > limits.max_argument_bytes:
        raise HarnessError(
            HarnessErrorCode.TOOL_ARGUMENTS_TOO_LARGE,
            f"Tool arguments exceed {limits.max_argument_bytes} bytes. Reduce the argument text.",
        )
    depth, largest_list = _shape(call.arguments)
    if depth > limits.max_nesting_depth:
        raise HarnessError(
            HarnessErrorCode.TOOL_ARGUMENTS_TOO_DEEP,
            f"Tool arguments exceed {limits.max_nesting_depth} nested levels. Use a shallower structure.",
        )
    if largest_list > limits.max_batch_size:
        raise HarnessError(
            HarnessErrorCode.BATCH_SIZE_EXCEEDED,
            f"An argument list exceeds {limits.max_batch_size} items. Split it into smaller calls.",
        )
