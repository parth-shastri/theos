"""Official GitLab MCP integration through private Theos accounts."""

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
from theos.services.gitlab import READ_TOOLS, create_account
from theos.settings import Settings

from .conftest import call_tool, collect
from .test_browser_connections import browser


@pytest.fixture
def connector(runtime):
    runtime.settings.token_encryption_key = SecretStr(Fernet.generate_key().decode())
    kind = type(runtime.settings.gitlab)
    runtime.settings.gitlab = kind(
        client_id="client",
        client_secret="private-client",
        redirect_uri="https://assistant.test/oauth/gitlab/callback",
    )
    runtime.gitlab = create_account(runtime.settings, runtime.db, runtime.http)
    return runtime.gitlab


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
        redirect_uri="https://assistant.test/oauth/gitlab/callback",
    )
    with pytest.raises(ValidationError, match="encryption key"):
        Settings(_env_file=None, gitlab=fields)
    fields["redirect_uri"] = "https://assistant.test/oauth/other/callback"
    with pytest.raises(ValidationError, match="callback"):
        Settings(_env_file=None, gitlab=fields, token_encryption_key=Fernet.generate_key().decode())


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
                await alice.post("/api/connections/gitlab/connect", json={"owner": "bob"})
            ).json()
            query = parse_qs(urlsplit(started["url"]).query)
            assert query["code_challenge_method"] == ["S256"]
            state = query["state"][0]
            response = await bob.get(
                "/oauth/gitlab/callback", params={"state": state, "code": "private-code"}
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/?connections=1"
            assert connector.connected("alice") and not connector.connected("bob")
            assert (
                await alice.get("/oauth/gitlab/callback", params={"state": state, "code": "replay"})
            ).status_code == 400
            a = (await alice.get("/api/connections")).json()
            b = (await bob.get("/api/connections")).json()
            assert next(x for x in a["accounts"] if x["id"] == "gitlab")["connected"]
            assert not next(x for x in b["accounts"] if x["id"] == "gitlab")["connected"]
            assert "secret" not in json.dumps(a)
            encrypted = runtime.db.one(
                "SELECT encrypted FROM credentials WHERE owner=? AND service=?", ("alice", "gitlab")
            )
            assert "account-secret" not in encrypted["encrypted"]
            restored = create_account(runtime.settings, runtime.db, http)
            assert await restored.access_token("alice") == "account-secret"
            await bob.post("/api/connections/gitlab/disconnect")
            assert connector.connected("alice")
            await alice.post("/api/connections/gitlab/disconnect")
            assert not restored.connected("alice")


async def test_denied_browser_consent_and_cancellation_do_not_issue_tokens(runtime, connector):
    async with browser(runtime) as client:
        link = (await client.post("/api/connections/gitlab/connect")).json()["url"]
        state = parse_qs(urlsplit(link).query)["state"][0]
        denied = await client.get(
            "/oauth/gitlab/callback", params={"state": state, "error": "access_denied"}
        )
        assert denied.status_code == 400
        assert not connector.connected("alice")
        assert not runtime.db.one("SELECT 1 FROM oauth_states WHERE service='gitlab'")
        link = (await client.post("/api/connections/gitlab/connect")).json()["url"]
        state = parse_qs(urlsplit(link).query)["state"][0]
        connector.save("alice", token_payload(connector))
        assert (await client.post("/api/connections/gitlab/cancel")).status_code == 200
        assert connector.connected("alice")
        assert (
            await client.get("/oauth/gitlab/callback", params={"state": state, "code": "code"})
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
                    name="get_repository_file",
                    inputSchema={
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                        "required": ["id"],
                        "additionalProperties": False,
                    },
                ),
                Tool(name="save_merge_request", inputSchema={"type": "object"}),
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
        assert not any(t.name.startswith("gitlab_") for t in await runtime.tools(other))
    for channel in ("browser", "telegram-private"):
        row = runtime.db.create_session("alice", runtime.settings.model, "default", channel=channel)
        names = {t.name for t in await runtime.tools(row)}
        assert "gitlab_get_repository_file" in names
        assert not any("save_merge_request" in name or "new_unknown_tool" in name for name in names)
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall("remote-read", "gitlab_get_repository_file", {"arguments": {"id": 7}})
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
    assert output["truncated"] and output["result_bytes"] > 12000
    assert "source evidence" in output["preview"]
    assert len(output["preview"].encode()) <= 4096
    assert "source_id" not in output
    assert calls == [("get_repository_file", {"id": 7})]


async def test_invalid_remote_arguments_never_start_call(
    runtime, connector, scripted_models, monkeypatch
):
    connector.save("alice", token_payload(connector))
    calls = []

    async def remote(owner, name=None, arguments=None):
        if name is None:
            return [
                Tool(
                    name="get_repository_file",
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
                    ToolCall(
                        "invalid", "gitlab_get_repository_file", {"arguments": {"id": "wrong"}}
                    )
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
    assert not any(t.name.startswith("gitlab_") for t in tools)
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
        bot, {"text": "/gitlab"}, "telegram:123", "telegram-private", 123, None, None
    )
    assert sent[-1][3]["inline_keyboard"][0][0]["url"].startswith(connector.spec.authorization_url)
    assert runtime.db.load_history("telegram:123", private["id"]) == []
    await command(bot, private, "/disconnect_gitlab", "", 123, None)
    assert not runtime.db.one("SELECT 1 FROM oauth_states WHERE owner='telegram:123'")
    group = runtime.db.create_session(
        "telegram:123", runtime.settings.model, "default", channel="telegram-group"
    )
    await command(bot, group, "/connect_gitlab", "", 123, None)
    assert "private chat" in sent[-1][1]
    assert not runtime.db.one("SELECT 1 FROM oauth_states WHERE owner='telegram:123'")


def test_fixed_catalog_keeps_writes_out(connector):
    assert "get_repository_file" in READ_TOOLS
    assert "save_merge_request" not in READ_TOOLS
    assert connector.spec.endpoint == "https://gitlab.com/api/v4/mcp"
    assert "repository" in connector.spec.headers["X-Gitlab-Enabled-Mcp-Server-Toolsets"].split(",")


async def test_large_gitlab_reads_stage_complete_results(runtime, connector, monkeypatch):
    connector.save("alice", token_payload(connector))
    text = "repository evidence " * 1600

    async def remote(owner, name=None, arguments=None):
        assert owner == "alice"
        if name is None:
            return [Tool(name="get_repository_file", inputSchema={"type": "object"})]
        return CallToolResult(content=[TextContent(type="text", text=text)])

    staged = {}

    async def save_result(name, content):
        staged.update(name=name, content=json.loads(content))
        return {"path": "/tmp/theos-results/gitlab-file.json"}

    monkeypatch.setattr(connector, "remote", remote)
    tools = await connector.tools("alice", result_stager=save_result)
    result = await call_tool(tools, "gitlab_get_repository_file", arguments={})
    assert result["result_file"] == "/tmp/theos-results/gitlab-file.json"
    assert not result["truncated"]
    assert staged["name"] == "gitlab_get_repository_file"
    assert staged["content"]["content"][0]["text"] == text


@pytest.mark.parametrize(
    "origin",
    [
        "http://gitlab.company.test",
        "https://user:secret@gitlab.company.test",
        "https://gitlab.company.test/path",
        "https://gitlab.company.test?token=secret",
    ],
)
def test_gitlab_instance_rejects_credentials_paths_and_insecure_origins(origin):
    with pytest.raises(ValidationError, match="GitLab origin"):
        Settings(_env_file=None, gitlab={"instance_url": origin})


def test_gitlab_instance_derives_all_endpoints_and_requires_mcp_scope(settings, db):
    from theos.settings import GitLabSettings

    settings.token_encryption_key = SecretStr(Fernet.generate_key().decode())
    fields = {
        "client_id": "client",
        "client_secret": "secret",
        "redirect_uri": "https://assistant.test/oauth/gitlab/callback",
        "instance_url": "https://gitlab.company.test/",
    }
    settings.gitlab = GitLabSettings(**fields)
    account = create_account(settings, db, None)
    assert account.spec.endpoint == "https://gitlab.company.test/api/v4/mcp"
    assert account.spec.authorization_url == "https://gitlab.company.test/oauth/authorize"
    assert account.spec.token_url == "https://gitlab.company.test/oauth/token"
    assert account.scopes == ("mcp",)
    with pytest.raises(ValidationError, match="mcp scope"):
        GitLabSettings(**fields, scopes=["read_api"])
