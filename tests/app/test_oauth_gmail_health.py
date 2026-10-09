"""Account authorization and uncertain health export acceptance tests."""

import base64
import json
import time
from email.message import EmailMessage
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet

from harness import AssistantMessage, ToolCall, ToolResultMessage
from theos.services.gmail.client import Gmail
from theos.services.google.oauth import SCOPES, OAuth
from theos.services.health.client import Health
from theos.settings import OAuthSettings

from .conftest import collect


def configure(settings):
    settings.token_encryption_key = __import__("pydantic").SecretStr(Fernet.generate_key().decode())
    settings.telegram_users = {123}
    settings.gmail = OAuthSettings(
        client_id="client",
        client_secret="secret",
        redirect_uri="http://127.0.0.1/oauth/gmail/callback",
    )
    settings.health = OAuthSettings(
        client_id="client",
        client_secret="secret",
        redirect_uri="http://127.0.0.1/oauth/health/callback",
    )


async def test_oauth_state_one_use_expiry_service_binding_and_encryption(settings, db):
    configure(settings)
    requests = []

    def endpoint(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "scope": " ".join(SCOPES["gmail"]),
                "expires_in": 3600,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        oauth = OAuth(settings, db, http)
        with pytest.raises(PermissionError):
            oauth.start("unconfigured-user", "gmail")
        link = oauth.start("telegram:123", "gmail")
        query = parse_qs(urlsplit(link).query)
        assert query["code_challenge_method"] == ["S256"]
        state = query["state"][0]
        with pytest.raises(ValueError):
            await oauth.callback("health", state, "code")
        assert await oauth.callback("gmail", state, "code") == "telegram:123"
        with pytest.raises(ValueError):
            await oauth.callback("gmail", state, "code")
        assert len(requests) == 1
        stored = db.one("SELECT encrypted FROM credentials")["encrypted"]
        assert "refresh-secret" not in stored and "access-secret" not in stored
        assert await oauth.access_token("telegram:123", "gmail") == "access-secret"
        with pytest.raises(PermissionError, match="account access"):
            await oauth.access_token("telegram:999", "gmail")
        link = oauth.start("telegram:123", "gmail")
        state = parse_qs(urlsplit(link).query)["state"][0]
        db.execute("UPDATE oauth_states SET expires=0")
        with pytest.raises(ValueError):
            await oauth.callback("gmail", state, "code")


async def test_gmail_changed_draft_is_not_sent(runtime, scripted_models):
    configure(runtime.settings)
    message = EmailMessage()
    message["To"] = "friend@example.com"
    message["Subject"] = "Approved subject"
    message.set_content("Hello")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = []

    def endpoint(request):
        if request.url.path.endswith("/drafts/send"):
            sent.append(request)
            return httpx.Response(200, json={"id": "sent"})
        return httpx.Response(
            200, json={"id": "draft1", "message": {"raw": raw, "labelIds": ["DRAFT"]}}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
    runtime.oauth = OAuth(runtime.settings, runtime.db, http)
    runtime.gmail = Gmail(runtime.oauth, http, runtime.files)
    runtime.oauth.save(
        "telegram:123",
        "gmail",
        {"access_token": "token", "refresh_token": "refresh", "expires_at": time.time() + 3600},
    )
    session = runtime.db.create_session(
        "telegram:123", "test", "default", "telegram-private", "123:0"
    )
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[ToolCall("send", "gmail_send_draft", {"draft_id": "draft1"})]
            )
        ]
    )
    await collect(runtime.start("telegram:123", session["id"], "send the draft"))
    approval = runtime.pending("telegram:123", session["id"])[0]
    assert "Approved subject" in approval["preview"]
    message.replace_header("Subject", "Changed subject")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    scripted_models.responses.append([AssistantMessage("The draft changed, so I did not send it.")])
    await collect(runtime.start("telegram:123", session["id"], approval=(approval["id"], True)))
    assert not sent
    result = next(
        m
        for m in runtime.db.load_history("telegram:123", session["id"])
        if isinstance(m, ToolResultMessage)
    )
    assert result.status == "denied"
    await http.aclose()


async def test_health_reconciles_create_after_connection_loss(runtime):
    configure(runtime.settings)
    remote = {}
    writes = 0

    def endpoint(request):
        nonlocal writes
        if request.url.path.endswith("/identity"):
            return httpx.Response(200, json={"healthUserId": "account1"})
        if request.method == "POST":
            body = json.loads(request.content)
            remote[body["name"]] = body
            writes += 1
            raise httpx.ReadTimeout("lost response")
        name = request.url.path.removeprefix("/v4/")
        return httpx.Response(200, json=remote[name]) if name in remote else httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        oauth = OAuth(runtime.settings, runtime.db, http)
        oauth.save(
            "telegram:123",
            "health",
            {"access_token": "token", "refresh_token": "refresh", "expires_at": time.time() + 3600},
        )
        health = Health(oauth, runtime.settings, runtime.db, http)
        meal = {
            "name": "Lunch",
            "calories": 500,
            "protein": 20,
            "carbohydrates": 60,
            "fat": 15,
            "eaten_at": "2026-01-01T12:00:00+05:30",
        }
        value = {"meal_id": "meal1", "meal": meal, "operation": "save"}
        runtime.db.execute(
            "INSERT INTO jobs(id,owner,kind,payload,due,updated) VALUES ('j','telegram:123','nutrition',?,?,?)",
            (json.dumps(value), time.time(), time.time()),
        )
        job = runtime.db.one("SELECT * FROM jobs WHERE id='j'")
        with pytest.raises(httpx.ReadTimeout):
            await health.export(job)
        assert writes == 1
        # Restart recovery reads the exact named record instead of repeating the POST.
        job = runtime.db.one("SELECT * FROM jobs WHERE id='j'")
        assert await health.export(job)
        assert writes == 1
        assert runtime.db.record("telegram:123", "nutrition_export", "meal1")["resource"] in remote


async def test_health_disconnect_stops_jobs_even_when_revocation_fails(settings, db):
    configure(settings)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ) as http:
        oauth = OAuth(settings, db, http)
        oauth.save("telegram:123", "health", {"access_token": "a", "refresh_token": "r"})
        db.execute(
            "INSERT INTO jobs(id,owner,kind,payload,due,updated) VALUES ('j','telegram:123','nutrition','{}',0,0)"
        )
        result = await oauth.disconnect("telegram:123", "health")
        assert result == {"disconnected": True, "revoked_at_google": False}
        assert db.one("SELECT status FROM jobs")["status"] == "cancelled"
        assert db.one("SELECT * FROM credentials") is None
