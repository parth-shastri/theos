"""Explicit research, evidence ownership, summary retention, and protected final calls."""

import json

import httpx
import pytest
from pydantic import SecretStr

from harness import (
    Agent,
    AssistantMessage,
    Budget,
    ContextMemory,
    RunContext,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from harness.testing import FakeModel
from harness.tools import execute_tool
from tests.context_fixtures import long_history
from theos.runtime import context, tools
from theos.runtime.budgets import TurnBudget
from theos.runtime.research_mode import explicit_request
from theos.services.research.store import valid_summary
from theos.services.research.tools import research_tools
from theos.storage.database import Database
from theos.transports.browser.app import create_app

from .conftest import call_tool, collect
from .test_recovery import use_models


@pytest.mark.parametrize(
    "text",
    [
        "What is deep research?",
        "Do deep research agents use summaries?",
        "Do not do deep research on this.",
        "The page says: run deep research on AI.",
        "Explain this normally.",
    ],
)
def test_mentions_and_negations_do_not_enable_research(text):
    assert explicit_request(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "/research AI scaling",
        "Deep research: AI scaling",
        "Please do deep research on AI scaling",
        "Start deep research: AI scaling",
    ],
)
def test_explicit_entry_points(text):
    assert explicit_request(text) == "AI scaling"


async def test_normal_turn_cannot_call_deep_research_or_create_records(runtime):
    row = runtime.db.create_session("alice", "test-model", "default")
    model = FakeModel(
        [
            AssistantMessage(tool_calls=[ToolCall("unavailable", "deep_research", {"tasks": []})]),
            AssistantMessage("Normal answer."),
        ]
    )
    use_models(runtime, model)
    await collect(runtime.start("alice", row["id"], "Explain deep research without running it."))
    assert not runtime.db.rows("SELECT * FROM research_runs")
    assert not any(t.name == "deep_research" for t in model.requests[0].tools)
    assert "unknown tool" in model.requests[1].messages[-1].content.lower()


async def test_explicit_mode_is_one_turn_and_persists_full_report(runtime):
    row = runtime.db.create_session("alice", "test-model", "default")
    report = "Full research report. " * 3000 + "REPORT END"
    deep = FakeModel([AssistantMessage(report)])
    normal = FakeModel([AssistantMessage("Ordinary follow-up.")])
    use_models(runtime, deep, normal)
    await collect(runtime.start("alice", row["id"], "Compare the evidence.", mode="deep_research"))
    await collect(runtime.start("alice", row["id"], "Thank you."))
    runs = runtime.research.runs("alice", row["id"])
    assert len(runs) == 1
    assert runtime.research.get("alice", row["id"], runs[0]["id"])["answer"] == report
    assert {"deep_research", "read_source", "save_research_note"} <= {
        t.name for t in deep.requests[0].tools
    }
    assert not {"deep_research", "read_source", "save_research_note"} & {
        t.name for t in normal.requests[0].tools
    }


async def test_named_brief_omits_unrelated_history_but_retains_selected_corrections(
    runtime, monkeypatch
):
    row = runtime.db.create_session("alice", "test-model", "default")
    history = [
        UserMessage("Only primary sources."),
        AssistantMessage("Unrelated content " * 1000),
        UserMessage("Compare AI forecasts."),
    ]
    child = FakeModel([AssistantMessage("Research findings.")])
    use_models(runtime, child)
    monkeypatch.setattr(tools, "information_tools", lambda *args: [])
    registry = await runtime.tools(row)
    delegate = next(t for t in registry if t.name == "delegate_tasks")
    args = delegate.input_model.model_validate(
        {
            "tasks": [
                {
                    "name": "forecast",
                    "task": "Check dates.",
                    "context": "Relevant source published in 2025.",
                    "requirements": ["Only primary sources."],
                }
            ]
        }
    )
    returned = await execute_tool(
        ToolCall("brief", "delegate_tasks", args.model_dump()),
        [delegate],
        ctx=RunContext(deps=None, history=history),
    )
    assert returned.status == "completed"
    encoded = str(child.requests[0].messages)
    assert "Only primary sources." in encoded
    assert "Relevant source published in 2025." in encoded
    assert "Unrelated content" not in encoded
    assert not runtime.research.runs("alice", row["id"])


async def test_deep_research_saves_child_transcript_and_search_evidence(runtime):
    row = runtime.db.create_session("alice", "test-model", "default")
    parent = FakeModel(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall(
                        "delegate",
                        "deep_research",
                        {
                            "tasks": [
                                {
                                    "name": "Sources",
                                    "task": "Compare the original sources.",
                                    "context": "AI forecasts",
                                }
                            ]
                        },
                    )
                ]
            ),
            AssistantMessage("Combined report."),
        ]
    )
    child = FakeModel(
        [
            AssistantMessage(
                tool_calls=[ToolCall("search", "web_search", {"query": "AI forecasts"})]
            ),
            AssistantMessage("Source has no publication date. https://example.com/source"),
        ]
    )
    runtime.settings.exa_key = SecretStr("test-key")

    def respond(request):
        if "/search" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": "https://example.com/source",
                            "text": "Original excerpt.",
                            "title": "Source",
                        }
                    ]
                },
            )
        return httpx.Response(503)

    runtime.http._transport = httpx.MockTransport(respond)
    use_models(runtime, parent, child)
    events = await collect(runtime.start("alice", row["id"], "AI forecasts", mode="deep_research"))
    assert events[-1]["status"] == "completed"
    runs = runtime.research.runs("alice", row["id"])
    assert len(runs) == 2
    researcher = next(r for r in runs if r["parent"])
    saved = runtime.research.get("alice", row["id"], researcher["id"])
    assert "Original excerpt." in saved["history"]
    assert saved["answer"].endswith("https://example.com/source")
    evidence = runtime.research.items("alice", row["id"], researcher["id"])
    source = next(item for item in evidence if item["kind"] == "source")
    assert source["content"]["text"] == "Original excerpt."
    assert source["id"].startswith("S")
    assert "source_ids" in child.requests[-1].messages[-1].content


async def test_full_source_and_notes_are_retrievable_without_text_cuts(runtime):
    row = runtime.db.create_session("alice", "test-model", "default")
    run = runtime.research.create("alice", row["id"], "Lead", "Find evidence")
    runtime.settings.exa_key = SecretStr("test-key")
    text = "Source evidence. " * 10000 + "SOURCE END"
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, json={"results": [{"url": "https://example.com/source", "text": text}]}
        )

    runtime.http._transport = httpx.MockTransport(respond)
    registry = research_tools(runtime, row, run)
    read = await call_tool(registry, "read_source", url="https://example.com/source")
    assert read["text"] == text
    assert requests == [{"urls": ["https://example.com/source"], "text": True}]
    note = await call_tool(
        registry,
        "save_research_note",
        kind="finding",
        text="A qualified claim.",
        source_ids=[read["source_id"]],
        status="supported",
    )
    saved = await call_tool(registry, "read_research", item_id=read["source_id"])
    assert saved["content"]["text"] == text
    assert note["id"] in json.dumps(runtime.research.summary_context("alice", row["id"], run))
    other = runtime.db.create_session("bob", "test-model", "default")
    with pytest.raises(LookupError):
        runtime.research.item("bob", other["id"], read["source_id"])
    with pytest.raises(LookupError):
        runtime.research.get("bob", other["id"], run)


async def test_supported_notes_require_actual_saved_source_ids(runtime):
    row = runtime.db.create_session("alice", "test-model", "default")
    run = runtime.research.create("alice", row["id"], "Lead", "Find evidence")
    registry = research_tools(runtime, row, run)
    with pytest.raises(ValueError, match="Attach saved sources"):
        await call_tool(
            registry, "save_research_note", kind="finding", text="Claim", status="supported"
        )
    with pytest.raises(LookupError):
        await call_tool(
            registry, "save_research_note", kind="finding", text="Claim", source_ids=["Sfake"]
        )


def test_protected_parent_and_delegate_summaries_cannot_be_spent_by_research(settings):
    settings.max_model_calls = 30
    settings.max_compaction_calls = 5
    budgets = TurnBudget(settings)
    delegate = budgets.reserve_final_summary()
    while budgets.compaction.spend():
        pass
    assert budgets.compaction.used == 3
    assert budgets.compaction.held == 2
    assert delegate.spend()
    assert budgets.final_compaction.spend()
    assert budgets.compaction.used == 5
    assert not budgets.final_compaction.spend()
    while budgets.research.spend():
        pass
    assert budgets.recovery.spend()
    assert budgets.total.used == 30
    assert not budgets.total.spend()


@pytest.mark.parametrize("total", range(1, 9))
def test_small_budgets_never_exceed_shared_total(settings, total):
    settings.max_model_calls = total
    budgets = TurnBudget(settings)
    while budgets.research.spend():
        pass
    while budgets.compaction.spend():
        pass
    while budgets.final_compaction.spend():
        pass
    assert budgets.recovery.spend()
    assert budgets.total.used == total


async def test_research_view_survives_restart_and_checks_ownership(runtime):
    row = runtime.db.create_session("alice", "test-model", "default")
    run = runtime.research.create("alice", row["id"], "Lead", "Research question")
    runtime.research.finish("alice", row["id"], run, "partial", "Full saved report.", "timeout")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
    ) as browser:
        path = f"/api/sessions/{row['id']}/research/{run}"
        assert (await browser.get(path)).status_code == 401
        browser.headers["Authorization"] = "Bearer " + "a" * 32
        assert (await browser.get(path)).json()["answer"] == "Full saved report."
        browser.headers["Authorization"] = "Bearer " + "b" * 32
        assert (await browser.get(path)).status_code == 404
    runtime.db.close()
    runtime.db = Database(runtime.settings.data_dir)
    runtime.research.db = runtime.db
    assert runtime.research.get("alice", row["id"], run)["answer"] == "Full saved report."


async def test_repeated_summary_preserves_corrections_references_and_questions(runtime):
    row = runtime.db.create_session("alice", "test-model", "default")
    run = runtime.research.create("alice", row["id"], "Lead", "Compare evidence")
    source = runtime.research.save_item(
        "alice",
        row["id"],
        run,
        "source",
        {
            "url": "https://example.com/source",
            "publishedDate": "2025-12-01",
            "text": "Qualified evidence.",
        },
    )
    question = runtime.research.save_item(
        "alice",
        row["id"],
        run,
        "question",
        {
            "text": "The opposing source is not dated.",
            "status": "open",
            "source_ids": [source],
        },
    )
    policy = context.compaction(runtime, row, context.ModelCapacity(100000, 500, "test"), run)
    summary = json.dumps(
        {
            "summary": "Only primary sources from December 2025 onward. Include opposing views. Evidence is qualified. The opposing source remains undated.",
            "record_ids": [source, question],
        }
    )
    memory = ContextMemory()
    history = long_history()
    history[0] = UserMessage("Only primary sources from December 2025 onward.")
    history.append(UserMessage("Include opposing views."))
    auxiliary = FakeModel([AssistantMessage(summary)] * 2)
    from contextlib import asynccontextmanager
    from dataclasses import replace

    @asynccontextmanager
    async def summaries():
        yield auxiliary

    policy = replace(policy, summary_model=summaries)
    model = FakeModel([AssistantMessage("Report with caveats.")] * 2)
    agent = Agent(model, context_window=100000, compaction=policy)
    await agent.run(history, memory=memory, budget=Budget(1), compaction_budget=Budget(6))
    assert memory.summary
    assert "Only primary sources" in str(memory.view(history))
    history.extend([*long_history(), UserMessage("Verify source dates.")])
    await agent.run(history, memory=memory, budget=Budget(1), compaction_budget=Budget(6))
    assert "Only primary sources" in str(memory.view(history))
    assert "Include opposing views" in str(memory.view(history))
    assert question in memory.summary and source in memory.summary
    assert ContextMemory.from_dict(memory.to_dict()) == memory
    assert (
        runtime.research.item("alice", row["id"], source)["content"]["publishedDate"]
        == "2025-12-01"
    )
    assert not valid_summary(
        json.dumps({"summary": "Everything is certain.", "record_ids": [source]}),
        runtime.research.summary_context("alice", row["id"], run),
    )


@pytest.mark.parametrize("recipient", ["parent", "delegate"])
async def test_final_reply_can_summarize_after_ordinary_summary_budget_exhaustion(
    runtime, recipient
):
    runtime.enforce_budgets = True
    from harness.model import default_estimate_tokens
    from theos.runtime.recovery import response_call

    runtime.settings.max_model_calls = 30
    runtime.settings.max_compaction_calls = 5
    runtime.settings.context_tokens = 100000
    row = runtime.db.create_session("alice", "test-model", "default")
    row["generation"] = json.dumps({"max_output_tokens": 1000})
    budgets = TurnBudget(runtime.settings)
    summaries = (
        budgets.final_compaction if recipient == "parent" else budgets.reserve_final_summary()
    )
    reply = budgets.recovery if recipient == "parent" else budgets.research.reserve()
    while budgets.compaction.spend():
        pass
    while budgets.research.spend():
        pass
    before = budgets.total.used
    history = [*long_history(), UserMessage("Answer with the evidence.")]
    original = list(history)
    answer_text = "Complete returned answer. " * 2000 + "ANSWER END"
    model = FakeModel([AssistantMessage(answer_text)])
    auxiliary = FakeModel([AssistantMessage("Evidence and original requirements retained.")])
    use_models(runtime, auxiliary)
    answer = await response_call(
        runtime,
        row,
        history,
        ContextMemory(),
        reply,
        "Task instructions. " * 350,
        "budget_limit",
        compact_budget=summaries,
        model=model,
    )
    assert answer.text == answer_text
    assert history == original
    assert len(model.requests) == len(auxiliary.requests) == 1
    assert not model.requests[0].tools
    assert budgets.total.used == before + 2
    for request in model.requests:
        assert request.options["max_output_tokens"] == 1000
        assert default_estimate_tokens(request) + 1000 <= 100000
    if recipient == "parent":
        assert budgets.total.used == 30
    else:
        assert budgets.recovery.spend()
        assert budgets.final_compaction.spend()
        assert budgets.total.used == 30


async def test_browser_mode_is_explicit_and_does_not_persist_to_followups(runtime):
    row = runtime.db.create_session("alice", "test-model", "default")
    use_models(
        runtime,
        FakeModel([AssistantMessage("Research report.")]),
        FakeModel([AssistantMessage("Normal reply.")]),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
        headers={"Authorization": "Bearer " + "a" * 32},
    ) as browser:
        path = f"/api/sessions/{row['id']}/turn"
        assert (
            await browser.post(path, json={"text": "Question", "mode": "automatic"})
        ).status_code == 422
        deep = await browser.post(path, json={"text": "Question", "mode": "deep_research"})
        assert '"status": "completed"' in deep.text
        normal = await browser.post(path, json={"text": "Follow-up"})
        assert '"status": "completed"' in normal.text
        assert len(runtime.research.runs("alice", row["id"])) == 1


async def test_replaced_questions_and_shared_source_references_remain_inspectable(runtime):
    row = runtime.db.create_session("alice", "test-model", "default")
    root = runtime.research.create("alice", row["id"], "Lead", "Compare evidence")
    child = runtime.research.create("alice", row["id"], "Dates", "Verify dates", root)
    source = runtime.research.save_item(
        "alice",
        row["id"],
        root,
        "source",
        {"url": "https://example.com", "publishedDate": "2025-12-01", "text": "Complete source."},
    )
    registry = research_tools(runtime, row, child)
    old = await call_tool(
        registry,
        "save_research_note",
        kind="question",
        text="Is this source dated?",
        source_ids=[source],
        status="open",
    )
    new = await call_tool(
        registry,
        "save_research_note",
        kind="question",
        text="Publication date confirmed: 2025-12-01.",
        source_ids=[source],
        status="resolved",
        replaces=old["id"],
    )
    protected = runtime.research.summary_context("alice", row["id"], child)
    assert {old["id"], new["id"], source} == {record["id"] for record in protected["records"]}
    assert "2025-12-01" in json.dumps(protected)
    assert runtime.research.item("alice", row["id"], old["id"])["content"]["status"] == "open"


async def test_invalid_research_summary_keeps_previous_summary_and_full_source(runtime):
    runtime.enforce_budgets = True
    row = runtime.db.create_session("alice", "test-model", "default")
    run = runtime.research.create("alice", row["id"], "Lead", "Compare sources")
    source_text = "Full source evidence. " * 1500 + "SOURCE END"
    source = runtime.research.save_item(
        "alice", row["id"], run, "source", {"url": "https://example.com", "text": source_text}
    )
    memory = ContextMemory("Earlier verified progress.", 2, [0])
    history = [
        UserMessage("Check publication dates."),
        AssistantMessage("Earlier exchange."),
        UserMessage("Continue research."),
        AssistantMessage(tool_calls=[ToolCall("read", "read_source", {})]),
        ToolResultMessage("read", "read_source", source_text),
    ]
    model = FakeModel(
        [AssistantMessage("Earlier progress retained. The source needs date verification.")]
    )
    agent = Agent(
        model,
        context_window=10000,
        compaction=context.compaction(runtime, row, context.ModelCapacity(10000, 500, "test"), run),
    )
    result = await agent.run(history, memory=memory, budget=Budget(1), compaction_budget=Budget(3))
    assert result.status == "completed"
    assert "Earlier verified progress." in memory.summary
    assert "Evidence summarized without" not in memory.summary
    assert memory.summary == "Earlier verified progress."
    assert runtime.research.item("alice", row["id"], source)["content"]["text"] == source_text
    assert len(model.requests) == 1


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/private",
        "http://[::1]/",
        "http://localhost/private",
        "http://host.local/private",
        "https://user:secret@example.com",
        "https://:secret@example.com",
    ],
)
async def test_source_reader_rejects_private_and_credential_urls(runtime, url):
    row = runtime.db.create_session("alice", "test-model", "default")
    run = runtime.research.create("alice", row["id"], "Lead", "Find evidence")
    with pytest.raises(ValueError, match="public HTTP"):
        await call_tool(research_tools(runtime, row, run), "read_source", url=url)
    assert not runtime.research.items("alice", row["id"], run)
