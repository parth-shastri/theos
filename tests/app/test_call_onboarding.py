"""Verify recipient ownership, explicit activation, preferences, and revocation."""

import json
import time

import httpx
import pytest

from theos.runtime.tools import build_tools
from theos.services.errors import ServiceError
from theos.settings import TelegramCallsSettings

from .test_browser_connections import browser


@pytest.fixture
def calls(runtime):
    runtime.settings.telegram_calls = TelegramCallsSettings(
        enabled=True,
        url="http://calling.test",
        key="k" * 32,
    )
    runtime.settings.kokoro_url = "http://speech.test/v1"
    runtime.phone_calls.provider = "telegram"
    runtime.phone_calls.config = runtime.settings.telegram_calls
    state = {"status": "waiting", "recipient": 123, "calls": []}

    def endpoint(request):
        if request.url.host == "speech.test":
            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"mp3")
        assert request.headers["Authorization"] == "Bearer " + "k" * 32
        if request.url.path.startswith("/v1/calls/"):
            if request.method == "GET":
                return httpx.Response(200, json={"status": "completed"})
            state["calls"].append(request)
            return httpx.Response(
                202, json={"id": request.url.path.rsplit("/", 1)[1], "status": "accepted"}
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={"status": "disabled"})
        if request.method == "POST":
            state["expected"] = json.loads(request.content)["expected_recipient"]
        return httpx.Response(
            200,
            json={
                **state,
                "calls": [],
                "url": "https://t.me/theos_test?text=proof",
                "expires": time.time() + 600,
            },
        )

    runtime.http._transport = httpx.MockTransport(endpoint)
    return runtime.phone_calls.connections, state


async def names(runtime, session):
    return {t.name: t for t in await build_tools(runtime, session)}


async def test_browser_activation_and_revocation_are_bound_to_the_authenticated_owner(
    runtime, calls
):
    service, state = calls
    alice = runtime.db.create_session("alice", "fake", "default")
    bob = runtime.db.create_session("bob", "fake", "default")
    assert "call_user" not in await names(runtime, alice)
    async with browser(runtime) as client:
        setup = (await client.get("/api/connections")).json()
        assert setup["onboarding"]["needed"] and setup["calling"]["status"] == "disconnected"
        assert (await client.post("/api/calling/test")).status_code == 400
        result = await client.post("/api/calling/connect", json={"owner": "bob"})
        assert result.status_code == 200 and result.json()["url"].startswith("https://t.me/")
        assert state["expected"] is None
        assert service.row("bob") is None
        state["status"] = "verified"
        assert (await client.get("/api/connections")).json()["calling"]["status"] == "linked"
        assert "call_user" not in await names(runtime, alice)
        assert (await client.post("/api/calling/confirm", json={})).status_code == 400
        assert (await client.post("/api/calling/test")).status_code == 200
        assert (await client.post("/api/calling/test")).status_code == 400
        await runtime.phone_calls.tick(time.time())
        assert len(state["calls"]) == 1
        assert state["calls"][0].url.params["recipient"] == "123"
        assert (
            await client.post("/api/calling/confirm", json={"reminders": True, "approvals": False})
        ).status_code == 200
        tools = await names(runtime, alice)
        assert "call_user" in tools and "call_user" not in await names(runtime, bob)
        schema = tools["schedule_reminder"].input_model.model_json_schema()
        assert schema["properties"]["delivery"]["default"] == "phone"
        assert not runtime.phone_calls.recipient("alice", "browser", purpose="approvals")
        assert not runtime.phone_calls.recipient("alice", "telegram-group")
        assert (
            await client.post(
                "/api/calling/preferences",
                json={"reminders": False, "approvals": True, "owner": "bob"},
            )
        ).status_code == 422
        assert (
            await client.post(
                "/api/calling/preferences", json={"reminders": False, "approvals": True}
            )
        ).status_code == 200
        schema = (await names(runtime, alice))["schedule_reminder"].input_model.model_json_schema()
        assert "delivery" not in schema["properties"]
        assert runtime.phone_calls.recipient("alice", "browser", purpose="approvals") == 123
        assert (await client.post("/api/calling/disconnect")).status_code == 200
        assert "call_user" not in await names(runtime, alice)
        assert not runtime.phone_calls.recipient("alice", "browser")


async def test_telegram_proof_must_match_the_enrolled_sender(runtime, calls):
    service, state = calls
    runtime.settings.telegram_token = "test-token"
    runtime.settings.telegram_users = {123}
    await service.start("telegram:123")
    assert state["expected"] == 123
    state.update(status="verified", recipient=456)
    with pytest.raises(ServiceError, match="own Telegram"):
        await service.refresh("telegram:123")
    assert service.row("telegram:123")["state"] == "waiting"
    state["recipient"] = 123
    await service.refresh("telegram:123")
    assert service.row("telegram:123")["state"] == "linked"


async def test_disconnect_during_synthesis_prevents_the_test_call(runtime, calls, monkeypatch):
    service, state = calls
    await service.start("alice")
    state["status"] = "verified"
    await service.refresh("alice")
    service.test("alice", "browser")
    original = runtime.phone_calls.voice.synthesize

    async def synthesize(text, **kwargs):
        audio = await original(text, **kwargs)
        await service.disconnect("alice")
        return audio

    monkeypatch.setattr(runtime.phone_calls.voice, "synthesize", synthesize)
    await runtime.phone_calls.tick(time.time())
    assert state["calls"] == []
    assert runtime.db.one("SELECT status FROM phone_calls")["status"] == "skipped"


async def test_saved_disconnect_overrides_legacy_mapping_even_if_gateway_is_down(runtime, calls):
    service, state = calls
    runtime.phone_calls.config.recipients = {"alice": 123}
    assert service.status("alice")["status"] == "ready"
    service.preferences("alice", False, True)
    runtime.http._transport = httpx.MockTransport(lambda request: httpx.Response(503))
    await service.disconnect("alice")
    assert not runtime.phone_calls.recipient("alice", "browser")


async def test_telegram_onboarding_offers_and_completes_calls_outside_model_history(runtime, calls):
    from theos.transports.telegram import call_setup

    from .test_telegram_onboarding import bot_for, message

    service, state = calls
    bot = bot_for(runtime)
    for text in ("/start", "/skip", "/skip"):
        await message(bot, text)
    buttons = [
        button
        for call in bot.api.call_args_list
        if call.args[0] == "sendMessage"
        for row in call.args[1].get("reply_markup", {}).get("inline_keyboard", [])
        for button in row
    ]
    assert any(button.get("callback_data") == "calls:start" for button in buttons)

    async def click(action):
        return await call_setup.handle(
            bot,
            {},
            "telegram:123",
            "telegram-private",
            123,
            None,
            {"id": action, "from": {"id": 123}, "data": "calls:" + action},
        )

    await click("start")
    assert state["expected"] == 123
    state["status"] = "verified"
    await click("status")
    await click("test")
    session = runtime.db.one("SELECT * FROM sessions")
    assert session["address"] == "123:0"
    await runtime.phone_calls.tick(time.time())
    await click("confirm")
    assert service.status("telegram:123")["status"] == "ready"
    assert runtime.db.load_history("telegram:123", session["id"]) == []
    await click("approvals")
    assert not runtime.phone_calls.recipient(
        "telegram:123", "telegram-private", purpose="approvals"
    )
    await click("disconnect")
    assert not runtime.phone_calls.recipient("telegram:123", "telegram-private")
