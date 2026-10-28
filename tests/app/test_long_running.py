"""Check Theos defaults independently of the optional bounded harness."""

import json

import pytest

from harness import (
    AssistantMessage,
    RunContext,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    history_tools,
    tool,
)
from harness.testing import FakeModel
from tests.context_fixtures import long_history
from theos.runtime.budgets import TurnBudget

from .conftest import collect
from .test_recovery import install_read, read_call, session, use_models


def test_disabled_allocations_still_count_calls(settings):
    settings.max_model_calls = 1
    settings.max_compaction_calls = 0
    allowances = TurnBudget(settings, enforce=False)
    for _ in range(100):
        assert allowances.research.spend()
        assert allowances.compaction.spend()
        assert allowances.recovery.spend()
    assert allowances.total.used == 300
    assert allowances.attributes()["theos.budget.total.limit"] == -1
    assert allowances.attributes()["theos.budget.enforced"] is False
    assert settings.max_model_calls == 1 and settings.max_compaction_calls == 0


async def test_default_parent_passes_configured_calls_and_deadline(runtime):
    assert not runtime.enforce_budgets
    runtime.settings.max_model_calls = 1
    runtime.settings.max_compaction_calls = 0
    runtime.settings.turn_timeout = 0
    runtime.settings.context_tokens = 100_000
    calls = await install_read(runtime)
    model = FakeModel(
        [read_call(str(i)) for i in range(35)] + [AssistantMessage("Complete findings.")]
    )
    use_models(runtime, model)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Read the evidence."))
    assert events[-1]["status"] == "completed", events[-1]
    assert len(model.requests) == 36 and len(calls) == 35
    assert runtime.db.one("SELECT COUNT(*) n FROM usage")["n"] == 36


async def test_default_delegates_ignore_configured_calls_and_time(runtime, monkeypatch):
    from theos.runtime import tools

    from .test_recovery import delegate_call

    runtime.settings.max_model_calls = 1
    runtime.settings.delegate_max_model_calls = 1
    runtime.settings.turn_timeout = 0
    runtime.settings.context_tokens = 100_000
    monkeypatch.setattr(tools, "DELEGATE_SECONDS", -1)

    @tool
    async def read_reference():
        """Read one saved reference."""
        return "A verified fact."

    monkeypatch.setattr(tools, "information_tools", lambda *args: [read_reference])
    parent = FakeModel([delegate_call(), AssistantMessage("Combined findings.")])
    children = [
        FakeModel(
            [
                *[
                    AssistantMessage(tool_calls=[ToolCall(f"{i}-{j}", "read_reference", {})])
                    for j in range(6)
                ],
                AssistantMessage("Complete findings."),
            ]
        )
        for i in range(2)
    ]
    use_models(runtime, parent, *children)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Compare two topics."))
    assert events[-1]["status"] == "completed", events[-1]
    assert all(len(child.requests) == 7 for child in children)


async def test_context_errors_retry_but_never_show_rejected_stream(runtime):
    runtime.settings.context_tokens = 1000000
    main = FakeModel(
        [
            RuntimeError("maximum context length exceeded"),
            AssistantMessage("Evidence and task retained."),
            AssistantMessage("Useful response."),
        ]
    )
    use_models(runtime, main)
    row = session(runtime)
    runtime.db.save_history("alice", row["id"], long_history())
    events = await collect(runtime.start("alice", row["id"], "Explain this."))
    assert events[-1]["status"] == "completed" and len(main.requests) == 3
    from harness.context_size import request_size

    assert request_size(main.requests[2]) < request_size(main.requests[0])
    assert not any("partial" in event.get("text", "") for event in events)


async def test_irreducible_context_error_never_claims_a_useful_answer(runtime):
    runtime.settings.context_tokens = 100000
    model = FakeModel([RuntimeError("maximum context length exceeded")])
    use_models(runtime, model)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Explain this."))
    assert events[-1]["status"] == "failed"
    from harness.context_size import request_size

    sizes = [request_size(request) for request in model.requests]
    assert len(sizes) == 1
    assert "context" in runtime.db.load_history("alice", row["id"])[-1].text


async def test_history_tools_read_original_pages_without_cross_agent_access():
    tools = {t.name: t for t in history_tools()}
    text = "invoice-123 " + "x" * 20_000 + " AMOUNT 123.45"
    ctx = RunContext(
        None, history=[UserMessage("Task"), ToolResultMessage("mail-1", "gmail", text)]
    )
    read = tools["history_read"]
    args = read.input_model.model_validate({"call_id": "mail-1", "offset": 20_000, "limit": 1000})
    result = await read.execute(args, ctx)
    assert "AMOUNT 123.45" in result["content"] and result["next_offset"] is None
    with pytest.raises(ValueError):
        await read.execute(args, RunContext(None, history=[UserMessage("Another agent.")]))
    search = tools["history_search"]
    result = await search.execute(search.input_model.model_validate({"query": "invoice-123"}), ctx)
    assert result["matches"][0]["message_index"] == 1
    assert len(json.dumps(result)) < 1000


async def test_gmail_sized_results_get_previews_with_zero_configured_allowance(runtime):
    import base64
    import random

    runtime.settings.max_model_calls = 1
    runtime.settings.max_compaction_calls = 0
    runtime.settings.context_tokens = 100_000
    evidence = (
        "Verified invoice USD 42.00. "
        + base64.b64encode(random.Random(7).randbytes(610_000)).decode()
    )
    calls = await install_read(runtime, evidence)
    row = session(runtime)
    model = FakeModel(
        [
            read_call("mail-batch-1"),
            AssistantMessage("The first saved source is available for comparison."),
            read_call("mail-batch-2"),
            AssistantMessage("Both saved sources are available for comparison."),
            AssistantMessage("Two verified invoices of USD 42.00 total USD 84.00."),
        ]
    )
    use_models(runtime, model)
    events = await collect(runtime.start("alice", row["id"], "Analyze last month's expenses."))
    assert events[-1]["status"] == "completed", events[-1]
    assert len(model.requests) == 5 and len(calls) == 2
    saved = runtime.db.load_history("alice", row["id"])
    assert [m.content for m in saved if isinstance(m, ToolResultMessage)] == [evidence, evidence]
    for request in [item for item in model.requests if item.tools][1:]:
        results = [m.content for m in request.messages if isinstance(m, ToolResultMessage)]
        assert all("source_id" in text and len(text) >= 1000 for text in results)
    # Summary requests use the conversation model and share its usage accounting.
    assert runtime.db.one("SELECT COUNT(*) n FROM usage")["n"] == len(model.requests)


@pytest.mark.parametrize("enforce", [False, True])
async def test_recovery_policy_is_independent_of_call_budgets(runtime, enforce):
    from theos.runtime import context

    runtime.enforce_budgets = enforce
    row = session(runtime)
    policy = context.compaction(runtime, row, await context.capacity(runtime, row))
    assert policy.prompt and policy.on_commit


async def test_history_tools_search_and_read_the_raw_mime_payload():
    import base64

    from harness.tools import execute_tool

    body = "<style>ignore 99999</style><p>Invoice total USD 37.42</p>"
    encoded = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    original = json.dumps(
        {
            "id": "receipt",
            "payload": {"mimeType": "text/html", "headers": [], "body": {"data": encoded}},
        }
    )
    ctx = RunContext(None, history=[ToolResultMessage("receipt-call", "connector_read", original)])
    read = await execute_tool(
        ToolCall("read", "history_read", {"message_index": 0}),
        history_tools(),
        ctx=ctx,
    )
    decoded = json.loads(read.content)
    assert decoded["content"] == original
    search = await execute_tool(
        ToolCall("search", "history_search", {"query": "37.42"}),
        history_tools(),
        ctx=ctx,
    )
    assert json.loads(search.content)["matches"] == []
    raw_search = await execute_tool(
        ToolCall("search-raw", "history_search", {"query": encoded[:20]}),
        history_tools(),
        ctx=ctx,
    )
    assert json.loads(raw_search.content)["matches"][0]["message_index"] == 0
    assert ctx.history[0].content == original


async def test_history_inventory_pages_original_sources_without_retrieval_duplicates():
    from harness.tools import execute_tool

    history = [
        ToolResultMessage("a", "connector_read", "Invoice alpha"),
        ToolResultMessage("copy", "history_read", "Invoice alpha"),
        ToolResultMessage("search-copy", "history_search", "Invoice alpha"),
        ToolResultMessage("b", "connector_read", "Invoice beta"),
    ]
    ctx = RunContext(None, history=history)
    first = await execute_tool(
        ToolCall("inventory", "history_search", {"query": "", "limit": 1}), history_tools(), ctx=ctx
    )
    data = json.loads(first.content)
    assert data["matches"][0]["message_index"] == 0
    second = await execute_tool(
        ToolCall("next", "history_search", {"query": "", "start_index": data["next_index"]}),
        history_tools(),
        ctx=ctx,
    )
    assert [m["message_index"] for m in json.loads(second.content)["matches"]] == [3]
    searched = await execute_tool(
        ToolCall("lookup", "history_search", {"query": "Invoice"}), history_tools(), ctx=ctx
    )
    assert [m["message_index"] for m in json.loads(searched.content)["matches"]] == [0, 3]


async def test_history_search_does_not_match_its_own_query_arguments():
    from harness.tools import execute_tool

    ctx = RunContext(
        None,
        history=[
            AssistantMessage(
                tool_calls=[
                    ToolCall("old-query", "history_search", {"query": "invented-receipt-id"})
                ]
            ),
            ToolResultMessage("old-query", "history_search", '{"matches":[]}'),
        ],
    )
    result = await execute_tool(
        ToolCall("new-query", "history_search", {"query": "invented-receipt-id"}),
        history_tools(),
        ctx=ctx,
    )
    assert json.loads(result.content)["matches"] == []


async def test_repeated_retrieval_can_finish_without_a_fixed_call_cutoff(runtime):
    row = session(runtime)
    original = [
        UserMessage("Read an invoice."),
        AssistantMessage(tool_calls=[ToolCall("receipt", "connector_read", {})]),
        ToolResultMessage("receipt", "connector_read", "Verified invoice USD 37.42"),
    ]
    runtime.db.save_history("alice", row["id"], original)
    model = FakeModel(
        [
            AssistantMessage(tool_calls=[ToolCall(str(i), "history_read", {"message_index": 2})])
            for i in range(4)
        ]
        + [AssistantMessage("The verified invoice is USD 37.42.")]
    )
    use_models(runtime, model)
    events = await collect(runtime.start("alice", row["id"], "Report expenses."))
    assert events[-1]["status"] == "completed"
    answer = runtime.db.load_history("alice", row["id"])[-1].text
    assert "USD 37.42" in answer
    assert "model context" not in answer
    assert len(model.requests) == 5 and model.requests[-1].tools
