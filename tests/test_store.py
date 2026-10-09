"""Tests for harness.store: the Store protocol, MemoryStore, and JsonlStore."""

from __future__ import annotations

import json
from pathlib import Path

from harness.store import JsonlStore, MemoryStore, Store
from harness.types import (
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    View,
    message_to_dict,
)


def sample_history() -> list:
    call = ToolCall(id="c1", name="get_order", arguments={"order_id": "A1"})
    return [
        SystemMessage(content="be brief"),
        UserMessage(content="where is order A1"),
        AssistantMessage(text="looking", tool_calls=[call], stop_reason="tool_calls"),
        ToolResultMessage(
            call_id="c1",
            name="get_order",
            content='{"status": "shipped"}',
            view=View("order-card", {"order_id": "A1"}),
        ),
        AssistantMessage(text="it shipped", stop_reason="stop"),
    ]


def test_memory_store_and_jsonl_store_satisfy_the_protocol():
    assert isinstance(MemoryStore(), Store)
    assert isinstance(JsonlStore(Path(".")), Store)


async def test_memory_store_returns_none_for_an_unknown_key():
    assert await MemoryStore().load("missing") is None


async def test_memory_store_round_trip():
    store = MemoryStore()
    history = sample_history()
    await store.save("thread-1", history)
    assert await store.load("thread-1") == history


async def test_memory_store_does_not_alias_the_saved_list():
    store = MemoryStore()
    history = sample_history()
    await store.save("thread-1", history)
    history.append(UserMessage(content="and now"))
    loaded = await store.load("thread-1")
    assert len(loaded) == 5


async def test_jsonl_store_returns_none_when_the_file_is_absent(tmp_path: Path):
    assert await JsonlStore(tmp_path).load("thread-1") is None


async def test_jsonl_store_round_trip_keeps_views(tmp_path: Path):
    store = JsonlStore(tmp_path)
    history = sample_history()
    await store.save("thread-1", history)
    loaded = await store.load("thread-1")
    assert loaded == history
    assert loaded[3].view == View("order-card", {"order_id": "A1"})


async def test_jsonl_store_writes_one_json_object_per_line(tmp_path: Path):
    store = JsonlStore(tmp_path)
    history = sample_history()
    await store.save("thread-1", history)
    path = tmp_path / "thread-1.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(history)
    assert [json.loads(line) for line in lines] == [message_to_dict(m) for m in history]


async def test_jsonl_store_save_overwrites_and_leaves_no_temporary_file(tmp_path: Path):
    store = JsonlStore(tmp_path)
    await store.save("thread-1", sample_history())
    await store.save("thread-1", [UserMessage(content="fresh")])
    assert await store.load("thread-1") == [UserMessage(content="fresh")]
    assert [p.name for p in tmp_path.iterdir()] == ["thread-1.jsonl"]


async def test_jsonl_store_creates_the_directory_on_save(tmp_path: Path):
    store = JsonlStore(tmp_path / "sessions")
    await store.save("thread-1", [UserMessage(content="hi")])
    assert (tmp_path / "sessions" / "thread-1.jsonl").exists()


async def test_jsonl_store_saves_an_empty_history(tmp_path: Path):
    store = JsonlStore(tmp_path)
    await store.save("thread-1", [])
    assert await store.load("thread-1") == []
