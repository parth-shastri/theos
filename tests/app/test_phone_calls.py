"""Verify call delivery through Theos and the two external HTTP contracts."""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from uuid import uuid4
from xml.etree.ElementTree import fromstring

import httpx
import pytest

from harness import AssistantMessage, ToolCall, ToolResultMessage
from theos.runtime import Runtime
from theos.runtime.scheduler import Scheduler
from theos.settings import Settings
from theos.storage.database import Database
from theos.transports.browser.app import create_app

from .conftest import collect


@pytest.fixture
def call_settings(settings, request):
    if getattr(request, "param", "twilio") == "telegram":
        return request.getfixturevalue("telegram_call_settings")
    return Settings(
        _env_file=None,
        **{
            **settings.model_dump(),
            "kokoro_url": "https://speech.example/v1",
            "kokoro_key": "k" * 32,
            "web_url": "https://theos.example",
            "frontend_secret": "f" * 32,
            "twilio": {
                "enabled": True,
                "account_sid": "AC" + "a" * 32,
                "api_key_sid": "SK" + "b" * 32,
                "api_key_secret": "s" * 32,
                "from_number": "+12025550100",
                "recipients": {"alice": "+919000000000"},
            },
        },
    )


async def schedule(runtime, scripted_models, session, *, delivery="phone"):
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall(
                        uuid4().hex,
                        "schedule_reminder",
                        {
                            "text": "Take the 8 milligram dose.",
                            "due": (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
                            **({"delivery": delivery} if delivery != "message" else {}),
                        },
                    )
                ]
            ),
            AssistantMessage("I checked the reminder."),
        ]
    )
    await collect(runtime.start(session["owner"], session["id"], "Schedule my reminder"))
    return next(
        message
        for message in reversed(runtime.db.load_history(session["owner"], session["id"]))
        if isinstance(message, ToolResultMessage)
    )


async def dispatch(scheduler):
    await scheduler.tick()
    await scheduler.phone_task


async def test_reminder_plays_app_voice_and_keeps_the_written_notice(
    call_settings, db, scripted_models
):
    requests = []
    media_urls = []

    async def provider(request):
        requests.append(request)
        if request.url.host == "speech.example":
            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"voice")
        assert request.url.host == "api.twilio.com"
        assert request.url.path.endswith(f"/{call_settings.twilio.account_sid}/Calls.json")
        assert request.headers["authorization"].startswith("Basic ")
        params = parse_qs(request.content.decode())
        assert params["From"] == ["+12025550100"]
        assert params["To"] == ["+919000000000"]
        xml = fromstring(params["Twiml"][0])
        assert [node.tag for node in xml] == ["Play", "Hangup"]
        media_urls.append(xml.findtext("Play"))
        assert media_urls[0].startswith("https://theos.example/api/audio/phone-call/")
        # Twilio can fetch audio even before the Calls API response reaches Theos.
        preview = await browser.get(media_urls[0], headers=frontend)
        assert preview.content == b"voice" and preview.headers["content-type"] == "audio/mpeg"
        assert preview.headers["cache-control"] == "no-store"
        return httpx.Response(201, json={"sid": "CA" + "a" * 32})

    runtime = Runtime(
        call_settings,
        db,
        httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        scripted_models,
    )
    scheduler = Scheduler(runtime)
    frontend = {"X-Theos-Frontend-Secret": call_settings.frontend_secret.get_secret_value()}
    app = create_app(call_settings, runtime)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as browser:
            alice = db.create_session("alice", "model", "default")
            bob = db.create_session("bob", "model", "default")
            group = db.create_session("alice", "model", "default", "telegram-group")
            for session in (bob, group):
                result = await schedule(runtime, scripted_models, session)
                assert result.status == "not_started" and "delivery" in result.content
            phone = await schedule(runtime, scripted_models, alice)
            assert phone.status == "completed"
            reminder_id = json.loads(phone.content)["id"]
            assert (await schedule(runtime, scripted_models, bob, delivery="message")).status == (
                "completed"
            )
            db.execute("UPDATE reminders SET due=?", (time.time() - 2,))
            await dispatch(scheduler)
            await dispatch(scheduler)

            assert len(requests) == 2
            assert requests[0].headers["authorization"] == "Bearer " + "k" * 32
            assert json.loads(requests[0].content) == {
                "model": "kokoro",
                "voice": call_settings.kokoro_voice,
                "speed": call_settings.kokoro_speed,
                "input": "This is Theos. Take the 8 milligram dose.",
                "response_format": "mp3",
            }
            assert db.one("SELECT status FROM phone_calls WHERE source_id=?", (reminder_id,)) == {
                "status": "accepted"
            }
            assert len(db.rows("SELECT * FROM notifications")) == 2
            assert db.one("SELECT count(*) AS count FROM files")["count"] == 0
            assert (await browser.get(media_urls[0])).status_code == 403
            db.execute("UPDATE phone_calls SET audio_expires=?", (time.time() - 1,))
            assert (await browser.get(media_urls[0], headers=frontend)).status_code == 404
    finally:
        await scheduler.close()
        await runtime.close()


@pytest.mark.parametrize("call_settings", ["twilio", "telegram"], indirect=True)
async def test_approval_call_waits_and_rechecks_after_synthesis(
    call_settings, db, scripted_models, checkout_tool
):
    speech = []
    dialed = []

    async def provider(request):
        if request.url.host == "speech.example":
            speech.append(json.loads(request.content)["input"])
            if len(speech) == 1:
                # Simulate a user decision arriving while the speech service is working.
                await collect(runtime.start("alice", resolved["id"], approval=(first["id"], False)))
            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"voice")
        dialed.append(request)
        raise httpx.ReadTimeout("unknown call outcome", request=request)

    runtime = Runtime(
        call_settings,
        db,
        httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        scripted_models,
    )
    scheduler = Scheduler(runtime)
    try:
        resolved, pending = [db.create_session("alice", "model", "default") for _ in range(2)]
        for session in (resolved, pending):
            scripted_models.responses.append(
                [
                    AssistantMessage(
                        tool_calls=[
                            ToolCall("checkout", "zepto_confirm_cart", {"name": "private detail"})
                        ]
                    )
                ]
            )
            await collect(runtime.start("alice", session["id"], "Prepare an order"))
        first = runtime.pending("alice", resolved["id"])[0]
        second = runtime.pending("alice", pending["id"])[0]
        slots = db.rows(
            "SELECT c.due-a.created AS delay FROM phone_calls c JOIN approvals a ON c.id=a.id"
        )
        assert [slot["delay"] for slot in slots] == [120, 120]
        await dispatch(scheduler)
        assert not speech
        db.execute("UPDATE phone_calls SET due=? WHERE id=?", (time.time() - 4, first["id"]))
        db.execute("UPDATE phone_calls SET due=? WHERE id=?", (time.time() - 2, second["id"]))
        await dispatch(scheduler)
        await dispatch(scheduler)
        assert len(dialed) == 1
        assert (
            speech
            == ["This is Theos. A request is waiting for your approval. Open Theos to review it."]
            * 2
        )
        assert db.one("SELECT status FROM phone_calls WHERE id=?", (first["id"],)) == {
            "status": "skipped"
        }
        assert db.one("SELECT status FROM phone_calls WHERE id=?", (second["id"],)) == {
            "status": "uncertain"
        }
        assert runtime.pending("alice", pending["id"])[0]["id"] == second["id"]
    finally:
        await scheduler.close()
        await runtime.close()


@pytest.mark.parametrize("call_settings", ["twilio", "telegram"], indirect=True)
async def test_restart_does_not_repeat_interrupted_dial(call_settings, scripted_models):
    db = Database(call_settings.data_dir)
    attempted = asyncio.Event()

    async def provider(request):
        if request.url.host == "speech.example":
            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"voice")
        attempted.set()
        await asyncio.Future()

    runtime = Runtime(
        call_settings,
        db,
        httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        scripted_models,
    )
    scheduler = Scheduler(runtime)
    try:
        session = db.create_session("alice", "model", "default")
        assert (await schedule(runtime, scripted_models, session)).status == "completed"
        db.execute("UPDATE reminders SET due=?", (time.time() - 2,))
        await scheduler.tick()
        await asyncio.wait_for(attempted.wait(), timeout=2)
    finally:
        await scheduler.close()
        await runtime.close()
        db.close()

    reopened = Database(call_settings.data_dir)
    try:
        assert reopened.one("SELECT status FROM phone_calls") == {"status": "uncertain"}
        assert reopened.one("SELECT count(*) AS count FROM notifications")["count"] == 1
    finally:
        reopened.close()


@pytest.fixture
def telegram_call_settings(settings):
    return Settings(
        _env_file=None,
        **{
            **settings.model_dump(),
            "kokoro_url": "https://speech.example/v1",
            "kokoro_key": "k" * 32,
            "telegram_calls": {
                "enabled": True,
                "url": "http://calling.example:8882",
                "key": "g" * 32,
                "recipients": {"alice": 123456789},
            },
        },
    )


@pytest.mark.parametrize("outcome", ["accepted", "timeout", "rejected"])
async def test_telegram_reminder_posts_private_audio_once(
    telegram_call_settings, db, scripted_models, outcome
):
    dialed = []
    speech = []

    async def provider(request):
        if request.url.host == "speech.example":
            speech.append(json.loads(request.content))
            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"voice")
        dialed.append(request)
        assert request.url.host == "calling.example"
        assert request.headers["authorization"] == "Bearer " + "g" * 32
        assert request.headers["content-type"] == "audio/mpeg"
        assert request.content == b"voice"
        assert request.url.params["recipient"] == "123456789"
        assert float(request.url.params["expires"]) > time.time()
        if outcome == "timeout":
            raise httpx.ReadTimeout("unknown call outcome", request=request)
        if outcome == "rejected":
            return httpx.Response(403)
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
        alice = db.create_session("alice", "model", "default")
        bob = db.create_session("bob", "model", "default")
        group = db.create_session("alice", "model", "default", "telegram-group")
        for other in (bob, group):
            assert (await schedule(runtime, scripted_models, other)).status == "not_started"
        assert (await schedule(runtime, scripted_models, alice)).status == "completed"
        db.execute("UPDATE reminders SET due=?", (time.time() - 1,))
        await dispatch(scheduler)
        await dispatch(scheduler)
        assert len(dialed) == 1
        assert speech[0]["voice"] == telegram_call_settings.kokoro_voice
        assert speech[0]["speed"] == telegram_call_settings.kokoro_speed
        assert speech[0]["input"] == "This is Theos. Take the 8 milligram dose."
        row = db.one("SELECT * FROM phone_calls")
        assert row["provider"] == "telegram"
        assert (
            row["status"]
            == {"accepted": "accepted", "timeout": "uncertain", "rejected": "failed"}[outcome]
        )
        assert row["audio"] is None and row["audio_digest"] is None
        assert len(db.rows("SELECT * FROM notifications")) == 1
        with pytest.raises(LookupError):
            runtime.phone_calls.audio("x" * 43)
    finally:
        await scheduler.close()
        await runtime.close()


def test_call_provider_configuration_is_explicit(telegram_call_settings):
    from pydantic import ValidationError

    config = telegram_call_settings.model_dump()
    with pytest.raises(ValidationError, match="one call provider"):
        Settings(
            _env_file=None,
            **{
                **config,
                "twilio": {
                    "enabled": True,
                    "account_sid": "AC" + "a" * 32,
                    "api_key_sid": "SK" + "b" * 32,
                    "api_key_secret": "s" * 32,
                    "from_number": "+12025550100",
                    "recipients": {"alice": "+919000000000"},
                },
            },
        )
    for invalid in (
        {"recipients": {"alice": -1001}},
        {"recipients": {"unknown": 123456789}},
        {"url": "http://user:password@calling.example"},
        {"key": "short"},
    ):
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                **{**config, "telegram_calls": {**config["telegram_calls"], **invalid}},
            )


@pytest.mark.parametrize(
    "case", ["cancelled", "expired", "rate_limited", "voice_error", "provider_changed", "revoked"]
)
async def test_telegram_call_rechecks_source_and_delivery_limits(
    telegram_call_settings, db, scripted_models, case
):
    speech = []

    async def provider(request):
        assert request.url.host == "speech.example"
        speech.append(request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"not audio")

    runtime = Runtime(
        telegram_call_settings,
        db,
        httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        scripted_models,
    )
    scheduler = Scheduler(runtime)
    try:
        session = db.create_session("alice", "model", "default")
        assert (await schedule(runtime, scripted_models, session)).status == "completed"
        db.execute("UPDATE reminders SET due=?", (time.time() - 1,))
        scheduler.reminders(time.time())
        if case == "cancelled":
            db.execute("UPDATE reminders SET status='cancelled'")
        elif case == "expired":
            db.execute("UPDATE phone_calls SET expires=?", (time.time() - 1,))
        elif case == "rate_limited":
            telegram_call_settings.telegram_calls.daily_limit = 1
            db.execute("UPDATE phone_calls SET attempted=?", (time.time(),))
        elif case == "provider_changed":
            db.execute("UPDATE phone_calls SET provider='twilio'")
        elif case == "revoked":
            telegram_call_settings.users.pop("alice")
        await dispatch(scheduler)
        await dispatch(scheduler)
        expected = (
            "failed"
            if case == "voice_error"
            else "rate_limited"
            if case == "rate_limited"
            else "skipped"
        )
        assert db.one("SELECT status FROM phone_calls")["status"] == expected
        assert len(speech) == (1 if case == "voice_error" else 0)
        assert len(db.rows("SELECT * FROM notifications")) == 1
    finally:
        await scheduler.close()
        await runtime.close()
