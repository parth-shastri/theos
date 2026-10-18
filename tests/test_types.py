"""Tests for harness.types: message serialization, tool specs, and budgets."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field

from harness.types import (
    AssistantMessage,
    Budget,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    View,
    message_from_dict,
    message_to_dict,
)


def round_trip(message):
    """Serialize a message, force it through JSON, and read it back."""
    payload = json.loads(json.dumps(message_to_dict(message)))
    return payload, message_from_dict(payload)


def test_system_message_round_trip():
    payload, restored = round_trip(SystemMessage(content="be brief"))
    assert payload == {"type": "system", "content": "be brief"}
    assert restored == SystemMessage(content="be brief")


def test_user_message_round_trip():
    payload, restored = round_trip(UserMessage(content="where is my order"))
    assert payload == {"type": "user", "content": "where is my order"}
    assert restored == UserMessage(content="where is my order")


def test_assistant_message_round_trip_with_tool_calls():
    message = AssistantMessage(
        text="looking it up",
        reasoning="the user wants order status",
        tool_calls=[ToolCall(id="call_1", name="get_order", arguments={"order_id": "A1"})],
        stop_reason="tool_calls",
        usage={"input_tokens": 12, "output_tokens": 3},
        provider_data={"anthropic": {"model": "claude-opus-5", "content": [{"type": "text"}]}},
    )
    payload, restored = round_trip(message)
    assert payload["type"] == "assistant"
    assert payload["tool_calls"] == [
        {"id": "call_1", "name": "get_order", "arguments": {"order_id": "A1"}}
    ]
    assert payload["provider_data"] == {
        "anthropic": {"model": "claude-opus-5", "content": [{"type": "text"}]}
    }
    assert restored == message
    assert isinstance(restored.tool_calls[0], ToolCall)


def test_assistant_message_defaults_round_trip():
    payload, restored = round_trip(AssistantMessage(text="done"))
    assert payload["tool_calls"] == []
    assert payload["reasoning"] is None
    assert restored == AssistantMessage(text="done")


def test_tool_result_message_round_trip_with_view():
    message = ToolResultMessage(
        call_id="call_1",
        name="get_order",
        content='{"status": "shipped"}',
        status="completed",
        view=View("order-card", {"order": {"id": "A1"}, "highlight": "status"}),
    )
    payload, restored = round_trip(message)
    assert payload["type"] == "tool_result"
    assert payload["status"] == "completed"
    assert payload["view"] == {
        "name": "order-card",
        "props": {"order": {"id": "A1"}, "highlight": "status"},
    }
    assert restored == message
    assert isinstance(restored.view, View)


def test_tool_result_message_without_view_serializes_null():
    message = ToolResultMessage(call_id="c", name="t", content="x", status="failed")
    payload, restored = round_trip(message)
    assert payload["view"] is None
    assert restored == message
    assert restored.view is None


def test_message_from_dict_rejects_unknown_type():
    with pytest.raises(ValueError):
        message_from_dict({"type": "widget", "content": "x"})


def test_message_to_dict_does_not_alias_mutable_fields():
    call = ToolCall(id="c", name="t", arguments={"k": "v"})
    message = AssistantMessage(tool_calls=[call], usage={"input_tokens": 1})
    payload = message_to_dict(message)
    payload["tool_calls"][0]["arguments"]["k"] = "changed"
    payload["usage"]["input_tokens"] = 99
    assert call.arguments == {"k": "v"}
    assert message.usage == {
        "input_tokens": 1,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 1,
    }


class OrderQuery(BaseModel):
    order_id: str = Field(description="The order identifier")
    verbose: bool = False


def test_tool_spec_to_openai_uses_the_chat_completions_shape():
    spec = ToolSpec.from_model("get_order", "Return one order.", OrderQuery)
    assert spec.to_openai() == {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "Return one order.",
            "parameters": OrderQuery.model_json_schema(),
        },
    }


def test_budget_spend_stops_at_the_maximum():
    budget = Budget(max_model_calls=2)
    assert budget.spend() is True
    assert budget.spend() is True
    assert budget.used == 2
    assert budget.spend() is False
    assert budget.used == 2


def test_budget_with_zero_calls_is_exhausted_immediately():
    budget = Budget(max_model_calls=0)
    assert budget.spend() is False
    assert budget.used == 0
