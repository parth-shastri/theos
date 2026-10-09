"""Telegram enrollment limits, profile setup, and durable access checks."""

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from theos.runtime import Runtime
from theos.settings import Settings
from theos.storage.database import Database
from theos.transports.telegram.polling import Telegram

from .test_interfaces import telegram_message


def bot_for(runtime):
    bot = Telegram(runtime)
    bot.api = AsyncMock(return_value={"message_id": 1})
    bot.media = AsyncMock(return_value=([], ""))
    return bot


async def message(bot, text, user=123, **fields):
    update = telegram_message(text, user=user, chat=user)
    update["message"]["from"].update(first_name="Ada", last_name="Lovelace")
    update["message"].update(fields)
    await bot.handle([update])


def sent(bot):
    return [
        call.args[1]["text"] for call in bot.api.call_args_list if call.args[0] == "sendMessage"
    ]


async def test_onboarding_saves_profile_validates_timezone_and_keeps_history(runtime):
    bot = bot_for(runtime)
    await message(bot, "/start@theos_bot invite")
    assert not runtime.db.rows("SELECT * FROM sessions")
    assert (
        runtime.db.record("telegram:123", "preferences", "settings")["display_name"]
        == "Ada Lovelace"
    )
    await message(bot, "Invalid/Timezone")
    assert any("not valid" in text for text in sent(bot))
    assert runtime.db.one("SELECT state FROM telegram_enrollments")["state"] == "timezone"
    await message(bot, "/start")
    assert len(runtime.db.rows("SELECT * FROM telegram_enrollments")) == 1
    await message(bot, "Asia/Kolkata")
    assert (
        runtime.db.record("telegram:123", "preferences", "settings")["timezone"] == "Asia/Kolkata"
    )
    assert runtime.db.one("SELECT state FROM telegram_enrollments")["state"] == "ready"
    assert not runtime.db.rows("SELECT * FROM sessions")
    assert not bot.media.called
    await message(bot, "Hello")
    session = runtime.db.one("SELECT * FROM sessions")
    history = runtime.db.load_history("telegram:123", session["id"])
    assert history[0].content == "Hello"
    assert len(history) == 2
    await message(bot, "/start")
    assert runtime.db.load_history("telegram:123", session["id"]) == history
    assert (
        runtime.db.record("telegram:123", "preferences", "settings")["timezone"] == "Asia/Kolkata"
    )


async def test_setup_blocks_commands_media_and_callbacks_without_claiming_extra_slots(runtime):
    bot = bot_for(runtime)
    await message(bot, "/help")
    await message(bot, "", photo=[{"file_id": "unregistered"}])
    assert not runtime.db.rows("SELECT * FROM telegram_enrollments")
    await message(bot, "/start")
    await message(bot, "/resume")
    await message(bot, "", voice={"file_id": "pending"})
    callback = {
        "callback_query": {
            "id": "cb",
            "from": {"id": 123},
            "message": {"chat": {"id": 123, "type": "private"}},
            "data": "a:unknown",
        }
    }
    await bot.handle([callback])
    assert not bot.media.called
    assert not runtime.db.rows("SELECT * FROM sessions")
    assert not runtime.db.rows("SELECT * FROM usage")
    assert any(call.args[0] == "answerCallbackQuery" for call in bot.api.call_args_list)
    runtime.settings.timezone = "Asia/Kolkata"
    # A restart or settings change must not alter the default saved at registration.
    await message(bot, "/skip")
    assert runtime.db.record("telegram:123", "preferences", "settings")["timezone"] == "UTC"


async def test_fifty_slots_include_pending_users_and_survive_concurrent_starts(runtime):
    bot = bot_for(runtime)

    async def deliver(*args, **kwargs):
        await asyncio.sleep(0)
        return {"message_id": 1}

    bot.api.side_effect = deliver
    runtime.db.create_session("browser-owner", "model", "default")
    await asyncio.gather(*(message(bot, "/start", user) for user in range(1, 56)))
    assert len(runtime.db.rows("SELECT * FROM telegram_enrollments")) == 50
    assert len(runtime.db.rows("SELECT * FROM users")) == 51
    assert sum("Registration is full" in text for text in sent(bot)) == 5
    assert not runtime.db.one("SELECT * FROM users WHERE id='telegram:51'")
    await message(bot, "/start", 1)
    await message(bot, "/skip", 1)
    await message(bot, "Hello", 1)
    await message(bot, "/start", 1)
    await message(bot, "/start", 51)
    assert len(runtime.db.rows("SELECT * FROM telegram_enrollments")) == 50
    assert runtime.db.one("SELECT * FROM sessions WHERE owner='telegram:1'")
    assert not runtime.db.one("SELECT * FROM sessions WHERE owner='telegram:51'")


async def test_allowlist_identity_and_group_enrollment_boundaries(runtime):
    runtime.settings.telegram_users = {123}
    runtime.settings.telegram_chats = {-100}
    bot = bot_for(runtime)
    with pytest.raises(PermissionError):
        await message(bot, "/start", 456)
    for sender in ({"id": 123, "is_bot": True}, {"id": True}, {}, {"id": -1}):
        update = telegram_message("/start")
        update["message"]["from"] = sender
        with pytest.raises(PermissionError):
            await bot.handle([update])
    with pytest.raises(PermissionError):
        await bot.handle([telegram_message("/start", chat=456)])
    group = telegram_message("/start", chat=-100, kind="supergroup")
    await bot.handle([group])
    assert not runtime.db.rows("SELECT * FROM telegram_enrollments")
    await message(bot, "/start")
    await bot.handle([telegram_message(chat=-100, kind="supergroup")])
    assert not runtime.db.rows("SELECT * FROM sessions")
    await message(bot, "/skip")
    for topic in (10, 11):
        await bot.handle([telegram_message(chat=-100, kind="supergroup", topic=topic)])
    assert len(runtime.db.rows("SELECT * FROM telegram_enrollments")) == 1
    assert len(runtime.db.rows("SELECT * FROM sessions WHERE channel='telegram-group'")) == 2
    runtime.settings.telegram_users = {456}
    with pytest.raises(PermissionError):
        await message(bot, "Hello")


async def test_completed_enrollment_grants_private_account_tools(runtime):
    bot = bot_for(runtime)
    runtime.settings.gmail.client_id = "configured"
    runtime.settings.health.client_id = "configured"
    await message(bot, "/start")
    await message(bot, "/skip")
    session = bot.session("telegram:123", "telegram-private", "123:0")
    names = [tool.name for tool in await runtime.tools(session)]
    assert "gmail_connect" in names
    runtime.oauth.start = Mock(return_value="https://accounts.example/authorize")
    runtime.health.import_summary = AsyncMock(return_value={"status": "imported"})
    for command in ("/gmail", "/connect_health", "/health_refresh"):
        await message(bot, command)
    assert runtime.oauth.start.call_count == 2
    runtime.health.import_summary.assert_awaited_once_with("telegram:123")


async def test_pending_setup_and_capacity_survive_restart(settings, scripted_models):
    settings.telegram_max_users = 1
    for run in range(2):
        db = Database(settings.data_dir)
        async with httpx.AsyncClient() as http:
            runtime = Runtime(settings, db, http, scripted_models)
            try:
                bot = bot_for(runtime)
                if run == 0:
                    await message(bot, "/start")
                else:
                    await message(bot, "/start", 456)
                    assert "Registration is full" in sent(bot)[-1]
                    await message(bot, "Asia/Kolkata")
                    assert db.one("SELECT state FROM telegram_enrollments")["state"] == "ready"
                    assert (
                        db.record("telegram:123", "preferences", "settings")["display_name"]
                        == "Ada Lovelace"
                    )
            finally:
                await runtime.close()
                db.close()


def test_migration_counts_existing_private_users_once(settings):
    settings.data_dir.mkdir(exist_ok=True)
    path = settings.data_dir / "theos.sqlite3"
    connection = sqlite3.connect(path)
    migrations = Path(__file__).parents[2] / "src/theos/storage/migrations"
    for name in ("001_initial.sql", "002_delivery.sql"):
        connection.executescript((migrations / name).read_text())
    connection.execute("PRAGMA user_version=2")
    connection.executemany("INSERT INTO users VALUES (?,0)", [("telegram:123",), ("alice",)])
    for session_id in ("first", "second"):
        connection.execute(
            "INSERT INTO sessions(id,owner,channel,title,model,reasoning,created,updated) "
            "VALUES (?,'telegram:123','telegram-private','chat','model','default',0,0)",
            (session_id,),
        )
    connection.execute(
        "INSERT INTO records VALUES ('telegram:123','preferences','settings',?,0)",
        (json.dumps({"display_name": "Custom name", "timezone": "Asia/Kolkata"}),),
    )
    connection.commit()
    connection.close()
    db = Database(settings.data_dir)
    try:
        assert db.one("SELECT COUNT(*) AS total FROM telegram_enrollments")["total"] == 1
        assert db.one("SELECT state FROM telegram_enrollments")["state"] == "ready"
        assert db.record("telegram:123", "preferences", "settings")["display_name"] == "Custom name"
        assert len(db.rows("SELECT * FROM sessions")) == 2
    finally:
        db.close()


@pytest.mark.parametrize("limit", [0, 51])
def test_enrollment_limit_cannot_exceed_fifty(limit):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, telegram_max_users=limit)


def test_polling_can_enable_public_enrollment():
    settings = Settings(_env_file=None, telegram_token="test-token")
    assert settings.telegram_users == set()
    assert settings.telegram_max_users == 50


async def test_access_code_blocks_invalid_starts_before_enrollment_and_model_work(runtime):
    runtime.settings.telegram_access_code = SecretStr("test-access-code")
    bot = bot_for(runtime)
    for text in ("/start", "/start wrong", "/start неверный", "Hello", "/gmail"):
        await message(bot, text)
    assert not runtime.db.rows("SELECT * FROM telegram_enrollments")
    assert not runtime.db.rows("SELECT * FROM telegram_access")
    assert not runtime.db.rows("SELECT * FROM users")
    assert not runtime.db.rows("SELECT * FROM usage")
    assert not bot.media.called
    assert all("access code" in text for text in sent(bot))
    await message(bot, "/start@theos_bot test-access-code", message_id=44)
    assert runtime.db.one("SELECT state FROM telegram_enrollments")["state"] == "timezone"
    assert runtime.db.one("SELECT owner FROM telegram_access")["owner"] == "telegram:123"
    assert any(call.args[0] == "deleteMessage" for call in bot.api.call_args_list)
    await message(bot, "/skip")
    await message(bot, "Hello")
    session = runtime.db.one("SELECT * FROM sessions")
    assert runtime.db.load_history("telegram:123", session["id"])[0].content == "Hello"


async def test_code_is_removed_from_durable_inbox_and_valid_start_survives_restart(
    settings, scripted_models
):
    settings.telegram_access_code = SecretStr("restart-access-code")
    for run in range(3):
        db = Database(settings.data_dir)
        async with httpx.AsyncClient() as http:
            runtime = Runtime(settings, db, http, scripted_models)
            try:
                bot = bot_for(runtime)
                if run == 0:
                    update = telegram_message("/start restart-access-code", chat=123)
                    update["update_id"] = 901
                    bot.save_updates([update])
                    bad = telegram_message("/start wrong-secret", chat=123)
                    bad["update_id"] = 902
                    bot.save_updates([bad])
                    payloads = str(db.rows("SELECT payload FROM telegram_updates"))
                    assert "restart-access-code" not in payloads
                    assert "wrong-secret" not in payloads
                    assert not db.rows("SELECT * FROM telegram_access")
                elif run == 1:
                    payload = json.loads(
                        db.one("SELECT payload FROM telegram_updates WHERE id=901")["payload"]
                    )
                    await bot.process([payload])
                    await message(bot, "/skip")
                else:
                    await message(bot, "Hello")
                    assert db.one("SELECT * FROM sessions WHERE owner='telegram:123'")
                    assert db.one("SELECT COUNT(*) AS n FROM telegram_enrollments")["n"] == 1
            finally:
                await runtime.close()
                db.close()


async def test_code_rotation_requires_reauthorization_without_losing_profile(runtime):
    from theos.storage.telegram_access import account_access

    runtime.settings.telegram_access_code = SecretStr("old-code")
    bot = bot_for(runtime)
    await message(bot, "/start old-code")
    await message(bot, "Asia/Kolkata")
    assert account_access(runtime.settings, runtime.db, "telegram:123")
    runtime.settings.telegram_access_code = SecretStr("new-code")
    assert not account_access(runtime.settings, runtime.db, "telegram:123")
    await message(bot, "Hello")
    assert not runtime.db.rows("SELECT * FROM sessions")
    await message(bot, "/start old-code")
    assert "access code" in sent(bot)[-1]
    await message(bot, "/start new-code")
    assert account_access(runtime.settings, runtime.db, "telegram:123")
    assert runtime.db.one("SELECT COUNT(*) AS n FROM telegram_enrollments")["n"] == 1
    assert (
        runtime.db.record("telegram:123", "preferences", "settings")["timezone"] == "Asia/Kolkata"
    )


async def test_code_enrollment_grants_oauth_without_allowlist_and_callback_rechecks_access(runtime):
    from urllib.parse import parse_qs, urlsplit

    from theos.services.google.oauth import OAuth

    from .test_oauth_gmail_health import configure

    configure(runtime.settings)
    runtime.settings.telegram_users = set()
    runtime.settings.telegram_access_code = SecretStr("account-code")
    runtime.oauth = OAuth(runtime.settings, runtime.db, runtime.http)
    bot = bot_for(runtime)
    await message(bot, "/start account-code")
    with pytest.raises(PermissionError):
        runtime.oauth.start("telegram:123", "gmail")
    await message(bot, "/skip")
    for service in ("gmail", "health"):
        link = runtime.oauth.start("telegram:123", service)
        assert "code_challenge=" in link
    session = bot.session("telegram:123", "telegram-private", "123:0")
    assert "gmail_connect" in [tool.name for tool in await runtime.tools(session)]
    group = runtime.db.create_session("telegram:123", "test", "default", "telegram-group")
    assert "gmail_connect" not in [tool.name for tool in await runtime.tools(group)]
    state = parse_qs(urlsplit(link).query)["state"][0]
    runtime.db.execute("DELETE FROM telegram_access WHERE owner='telegram:123'")
    with pytest.raises(PermissionError):
        await runtime.oauth.callback("health", state, "unused-code")
    assert not runtime.db.rows("SELECT * FROM credentials")


async def test_code_cannot_enroll_in_group_or_bypass_capacity(runtime):
    runtime.settings.telegram_access_code = SecretStr("group-code")
    runtime.settings.telegram_chats = {-100}
    runtime.settings.telegram_max_users = 1
    bot = bot_for(runtime)
    await bot.handle([telegram_message("/start group-code", chat=-100, kind="supergroup")])
    assert not runtime.db.rows("SELECT * FROM telegram_access")
    await message(bot, "/start group-code")
    await message(bot, "/start group-code", 456)
    assert "Registration is full" in sent(bot)[-1]
    assert runtime.db.one("SELECT COUNT(*) AS n FROM telegram_access")["n"] == 1


def test_access_code_loads_from_private_env_and_is_masked(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AGENT_TELEGRAM_ACCESS_CODE=replica-code\n")
    settings = Settings(_env_file=env)
    assert settings.telegram_access_code.get_secret_value() == "replica-code"
    assert "replica-code" not in repr(settings)
