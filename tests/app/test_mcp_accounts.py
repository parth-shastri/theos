"""Remote connector contracts without provider accounts or live requests."""

import asyncio
import json
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import SecretStr, ValidationError

from harness import RunContext
from theos.services.errors import ServiceError
from theos.services.mcp_accounts.account import AccountSpec, MCPAccount
from theos.services.mcp_accounts.config import MCPAccountSettings
from theos.services.mcp_accounts.session import AccountAuth


def make_account(settings, db, http, **spec_values):
    settings.token_encryption_key = SecretStr(Fernet.generate_key().decode())
    config = MCPAccountSettings(
        client_id="test-client",
        client_secret="client-secret",
        redirect_uri="https://assistant.test/oauth/example/callback",
    )
    spec = AccountSpec(
        name="example",
        label="Example",
        endpoint="https://provider.test/mcp",
        authorization_url="https://provider.test/authorize",
        token_url="https://provider.test/token",
        read_tools=frozenset({"get_item"}),
        **spec_values,
    )
    return MCPAccount(settings, config, spec, db, http)


def state_from(started):
    query = parse_qs(urlsplit(started["url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    return query["state"][0]


@pytest.mark.parametrize(
    "redirect",
    [
        "https://a.test/wrong",
        "http://a.test/oauth/example/callback",
        "https://a.test/oauth/example/callback?x=1",
        "https://user@a.test/oauth/example/callback",
    ],
)
def test_connector_callback_configuration_rejects_wrong_origins_and_paths(redirect):
    config = MCPAccountSettings(client_id="id", client_secret="secret", redirect_uri=redirect)
    with pytest.raises(ValueError, match="callback"):
        config.check_callback("example")


async def test_oauth_owns_state_encrypts_tokens_and_restores_without_session(settings, db):
    requests = []

    def remote(request):
        requests.append(request)
        form = parse_qs(request.content.decode())
        assert form["code_verifier"] and form["redirect_uri"]
        return httpx.Response(
            200,
            json={
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
                "scope": "read",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        account = make_account(settings, db, http, scopes=("read",))
        started = await account.start("alice")
        state = state_from(started)
        saved = db.one("SELECT * FROM oauth_states")
        assert state not in saved["digest"] and "verifier" not in saved["verifier"]
        assert await account.callback(state, "code") == "alice"
        encrypted = db.one("SELECT * FROM credentials")["encrypted"]
        assert "secret" not in encrypted
        restored = MCPAccount(settings, account.config, account.spec, db, http)
        assert await restored.access_token("alice") == "access-secret"
        assert restored.connected("alice") and not restored.connected("bob")
        assert "secret" not in json.dumps(restored.status("alice"))
        assert not db.rows("SELECT * FROM sessions")
        with pytest.raises(ValueError, match="invalid or expired"):
            await restored.callback(state, "code")
        assert len(requests) == 1
        await restored.disconnect("bob")
        assert restored.connected("alice")
        assert (await restored.disconnect("alice"))["disconnected"]
        assert not restored.connected("alice")
        assert not db.rows("SELECT * FROM credentials")


async def test_expired_canceled_replaced_and_denied_state_preserves_old_grant(settings, db):
    async with httpx.AsyncClient() as http:
        account = make_account(settings, db, http)
        account.save("alice", {"access_token": "old"})
        old = state_from(await account.start("alice"))
        current = state_from(await account.start("alice"))
        with pytest.raises(ValueError):
            await account.callback(old, "code")
        with pytest.raises(ValueError, match="canceled"):
            await account.callback(current, "", "access_denied")
        assert account.connected("alice")
        expired = state_from(await account.start("alice"))
        db.execute("UPDATE oauth_states SET expires=0")
        with pytest.raises(ValueError):
            await account.callback(expired, "code")
        canceled = state_from(await account.start("alice"))
        await account.disconnect("alice")
        with pytest.raises(ValueError):
            await account.callback(canceled, "code")


async def test_refresh_rotates_once_under_concurrency_and_disconnect_cannot_resurrect(settings, db):
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    async def remote(request):
        requests.append(request)
        assert parse_qs(request.content.decode())["redirect_uri"] == [
            "https://assistant.test/oauth/example/callback"
        ]
        entered.set()
        await release.wait()
        return httpx.Response(
            200, json={"access_token": "fresh", "refresh_token": "rotated", "expires_in": 3600}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        account = make_account(settings, db, http)
        account.save("alice", {"access_token": "old", "refresh_token": "first", "expires_at": 0})
        reads = [asyncio.create_task(account.access_token("alice")) for _ in range(3)]
        await entered.wait()
        release.set()
        assert await asyncio.gather(*reads) == ["fresh"] * 3
        assert account.read("alice")["refresh_token"] == "rotated"
        assert len(requests) == 1
        account.save("alice", {"access_token": "old", "refresh_token": "rotated", "expires_at": 0})
        entered.clear()
        release.clear()
        refreshing = asyncio.create_task(account.access_token("alice"))
        await entered.wait()
        disconnecting = asyncio.create_task(account.disconnect("alice"))
        release.set()
        await asyncio.gather(refreshing, disconnecting)
        assert not account.connected("alice")


@pytest.mark.parametrize(
    "payload",
    [
        {"access_token": "s", "scope": "other"},
        {"ok": False, "error": "private secret"},
        {"access_token": "s", "expires_in": -1},
        {"access_token": "s", "expires_in": "nan"},
        {"access_token": "s", "token_type": "bot"},
    ],
)
async def test_token_rejections_are_safe_and_do_not_replace_credentials(settings, db, payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as http:
        account = make_account(settings, db, http, scopes=("read",))
        account.save("alice", {"access_token": "old"})
        state = state_from(await account.start("alice"))
        with pytest.raises(ServiceError, match="authorization failed") as error:
            await account.callback(state, "code")
        assert "secret" not in str(error.value)
        assert account.read("alice")["access_token"] == "old"
        assert not db.rows("SELECT * FROM oauth_states")


async def test_configuration_and_owner_changes_reject_saved_or_inflight_grants(settings, db):
    async with httpx.AsyncClient() as http:
        account = make_account(settings, db, http)
        account.save("alice", {"access_token": "old"})
        account.spec = replace(account.spec, endpoint="https://other.test/mcp")
        assert not account.connected("alice")
        with pytest.raises(ServiceError, match="saved account"):
            await account.access_token("alice")
        state = state_from(await account.start("alice"))
        settings.users.pop("alice")
        with pytest.raises(PermissionError):
            await account.callback(state, "code")
        for owner in ("terminal:local", "telegram-group:123"):
            with pytest.raises(PermissionError):
                await account.start(owner)


async def test_revoked_owner_during_exchange_cannot_save_tokens(settings, db):
    async def remote(request):
        settings.users.pop("alice")
        return httpx.Response(200, json={"access_token": "private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        account = make_account(settings, db, http)
        state = state_from(await account.start("alice"))
        with pytest.raises(PermissionError):
            await account.callback(state, "code")
        assert not db.rows("SELECT * FROM credentials")


async def test_slack_user_token_shape_and_basic_client_auth(settings, db):
    def remote(request):
        assert request.headers["authorization"].startswith("Basic ")
        assert "client_secret" not in parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "ok": True,
                "access_token": "xoxp-secret",
                "token_type": "user",
                "authed_user": {"id": "U1", "scope": "read,profile"},
                "team": {"id": "T1"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        account = make_account(
            settings, db, http, scopes=("read",), token_basic_auth=True, scope_separator=","
        )
        await account.callback(state_from(await account.start("alice")), "code")
        assert account.read("alice")["team"] == {"id": "T1"}
        assert "T1" not in json.dumps(account.status("alice"))


async def test_tool_allowlist_schema_methods_and_disconnected_closures(settings, db, monkeypatch):
    async with httpx.AsyncClient() as http:
        account = make_account(settings, db, http, methods={"get_item": frozenset({"get"})})
        account.save("alice", {"access_token": "secret"})
        calls = []

        async def remote(owner, name=None, arguments=None):
            calls.append((owner, name, arguments))
            if name is None:
                return [
                    Tool(
                        name="get_item",
                        inputSchema={
                            "type": "object",
                            "properties": {"method": {"type": "string"}, "id": {"type": "integer"}},
                            "required": ["method", "id"],
                            "additionalProperties": False,
                        },
                    ),
                    Tool(name="delete_item", inputSchema={"type": "object"}),
                ]
            return CallToolResult(content=[TextContent(type="text", text="complete source")])

        monkeypatch.setattr(account, "remote", remote)
        tools = await account.tools("alice")
        assert [t.name for t in tools] == ["example_get_item"]
        chosen = tools[0]
        assert chosen.view == "mcp_account_read" and not chosen.parallel_safe
        for args in (
            {"method": "delete", "id": 1},
            {"method": "get", "id": "wrong"},
            {"method": "get", "id": 1, "extra": True},
        ):
            with pytest.raises(ValidationError):
                chosen.input_model.model_validate({"arguments": args})
        assert len(calls) == 1
        args = chosen.input_model.model_validate({"arguments": {"method": "get", "id": 1}})
        result = await chosen.execute(args, RunContext(deps=None))
        assert result["content"][0]["text"] == "complete source"
        settings.users.pop("alice")
        with pytest.raises(PermissionError):
            await chosen.execute(args, RunContext(deps=None))
        assert len(calls) == 2


@pytest.mark.parametrize("schema", [{"$ref": "https://attacker.test/schema"}, {"type": "invalid"}])
async def test_unsupported_catalog_never_fetches_schema_references(
    settings, db, monkeypatch, schema
):
    async with httpx.AsyncClient() as http:
        account = make_account(settings, db, http)
        account.save("alice", {"access_token": "secret"})

        async def remote(*args):
            return [Tool(name="get_item", inputSchema=schema)]

        monkeypatch.setattr(account, "remote", remote)
        with pytest.raises(ServiceError, match="catalog is unsupported"):
            await account.tools("alice")


async def test_real_mcp_protocol_pages_discovery_and_never_retries_failed_read(
    settings, db, monkeypatch
):
    from theos.services.mcp_accounts import session as wire

    calls = []

    def remote(request):
        assert request.headers["authorization"] == "Bearer access-secret"
        if request.method != "POST":
            return httpx.Response(405)
        body = json.loads(request.content)
        method = body["method"]
        if "id" not in body:
            return httpx.Response(202)
        calls.append(body)
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fixture", "version": "1"},
            }
        elif method == "tools/list":
            cursor = body.get("params", {}).get("cursor")
            result = {
                "tools": [
                    {
                        "name": "get_item" if cursor else "hidden_write",
                        "inputSchema": {"type": "object"},
                    }
                ]
            }
            if not cursor:
                result["nextCursor"] = "second-page"
        else:
            return httpx.Response(503)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        wire,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(remote), **kwargs),
    )
    async with original_client() as http:
        account = make_account(settings, db, http)
        account.save("alice", {"access_token": "access-secret"})
        tools = await account.tools("alice")
        assert [t.name for t in tools] == ["example_get_item"]
        with pytest.raises(ServiceError, match="unavailable"):
            await account.remote("alice", "get_item", {})
        assert sum(call["method"] == "tools/call" for call in calls) == 1
        assert [call["method"] for call in calls[:3]] == ["initialize", "tools/list", "tools/list"]
        await account.close()
        assert not account.sessions


async def test_http_auth_rechecks_disconnect_without_forwarding_token(settings, db):
    async with httpx.AsyncClient() as http:
        account = make_account(settings, db, http)
        account.save("alice", {"access_token": "secret"})
        await account.disconnect("alice")
        flow = AccountAuth(account, "alice").async_auth_flow(
            httpx.Request("POST", account.spec.endpoint)
        )
        with pytest.raises(ServiceError, match="Connect this account"):
            await anext(flow)


@pytest.mark.parametrize("action", ["disconnect", "reconnect"])
async def test_session_teardown_can_finish_authentication_without_token_lock_deadlock(
    settings, db, action
):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"access_token": "fresh"})
        )
    ) as http:
        account = make_account(settings, db, http)
        account.save("alice", {"access_token": "old"})
        closed = []

        class Session:
            async def close(self):
                # A remote session can authenticate DELETE during context teardown.
                try:
                    closed.append(await account.access_token("alice"))
                except ServiceError:
                    closed.append("disconnected")

        account.sessions["alice"] = Session()
        async with asyncio.timeout(1):
            if action == "disconnect":
                await account.disconnect("alice")
            else:
                await account.callback(state_from(await account.start("alice")), "code")
        assert closed == ["disconnected" if action == "disconnect" else "fresh"]
        assert not account.sessions
