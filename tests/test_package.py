"""Tests for the harness package surface and its import order."""

from __future__ import annotations

import subprocess
import sys

import harness


def test_public_names_are_re_exported():
    expected = {
        "ALLOW",
        "ASK",
        "DENY",
        "Agent",
        "AssistantMessage",
        "Budget",
        "Capabilities",
        "ChatModel",
        "Decision",
        "Emit",
        "Event",
        "GenerationComplete",
        "Hooks",
        "Inbox",
        "Instructions",
        "JsonlStore",
        "MemoryStore",
        "Message",
        "Model",
        "ModelEvent",
        "ModelCalled",
        "ModelRequest",
        "ModelResponded",
        "PendingApproval",
        "RunContext",
        "RunEvent",
        "Store",
        "SystemMessage",
        "TextDelta",
        "ToolCall",
        "ToolFinished",
        "ToolOutput",
        "ToolResultMessage",
        "ToolSpec",
        "ToolStarted",
        "TurnResult",
        "TurnFinished",
        "UserMessage",
        "View",
        "allow_all",
        "collect_model_stream",
        "collect_run_stream",
        "default_estimate",
        "default_estimate_tokens",
        "message_from_dict",
        "message_to_dict",
        "require_approval",
        "run_turn",
        "run_turn_stream",
        "select_context",
        "unanswered_calls",
    }
    assert expected <= set(harness.__all__)
    import harness.hooks as hooks
    import harness.tools as tools
    from harness.types import PendingApproval

    assert hooks.PendingApproval is harness.PendingApproval is PendingApproval
    for name in ("OutcomeUnknown", "Tool", "execute_tool", "execute_tools", "tool"):
        assert name in harness.__all__
        assert getattr(harness, name) is getattr(tools, name)
    for name in harness.__all__:
        assert getattr(harness, name) is not None


def test_importing_harness_loads_no_provider_sdk():
    code = (
        "import sys, harness, harness.hooks, harness.store, harness.agent; "
        "print([m for m in sys.modules if m.split('.')[0] "
        "in ('openai', 'anthropic', 'google')])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
