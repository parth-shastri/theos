"""Provider services stage only their filtered, normalized read results."""

import json

from theos.services.health.imports import SUMMARY_VERSION

from .conftest import call_tool


async def test_large_gmail_thread_stages_filtered_tool_result(runtime):
    messages = [
        {
            "id": f"message-{index}",
            "threadId": "thread-large",
            "snippet": "s" * 400,
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.org"},
                    {"name": "Subject", "value": "s" * 500},
                ]
            },
        }
        for index in range(50)
    ]

    async def request(_owner, _method, path, **_kwargs):
        assert path == "threads/thread-large"
        return {"messages": messages}

    runtime.gmail.request = request
    staged = {}

    async def save_result(name, content):
        staged.update(name=name, content=content)
        return {"path": "/tmp/theos-results/thread.json"}

    result = await call_tool(
        runtime.gmail.tools("alice", result_stager=save_result),
        "gmail_get_thread",
        thread_id="thread-large",
        message_limit=50,
    )

    assert result["result_file"] == "/tmp/theos-results/thread.json"
    assert staged["name"] == "gmail_get_thread"
    assert len(json.loads(staged["content"])["messages"]) == 50


async def test_large_health_detail_stages_filtered_tool_result(runtime):
    snapshot = {
        "schema_version": SUMMARY_VERSION,
        "from": "2026-10-01T00:00:00+00:00",
        "to": "2026-10-02T00:00:00+00:00",
        "days": [
            {
                "date": "2026-10-01",
                "sleep": [{"stage": f"stage-{index}", "minutes": index} for index in range(500)],
                "unselected_provider_field": "must not be staged",
            }
        ],
    }
    runtime.db.put_record("alice", "health", "summary", snapshot)
    staged = {}

    async def save_result(name, content):
        staged.update(name=name, content=content)
        return {"path": "/tmp/theos-results/health.json"}

    result = await call_tool(
        runtime.health.tools("alice", result_stager=save_result),
        "get_health_summary",
        start_date="2026-10-01",
        end_date="2026-10-01",
        metrics=["sleep"],
    )

    assert result["result_file"] == "/tmp/theos-results/health.json"
    assert staged["name"] == "get_health_summary"
    contents = json.loads(staged["content"])
    assert len(contents["days"][0]["sleep"]) == 500
    assert "unselected_provider_field" not in staged["content"]
