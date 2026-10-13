"""Text summary structure, trusted references, and bounded request indexes."""

import json
from contextlib import asynccontextmanager
from math import inf

import pytest

from harness import (
    Agent,
    AssistantMessage,
    Budget,
    CompactionConfig,
    ContextMemory,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from harness.compression_policy import ContextCompressor
from harness.lean_context import LeanModel
from harness.summary_references import ANCHOR_HEADING, reference_state, render_reference_index
from harness.testing import FakeModel
from harness.types import ModelRequest, message_to_dict
from tests.test_bounded_context import transcript

HEADINGS = [
    "Historical Task Snapshot",
    "Goal",
    "Constraints & Preferences",
    "Completed Actions",
    "Active State",
    "Blocked",
    "Key Decisions",
    "Errors & Fixes",
    "Resolved Questions",
    "Relevant Files",
    "Critical Context",
    "Detailed Session Log (oldest first)",
]
SUMMARY = "\n\n".join("## " + heading + "\nNone." for heading in HEADINGS)


@pytest.mark.parametrize("previous", ["", SUMMARY])
def test_fresh_and_iterative_prompts_use_the_same_text_template(previous):
    policy = ContextCompressor(100000, previous=previous)
    prompt = policy._build_summary_prompt("Evidence.", 2000, None, "", True)
    positions = [prompt.rindex("## " + heading) for heading in HEADINGS]
    assert positions == sorted(positions)
    assert "## Pruned Skills" in prompt
    assert "JSON" not in prompt and "json_schema" not in prompt
    assert bool("PREVIOUS SUMMARY:" in prompt) == bool(previous)


async def test_text_summary_cannot_replace_mechanical_identifiers_or_unknown_outcomes():
    history = transcript()
    history[10:10] = [
        AssistantMessage(tool_calls=[ToolCall("write-17", "save", {"operation_id": "op-17"})]),
        ToolResultMessage("write-17", "save", '{"source_ids":["source-exact"]}', "unknown"),
        UserMessage("Check #7 in src/theos/runtime/context.py at commit abc1234."),
    ]
    original = [message_to_dict(m) for m in history]
    ids = [f"S{i:032x}" for i in range(350)]
    response = SUMMARY + "\n\n" + ANCHOR_HEADING + "\nFAKE-RESEARCH-ID\n"
    auxiliary = FakeModel([AssistantMessage(response)])

    @asynccontextmanager
    async def summaries():
        yield auxiliary

    memory = ContextMemory()
    main = FakeModel([AssistantMessage("Useful answer.")])
    policy = CompactionConfig(
        "",
        summary_model=summaries,
        summary_context=lambda: {"records": [{"id": ref} for ref in ids]},
    )
    await Agent(main, context_window=100000, compaction=policy).run(
        history, memory=memory, budget=Budget(inf)
    )
    assert isinstance(memory.summary, str) and memory.summary.count(ANCHOR_HEADING) == 1
    assert "FAKE-RESEARCH-ID" not in memory.summary
    assert memory.state["references"]["record_ids"] == ids
    exact = {anchor["exact"] for anchor in memory.state["references"]["anchors"]}
    assert {"write-17", "op-17", "source-exact", "#7", "abc1234"} <= exact
    assert "UNKNOWN action: save call_id=write-17" in memory.summary
    assert [message_to_dict(m) for m in history[:-1]] == original
    assert not auxiliary.requests[0].tools
    assert "response_format" not in auxiliary.requests[0].options
    assert ContextMemory.from_dict(memory.to_dict()) == memory


def test_full_reference_state_survives_bounded_rendering_and_route_changes():
    history = [UserMessage("https://example.org/source src/harness/lean_context.py")]
    ids = [f"S{i:032x}" for i in range(350)]
    references = reference_state(history, {"records": [{"id": i} for i in ids]}, [])
    rendered = render_reference_index(references, 700, lambda text: text)
    assert len(rendered) <= 700 and "bounded index" in rendered
    assert all(i in references["record_ids"] for i in ids)
    assert sum(i in rendered for i in ids) < len(ids)
    memory = ContextMemory(state={"references": references, "route": "old/model"})
    restored = ContextMemory.from_dict(json.loads(json.dumps(memory.to_dict())))
    LeanModel(FakeModel([]), 100000, CompactionConfig(""), restored, history, Budget(inf))
    assert restored.state["references"] == references
    later = reference_state(history, {}, restored.state["references"]["record_ids"])
    assert later["record_ids"] == ids


def test_reference_rendering_redacts_credentials_without_changing_the_originals():
    from harness.compression_policy import _redact_compaction_text

    history = [UserMessage("https://example.org/query?api_key=demo-value")]
    references = reference_state(history, {}, [])
    rendered = render_reference_index(references, 2000, _redact_compaction_text)
    assert "demo-value" not in rendered
    assert any("demo-value" in a["exact"] for a in references["anchors"])


@pytest.mark.parametrize("mode,session_log", [("lean", True), ("current", False)])
@pytest.mark.parametrize("users", [1, 3])
async def test_tail_mode_changes_the_prompt_without_removing_exact_references(
    mode, session_log, users
):
    auxiliary = FakeModel([AssistantMessage("## Goal\nFinish the report.")])

    @asynccontextmanager
    async def summaries():
        yield auxiliary

    history = transcript()
    history[11] = UserMessage("Preserve src/harness/lean_context.py.")
    model = LeanModel(
        FakeModel([]),
        100000,
        CompactionConfig("", summary_model=summaries, tail_mode=mode, min_tail_user_messages=users),
        ContextMemory(),
        history,
        Budget(inf),
    )
    events = [event async for event in model.prepare(ModelRequest(history), force=True)]
    assert any(isinstance(event, ModelRequest) for event in events)
    assert ("Detailed Session Log" in auxiliary.requests[0].messages[0].content) == session_log
    assert ANCHOR_HEADING in model.memory.summary
    assert "src/harness/lean_context.py" in model.memory.summary
    prepared = next(event for event in events if isinstance(event, ModelRequest))
    recent = [m for m in history if isinstance(m, UserMessage)][-users:]
    assert all(m in prepared.messages for m in recent)


def test_source_indexes_ignore_provider_replay_reasoning_and_system_instructions():
    history = [
        SystemMessage("https://system.example.org/private"),
        AssistantMessage(
            "https://visible.example.org/evidence",
            reasoning="https://reasoning.example.org/private",
            provider_data={"opaque": "https://provider.example.org/private"},
        ),
    ]
    references = reference_state(history, {}, [])
    urls = [a["exact"] for a in references["anchors"] if a["kind"] == "url"]
    assert urls == ["https://visible.example.org/evidence"]
