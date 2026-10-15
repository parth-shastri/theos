"""Failed model generations produce attributed errors and keep evidence private."""

import json

import httpx
import pytest

from harness import AssistantMessage, ToolResultMessage
from harness.events import GenerationComplete, TextDelta
from harness.testing import FakeModel
from tests.context_fixtures import long_history
from theos.runtime.errors import ProviderFailure

from .conftest import collect
from .test_recovery import delegate_call, install_read, read_call, session, use_models


@pytest.mark.parametrize(
    "status,detail",
    [
        (400, "request I sent"),
        (401, "credentials"),
        (403, "permissions"),
        (402, "insufficient credit"),
        (404, "model or route"),
        (429, "rate or quota"),
        (502, "server error"),
    ],
)
def test_provider_error_names_source_and_safe_cause(status, detail):
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.test"))
    error = httpx.HTTPStatusError("secret raw body", request=response.request, response=response)
    text = ProviderFailure("openrouter", error).public_message
    assert "OpenRouter" in text and detail in text and f"HTTP {status}" in text
    assert "secret" not in text


async def test_provider_failure_after_tool_keeps_evidence_out_of_reply(runtime):
    await install_read(runtime, "UNRELATED PRIVATE FINDING")
    model = FakeModel([read_call("read"), RuntimeError("secret response")])
    use_models(runtime, model)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Check the source."))
    assert events[-1]["status"] == "failed"
    assert not any(e["type"] == "text" for e in events)
    history = runtime.db.load_history("alice", row["id"])
    assert "test model" in history[-1].text
    assert "UNRELATED" not in history[-1].text
    assert any(isinstance(m, ToolResultMessage) and "UNRELATED" in m.content for m in history)
    assert len(model.requests) == 2


@pytest.mark.parametrize("complete_first", [False, True])
async def test_broken_stream_never_publishes_a_partial_reply(runtime, complete_first):
    class BrokenStream(FakeModel):
        async def stream(self, request):
            self.requests.append(request)
            yield TextDelta("UNFINISHED DRAFT")
            if complete_first:
                yield GenerationComplete(AssistantMessage("UNFINISHED DRAFT"))
            raise TimeoutError("private endpoint")

    model = BrokenStream([])
    use_models(runtime, model)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Answer."))
    assert events[-1]["status"] == "failed"
    assert not any(e["type"] in {"text", "assistant_complete"} for e in events)
    replacement = next(e for e in events if e["type"] == "answer_replace")
    assert "timed out" in replacement["text"]
    assert "UNFINISHED" not in json.dumps(events)
    assert len(model.requests) == 1


@pytest.mark.parametrize("max_calls", [4, 12])
async def test_delegate_provider_failure_stops_parent_without_publishing_sibling(
    runtime, max_calls
):
    runtime.enforce_budgets = True
    runtime.settings.max_model_calls = max_calls
    runtime.settings.max_compaction_calls = 0
    parent = FakeModel([delegate_call(), AssistantMessage("Must not publish this answer")])
    sibling = FakeModel([AssistantMessage("Sibling private finding")])
    failed = FakeModel([RuntimeError("private provider body")])
    use_models(runtime, parent, sibling, failed)
    row = session(runtime)
    events = await collect(runtime.start("alice", row["id"], "Compare opening times."))
    assert events[-1]["status"] == "failed"
    assert len(parent.requests) == len(sibling.requests) == len(failed.requests) == 1
    answer = runtime.db.load_history("alice", row["id"])[-1].text
    assert "test model" in answer
    assert "Sibling" not in answer and "Must not" not in answer


async def test_compaction_provider_failure_still_allows_main_answer(runtime):
    runtime.settings.context_tokens = 100000

    async def no_tools(current):
        return []

    runtime.tools = no_tools
    row = session(runtime)
    original = long_history()
    runtime.db.save_history("alice", row["id"], original)
    main = FakeModel([AssistantMessage("The saved source remains available for the report.")])
    auxiliary = FakeModel([RuntimeError("private compaction error")])
    use_models(runtime, main, auxiliary)
    events = await collect(runtime.start("alice", row["id"], "Continue."))
    assert events[-1]["status"] == "completed"
    assert len(main.requests) == len(auxiliary.requests) == 1
    history = runtime.db.load_history("alice", row["id"])
    assert history[: len(original)] == original and "saved source" in history[-1].text
    assert "private compaction error" not in json.dumps(events)


def test_provider_diagnostics_reject_arbitrary_remote_fields():
    import logging

    from theos.operations.logging import SafeFormatter
    from theos.operations.provider_diagnostics import diagnostics

    error = {
        "code": 502,
        "message": "PRIVATE PROMPT",
        "metadata": {
            "provider_name": "PRIVATE PROVIDER",
            "error_type": "PRIVATE SECRET",
            "provider_code": "PRIVATE TOKEN",
            "raw": {"password": "PRIVATE PASSWORD"},
        },
    }
    values = diagnostics(error, generation_id="PRIVATE REQUEST", request_id="PRIVATE KEY")
    assert values == {"status_code": 502}
    record = logging.LogRecord(
        "theos", logging.WARNING, __file__, 1, "provider_request_failed", (), None
    )
    record.__dict__.update(error["metadata"])
    record.__dict__.update(values)
    assert "PRIVATE" not in SafeFormatter().format(record)
