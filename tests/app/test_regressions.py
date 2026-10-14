"""Acceptance checks for account races, confirmations, and transport recovery."""

import asyncio
import base64
import json
import time
from email.message import EmailMessage
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from harness import AssistantMessage, ToolCall
from theos.runtime.scheduler import Scheduler
from theos.services.errors import ServiceError
from theos.services.gmail.client import Gmail
from theos.services.google.oauth import SCOPES, OAuth
from theos.services.health.client import Health
from theos.transports.telegram.polling import Telegram

from .conftest import call_tool, collect
from .test_interfaces import telegram_message
from .test_oauth_gmail_health import configure


@pytest.mark.parametrize("exchange", ["refresh", "callback"])
async def test_disconnect_waits_for_token_exchange(settings, db, exchange):
    configure(settings)
    entered, release = asyncio.Event(), asyncio.Event()

    async def endpoint(request):
        if request.url.path.endswith("/token"):
            entered.set()
            await release.wait()
            return httpx.Response(
                200,
                json={
                    "access_token": "new",
                    "refresh_token": "refresh",
                    "scope": " ".join(SCOPES["gmail"]),
                },
            )
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        oauth = OAuth(settings, db, http)
        if exchange == "refresh":
            oauth.save(
                "telegram:123",
                "gmail",
                {"access_token": "old", "refresh_token": "refresh", "expires_at": 0},
            )
            task = asyncio.create_task(oauth.access_token("telegram:123", "gmail"))
        else:
            state = parse_qs(urlsplit(oauth.start("telegram:123", "gmail")).query)["state"][0]
            task = asyncio.create_task(oauth.callback("gmail", state, "code"))
        await entered.wait()
        disconnect = asyncio.create_task(oauth.disconnect("telegram:123", "gmail"))
        await asyncio.sleep(0)
        assert not disconnect.done()
        release.set()
        await asyncio.gather(task, disconnect)
        assert db.one("SELECT * FROM credentials") is None
        assert db.one("SELECT * FROM oauth_states") is None


async def test_cancel_pending_oauth_connection(settings, db):
    configure(settings)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ) as http:
        oauth = OAuth(settings, db, http)
        state = parse_qs(urlsplit(oauth.start("telegram:123", "gmail")).query)["state"][0]
        await oauth.disconnect("telegram:123", "gmail")
        with pytest.raises(ValueError, match="invalid or expired"):
            await oauth.callback("gmail", state, "code")


async def test_gmail_confirmed_send_attachment_and_labels(runtime, scripted_models):
    configure(runtime.settings)
    mail = EmailMessage()
    mail["To"], mail["Subject"] = "friend@example.org", "Report"
    mail.set_content("Please read the attached report.")
    raw = base64.urlsafe_b64encode(mail.as_bytes()).decode()
    calls = []

    def endpoint(request):
        calls.append(request)
        path = request.url.path
        if path.endswith("drafts/draft1"):
            return httpx.Response(200, json={"message": {"raw": raw, "labelIds": ["DRAFT"]}})
        if path.endswith("attachments/att1"):
            return httpx.Response(200, json={"data": base64.urlsafe_b64encode(b"report").decode()})
        if path.endswith("messages/msg1"):
            return httpx.Response(
                200,
                json={
                    "payload": {
                        "parts": [
                            {
                                "filename": "report.txt",
                                "mimeType": "text/plain",
                                "body": {"attachmentId": "att1"},
                            }
                        ]
                    }
                },
            )
        if path.endswith("threads/thread1"):
            return httpx.Response(
                200, json={"messages": [{"id": "ok"}, {"id": "spam", "labelIds": ["SPAM"]}]}
            )
        return httpx.Response(200, json={"id": "saved", "labels": [], "drafts": [], "messages": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        runtime.oauth = OAuth(runtime.settings, runtime.db, http)
        runtime.gmail = Gmail(runtime.oauth, http, runtime.files)
        runtime.oauth.save(
            "telegram:123", "gmail", {"access_token": "token", "expires_at": time.time() + 1000}
        )
        tools = runtime.gmail.tools("telegram:123")
        result = await call_tool(
            tools, "gmail_download_attachment", message_id="msg1", attachment_id="att1"
        )
        assert runtime.files.get("telegram:123", result["file_id"])["size"] == 6
        with pytest.raises(LookupError):
            await call_tool(
                tools, "gmail_download_attachment", message_id="msg1", attachment_id="foreign"
            )
        assert (
            len((await call_tool(tools, "gmail_get_thread", thread_id="thread1"))["messages"]) == 1
        )
        await call_tool(tools, "gmail_search_messages", query="report", page_token="next")
        assert "-in:spam -in:trash" in calls[-1].url.params["q"]
        await call_tool(tools, "gmail_list_drafts")
        await call_tool(
            tools,
            "gmail_create_draft",
            to="friend@example.org",
            subject="Report",
            body="Hello",
            attachment_ids=[result["file_id"]],
        )
        assert "raw" in json.loads(calls[-1].content)["message"]
        await call_tool(tools, "gmail_list_labels")
        await call_tool(tools, "gmail_create_label", name="Project")
        await call_tool(
            tools,
            "gmail_modify_labels",
            resource="msg1",
            resource_type="messages",
            add=["Label_1"],
            remove=[],
        )
        with pytest.raises(PermissionError):
            await call_tool(
                tools,
                "gmail_modify_labels",
                resource="msg1",
                resource_type="messages",
                add=["TRASH"],
                remove=[],
            )
        session = runtime.db.create_session(
            "telegram:123", "test", "default", "telegram-private", "123:0"
        )
        scripted_models.responses.append(
            [
                AssistantMessage(
                    tool_calls=[ToolCall("send", "gmail_send_draft", {"draft_id": "draft1"})]
                ),
                AssistantMessage("Sent."),
            ]
        )
        await collect(runtime.start("telegram:123", session["id"], "Send this draft"))
        assert not runtime.pending("telegram:123", session["id"])
        assert sum(r.url.path.endswith("drafts/send") for r in calls) == 1


async def test_zepto_schema_account_scope_and_order_confirmation(
    runtime, scripted_models, monkeypatch
):
    from cryptography.fernet import Fernet
    from mcp.shared.auth import OAuthToken

    from theos.services.zepto.auth import ZeptoTokenStorage
    from theos.services.zepto.tools import zepto_tools

    runtime.settings.telegram_users = {123, 456}
    runtime.settings.zepto_url = "https://shopping.test/mcp"
    runtime.settings.token_encryption_key = SecretStr(Fernet.generate_key().decode())
    await ZeptoTokenStorage(runtime.settings, runtime.db, "telegram:123").set_tokens(
        OAuthToken(access_token="owner-token", token_type="Bearer", expires_in=3600)
    )
    calls = []

    async def remote(owner, name=None, arguments=None):
        assert owner == "telegram:123"
        if name is None:
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="place_order",
                        description="Place the reviewed order",
                        inputSchema={
                            "type": "object",
                            "properties": {"cart_id": {"type": "string"}},
                            "required": ["cart_id"],
                            "additionalProperties": False,
                        },
                    ),
                    SimpleNamespace(name="zepto_shop"),
                ]
            )
        calls.append((name, arguments))
        return SimpleNamespace(isError=False, model_dump=lambda **kw: {"order_id": "1"})

    monkeypatch.setattr(runtime.zepto, "_remote", remote)
    with pytest.raises(PermissionError):
        await zepto_tools(runtime.zepto, "unconfigured-user")
    tools = await zepto_tools(runtime.zepto, "telegram:123")
    assert [tool.name for tool in tools] == ["zepto_place_order"]
    with pytest.raises(ValueError, match="schema"):
        await call_tool(tools, "zepto_place_order", arguments={"unexpected": True})
    session = runtime.db.create_session(
        "telegram:123", "test", "default", "telegram-private", "123:0"
    )
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall("order", "zepto_place_order", {"arguments": {"cart_id": "cart1"}})
                ]
            )
        ]
    )
    await collect(runtime.start("telegram:123", session["id"], "Place my order"))
    assert not calls
    approval = runtime.pending("telegram:123", session["id"])[0]
    await collect(runtime.start("telegram:123", session["id"], approval=(approval["id"], True)))
    assert calls == [("place_order", {"cart_id": "cart1"})]


async def test_telegram_shutdown_and_long_stream(runtime):
    telegram = Telegram(runtime)
    update = telegram_message()
    runtime.db.execute(
        "INSERT INTO telegram_updates(id,payload) VALUES (?,?)", (1, json.dumps(update))
    )
    entered = asyncio.Event()

    async def hang(updates):
        entered.set()
        await asyncio.Future()

    telegram.handle = hang
    task = asyncio.create_task(telegram.process([update]))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.db.one("SELECT status FROM telegram_updates")["status"] == "uncertain"
    messages = {}

    async def api(method, payload=None, files=None):
        assert len(payload["text"]) <= 4000
        if method == "sendMessage":
            message_id = len(messages) + 1
            messages[message_id] = payload["text"]
            return {"message_id": message_id}
        assert messages[payload["message_id"]] != payload["text"]
        messages[payload["message_id"]] = payload["text"]

    telegram.api = api

    async def events():
        yield {"type": "text", "text": "x" * 12000}
        yield {"type": "done", "status": "completed"}

    await telegram.render(SimpleNamespace(events=events), 123, None)
    displayed = list(messages.values())
    assert "".join(displayed[:-1]) == "x" * 12000
    assert "0 tool calls · Complete" in displayed[-1]


async def test_slow_health_work_does_not_delay_reminders(runtime):
    runtime.settings.health.client_id = "enabled"
    entered = asyncio.Event()

    async def slow_import():
        entered.set()
        await asyncio.Future()

    runtime.health.tick = slow_import
    scheduler = Scheduler(runtime)
    await scheduler.tick()
    await entered.wait()
    first_task = scheduler.health_task
    await asyncio.wait_for(scheduler.tick(), timeout=0.5)
    assert scheduler.health_task is first_task
    await scheduler.close()


async def test_health_cancelled_job_stays_cancelled(runtime):
    configure(runtime.settings)
    runtime.oauth = OAuth(runtime.settings, runtime.db, runtime.http)
    runtime.oauth.save("telegram:123", "health", {"access_token": "a", "refresh_token": "r"})
    health = Health(runtime.oauth, runtime.settings, runtime.db, runtime.http)
    runtime.db.put_record("telegram:123", "health", "last_import", {"at": time.time()})
    runtime.db.execute(
        "INSERT INTO jobs(id,owner,kind,payload,due,updated) VALUES ('j','telegram:123','nutrition','{}',0,0)"
    )

    async def export(job):
        await runtime.oauth.disconnect("telegram:123", "health")
        raise ServiceError("Disconnected during export")

    health.export = export
    await health.tick()
    assert runtime.db.one("SELECT status FROM jobs WHERE id='j'")["status"] == "cancelled"


async def test_nutrition_backfill_edits_deletion_and_retry(runtime):
    from theos.services.personal import personal_tools

    configure(runtime.settings)
    owner = "telegram:123"
    session = runtime.db.create_session(owner, "test", "default", "telegram-private", "123:0")
    tools = personal_tools(runtime.db, owner, session["id"], "UTC")
    meal = {"name": "Lunch", "calories": 500, "eaten_at": "2026-01-01T12:00:00Z"}
    saved = await call_tool(tools, "log_meal", meal=meal)
    remote = {}

    def endpoint(request):
        path = request.url.path.removeprefix("/v4/")
        if path.endswith("/identity"):
            return httpx.Response(200, json={"healthUserId": "account1"})
        if request.method == "POST":
            payload = json.loads(request.content)
            if path.endswith(":batchDelete"):
                for name in payload["names"]:
                    remote.pop(name, None)
            else:
                remote[payload["name"]] = payload
            return httpx.Response(200, json={"done": True})
        return httpx.Response(200, json=remote[path]) if path in remote else httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        oauth = OAuth(runtime.settings, runtime.db, http)
        oauth.save(owner, "health", {"access_token": "a", "expires_at": time.time() + 1000})
        health = Health(oauth, runtime.settings, runtime.db, http)
        assert health.backfill(owner) == 1
        assert health.backfill(owner) == 0

        async def finish_latest():
            for _ in range(5):
                job = runtime.db.one("SELECT * FROM jobs ORDER BY rowid DESC LIMIT 1")
                if await health.export(job):
                    runtime.db.execute(
                        "UPDATE jobs SET status='completed' WHERE id=?", (job["id"],)
                    )
                    return
            pytest.fail("Nutrition export did not finish")

        await finish_latest()
        assert len(remote) == 1
        assert "nutrients" not in next(iter(remote.values()))["nutritionLog"]
        await call_tool(tools, "edit_meal", meal_id=saved["id"], meal={**meal, "calories": 550})
        await finish_latest()
        assert len(remote) == 1 and next(iter(remote.values()))["nutritionLog"]["energy"] == {
            "kcal": 550
        }
        await call_tool(tools, "delete_meal", meal_id=saved["id"])
        await finish_latest()
        assert not remote
        runtime.db.execute("UPDATE jobs SET status='failed',attempts=5")
        assert (await call_tool(health.tools(owner), "retry_meal_sync"))["queued"] == 3
        assert all(
            row["status"] == "reconcile"
            for row in await call_tool(health.tools(owner), "get_meal_sync_status")
        )


async def test_bmp_image_keeps_original_and_supplies_png(runtime):
    from io import BytesIO
    from pathlib import Path

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (2, 2)).save(output, format="BMP")
    row = runtime.files.save("alice", "picture.bmp", "image/bmp", output.getvalue())
    assert Path(row["path"]).read_bytes().startswith(b"BM")
    assert runtime.files.image("alice", row["id"]).url.startswith("data:image/png;")


async def test_zepto_discovery_outage_allows_chat(runtime, monkeypatch):
    from cryptography.fernet import Fernet
    from mcp.shared.auth import OAuthToken
    from pydantic import SecretStr

    from theos.services.zepto.auth import ZeptoTokenStorage

    runtime.settings.telegram_users = {123}
    runtime.settings.zepto_url = "https://shopping.test/mcp"
    runtime.settings.token_encryption_key = SecretStr(Fernet.generate_key().decode())
    await ZeptoTokenStorage(runtime.settings, runtime.db, "telegram:123").set_tokens(
        OAuthToken(access_token="token", token_type="Bearer", expires_in=3600)
    )

    async def unavailable(owner, name=None, arguments=None):
        raise ServiceError("Unavailable")

    monkeypatch.setattr(runtime.zepto, "_remote", unavailable)
    session = runtime.db.create_session(
        "telegram:123", "test", "default", "telegram-private", "123:0"
    )
    assert (await collect(runtime.start("telegram:123", session["id"], "Hello")))[-1][
        "status"
    ] == "completed"
