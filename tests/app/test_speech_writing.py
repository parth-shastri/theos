"""Speech tools and browser playback share expressive writing and owner accounting."""

import json
from contextlib import asynccontextmanager

import httpx
import pytest

from harness import AssistantMessage, ToolCall
from harness.testing import FakeModel
from theos.runtime.speech import prepare
from theos.services.errors import ServiceError
from theos.services.voice.tools import voice_tools
from theos.transports.browser.app import create_app

from .conftest import call_tool


async def test_tool_sends_spoken_rendition_and_accounts_without_changing_history(runtime):
    source = "Review 3 proposals at 16:30. Deployment failed."
    spoken = "Let's review those 3 proposals at 16:30. The deployment failed."
    session = runtime.db.create_session("alice", "gpt-6-luna", "default")
    model = FakeModel([AssistantMessage(spoken, usage={"input_tokens": 40, "output_tokens": 20})])

    @asynccontextmanager
    async def factory(*args):
        yield model

    runtime.models = factory
    runtime.settings.kokoro_url = "http://gateway/v1"
    sent = []

    def endpoint(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=b"ID3audio")

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        runtime.files.voice.http = http
        result = await call_tool(
            voice_tools(runtime.files.voice, "alice", session["id"]),
            "send_text_to_speech",
            text=source,
        )
    assert sent[0]["input"] == spoken and sent[0]["input"] != source
    assert runtime.files.get("alice", result["file_id"])["media_type"] == "audio/mpeg"
    assert len(model.requests) == 1 and not model.requests[0].tools
    assert json.loads(model.requests[0].messages[-1].content) == {"source_text": source}
    assert runtime.db.load_history("alice", session["id"]) == []
    usage = runtime.db.one("SELECT owner,session,input_tokens,output_tokens FROM usage")
    assert usage == {
        "owner": "alice",
        "session": session["id"],
        "input_tokens": 40,
        "output_tokens": 20,
    }


async def test_browser_also_prepares_expressive_text_and_checks_session_owner(
    runtime, scripted_models
):
    runtime.settings.kokoro_url = "http://gateway/v1"
    session = runtime.db.create_session("alice", "gpt-6-luna", "default")
    scripted_models.responses.append([AssistantMessage("All right. Let's begin.")])
    sent = []

    def endpoint(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=b"ID3audio")

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        runtime.files.voice.http = http
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
            base_url="http://browser",
            headers={"Authorization": "Bearer " + "a" * 32},
        ) as browser:
            body = {"text": "Begin.", "session_id": session["id"]}
            assert (await browser.post("/api/audio/speech", json=body)).status_code == 200
            assert sent[0]["input"] == "All right. Let's begin."
            browser.headers["Authorization"] = "Bearer " + "b" * 32
            assert (await browser.post("/api/audio/speech", json=body)).status_code == 404
            assert len(sent) == 1


@pytest.mark.parametrize(
    "response",
    [
        AssistantMessage(""),
        AssistantMessage("x" * 12001),
        AssistantMessage("Meet at 17:30."),
        AssistantMessage("Meet at 16:30.", stop_reason="length"),
        AssistantMessage("Meet at 16:30.", tool_calls=[ToolCall("c", "send_email", {})]),
        TimeoutError("private provider detail"),
    ],
)
async def test_failed_writing_never_falls_back_to_plain_speech(runtime, scripted_models, response):
    runtime.settings.kokoro_url = "http://gateway/v1"
    scripted_models.responses.append([response])
    sent = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: sent.append(req) or httpx.Response(200))
    ) as http:
        runtime.files.voice.http = http
        with pytest.raises(ServiceError, match="Expressive speech preparation failed"):
            await runtime.files.speech("alice", "Meet at 16:30.")
    assert not sent and runtime.files.list("alice") == []


async def test_prepare_rejects_another_owners_session_before_model_access(runtime, scripted_models):
    session = runtime.db.create_session("alice", "gpt-6-luna", "default")
    scripted_models.responses.append([AssistantMessage("Private result")])
    with pytest.raises(LookupError):
        await prepare(runtime, "bob", "Hello", session_id=session["id"])
    assert len(scripted_models.responses) == 1
