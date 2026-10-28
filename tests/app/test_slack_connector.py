"""Official Slack MCP integration through private Theos accounts."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import SecretStr, ValidationError

from harness import AssistantMessage, ToolCall
from theos.services.errors import ServiceError
from theos.services.slack import READ_TOOLS, create_account
from theos.settings import Settings

from .conftest import call_tool, collect
from .test_browser_connections import browser


@pytest.fixture
def connector(runtime):
    runtime.settings.token_encryption_key = SecretStr(Fernet.generate_key().decode())
    kind = type(runtime.settings.slack)
    runtime.settings.slack = kind(
        client_id="client",
        client_secret="private-client",
        redirect_uri="https://assistant.test/oauth/slack/callback",
    )
    runtime.slack = create_account(runtime.settings, runtime.db, runtime.http)
    return runtime.slack


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
        redirect_uri="https://assistant.test/oauth/slack/callback",
    )
    with pytest.raises(ValidationError, match="encryption key"):
        Settings(_env_file=None, slack=fields)
    fields["redirect_uri"] = "https://assistant.test/oauth/other/callback"
    with pytest.raises(ValidationError, match="callback"):
        Settings(_env_file=None, slack=fields, token_encryption_key=Fernet.generate_key().decode())


async def test_browser_oauth_connections_bind_callback_to_original_owner(runtime, connector):
    def remote(request):
        assert str(request.url) == connector.spec.token_url
        data = parse_qs(request.content.decode())
        assert "code_verifier" not in data and data["redirect_uri"]
        return httpx.Response(200, json=token_payload(connector))

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        connector.http = http
        async with browser(runtime) as alice, browser(runtime, "bob") as bob:
            started = (
                await alice.post("/api/connections/slack/connect", json={"owner": "bob"})
            ).json()
            query = parse_qs(urlsplit(started["url"]).query)
            assert "code_challenge_method" not in query
            state = query["state"][0]
            response = await bob.get(
                "/oauth/slack/callback", params={"state": state, "code": "private-code"}
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/?connections=1"
            assert connector.connected("alice") and not connector.connected("bob")
            assert (
                await alice.get("/oauth/slack/callback", params={"state": state, "code": "replay"})
            ).status_code == 400
            a = (await alice.get("/api/connections")).json()
            b = (await bob.get("/api/connections")).json()
            assert next(x for x in a["accounts"] if x["id"] == "slack")["connected"]
            assert not next(x for x in b["accounts"] if x["id"] == "slack")["connected"]
            assert "secret" not in json.dumps(a)
            encrypted = runtime.db.one(
                "SELECT encrypted FROM credentials WHERE owner=? AND service=?", ("alice", "slack")
            )
            assert "account-secret" not in encrypted["encrypted"]
            restored = create_account(runtime.settings, runtime.db, http)
            assert await restored.access_token("alice") == "account-secret"
            await bob.post("/api/connections/slack/disconnect")
            assert connector.connected("alice")
            await alice.post("/api/connections/slack/disconnect")
            assert not restored.connected("alice")


async def test_denied_browser_consent_and_cancellation_do_not_issue_tokens(runtime, connector):
    async with browser(runtime) as client:
        link = (await client.post("/api/connections/slack/connect")).json()["url"]
        state = parse_qs(urlsplit(link).query)["state"][0]
        denied = await client.get(
            "/oauth/slack/callback", params={"state": state, "error": "access_denied"}
        )
        assert denied.status_code == 400
        assert not connector.connected("alice")
        assert not runtime.db.one("SELECT 1 FROM oauth_states WHERE service='slack'")
        link = (await client.post("/api/connections/slack/connect")).json()["url"]
        state = parse_qs(urlsplit(link).query)["state"][0]
        connector.save("alice", token_payload(connector))
        assert (await client.post("/api/connections/slack/cancel")).status_code == 200
        assert connector.connected("alice")
        assert (
            await client.get("/oauth/slack/callback", params={"state": state, "code": "code"})
        ).status_code == 400


async def test_runtime_read_is_owner_scoped_bounded_and_journaled(
    runtime, connector, scripted_models, monkeypatch
):
    connector.save("alice", token_payload(connector))
    calls = []

    async def remote(owner, name=None, arguments=None):
        assert owner == "alice"
        if name is None:
            return [
                Tool(
                    name="slack_read_thread",
                    inputSchema={
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                        "required": ["id"],
                        "additionalProperties": False,
                    },
                ),
                Tool(name="slack_send_message", inputSchema={"type": "object"}),
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
        assert not any(t.name.startswith("slack_") for t in await runtime.tools(other))
    for channel in ("browser", "telegram-private"):
        row = runtime.db.create_session("alice", runtime.settings.model, "default", channel=channel)
        names = {t.name for t in await runtime.tools(row)}
        assert "slack_read_thread" in names
        assert not any("slack_send_message" in name or "new_unknown_tool" in name for name in names)
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[ToolCall("remote-read", "slack_read_thread", {"arguments": {"id": 7}})]
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
    assert output["truncated"] and output["result_bytes"] > 12000
    assert "source evidence" in output["preview"]
    assert len(output["preview"].encode()) <= 4096
    assert "source_id" not in output
    assert calls == [("slack_read_thread", {"id": 7})]


async def test_invalid_remote_arguments_never_start_call(
    runtime, connector, scripted_models, monkeypatch
):
    connector.save("alice", token_payload(connector))
    calls = []

    async def remote(owner, name=None, arguments=None):
        if name is None:
            return [
                Tool(
                    name="slack_read_thread",
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
                    ToolCall("invalid", "slack_read_thread", {"arguments": {"id": "wrong"}})
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
    assert not any(t.name.startswith("slack_") for t in tools)
    events = await collect(runtime.start("alice", row["id"], "Hello"))
    assert events[-1]["status"] == "completed"


async def test_private_telegram_connect_and_disconnect_never_use_model_history(runtime, connector):
    from theos.transports.telegram.commands import command
    from theos.transports.telegram.connections import handle

    runtime.settings.telegram_users.add(123)
    sent = []

    async def send(*args):
        sent.append(args)

    bot = SimpleNamespace(settings=runtime.settings, db=runtime.db, runtime=runtime, send=send)
    private = runtime.db.create_session(
        "telegram:123", runtime.settings.model, "default", channel="telegram-private"
    )
    assert await handle(
        bot, {"text": "/slack"}, "telegram:123", "telegram-private", 123, None, None
    )
    assert sent[-1][3]["inline_keyboard"][0][0]["url"].startswith(connector.spec.authorization_url)
    assert runtime.db.load_history("telegram:123", private["id"]) == []
    await command(bot, private, "/disconnect_slack", "", 123, None)
    assert not runtime.db.one("SELECT 1 FROM oauth_states WHERE owner='telegram:123'")
    group = runtime.db.create_session(
        "telegram:123", runtime.settings.model, "default", channel="telegram-group"
    )
    await command(bot, group, "/connect_slack", "", 123, None)
    assert "private chat" in sent[-1][1]
    assert not runtime.db.one("SELECT 1 FROM oauth_states WHERE owner='telegram:123'")


def test_fixed_catalog_keeps_writes_out(connector):
    assert "slack_read_thread" in READ_TOOLS
    assert "slack_send_message" not in READ_TOOLS
    assert connector.spec.endpoint == "https://mcp.slack.com/mcp"


def test_slack_uses_confidential_user_oauth_and_public_scopes_by_default(connector):
    assert not connector.spec.pkce and connector.spec.token_basic_auth
    assert connector.spec.authorization_url == "https://slack.com/oauth/v2_user/authorize"
    assert connector.spec.token_url == "https://slack.com/api/oauth.v2.user.access"
    assert "search:read.public" in connector.scopes
    assert not any(
        scope in connector.scopes
        for scope in ("search:read.private", "search:read.im", "chat:write")
    )


async def test_slack_private_consent_failure_is_saved_as_failed_not_empty_success(
    runtime, connector, scripted_models, monkeypatch
):
    connector.save("alice", token_payload(connector))
    calls = []

    async def remote(owner, name=None, arguments=None):
        if name is None:
            return [Tool(name="slack_search_public_and_private", inputSchema={"type": "object"})]
        calls.append(name)
        return CallToolResult(
            isError=True,
            content=[TextContent(type="text", text="Missing consent. Bearer private-token")],
        )

    monkeypatch.setattr(connector, "remote", remote)
    session = runtime.db.create_session(
        "alice", runtime.settings.model, "default", channel="browser"
    )
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall("denied-read", "slack_search_public_and_private", {"arguments": {}})
                ]
            ),
            AssistantMessage("The account could not read the requested conversation."),
        ]
    )
    await collect(runtime.start("alice", session["id"], "Search my private conversations."))
    row = runtime.db.one(
        "SELECT * FROM tool_runs WHERE session=? AND call_id='denied-read'", (session["id"],)
    )
    assert row["status"] == "failed"
    assert "private-token" not in row["result"]
    assert "source_id" not in row["result"]
    assert calls == ["slack_search_public_and_private"]


async def test_large_slack_reads_stage_complete_results(runtime, connector, monkeypatch):
    connector.save("alice", token_payload(connector))
    text = "thread evidence " * 1600

    async def remote(owner, name=None, arguments=None):
        assert owner == "alice"
        if name is None:
            return [Tool(name="slack_read_thread", inputSchema={"type": "object"})]
        return CallToolResult(content=[TextContent(type="text", text=text)])

    staged = {}

    async def save_result(name, content):
        staged.update(name=name, content=json.loads(content))
        return {"path": "/tmp/theos-results/slack-thread.json"}

    monkeypatch.setattr(connector, "remote", remote)
    tools = await connector.tools("alice", result_stager=save_result)
    result = await call_tool(tools, "slack_read_thread", arguments={})
    assert result["result_file"] == "/tmp/theos-results/slack-thread.json"
    assert not result["truncated"]
    assert staged["name"] == "slack_read_thread"
    assert staged["content"]["content"][0]["text"] == text
