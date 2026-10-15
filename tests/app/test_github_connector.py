"""Official GitHub MCP integration through private Theos accounts."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import SecretStr, ValidationError

from harness import AssistantMessage, ToolCall
from theos.server import create_app
from theos.services.errors import ServiceError
from theos.services.github import READ_TOOLS, create_account
from theos.settings import Settings

from .conftest import collect
from .test_browser_connections import browser


@pytest.fixture
def connector(runtime):
    runtime.settings.token_encryption_key = SecretStr(Fernet.generate_key().decode())
    kind = type(runtime.settings.github)
    runtime.settings.github = kind(
        client_id="client",
        client_secret="private-client",
        redirect_uri="https://assistant.test/oauth/github/callback",
    )
    runtime.github = create_account(runtime.settings, runtime.db, runtime.http)
    return runtime.github


def token_payload(account):
    return {
        "access_token": "account-secret",
        "refresh_token": "refresh-secret",
        "scope": " ".join(account.scopes),
        "expires_in": 3600,
        "token_type": "user" if account.spec.name == "slack" else "bearer",
    }


def test_enabled_connector_requires_encryption_and_registered_callback():
    fields = dict(
        client_id="client",
        client_secret="secret",
        redirect_uri="https://assistant.test/oauth/github/callback",
    )
    with pytest.raises(ValidationError, match="encryption key"):
        Settings(_env_file=None, github=fields)
    fields["redirect_uri"] = "https://assistant.test/oauth/other/callback"
    with pytest.raises(ValidationError, match="callback"):
        Settings(_env_file=None, github=fields, token_encryption_key=Fernet.generate_key().decode())


async def test_browser_oauth_connections_bind_callback_to_original_owner(runtime, connector):
    def remote(request):
        assert str(request.url) == connector.spec.token_url
        data = parse_qs(request.content.decode())
        assert data["code_verifier"] and data["redirect_uri"]
        return httpx.Response(200, json=token_payload(connector))

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        connector.http = http
        async with browser(runtime) as alice, browser(runtime, "bob") as bob:
            started = (
                await alice.post("/api/connections/github/connect", json={"owner": "bob"})
            ).json()
            query = parse_qs(urlsplit(started["url"]).query)
            assert query["code_challenge_method"] == ["S256"]
            state = query["state"][0]
            response = await bob.get(
                "/oauth/github/callback", params={"state": state, "code": "private-code"}
            )
            assert response.status_code == 200
            assert "Return to the workspace" in response.text
            assert connector.connected("alice") and not connector.connected("bob")
            assert (
                await alice.get("/oauth/github/callback", params={"state": state, "code": "replay"})
            ).status_code == 400
            a = (await alice.get("/api/connections")).json()
            b = (await bob.get("/api/connections")).json()
            assert next(x for x in a["accounts"] if x["id"] == "github")["connected"]
            assert not next(x for x in b["accounts"] if x["id"] == "github")["connected"]
            assert "secret" not in json.dumps(a)
            encrypted = runtime.db.one(
                "SELECT encrypted FROM credentials WHERE owner=? AND service=?", ("alice", "github")
            )
            assert "account-secret" not in encrypted["encrypted"]
            restored = create_account(runtime.settings, runtime.db, http)
            assert await restored.access_token("alice") == "account-secret"
            await bob.post("/api/connections/github/disconnect")
            assert connector.connected("alice")
            await alice.post("/api/connections/github/disconnect")
            assert not restored.connected("alice")


async def test_denied_browser_consent_and_cancellation_do_not_issue_tokens(runtime, connector):
    async with browser(runtime) as client:
        link = (await client.post("/api/connections/github/connect")).json()["url"]
        state = parse_qs(urlsplit(link).query)["state"][0]
        denied = await client.get(
            "/oauth/github/callback", params={"state": state, "error": "access_denied"}
        )
        assert denied.status_code == 400
        assert not connector.connected("alice")
        assert not runtime.db.one("SELECT 1 FROM oauth_states WHERE service='github'")
        link = (await client.post("/api/connections/github/connect")).json()["url"]
        state = parse_qs(urlsplit(link).query)["state"][0]
        await client.post("/api/connections/github/disconnect")
        assert (
            await client.get("/oauth/github/callback", params={"state": state, "code": "code"})
        ).status_code == 400


async def test_runtime_read_is_owner_scoped_paged_and_durably_saved(
    runtime, connector, scripted_models, monkeypatch
):
    connector.save("alice", token_payload(connector))
    calls = []

    async def remote(owner, name=None, arguments=None):
        assert owner == "alice"
        if name is None:
            return [
                Tool(
                    name="get_file_contents",
                    inputSchema={
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                        "required": ["id"],
                        "additionalProperties": False,
                    },
                ),
                Tool(name="create_pull_request", inputSchema={"type": "object"}),
                Tool(name="new_unknown_tool", inputSchema={"type": "object"}),
            ]
        calls.append((name, arguments))
        return CallToolResult(content=[TextContent(type="text", text="source evidence " * 1600)])

    monkeypatch.setattr(connector, "remote", remote)
    session = runtime.db.create_session(
        "alice", runtime.settings.model, "default", channel="browser"
    )
    for owner, channel in [("bob", "browser"), ("alice", "telegram-group"), ("alice", "terminal")]:
        other = runtime.db.create_session(owner, runtime.settings.model, "default", channel=channel)
        assert not any(t.name.startswith("github_") for t in await runtime.tools(other))
    for channel in ("browser", "telegram-private"):
        row = runtime.db.create_session("alice", runtime.settings.model, "default", channel=channel)
        names = {t.name for t in await runtime.tools(row)}
        assert "github_get_file_contents" in names
        assert not any(
            "create_pull_request" in name or "new_unknown_tool" in name for name in names
        )
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall("remote-read", "github_get_file_contents", {"arguments": {"id": 7}})
                ]
            ),
            AssistantMessage("Read the saved account source."),
        ]
    )
    await collect(runtime.start("alice", session["id"], "Read the account item."))
    row = runtime.db.one(
        "SELECT * FROM tool_runs WHERE session=? AND call_id=?", (session["id"], "remote-read")
    )
    assert row["status"] == "completed"
    output = json.loads(json.loads(row["result"])["content"])
    assert output["next_offset"] == 12000
    source = await runtime.checkpoints.get("alice", session["id"], output["source_id"])
    assert len(source["raw"]["content"][0]["text"]) > 12000
    with pytest.raises(LookupError):
        await runtime.checkpoints.get("bob", session["id"], output["source_id"])
    assert calls == [("get_file_contents", {"id": 7})]


async def test_invalid_remote_arguments_never_start_call(
    runtime, connector, scripted_models, monkeypatch
):
    connector.save("alice", token_payload(connector))
    calls = []

    async def remote(owner, name=None, arguments=None):
        if name is None:
            return [
                Tool(
                    name="get_file_contents",
                    inputSchema={
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                        "required": ["id"],
                    },
                )
            ]
        calls.append(name)
        return CallToolResult(content=[])

    monkeypatch.setattr(connector, "remote", remote)
    session = runtime.db.create_session(
        "alice", runtime.settings.model, "default", channel="browser"
    )
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall("invalid", "github_get_file_contents", {"arguments": {"id": "wrong"}})
                ]
            ),
            AssistantMessage("The input needs correction."),
        ]
    )
    await collect(runtime.start("alice", session["id"], "Read the account."))
    row = runtime.db.one(
        "SELECT * FROM tool_runs WHERE session=? AND call_id='invalid'", (session["id"],)
    )
    assert row["status"] == "not_started"
    assert not calls


async def test_unavailable_connector_does_not_block_ordinary_chat(runtime, connector, monkeypatch):
    connector.save("alice", token_payload(connector))

    async def offline(*args, **kwargs):
        raise ServiceError("Remote service unavailable.")

    monkeypatch.setattr(connector, "remote", offline)
    row = runtime.db.create_session("alice", runtime.settings.model, "default", channel="browser")
    tools = await runtime.tools(row)
    assert not any(t.name.startswith("github_") for t in tools)
    events = await collect(runtime.start("alice", row["id"], "Hello"))
    assert events[-1]["status"] == "completed"


async def test_private_telegram_connect_and_disconnect_never_use_model_history(runtime, connector):
    from theos.transports.telegram.commands import command

    runtime.settings.telegram_users.add(123)
    sent = []

    async def send(*args):
        sent.append(args)

    bot = SimpleNamespace(settings=runtime.settings, db=runtime.db, runtime=runtime, send=send)
    private = runtime.db.create_session(
        "telegram:123", runtime.settings.model, "default", channel="telegram-private"
    )
    await command(bot, private, "/connect_github", "", 123, None)
    assert sent[-1][3]["inline_keyboard"][0][0]["url"].startswith(connector.spec.authorization_url)
    assert runtime.db.load_history("telegram:123", private["id"]) == []
    await command(bot, private, "/disconnect_github", "", 123, None)
    assert not runtime.db.one("SELECT 1 FROM oauth_states WHERE owner='telegram:123'")
    group = runtime.db.create_session(
        "telegram:123", runtime.settings.model, "default", channel="telegram-group"
    )
    await command(bot, group, "/connect_github", "", 123, None)
    assert "private chat" in sent[-1][1]
    assert not runtime.db.one("SELECT 1 FROM oauth_states WHERE owner='telegram:123'")


async def test_browser_connection_assets_and_mentions(runtime):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
    ) as client:
        asset = await client.get("/static/providers/github.svg")
        assert asset.status_code == 200 and "<svg" in asset.text
        script = await client.get("/static/app.js")
        assert '"/static/providers/github.svg"' in script.text
        assert "official GitHub MCP server" in script.text


def test_fixed_catalog_keeps_writes_out(connector):
    assert "get_file_contents" in READ_TOOLS
    assert "create_pull_request" not in READ_TOOLS
    assert connector.spec.endpoint == "https://api.githubcopilot.com/mcp/"
    assert "git" in connector.spec.headers["X-MCP-Toolsets"].split(",")
    assert connector.spec.headers["X-MCP-Readonly"] == "true"
