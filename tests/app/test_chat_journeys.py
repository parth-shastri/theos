"""Chat onboarding, real Telegram navigation, and authorization return contracts."""

import json
from urllib.parse import parse_qs, urlsplit

import httpx

from theos.runtime.tools import build_tools
from theos.services import journeys
from theos.services.account_setup import connection_tools
from theos.services.google.oauth import SCOPES, OAuth
from theos.transports.telegram import menus
from theos.transports.telegram.polling import Telegram

from .conftest import call_tool
from .test_browser_connections import browser
from .test_interfaces import onboard, telegram_message
from .test_oauth_gmail_health import configure
from .test_telegram_onboarding import bot_for, message


def menu(bot, owner="telegram:123"):
    return bot.db.record(owner, "telegram_menu", "active")


async def press(bot, action, *, saved=None, user=123):
    saved = saved or menu(bot, f"telegram:{user}")
    index = next(key for key, value in saved["actions"].items() if value == action)
    await bot.handle(
        [
            {
                "callback_query": {
                    "id": "press",
                    "from": {"id": user},
                    "data": f"ui:{saved['key']}:{saved['revision']}:{index}",
                    "message": {
                        "message_id": saved["message_id"],
                        "chat": {"id": user, "type": "private"},
                    },
                }
            }
        ]
    )


async def test_browser_profile_is_independent_of_optional_accounts_and_confirms_input(runtime):
    async with browser(runtime) as client:
        state = (await client.get("/api/journey")).json()
        assert state["needed"] and state["step"] == "name"
        response = await client.post(
            "/api/journey", json={"action": "reply", "value": "Ada", "revision": state["revision"]}
        )
        candidate = response.json()
        assert candidate["step"] == "confirm_name"
        assert "display_name" not in runtime.db.record("alice", "preferences", "settings")
        assert (
            await client.post("/api/journey", json={"action": "confirm", "revision": 0})
        ).status_code == 400
        state = (
            await client.post(
                "/api/journey", json={"action": "confirm", "revision": candidate["revision"]}
            )
        ).json()
        assert state["display_name"] == "Ada" and state["step"] == "timezone"
        state = (
            await client.post(
                "/api/journey",
                json={
                    "action": "reply",
                    "value": "I live in Mumbai",
                    "revision": state["revision"],
                },
            )
        ).json()
        assert state["candidate"] == "Asia/Kolkata"
        state = (
            await client.post(
                "/api/journey", json={"action": "confirm", "revision": state["revision"]}
            )
        ).json()
        assert not state["needed"]
        assert (await client.get("/api/connections")).json()["onboarding"]["needed"] is False
        assert not runtime.db.rows("SELECT * FROM sessions")
        assert not runtime.db.rows("SELECT * FROM usage")


async def test_requests_during_setup_survive_skip_and_are_never_saved_as_names(runtime):
    bot = bot_for(runtime)
    await message(bot, "/start")
    await message(bot, "Can you help me plan tomorrow?")
    assert (
        runtime.db.record("telegram:123", "preferences", "settings")["display_name"]
        == "Ada Lovelace"
    )
    await press(bot, "onboarding:finish")
    saved = menu(bot)
    await press(bot, "onboarding:resume", saved=saved)
    history = runtime.db.load_history(
        "telegram:123", runtime.db.one("SELECT id FROM sessions")["id"]
    )
    assert history[0].content == "Can you help me plan tomorrow?"
    await press(bot, "onboarding:resume", saved=saved)
    assert len(
        runtime.db.load_history("telegram:123", runtime.db.one("SELECT id FROM sessions")["id"])
    ) == len(history)


async def test_telegram_settings_edit_profile_and_survive_transport_restart(runtime):
    bot = bot_for(runtime)
    await onboard(bot)
    await message(bot, "/settings")
    assert menu(bot)["stack"] == ["settings:menu"]
    await press(bot, "settings:display_name")
    await message(bot, "Ada L.")
    assert (
        runtime.db.record("telegram:123", "preferences", "settings")["display_name"] == "Test user"
    )
    restarted = Telegram(runtime)
    restarted.api = bot.api
    await press(restarted, "settings:save")
    assert runtime.db.record("telegram:123", "preferences", "settings")["display_name"] == "Ada L."
    assert menu(bot)["stack"] == ["settings:menu"]
    await press(restarted, "settings:timezone")
    await message(restarted, "Mumbai")
    await press(restarted, "settings:save")
    assert (
        runtime.db.record("telegram:123", "preferences", "settings")["timezone"] == "Asia/Kolkata"
    )


async def test_telegram_root_commands_and_nested_menus_have_real_parents(runtime):
    configure(runtime.settings)
    runtime.oauth = OAuth(runtime.settings, runtime.db, runtime.http)
    bot = bot_for(runtime)
    await onboard(bot)
    await message(bot, "/gmail")
    assert menu(bot)["stack"] == ["connection:gmail"]
    assert "nav:done" in menu(bot)["actions"].values()
    assert "nav:back" not in menu(bot)["actions"].values()
    await message(bot, "/connections")
    await press(bot, "connect:gmail")
    assert menu(bot)["stack"] == ["accounts", "connection:gmail"]
    await press(bot, "nav:back")
    assert menu(bot)["stack"] == ["accounts"]


async def test_stale_cross_owner_and_duplicate_buttons_cannot_change_settings(runtime):
    bot = bot_for(runtime)
    await onboard(bot)
    await onboard(bot, 456)
    await message(bot, "/reasoning")
    old = menu(bot)
    await press(bot, "settings:set:reasoning:high", saved=old, user=456)
    assert (
        runtime.db.one("SELECT reasoning FROM sessions WHERE owner='telegram:123'")["reasoning"]
        == "default"
    )
    await press(bot, "settings:set:reasoning:high", saved=old)
    await press(bot, "settings:set:reasoning:low", saved=old)
    assert (
        runtime.db.one("SELECT reasoning FROM sessions WHERE owner='telegram:123'")["reasoning"]
        == "high"
    )
    await message(bot, "/settings")
    await press(bot, "settings:set:reasoning:low", saved=old)
    assert (
        runtime.db.one("SELECT reasoning FROM sessions WHERE owner='telegram:123'")["reasoning"]
        == "high"
    )


async def test_existing_profile_completion_is_shared_without_repeating_optional_connections(
    runtime,
):
    configure(runtime.settings)
    bot = bot_for(runtime)
    await onboard(bot)
    assert not journeys.state(runtime.settings, runtime.db, "telegram:123")["needed"]
    await message(bot, "/start")
    assert "connect:" not in json.dumps(menu(bot)["actions"])
    assert not runtime.db.rows("SELECT * FROM credentials")


async def test_oauth_return_is_bound_to_the_attempt_and_owned_browser_conversation(runtime):
    configure(runtime.settings)
    session = runtime.db.create_session("alice", "fake", "default")
    other = runtime.db.create_session("bob", "fake", "default")
    runtime.http._transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "access_token": "access",
                "refresh_token": "refresh",
                "scope": " ".join(SCOPES["gmail"]),
                "expires_in": 3600,
            },
        )
    )
    runtime.oauth = OAuth(runtime.settings, runtime.db, runtime.http)
    async with browser(runtime) as client:
        assert (
            await client.post(
                "/api/connections/gmail/connect", json={"source": "chat", "session_id": other["id"]}
            )
        ).status_code == 404
        result = (
            await client.post(
                "/api/connections/gmail/connect",
                json={"source": "chat", "session_id": session["id"]},
            )
        ).json()
        state = parse_qs(urlsplit(result["url"]).query)["state"][0]
        journeys.remember_connection(runtime.db, "alice", "gmail", None, "connections")
        response = await client.get(
            "/oauth/gmail/callback", params={"state": state, "code": "code"}
        )
        assert response.status_code == 303, response.text
        assert response.headers["location"] == f"/?conversation={session['id']}&connected=gmail"


async def test_invalid_settings_command_explains_the_validation_error(runtime):
    bot = bot_for(runtime)
    await onboard(bot)
    await bot.process(
        [
            {
                "update_id": 900,
                "message": {
                    "message_id": 1,
                    "text": "/reasoning invalid",
                    "from": {"id": 123},
                    "chat": {"id": 123, "type": "private"},
                },
            }
        ]
    )
    replies = [call.args[1].get("text", "") for call in bot.api.call_args_list]
    assert any("supported reasoning" in text for text in replies)
    assert not any("Check the integration settings" in text for text in replies)


async def test_group_conversation_settings_keep_private_profile_controls_out(runtime):
    runtime.settings.telegram_chats = {-100}
    bot = bot_for(runtime)
    await onboard(bot)
    await bot.handle([telegram_message("/settings", chat=-100, kind="group")])
    group_menu = menu(bot, "telegram-group:-100:0:123")
    assert "settings:model" in group_menu["actions"].values()
    assert "settings:display_name" not in group_menu["actions"].values()
    assert "connect:menu" not in group_menu["actions"].values()
    await bot.handle([telegram_message("/reasoning high", chat=-100, kind="group")])
    assert (
        runtime.db.one("SELECT reasoning FROM sessions WHERE channel='telegram-group'")["reasoning"]
        == "high"
    )


async def test_model_connection_tools_retain_context_and_offer_only_configured_services(runtime):
    configure(runtime.settings)
    runtime.settings.web_url = "https://theos.test"
    runtime.oauth = OAuth(runtime.settings, runtime.db, runtime.http)
    runtime.gmail.oauth = runtime.oauth
    session = runtime.db.create_session("alice", "fake", "default")
    registered = await build_tools(runtime, session)
    assert any(item.name == "connect_account" for item in registered)
    tools = connection_tools(runtime.settings, runtime.db, session)
    tools += journeys.bind_tool_returns(runtime.gmail.tools("alice"), runtime.db, session)
    offered = next(item for item in tools if item.name == "connect_account")
    schema = offered.input_model.model_json_schema()["properties"]["service"]
    assert set(schema["enum"]) == {"gmail", "health"}
    result = await call_tool(tools, "connect_account", service="health")
    assert parse_qs(urlsplit(result["url"]).query) == {
        "conversation": [session["id"]],
        "connect": ["health"],
    }
    assert not runtime.db.rows("SELECT * FROM oauth_states")
    result = await call_tool(tools, "gmail_connect")
    state = parse_qs(urlsplit(result["url"]).query)["state"][0]
    assert (
        journeys.authorization_return(runtime.db, "alice", "gmail", state)["destination"]
        == f"/?conversation={session['id']}&connected=gmail"
    )


async def test_delayed_status_cannot_reopen_a_dismissed_menu(runtime):
    bot = bot_for(runtime)
    await onboard(bot)
    await message(bot, "/settings")
    previous = menu(bot)
    await press(bot, "nav:done")
    before = len(bot.api.call_args_list)
    token = menus.interaction.set({"owner": "telegram:123", **previous})
    try:
        await menus.show(
            bot,
            "telegram:123",
            123,
            None,
            "Delayed provider update",
            {"inline_keyboard": []},
            "calls",
        )
    finally:
        menus.interaction.reset(token)
    assert len(bot.api.call_args_list) == before
    assert menu(bot)["closed"]


async def test_disconnect_from_a_direct_command_returns_to_its_root(runtime):
    configure(runtime.settings)
    runtime.oauth = OAuth(runtime.settings, runtime.db, runtime.http)
    bot = bot_for(runtime)
    await onboard(bot)
    await message(bot, "/gmail")
    runtime.oauth.save("telegram:123", "gmail", {"access_token": "existing"})
    runtime.db.execute("DELETE FROM oauth_states WHERE owner='telegram:123' AND service='gmail'")
    runtime.oauth._status("telegram:123", "gmail", "connected", "Account connected.")
    await press(bot, "connect:status:gmail")
    await press(bot, "connect:disconnect:gmail")
    await press(bot, "connect:remove:gmail")
    assert menu(bot)["stack"] == ["connection:gmail"]
    assert "nav:back" not in menu(bot)["actions"].values()
    assert "connect:retry:gmail" in menu(bot)["actions"].values()
    assert not runtime.db.one(
        "SELECT 1 FROM credentials WHERE owner='telegram:123' AND service='gmail'"
    )
