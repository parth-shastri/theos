"""Only advertise calls when the deployment and current account can use them."""

import json
import time
from pathlib import Path

import httpx
import pytest

from harness import AssistantMessage, ToolCall
from theos.runtime import Runtime
from theos.runtime.scheduler import Scheduler
from theos.runtime.tools import build_tools
from theos.services.errors import ServiceError
from theos.settings import Settings
from theos.storage.database import Database

from .conftest import call_tool, collect
from .test_phone_calls import call_settings as call_settings
from .test_phone_calls import telegram_call_settings as telegram_call_settings


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"telegram_calls": {"enabled": True}},
        {"telegram_calls": {"enabled": True, "url": "https://calling.example"}},
        {"telegram_calls": {"enabled": True, "key": "k" * 32}},
        {"twilio": {"enabled": True}},
    ],
)
async def test_unset_or_incomplete_call_environment_is_not_discoverable(
    settings, db, scripted_models, config
):
    configured = Settings(_env_file=None, **{**settings.model_dump(), **config})
    runtime = Runtime(configured, db, httpx.AsyncClient(), scripted_models)
    try:
        session = db.create_session("alice", "model", "default")
        tools = {tool.name: tool for tool in await build_tools(runtime, session)}
        assert "call_user" not in tools
        schedule = tools["schedule_reminder"]
        assert "delivery" not in schedule.input_model.model_json_schema()["properties"]
        assert "phone" not in schedule.description.lower()
        assert "list_reminders" in tools and "cancel_reminder" in tools
    finally:
        await runtime.close()


@pytest.mark.parametrize("call_settings", ["twilio", "telegram"], indirect=True)
async def test_calls_are_discovered_only_for_mapped_private_accounts(
    call_settings, db, scripted_models
):
    runtime = Runtime(call_settings, db, httpx.AsyncClient(), scripted_models)
    try:
        for owner, channel, expected in (
            ("alice", "browser", True),
            ("bob", "browser", False),
            ("alice", "telegram-group", False),
            ("alice", "terminal", False),
        ):
            session = db.create_session(owner, "model", "default", channel)
            tools = {tool.name: tool for tool in await build_tools(runtime, session)}
            assert ("call_user" in tools) is expected
            properties = tools["schedule_reminder"].input_model.model_json_schema()["properties"]
            assert ("delivery" in properties) is expected
            if expected:
                assert properties["delivery"]["enum"] == ["message", "phone"]
                assert set(tools["call_user"].input_model.model_json_schema()["properties"]) == {
                    "message"
                }
        call_settings.telegram_calls.enabled = False
        call_settings.twilio.enabled = False
        session = db.create_session("alice", "model", "default")
        assert "call_user" not in {tool.name for tool in await build_tools(runtime, session)}
    finally:
        await runtime.close()


@pytest.mark.parametrize("missing", ["kokoro_url", "url", "key", "recipients"])
async def test_missing_required_telegram_call_values_hide_discovery(
    telegram_call_settings, db, scripted_models, missing
):
    config = telegram_call_settings.model_dump()
    if missing == "kokoro_url":
        config[missing] = ""
    else:
        config["telegram_calls"][missing] = {} if missing == "recipients" else ""
    runtime = Runtime(Settings(_env_file=None, **config), db, httpx.AsyncClient(), scripted_models)
    try:
        session = db.create_session("alice", "model", "default")
        tools = {tool.name: tool for tool in await build_tools(runtime, session)}
        assert "call_user" not in tools
        assert (
            "delivery"
            not in tools["schedule_reminder"].input_model.model_json_schema()["properties"]
        )
    finally:
        await runtime.close()


async def test_call_user_queues_one_owned_call_and_uses_the_existing_worker(
    telegram_call_settings, db, scripted_models
):
    requests = []

    async def provider(request):
        requests.append(request)
        if request.url.host == "speech.example":
            assert json.loads(request.content)["input"] == "This is Theos. Your account is ready."
            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"voice")
        assert request.url.params["recipient"] == "123456789"
        return httpx.Response(
            202, json={"id": request.url.path.split("/")[-1], "status": "accepted"}
        )

    runtime = Runtime(
        telegram_call_settings,
        db,
        httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        scripted_models,
    )
    scheduler = Scheduler(runtime)
    try:
        session = db.create_session("alice", "model", "default")
        scripted_models.responses.append(
            [
                AssistantMessage(
                    tool_calls=[
                        ToolCall("call-now", "call_user", {"message": "Your account is ready."})
                    ]
                ),
                AssistantMessage("Your call is queued."),
            ]
        )
        await collect(runtime.start("alice", session["id"], "Call me now."))
        job = db.one("SELECT * FROM phone_calls")
        assert job["kind"] == "request" and job["owner"] == "alice" and job["status"] == "pending"
        assert not requests
        for _ in range(2):
            await scheduler.tick()
            await scheduler.phone_task
        assert len(requests) == 2
        assert db.one("SELECT status FROM phone_calls")["status"] == "accepted"
        assert len(db.rows("SELECT * FROM notifications")) == 1
        assert not db.rows("SELECT * FROM reminders")
    finally:
        await scheduler.close()
        await runtime.close()


@pytest.mark.parametrize("change", ["disabled", "revoked"])
async def test_previously_discovered_call_tool_rechecks_current_access(
    telegram_call_settings, db, scripted_models, change
):
    runtime = Runtime(telegram_call_settings, db, httpx.AsyncClient(), scripted_models)
    try:
        session = db.create_session("alice", "model", "default")
        tools = runtime.phone_calls.tools("alice", session["id"], "browser")
        assert tools
        if change == "disabled":
            telegram_call_settings.telegram_calls.enabled = False
        else:
            telegram_call_settings.users.pop("alice")
        with pytest.raises(ServiceError, match="unavailable"):
            await call_tool(tools, "call_user", message="Your account is ready.")
        assert not db.rows("SELECT * FROM phone_calls")
        assert not db.rows("SELECT * FROM notifications")
    finally:
        await runtime.close()


def test_call_migration_preserves_existing_provider_attempts(settings):
    db = Database(settings.data_dir)
    session = db.create_session("alice", "model", "default")
    # Recreate the actual prior table, then upgrade an accepted call with private audio.
    db.execute("DROP TABLE phone_calls")
    db.execute("DROP TABLE call_connections")
    db.execute("DROP TABLE browser_login_aliases")
    previous = Path(__file__).parents[2] / "src/theos/storage/migrations/019_phone_calls.sql"
    db.connection.executescript(
        "CREATE TABLE phone_calls" + previous.read_text().split("CREATE TABLE phone_calls", 1)[1]
    )
    db.execute("PRAGMA user_version=19")
    now = time.time()
    db.execute(
        "INSERT INTO phone_calls(id,owner,session,kind,source_id,provider,due,expires,status,audio) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "existing",
            "alice",
            session["id"],
            "reminder",
            "source",
            "telegram",
            now,
            now + 120,
            "accepted",
            b"private-audio",
        ),
    )
    before = db.one("SELECT * FROM phone_calls")
    db.close()
    upgraded = Database(settings.data_dir)
    try:
        assert upgraded.one("PRAGMA user_version")["user_version"] == 22
        assert upgraded.one("SELECT * FROM phone_calls") == before
        assert not upgraded.rows("PRAGMA foreign_key_check")
    finally:
        upgraded.close()


@pytest.mark.parametrize(
    "missing",
    [
        "account_sid",
        "api_key_sid",
        "api_key_secret",
        "from_number",
        "recipients",
        "kokoro_url",
        "web_url",
        "frontend_secret",
    ],
)
async def test_missing_required_twilio_values_hide_discovery(
    settings, db, scripted_models, request, missing
):
    configured = request.getfixturevalue("call_settings")
    config = configured.model_dump()
    if missing in {"kokoro_url", "web_url", "frontend_secret"}:
        config[missing] = ""
    else:
        config["twilio"][missing] = {} if missing == "recipients" else ""
    runtime = Runtime(Settings(_env_file=None, **config), db, httpx.AsyncClient(), scripted_models)
    try:
        session = db.create_session("alice", "model", "default")
        tools = {tool.name: tool for tool in await build_tools(runtime, session)}
        assert "call_user" not in tools
        assert (
            "delivery"
            not in tools["schedule_reminder"].input_model.model_json_schema()["properties"]
        )
    finally:
        await runtime.close()
