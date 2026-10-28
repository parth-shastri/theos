"""Optional onboarding, consent cancellation, and verified Zepto connection state."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp.shared.auth import OAuthToken

from theos.services.google.oauth import OAuth
from theos.services.zepto import auth as zepto_auth
from theos.services.zepto.auth import ZeptoTokenStorage

from .test_browser_connections import browser
from .test_oauth_gmail_health import configure
from .test_telegram_onboarding import bot_for, message, sent


def configured(runtime):
    configure(runtime.settings)
    runtime.settings.zepto_url = "https://shopping.test/mcp"
    runtime.oauth = OAuth(runtime.settings, runtime.db, runtime.http)


async def test_optional_setup_offers_only_unconnected_accounts_and_keeps_owner_profile(runtime):
    configured(runtime)
    runtime.oauth.save("alice", "gmail", {"access_token": "existing"})
    runtime.db.put_record(
        "alice", "preferences", "settings", {"display_name": "Ada", "timezone": "Asia/Kolkata"}
    )
    async with browser(runtime) as alice, browser(runtime, "bob") as bob:
        setup = (await alice.get("/api/connections")).json()["onboarding"]
        assert setup["needed"] and setup["display_name"] == "Ada"
        assert {account["id"] for account in setup["accounts"]} == {"health", "zepto"}
        assert (
            await alice.post("/api/connections/onboarding", json={"timezone": "invalid"})
        ).status_code == 400
        response = await alice.post(
            "/api/connections/onboarding",
            json={"display_name": "  Ada L.  ", "timezone": "Asia/Kolkata", "owner": "bob"},
        )
        assert response.json() == {"display_name": "Ada L.", "timezone": "Asia/Kolkata"}
        assert not (await alice.get("/api/connections")).json()["onboarding"]["needed"]
        assert (await bob.get("/api/connections")).json()["onboarding"]["needed"]
        assert runtime.db.record("alice", "preferences", "settings")["display_name"] == "Ada L."
        assert not runtime.db.rows("SELECT * FROM oauth_states")
        assert (await bob.post("/api/connections/onboarding", json={})).status_code == 200
        assert not (await bob.get("/api/connections")).json()["onboarding"]["needed"]


async def test_google_cancel_and_provider_denial_preserve_existing_account(runtime):
    configured(runtime)
    runtime.oauth.save("alice", "gmail", {"access_token": "existing"})
    original = runtime.db.one("SELECT encrypted FROM credentials WHERE owner='alice'")["encrypted"]
    async with browser(runtime) as client:

        async def start():
            data = (await client.post("/api/connections/gmail/connect")).json()
            return parse_qs(urlsplit(data["url"]).query)["state"][0]

        state = await start()
        assert (await client.post("/api/connections/gmail/cancel")).json() == {"cancelled": True}
        assert (
            await client.get("/oauth/gmail/callback", params={"state": state, "code": "unused"})
        ).status_code == 400
        state = await start()
        denied = await client.get(
            "/oauth/gmail/callback", params={"state": state, "error": "access_denied<script>"}
        )
        assert denied.status_code == 400 and "cancelled" in denied.text
        assert "<script>" not in denied.text
        assert (
            runtime.db.one("SELECT encrypted FROM credentials WHERE owner='alice'")["encrypted"]
            == original
        )
        status = (await client.get("/api/connections")).json()
        gmail = next(account for account in status["accounts"] if account["id"] == "gmail")
        assert gmail["connected"] and gmail["setup"]["status"] == "cancelled"
        assert not runtime.db.rows("SELECT * FROM oauth_states")
        assert not runtime.db.rows("SELECT * FROM sessions")


@pytest.mark.parametrize(
    "existing, outcome",
    [
        (False, "failed"),
        (True, "failed"),
        (False, "cancelled"),
        (True, "cancelled"),
        (False, "connected"),
    ],
)
async def test_zepto_only_publishes_verified_connections_and_restores_cancelled_reconnect(
    runtime, monkeypatch, existing, outcome
):
    configured(runtime)
    store = ZeptoTokenStorage(runtime.settings, runtime.db, "alice")
    if existing:
        await store.set_tokens(OAuthToken(access_token="previous-token", token_type="Bearer"))
    checking = asyncio.Event()

    @asynccontextmanager
    async def stream(*args, **kwargs):
        yield None, None, None

    class Session:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            staged = ZeptoTokenStorage(
                runtime.settings, runtime.db, "alice", pending=runtime.zepto.pending["alice"]
            )
            await staged.set_tokens(
                OAuthToken(access_token="unverified-token", token_type="Bearer")
            )
            assert (
                (await store.get_tokens()).access_token == "previous-token"
                if existing
                else await store.get_tokens() is None
            )

        async def list_tools(self):
            assert not runtime.zepto.connected("alice")
            checking.set()
            if outcome == "cancelled":
                await asyncio.Event().wait()
            if outcome == "connected":
                return SimpleNamespace(tools=[])
            raise RuntimeError("Tool discovery failed")

    async def registration():
        pass

    monkeypatch.setattr(runtime.zepto, "_ensure_client_info", registration)
    monkeypatch.setattr(runtime.zepto, "_provider", lambda *args: None)
    monkeypatch.setattr(zepto_auth, "streamable_http_client", stream)
    monkeypatch.setattr(zepto_auth, "ClientSession", Session)
    await runtime.zepto.connect_from_browser("alice")
    flow = runtime.zepto.pending["alice"]
    await checking.wait()
    if outcome == "cancelled":
        await runtime.zepto.cancel("alice")
    else:
        await flow.task
    assert runtime.zepto.connection_status("alice")["status"] == outcome
    assert runtime.zepto.connected("alice") == (existing or outcome == "connected")
    assert (
        (await store.get_tokens()).access_token
        == ("unverified-token" if outcome == "connected" else "previous-token")
        if existing or outcome == "connected"
        else await store.get_tokens() is None
    )
    assert "unverified-token" not in json.dumps(runtime.db.rows("SELECT * FROM records"))


async def test_telegram_onboarding_offers_optional_accounts_without_model_history(runtime):
    configured(runtime)
    runtime.oauth.save("telegram:123", "gmail", {"access_token": "existing"})
    bot = bot_for(runtime)
    for text in ("/start", "/skip", "/skip"):
        await message(bot, text)
    offers = [
        call.args[1]
        for call in bot.api.call_args_list
        if call.args[0] == "sendMessage" and "reply_markup" in call.args[1]
    ]
    buttons = [button for row in offers[-1]["reply_markup"]["inline_keyboard"] for button in row]
    assert {button["callback_data"] for button in buttons} == {
        "connect:health",
        "connect:zepto",
        "connect:skip",
    }
    callback = {
        "update_id": 500,
        "callback_query": {
            "id": "skip-setup",
            "from": {"id": 123},
            "data": "connect:skip",
            "message": {
                "message_id": 10,
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 123},
            },
        },
    }
    await bot.handle([callback])
    assert "ready to chat" in sent(bot)[-1]
    assert runtime.db.record("telegram:123", "onboarding", "connections")["completed"]
    assert (
        runtime.db.record("telegram:123", "preferences", "settings")["display_name"]
        == "Ada Lovelace"
    )
    assert not runtime.db.rows("SELECT * FROM sessions")
    assert not runtime.db.rows("SELECT * FROM usage")
