"""Browser cost scopes, tool access, and reasoning event delivery."""

import json

import httpx
import pytest

from harness import AssistantMessage, ToolCall
from harness.events import ModelResponded, ReasoningDelta, ToolFinished, ToolStarted
from harness.types import ToolResultMessage
from theos.runtime.events import publish_event
from theos.runtime.model_catalog import MODEL_CHOICES, generation_options, wire_model
from theos.runtime.models import model_client, model_options, session_options
from theos.server import create_app
from theos.settings import ModelCosts


async def test_costs_preserve_missing_prices_and_owner_boundaries(runtime):
    db = runtime.db
    alice = db.create_session("alice", runtime.settings.model, "default")
    bob = db.create_session("bob", runtime.settings.model, "default", channel="terminal")
    empty = db.create_session("alice", runtime.settings.model, "default")
    for session, cost in ((alice, 0.3), (alice, None), (bob, 1.2)):
        db.execute(
            "INSERT INTO usage(owner,session,model,input_tokens,output_tokens,cache_tokens,cost,created) "
            "VALUES (?,?,?,100,20,0,?,0)",
            (session["owner"], session["id"], session["model"], cost),
        )
    # Dashboard cost totals must include sessions beyond the recent-session limit.
    for _ in range(101):
        db.create_session("alice", runtime.settings.model, "default")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
    ) as browser:
        assert (await browser.get("/api/usage")).status_code == 401
        browser.headers["Authorization"] = "Bearer " + "a" * 32
        usage = (await browser.get("/api/usage")).json()
        assert usage["cost"] == pytest.approx(0.3)
        assert usage["requests"] == 2 and usage["unpriced_requests"] == 1
        saved = (await browser.get(f"/api/sessions/{alice['id']}")).json()
        assert saved["usage"] == usage
        assert (await browser.get(f"/api/sessions/{empty['id']}")).json()["usage"]["requests"] == 0
        dashboard = (await browser.get("/api/dashboard")).json()
        assert dashboard["totals"]["cost"] == pytest.approx(1.5)
        assert dashboard["totals"]["conversations"] == 104
        assert len(dashboard["sessions"]) == 100
        assert len(dashboard["cost_per_conversation"]) == 104
        by_user = {row["owner"]: row for row in dashboard["cost_per_user"]}
        assert by_user["alice"]["unpriced_requests"] == 1
        assert by_user["bob"]["cost"] == pytest.approx(1.2)
        browser.headers["Authorization"] = "Bearer " + "b" * 32
        assert (await browser.get("/api/usage")).json()["cost"] == pytest.approx(1.2)
        assert (await browser.get(f"/api/sessions/{alice['id']}")).status_code == 404
        assert (await browser.get("/api/dashboard")).status_code == 403
        db.execute("UPDATE usage SET cost=NULL WHERE owner='bob'")
        usage = (await browser.get("/api/usage")).json()
        assert usage["cost"] is None and usage["unpriced_requests"] == 1


async def test_tools_view_matches_registry_without_executing_tools(runtime):
    session = runtime.db.create_session("alice", runtime.settings.model, "default")
    terminal = runtime.db.create_session(
        "alice", runtime.settings.model, "default", channel="terminal"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
    ) as browser:
        path = f"/api/sessions/{session['id']}/tools"
        assert (await browser.get(path)).status_code == 401
        browser.headers["Authorization"] = "Bearer " + "a" * 32
        tools = (await browser.get(path)).json()
        expected = await runtime.tools(session)
        assert {tool["name"] for tool in tools} == {tool.name for tool in expected}
        by_name = {tool["name"]: tool for tool in tools}
        assert by_name["delete_custom_table"]["requires_approval"]
        assert not by_name["get_preferences"]["requires_approval"]
        assert by_name["delete_custom_table"]["parameters"]["type"] == "object"
        assert not any(tool["name"].startswith(("gmail_", "health_", "zepto_")) for tool in tools)
        assert runtime.db.rows("SELECT * FROM tool_runs") == []
        assert (await browser.get(f"/api/sessions/{terminal['id']}/tools")).status_code == 403
        browser.headers["Authorization"] = "Bearer " + "b" * 32
        assert (await browser.get(path)).status_code == 404


async def test_reasoning_summary_is_streamed_and_saved(runtime, scripted_models):
    scripted_models.responses.append(
        [
            AssistantMessage(
                "Answer",
                reasoning="A short summary",
                provider_data={"private": "hidden"},
                usage={"input_tokens": 12, "output_tokens": 8},
            )
        ]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
        headers={"Authorization": "Bearer " + "a" * 32},
    ) as browser:
        session = (await browser.post("/api/sessions", json={})).json()
        path = f"/api/sessions/{session['id']}"
        response = await browser.post(path + "/turn", json={"text": "Hello"})
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        complete = next(event for event in events if event["type"] == "assistant_complete")
        assert {key: complete[key] for key in ("type", "text", "reasoning")} == {
            "type": "assistant_complete",
            "text": "Answer",
            "reasoning": "A short summary",
        }
        assert complete["usage"]["output_tokens"] == 8
        assert complete["display"]["duration_ms"] >= 0
        assert complete["display"]["created_at"] > 0
        assert "hidden" not in response.text
        history = (await browser.get(path)).json()["history"]
        assert history[-1]["reasoning"] == "A short summary"
        assert history[-1]["display"] == complete["display"]
        assert history[0]["display"]["created_at"] <= history[-1]["display"]["created_at"]


def test_reasoning_deltas_do_not_enter_traces_or_mix_with_child_progress(runtime):
    class Turn:
        owner = "alice"
        session_id = "test"
        raw_events = False

        def __init__(self):
            self.events = []

        def emit(self, event):
            self.events.append(event)

    turn = Turn()
    publish_event(runtime, turn, ReasoningDelta("Summary"), "running")
    publish_event(runtime, turn, ReasoningDelta("Child", parent_call_id="delegate"), "running")
    assert turn.events == [{"type": "reasoning", "text": "Summary"}]
    assert runtime.db.rows("SELECT * FROM traces") == []
    publish_event(runtime, turn, ModelResponded(AssistantMessage(reasoning="Summary")), "running")
    call = ToolCall("one", "get_preferences", {})
    publish_event(runtime, turn, ToolStarted(call), "running")
    publish_event(runtime, turn, ToolFinished(ToolResultMessage("one", call.name, "{}")), "running")
    assert turn.events[-2]["call_id"] == turn.events[-1]["call_id"] == "one"
    assert turn.events[-2]["arguments"] == {}
    assert turn.events[-1]["content"] == "{}"


def test_openai_requests_summaries_without_changing_default_effort():
    assert model_options("openai", "default") == {"reasoning": {"summary": "auto"}}
    assert model_options("openai", "low") == {"reasoning": {"effort": "low", "summary": "auto"}}
    assert model_options("openai", "none") == {"reasoning": {"effort": "none"}}
    assert model_options("openrouter", "default") == {}


async def test_model_choices_generation_validation_and_saved_settings(runtime):
    runtime.settings.provider = "openrouter"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
        headers={"Authorization": "Bearer " + "a" * 32},
    ) as browser:
        me = (await browser.get("/api/me")).json()
        assert set(MODEL_CHOICES) <= set(me["models"])
        assert "temperature" not in me["generation_capabilities"]["gpt-5.6-luna"]["parameters"]
        assert "top_k" in me["generation_capabilities"]["qwen-3.8-27b"]["parameters"]
        assert "none" not in me["generation_capabilities"]["sonnet-5.5"]["reasoning"]
        session = (await browser.post("/api/sessions", json={})).json()
        path = f"/api/sessions/{session['id']}"
        values = {
            "model": "qwen-3.8-27b",
            "reasoning": "xhigh",
            "generation": {"temperature": 0.7, "top_k": 25, "max_output_tokens": 100000},
        }
        assert (await browser.patch(path, json=values)).status_code == 200
        assert (await browser.get(path)).json()["generation"] == values["generation"]
        row = runtime.session("alice", session["id"])
        options = session_options(runtime.settings, row)
        assert options["extra_body"] == {"reasoning": {"effort": "xhigh"}, "top_k": 25}
        assert options["max_tokens"] == 100000
        assert options["temperature"] == 0.7
        # Model switches remove unsupported controls and bound the output limit.
        assert (await browser.patch(path, json={"model": "gemini-3.8-flash"})).status_code == 200
        assert (await browser.get(path)).json()["generation"] == {
            "temperature": 0.7,
            "max_output_tokens": 65536,
        }
        assert (
            await browser.patch(
                path, json={"model": "gpt-5.6-luna", "generation": {"temperature": 0.5}}
            )
        ).status_code == 400
        assert (
            await browser.patch(path, json={"model": "sonnet-5.5", "reasoning": "none"})
        ).status_code == 400
        assert (
            await browser.patch(
                path, json={"model": "gemini-3.8-flash", "generation": {"max_output_tokens": 65537}}
            )
        ).status_code == 400
        assert (
            await browser.patch(path, json={"model": "qwen-3.8-27b", "generation": {"top_p": 2}})
        ).status_code == 422
        assert (
            await browser.patch(path, json={"model": "qwen-3.8-27b", "generation": {"seed": 1.5}})
        ).status_code == 422
        assert (
            await browser.patch(path, json={"model": "qwen-3.8-27b", "generation": {"secret": "x"}})
        ).status_code == 422
        browser.headers["Authorization"] = "Bearer " + "b" * 32
        assert (await browser.patch(path, json=values)).status_code == 404


async def test_aliases_use_provider_model_ids_and_keep_direct_openai(settings, monkeypatch):
    import openai

    class Client:
        def __init__(self, **kwargs):
            self.options = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(openai, "AsyncOpenAI", Client)
    from pydantic import SecretStr

    settings.api_key = SecretStr("test-key")
    settings.provider = "openrouter"
    async with model_client(settings, "deepseek-flash-v4.1", "default") as model:
        assert model.model_id == "deepseek/deepseek-v4.1-flash"
        assert model.api == "chat_completions"
    settings.provider = "openai"
    async with model_client(settings, "gpt-5.6-luna", "default") as model:
        assert model.model_id == "gpt-5.6-luna"
        assert model.api == "responses"
    assert wire_model("openrouter", "custom/model") == "custom/model"
    assert generation_options("openai", "gpt-5.6-luna", {"max_output_tokens": 100}) == {
        "max_output_tokens": 100
    }


async def test_voice_routes_service_flags_owner_checks_and_failures(runtime):
    calls = []

    async def transcribe(owner, file_id):
        calls.append(("transcribe", owner, file_id))
        return "Editable recorded text"

    async def speech(owner, text):
        calls.append(("speech", owner, text))
        return runtime.files.save(owner, "speech.mp3", "audio/mpeg", b"test-audio")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
    ) as browser:
        assert (await browser.post("/api/audio/speech", json={"text": "hello"})).status_code == 401
        browser.headers["Authorization"] = "Bearer " + "a" * 32
        assert (await browser.get("/api/me")).json()["voice"]["tts"] is False
        assert (await browser.post("/api/audio/speech", json={"text": "hello"})).status_code == 502
        runtime.settings.kokoro_url = "http://speech.test"
        runtime.settings.transcription_url = "http://transcription.test"
        runtime.files.speech = speech
        runtime.files.transcribe = transcribe
        assert (await browser.get("/api/me")).json()["voice"]["transcription"] is True
        audio = (
            await browser.post(
                "/api/files", files={"file": ("recording.webm", b"audio", "audio/webm")}
            )
        ).json()
        text = (
            await browser.post("/api/files", files={"file": ("notes.txt", b"text", "text/plain")})
        ).json()
        assert (
            await browser.post("/api/audio/transcribe", json={"file_id": text["id"]})
        ).status_code == 400
        assert not calls
        transcript = await browser.post("/api/audio/transcribe", json={"file_id": audio["id"]})
        assert transcript.json()["text"] == "Editable recorded text"
        output = (await browser.post("/api/audio/speech", json={"text": "hello"})).json()
        assert calls[-1] == ("speech", "alice", "hello")
        assert (await browser.get(f"/api/files/{output['file_id']}")).content == b"test-audio"
        assert (
            await browser.post("/api/audio/speech", json={"text": "x" * 12001})
        ).status_code == 422
        browser.headers["Authorization"] = "Bearer " + "b" * 32
        before = len(calls)
        assert (
            await browser.post("/api/audio/transcribe", json={"file_id": audio["id"]})
        ).status_code == 404
        assert (await browser.get(f"/api/files/{output['file_id']}")).status_code == 404
        assert len(calls) == before


def test_cost_rates_can_differ_between_models(runtime):
    runtime.settings.model_costs = {"qwen-3.8-27b": ModelCosts(input=0.425, output=2.55)}
    session = runtime.db.create_session("alice", "qwen-3.8-27b", "default")
    runtime.record_usage(session, {"input_tokens": 1000000, "output_tokens": 1000000})
    assert runtime.db.one("SELECT cost FROM usage")["cost"] == pytest.approx(2.975)
