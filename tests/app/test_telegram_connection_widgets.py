"""Native private account controls, return prompts, and safe Telegram routing."""

import asyncio
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp.shared.auth import OAuthToken

from theos.services.zepto.auth import PendingConnection, ZeptoTokenStorage
from theos.transports.telegram.polling import Telegram

from .test_connection_setup import configured
from .test_interfaces import onboard, telegram_message
from .test_telegram_onboarding import bot_for, message


async def tap(bot, data, user=123, kind="private", chat=None):
    await bot.handle(
        [
            {
                "update_id": 900,
                "callback_query": {
                    "id": "account-button",
                    "from": {"id": user},
                    "data": data,
                    "message": {"message_id": 10, "chat": {"id": chat or user, "type": kind}},
                },
            }
        ]
    )


def card(bot):
    return [call.args[1] for call in bot.api.call_args_list if call.args[0] == "sendMessage"][-1]


def buttons(payload):
    return [button for row in payload["reply_markup"]["inline_keyboard"] for button in row]


async def ready(runtime):
    configured(runtime)
    bot = bot_for(runtime)
    await onboard(bot)
    return bot


def wait_for_return(runtime, *, https=False):
    flow = PendingConnection(
        owner="telegram:123",
        redirect_uri="https://theos.test/oauth/zepto/callback"
        if https
        else "http://localhost/callback",
        callback=asyncio.get_running_loop().create_future(),
        send_link=None,
        send_status=None,
        created=time.time(),
        state="private-state",
        authorization_url="https://shopping.test/authorize?state=private-state",
    )
    runtime.zepto.pending[flow.owner] = flow
    flow.task = asyncio.create_task(asyncio.Event().wait())
    return flow


@pytest.mark.parametrize("service", ["gmail", "health"])
async def test_google_buttons_retry_cancel_expiry_and_status_without_a_turn(runtime, service):
    bot = await ready(runtime)
    await tap(bot, "connect:" + service)
    first = card(bot)
    sign_in = next(button for button in buttons(first) if "url" in button)
    assert urlsplit(sign_in["url"]).hostname == "accounts.google.com"
    state = parse_qs(urlsplit(sign_in["url"]).query)["state"][0]
    assert state not in first["text"]
    assert {
        button.get("callback_data") for button in buttons(first) if "callback_data" in button
    } == {
        "connect:status:" + service,
        "connect:retry:" + service,
        "connect:cancel:" + service,
        "connect:menu",
    }
    await tap(bot, "connect:retry:" + service)
    second_url = next(button["url"] for button in buttons(card(bot)) if "url" in button)
    assert parse_qs(urlsplit(second_url).query)["state"][0] != state
    assert len(runtime.db.rows("SELECT * FROM oauth_states")) == 1
    with pytest.raises(ValueError, match="invalid or expired"):
        await runtime.oauth.callback(service, state, "old-code")
    runtime.db.execute("UPDATE oauth_states SET expires=0")
    await tap(bot, "connect:status:" + service)
    assert "expired" in card(bot)["text"]
    assert not any("url" in button for button in buttons(card(bot)))
    runtime.oauth.save("telegram:123", service, {"access_token": "old-account"})
    previous = runtime.db.one("SELECT encrypted FROM credentials")["encrypted"]
    await tap(bot, "connect:cancel:" + service)
    assert not runtime.db.rows("SELECT * FROM oauth_states")
    assert runtime.db.one("SELECT encrypted FROM credentials")["encrypted"] == previous
    await tap(bot, "connect:status:" + service)
    assert "is connected" in card(bot)["text"]
    await tap(bot, "connect:menu")
    assert not any(
        button.get("callback_data") == "connect:" + service for button in buttons(card(bot))
    )
    assert not runtime.db.rows("SELECT * FROM sessions")
    assert not runtime.db.rows("SELECT * FROM usage")


async def test_zepto_delayed_sign_in_and_native_paste_prompt(runtime, monkeypatch):
    bot = await ready(runtime)
    callbacks = {}

    async def connect(owner, send_link, send_status):
        callbacks.update(link=send_link, status=send_status)

    monkeypatch.setattr(runtime.zepto, "connect", connect)
    await tap(bot, "connect:zepto")
    assert "Preparing" in card(bot)["text"]
    flow = wait_for_return(runtime)
    await callbacks["link"](flow.authorization_url)
    assert "connection error" in card(bot)["text"]
    assert any(
        button.get("callback_data") == "connect:paste:zepto" for button in buttons(card(bot))
    )
    assert (
        next(button["url"] for button in buttons(card(bot)) if "url" in button)
        == flow.authorization_url
    )
    await tap(bot, "connect:paste:zepto")
    assert card(bot)["reply_markup"]["force_reply"] is True
    prompt_id = runtime.db.record("telegram:123", "telegram_connections", "zepto_return")[
        "messages"
    ][-1]
    # The owner can reply after a transport restart. Prompt records contain no OAuth values.
    restarted = Telegram(runtime)
    restarted.api = bot.api
    return_url = "http://localhost/callback?code=secret-code&state=private-state"
    update = telegram_message(return_url)
    update["update_id"] = 78
    update["message"]["reply_to_message"] = {
        "message_id": prompt_id,
        "text": "Paste the full Zepto return link",
    }
    update["message"]["entities"] = [
        {"type": "text_link", "offset": 0, "length": 1, "url": return_url}
    ]
    restarted.save_updates([update])
    payload = runtime.db.one("SELECT payload FROM telegram_updates WHERE id=78")["payload"]
    assert "secret-code" not in payload and "private-state" not in payload
    saved = json.loads(payload)
    assert "_theos_zepto_return" in saved["message"]
    await restarted.process([saved])
    assert await flow.callback == ("secret-code", "private-state")
    assert "after verification" in card(bot)["text"]
    await tap(bot, "connect:status:zepto")
    assert "Verifying" in card(bot)["text"]
    assert not any(
        button.get("callback_data") == "connect:paste:zepto" for button in buttons(card(bot))
    )
    flow.verified = True
    await ZeptoTokenStorage(runtime.settings, runtime.db, flow.owner).set_tokens(
        OAuthToken(access_token="verified-token", token_type="Bearer")
    )
    runtime.zepto._status(flow.owner, "connected", "Zepto is connected.")
    await callbacks["status"]("Zepto is connected")
    assert "is connected" in card(bot)["text"]
    assert "delivery address" in card(bot)["text"]
    assert {button.get("callback_data") for button in buttons(card(bot))} == {"connect:menu"}
    payload = runtime.db.one("SELECT payload FROM telegram_updates WHERE id=78")["payload"]
    assert "_theos_zepto_return" not in payload and "secret-code" not in payload
    assert any(call.args[0] == "deleteMessage" for call in bot.api.call_args_list)
    assert not runtime.db.rows("SELECT * FROM sessions")
    assert not runtime.db.rows("SELECT * FROM usage")


@pytest.mark.parametrize(
    "value",
    [
        "not a return URL",
        "http://localhost/callback?error=access_denied&state=private-state",
        "http://localhost/callback?code=secret-code&state=wrong-state",
        "http://localhost/callback?code=secret-code",
        "x" * 4100,
    ],
)
async def test_invalid_and_denied_prompt_replies_stay_out_of_history(runtime, value):
    bot = await ready(runtime)
    flow = wait_for_return(runtime)
    await tap(bot, "connect:paste:zepto")
    update = telegram_message(value)
    update["update_id"] = 80
    update["message"]["reply_to_message"] = {"message_id": 1}
    bot.save_updates([update])
    payload = runtime.db.one("SELECT payload FROM telegram_updates WHERE id=80")["payload"]
    assert value not in payload and "secret-code" not in payload and "private-state" not in payload
    await bot.process([json.loads(payload)])
    assert not runtime.db.rows("SELECT * FROM sessions")
    assert not runtime.db.rows("SELECT * FROM usage")
    assert any(
        button.get("callback_data") == "connect:paste:zepto" for button in buttons(card(bot))
    )
    if flow.callback.done():
        assert flow.callback.exception() is not None


async def test_expired_zepto_prompt_retry_and_cancel_preserve_previous_tokens(runtime, monkeypatch):
    bot = await ready(runtime)
    await ZeptoTokenStorage(runtime.settings, runtime.db, "telegram:123").set_tokens(
        OAuthToken(access_token="previous-token", token_type="Bearer")
    )
    previous = runtime.db.one("SELECT encrypted FROM credentials")["encrypted"]
    flow = wait_for_return(runtime)
    flow.created = 0
    await tap(bot, "connect:paste:zepto")
    assert "expired" in card(bot)["text"]
    assert "force_reply" not in card(bot)["reply_markup"]
    calls = []

    async def connect(owner, send_link, send_status):
        calls.append(owner)

    monkeypatch.setattr(runtime.zepto, "connect", connect)
    await tap(bot, "connect:retry:zepto")
    assert calls == ["telegram:123"]
    await tap(bot, "connect:cancel:zepto")
    assert runtime.db.one("SELECT encrypted FROM credentials")["encrypted"] == previous
    assert "cancelled" in card(bot)["text"]
    assert not runtime.db.rows("SELECT * FROM sessions")


async def test_https_zepto_has_no_manual_paste_control(runtime):
    bot = await ready(runtime)
    wait_for_return(runtime, https=True)
    await tap(bot, "connect:status:zepto")
    assert not any(
        button.get("callback_data") == "connect:paste:zepto" for button in buttons(card(bot))
    )
    await tap(bot, "connect:paste:zepto")
    assert "force_reply" not in card(bot)["reply_markup"]


async def test_connection_commands_and_buttons_require_private_owner_access(runtime):
    bot = await ready(runtime)
    runtime.settings.telegram_chats = {-100}
    await tap(bot, "connect:gmail", kind="group", chat=-100)
    assert not runtime.db.rows("SELECT * FROM oauth_states")
    assert bot.api.call_args.args[0] == "answerCallbackQuery"
    # A valid second user gets a different OAuth state and cannot cancel the first owner's flow.
    runtime.settings.telegram_users.add(456)
    await onboard(bot, user=456)
    await tap(bot, "connect:gmail")
    original = runtime.db.one("SELECT * FROM oauth_states WHERE owner='telegram:123'")
    await tap(bot, "connect:cancel:gmail", user=456)
    assert runtime.db.one("SELECT * FROM oauth_states WHERE owner='telegram:123'") == original
    await message(bot, "/connections")
    assert "Your accounts" in card(bot)["text"]
    await message(bot, "/gmail")
    assert any("url" in button for button in buttons(card(bot)))
    await tap(bot, "connect:paste:gmail")
    assert "unavailable" in card(bot)["text"]
    assert not runtime.db.rows("SELECT * FROM sessions")


@pytest.mark.parametrize("service", ["gmail", "health"])
async def test_google_callback_confirms_with_account_navigation(runtime, monkeypatch, service):
    from unittest.mock import AsyncMock

    from pydantic import SecretStr

    from .test_browser_connections import browser

    await ready(runtime)
    runtime.settings.telegram_token = SecretStr("test-only-bot-token")
    callback = AsyncMock(return_value="telegram:123")
    api = AsyncMock(return_value={"message_id": 92})
    monkeypatch.setattr(runtime.oauth, "callback", callback)
    monkeypatch.setattr(Telegram, "api", api)
    async with browser(runtime) as client:
        response = await client.get(
            "/oauth/" + service + "/callback?state=private-state&code=secret-code"
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/?connections=1"
    payload = api.call_args.args[1]
    assert payload["chat_id"] == 123 and "is connected" in payload["text"]
    assert buttons(payload) == [{"text": "Back to accounts", "callback_data": "connect:menu"}]
    assert "secret-code" not in json.dumps(payload) and "private-state" not in json.dumps(payload)


@pytest.mark.parametrize("prompted", [False, True])
async def test_plain_callback_and_caption_handoffs_are_encrypted(runtime, prompted):
    bot = await ready(runtime)
    flow = wait_for_return(runtime)
    return_url = "http://localhost/callback?error=access_denied&state=private-state"
    update = telegram_message(return_url)
    update["update_id"] = 81
    if prompted:
        await tap(bot, "connect:paste:zepto")
        update["message"].update(
            caption=update["message"].pop("text"),
            caption_entities=[{"type": "text_link", "url": return_url, "offset": 0, "length": 1}],
            reply_to_message={"message_id": 1},
        )
    bot.save_updates([update])
    payload = runtime.db.one("SELECT payload FROM telegram_updates WHERE id=81")["payload"]
    assert "private-state" not in payload and "access_denied" not in payload
    await bot.process([json.loads(payload)])
    assert flow.callback.exception() is not None
    assert not runtime.db.rows("SELECT * FROM sessions")
