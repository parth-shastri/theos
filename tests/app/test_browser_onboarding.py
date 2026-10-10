"""Telegram-confirmed UI access, credential persistence, and user isolation."""

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from theos.runtime import Runtime
from theos.server import create_app
from theos.settings import Settings
from theos.storage import browser_access
from theos.storage.database import Database
from theos.transports.telegram.polling import Telegram

from .test_interfaces import telegram_message
from .test_telegram_onboarding import bot_for, message

HEADERS = {"X-Theos-Request": "1", "Origin": "https://theos.test"}


@pytest.fixture
def web_bot(runtime, monkeypatch):
    runtime.settings.web_url = "https://theos.test"
    runtime.settings.telegram_token = SecretStr("test-bot-token")
    monkeypatch.setattr(Telegram, "api", AsyncMock(return_value={"message_id": 1}))
    return bot_for(runtime)


async def enroll(bot, user=123):
    await message(bot, "/start", user)
    await message(bot, f"Preferred {user}", user)
    await message(bot, "UTC", user)
    urls = [
        button["url"]
        for call in bot.api.call_args_list
        if call.args[0] == "sendMessage" and call.args[1]["chat_id"] == user
        for row in call.args[1].get("reply_markup", {}).get("inline_keyboard", [])
        for button in row
        if "url" in button
    ]
    assert len(urls) == 1
    assert urlsplit(urls[0]).query == ""
    return parse_qs(urlsplit(urls[0]).fragment)["onboard"][0]


async def confirm(bot, request_id, user=123, approved=True):
    await bot.handle(
        [
            {
                "callback_query": {
                    "id": "confirmation",
                    "from": {"id": user},
                    "message": {"chat": {"id": user, "type": "private"}},
                    "data": ("web:" if approved else "webdeny:") + request_id,
                }
            }
        ]
    )


def client(runtime, headers=HEADERS):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="https://theos.test",
        headers=headers,
    )


async def test_telegram_onboarding_opens_own_ui_and_keeps_seed_admin_separate(runtime, web_bot):
    invite = await enroll(web_bot)
    await enroll(web_bot, 456)
    assert not runtime.db.rows("SELECT * FROM sessions")
    assert not runtime.db.rows("SELECT * FROM browser_credentials")
    other = runtime.db.create_session("telegram:456", "model", "default")
    async with client(runtime) as browser:
        started = await browser.post("/api/onboarding/start", json={"invite": invite})
        assert started.status_code == 200
        assert started.headers["cache-control"] == "no-store"
        cookie = started.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        row = runtime.db.one("SELECT * FROM browser_signins WHERE owner='telegram:123'")
        assert started.json()["code"] == row["code"]
        assert (await browser.get("/api/me")).status_code == 401
        assert (await browser.post("/api/onboarding/complete")).status_code == 400
        await confirm(web_bot, row["id"], user=456)
        assert (await browser.get("/api/onboarding/status")).json()["state"] == "pending"
        await confirm(web_bot, row["id"])
        # The same browser can recover its status after reload before consuming approval.
        assert (await browser.get("/api/onboarding/status")).json()["state"] == "approved"
        completed = await browser.post("/api/onboarding/complete")
        assert completed.status_code == 200
        saved_token = completed.json()["token"]
        assert len(saved_token) >= 32
        me = (await browser.get("/api/me")).json()
        assert me["id"] == "telegram:123"
        assert me["display_name"] == "Preferred 123"
        assert me["admin"] is False
        assert (await browser.get("/api/dashboard")).status_code == 403
        assert (await browser.get("/api/logs")).status_code == 403
        assert (await browser.get(f"/api/sessions/{other['id']}")).status_code == 404
        session = (await browser.post("/api/sessions", json={})).json()
        assert session["owner"] == "telegram:123"
        response = await browser.post(f"/api/sessions/{session['id']}/turn", json={"text": "Hello"})
        assert '"status": "completed"' in response.text
        await message(web_bot, "Hello from Telegram")
        activity = (await browser.get("/api/activity?owner=telegram:456")).json()
        assert activity["totals"]["conversations"] == 2
        assert activity["usage"]
        assert all(row["owner"] == "telegram:123" for row in activity["usage"])
        assert {row["channel"] for row in activity["cost_per_conversation"]} == {
            "browser",
            "telegram-private",
        }
        assert (await browser.post("/api/onboarding/complete")).status_code == 400
        assert (
            await browser.get("/api/me", headers={"Authorization": "Bearer invalid"})
        ).status_code == 401
        assert (await browser.post("/api/auth/logout")).status_code == 200
        assert (await browser.get("/api/me")).status_code == 401
    async with client(runtime, {"Authorization": "Bearer " + saved_token}) as browser:
        assert (await browser.get("/api/me")).json()["id"] == "telegram:123"
        assert (await browser.get(f"/api/sessions/{session['id']}")).status_code == 200
        assert (await browser.get("/api/connections")).status_code == 200
        assert {item["id"] for item in (await browser.get("/api/terminal/sessions")).json()} == {
            session["id"]
        }
        assert (await browser.get("/api/dashboard")).status_code == 403
    async with client(runtime, {"Authorization": "Bearer " + "a" * 32}) as browser:
        assert (await browser.get("/api/me")).json()["admin"] is True
        assert (await browser.get("/api/dashboard")).status_code == 200
        assert (await browser.get(f"/api/sessions/{session['id']}")).status_code == 404
    stored = str(runtime.db.rows("SELECT * FROM browser_credentials"))
    assert saved_token not in stored
    assert invite not in str(runtime.db.rows("SELECT * FROM browser_signins"))


async def test_links_are_single_use_browser_bound_and_requests_can_be_denied(runtime, web_bot):
    invite = await enroll(web_bot)
    async with client(runtime) as browser, client(runtime) as stranger:
        assert (
            await browser.post("/api/onboarding/start", json={"invite": invite, "owner": "alice"})
        ).status_code == 422
        assert (
            await browser.post("/api/onboarding/start", json={"invite": invite})
        ).status_code == 200
        assert (
            await stranger.post("/api/onboarding/start", json={"invite": invite})
        ).status_code == 400
        assert (await stranger.get("/api/onboarding/status")).status_code == 400
        row = runtime.db.one("SELECT * FROM browser_signins")
        await confirm(web_bot, row["id"], approved=False)
        assert (await browser.get("/api/onboarding/status")).json()["state"] == "denied"
        assert (await browser.post("/api/onboarding/complete")).status_code == 400
        await confirm(web_bot, row["id"])
        assert (await browser.get("/api/onboarding/status")).json()["state"] == "denied"
        assert not runtime.db.rows("SELECT * FROM browser_credentials")


async def test_cookie_mutations_require_same_origin_and_cancel_prevents_late_approval(
    runtime, web_bot
):
    invite = await enroll(web_bot)
    async with client(runtime, {}) as browser:
        assert (
            await browser.post("/api/onboarding/start", json={"invite": invite})
        ).status_code == 403
        assert (
            await browser.post(
                "/api/onboarding/start",
                json={"invite": invite},
                headers={**HEADERS, "Origin": "https://evil.test"},
            )
        ).status_code == 403
        browser.headers.update(HEADERS)
        await browser.post("/api/onboarding/start", json={"invite": invite})
        row = runtime.db.one("SELECT * FROM browser_signins")
        assert (await browser.post("/api/onboarding/cancel")).status_code == 200
        await confirm(web_bot, row["id"])
        assert runtime.db.one("SELECT state FROM browser_signins")["state"] == "denied"
        assert (await browser.post("/api/onboarding/complete")).status_code == 400
        fresh = browser_access.invite(runtime.settings, runtime.db, "telegram:123")
        await browser.post("/api/onboarding/start", json={"invite": fresh})
        row = runtime.db.one("SELECT * FROM browser_signins")
        await confirm(web_bot, row["id"])
        await browser.post("/api/onboarding/complete")
        browser.headers.clear()
        assert (await browser.post("/api/sessions", json={})).status_code == 403
        assert (
            await browser.post(
                "/api/sessions", json={}, headers={**HEADERS, "Origin": "https://evil.test"}
            )
        ).status_code == 403
        assert (await browser.post("/api/sessions", json={}, headers=HEADERS)).status_code == 200
        assert (
            await browser.post(
                "/api/auth/logout", headers={**HEADERS, "Origin": "https://theos.test"}
            )
        ).status_code == 200


async def test_expiry_revocation_and_access_code_rotation_preserve_data(runtime, web_bot):
    runtime.settings.telegram_access_code = SecretStr("deployment-code")
    await message(web_bot, "/start deployment-code")
    await message(web_bot, "Ada")
    await message(web_bot, "UTC")
    old = browser_access.invite(runtime.settings, runtime.db, "telegram:123")
    fresh = browser_access.invite(runtime.settings, runtime.db, "telegram:123")
    with pytest.raises(ValueError):
        browser_access.begin(runtime.settings, runtime.db, old)
    row, pairing = browser_access.begin(runtime.settings, runtime.db, fresh)
    runtime.db.execute("UPDATE browser_signins SET expires=0")
    with pytest.raises(ValueError):
        browser_access.confirm(runtime.settings, runtime.db, "telegram:123", row["id"], True)
    fresh = browser_access.invite(runtime.settings, runtime.db, "telegram:123")
    row, pairing = browser_access.begin(runtime.settings, runtime.db, fresh)
    browser_access.confirm(runtime.settings, runtime.db, "telegram:123", row["id"], True)
    owner, token, session = browser_access.complete(runtime.settings, runtime.db, pairing)
    assert browser_access.credential_owner(runtime.settings, runtime.db, token, "token") == owner
    runtime.db.execute("UPDATE browser_credentials SET expires=0 WHERE kind='session'")
    assert browser_access.credential_owner(runtime.settings, runtime.db, session, "session") is None
    runtime.settings.telegram_access_code = SecretStr("changed-code")
    assert browser_access.credential_owner(runtime.settings, runtime.db, token, "token") is None
    await message(web_bot, "/start changed-code")
    assert browser_access.credential_owner(runtime.settings, runtime.db, token, "token") == owner
    await message(web_bot, "/web revoke")
    assert browser_access.credential_owner(runtime.settings, runtime.db, token, "token") is None
    assert runtime.db.record(owner, "preferences", "settings")["display_name"] == "Ada"
    assert not runtime.db.rows("SELECT * FROM browser_credentials")


async def test_new_signin_rotates_saved_token_and_retains_other_device_sessions(runtime, web_bot):
    await enroll(web_bot)
    credentials = []
    for _ in range(2):
        secret = browser_access.invite(runtime.settings, runtime.db, "telegram:123")
        row, pairing = browser_access.begin(runtime.settings, runtime.db, secret)
        browser_access.confirm(runtime.settings, runtime.db, "telegram:123", row["id"], True)
        credentials.append(browser_access.complete(runtime.settings, runtime.db, pairing))
    owner, old_token, old_session = credentials[0]
    assert browser_access.credential_owner(runtime.settings, runtime.db, old_token, "token") is None
    assert (
        browser_access.credential_owner(runtime.settings, runtime.db, old_session, "session")
        == owner
    )
    assert (
        browser_access.credential_owner(runtime.settings, runtime.db, credentials[1][1], "token")
        == owner
    )
    runtime.settings.telegram_users = {456}
    assert (
        browser_access.credential_owner(runtime.settings, runtime.db, credentials[1][1], "token")
        is None
    )
    assert (
        browser_access.credential_owner(runtime.settings, runtime.db, old_session, "session")
        is None
    )


async def test_pending_profiles_groups_and_missing_configuration_do_not_issue_access(
    runtime, web_bot
):
    await message(web_bot, "/start")
    await message(web_bot, "/web")
    assert not runtime.db.rows("SELECT * FROM browser_signins")
    await message(web_bot, "Ada")
    await message(web_bot, "UTC")
    runtime.settings.telegram_chats = {-100}
    before = runtime.db.rows("SELECT * FROM browser_signins")
    await web_bot.handle([telegram_message("/web", chat=-100, kind="supergroup")])
    assert runtime.db.rows("SELECT * FROM browser_signins") == before
    runtime.settings.web_url = ""
    await message(web_bot, "/web")
    assert runtime.db.rows("SELECT * FROM browser_signins") == before


async def test_confirmation_delivery_failure_issues_no_credentials(runtime, web_bot, monkeypatch):
    invite = await enroll(web_bot)
    monkeypatch.setattr(Telegram, "send", AsyncMock(side_effect=RuntimeError("sensitive detail")))
    async with client(runtime) as browser:
        response = await browser.post("/api/onboarding/start", json={"invite": invite})
        assert response.status_code == 503
        assert "sensitive detail" not in response.text
        assert not runtime.db.rows("SELECT * FROM browser_credentials")
        assert (await browser.get("/api/me")).status_code == 401


async def test_generated_token_and_approved_signin_survive_restart(settings, scripted_models):
    settings.web_url = "https://theos.test"
    token = ""
    for run in range(3):
        db = Database(settings.data_dir)
        runtime = Runtime(settings, db, models=scripted_models)
        try:
            if run == 0:
                db.ensure_user("telegram:123")
                db.execute("INSERT INTO telegram_enrollments VALUES (123,'telegram:123','ready',0)")
                secret = browser_access.invite(settings, db, "telegram:123")
                row, pairing = browser_access.begin(settings, db, secret)
                browser_access.confirm(settings, db, "telegram:123", row["id"], True)
            elif run == 1:
                _, token, _ = browser_access.complete(settings, db, pairing)
            else:
                async with client(runtime, {"Authorization": "Bearer " + token}) as browser:
                    assert (await browser.get("/api/me")).json()["id"] == "telegram:123"
                    assert (await browser.get("/api/dashboard")).status_code == 403
        finally:
            await runtime.close()
            db.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://theos.test",
        "https://user:secret@theos.test",
        "https://theos.test/path",
        "https://theos.test?token=secret",
        "https://theos.test#fragment",
    ],
)
def test_web_origin_configuration_rejects_unsafe_addresses(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, web_url=url)


def test_web_origin_accepts_https_and_local_development():
    assert Settings(_env_file=None, web_url="https://theos.test/").web_url == "https://theos.test"
    assert (
        Settings(_env_file=None, web_url="http://127.0.0.1:8080").web_url == "http://127.0.0.1:8080"
    )
